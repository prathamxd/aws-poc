"""Attachment storage.

S3 when S3_BUCKET is set (AWS), otherwise a local folder (development and tests).
Every object is written under the "attachments/" prefix, which is the prefix
that triggers the Lambda file processor.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import BinaryIO

from fastapi.responses import FileResponse, RedirectResponse, Response

from .config import Settings

log = logging.getLogger("ticketdesk.storage")

KEY_PREFIX = "attachments/"


class StorageError(Exception):
    """Raised when an upload or download cannot be completed."""


def safe_filename(name: str) -> str:
    name = Path(name or "").name  # drop any client-side path
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or "file")[-100:]


class LocalStorage:
    kind = "local"

    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.base / key).resolve()
        if self.base not in path.parents:
            raise StorageError("Invalid storage key")
        return path

    def save(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as out:
            shutil.copyfileobj(fileobj, out)

    def download_response(self, key: str, filename: str, content_type: str) -> Response:
        return FileResponse(self._path(key), filename=filename, media_type=content_type)

    def processing_status(self, key: str) -> dict:
        return {"status": "local", "detail": "Local storage - S3 and Lambda are not used"}


class S3Storage:
    kind = "s3"

    def __init__(self, bucket: str, region: str | None) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        # Regional endpoint: avoids redirect/signature errors on presigned URLs
        # for newly created buckets outside us-east-1.
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com" if region else None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def save(self, key: str, fileobj: BinaryIO, content_type: str) -> None:
        try:
            self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs={"ContentType": content_type})
        except Exception as exc:  # botocore raises many exception types
            log.exception("S3 upload failed for %s", key)
            raise StorageError(str(exc)) from exc

    def download_response(self, key: str, filename: str, content_type: str) -> Response:
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
                "ResponseContentType": content_type,
            },
            ExpiresIn=300,
        )
        return RedirectResponse(url, status_code=302)

    def processing_status(self, key: str) -> dict:
        """Read the tags that the Lambda file processor writes on the object."""
        try:
            tag_set = self.client.get_object_tagging(Bucket=self.bucket, Key=key)["TagSet"]
        except Exception:
            log.exception("Could not read tags for %s", key)
            return {"status": "unknown", "detail": "Could not read object tags"}
        tags = {t["Key"]: t["Value"] for t in tag_set}
        if "lambda-status" not in tags:
            return {"status": "pending", "detail": "Waiting for Lambda (refresh in a few seconds)"}
        return {
            "status": tags["lambda-status"],
            "detail": tags.get("lambda-reason", ""),
            "checked_at": tags.get("lambda-checked-at", ""),
        }


_storage: LocalStorage | S3Storage | None = None


def get_storage(settings: Settings) -> LocalStorage | S3Storage:
    global _storage
    if _storage is None:
        if settings.s3_bucket:
            _storage = S3Storage(settings.s3_bucket, settings.region)
            log.info("Attachments stored in S3 bucket %s", settings.s3_bucket)
        else:
            _storage = LocalStorage(settings.upload_dir)
            log.info("Attachments stored locally in %s", settings.upload_dir)
    return _storage

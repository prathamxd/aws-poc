"""TicketDesk attachment processor (AWS Lambda, Python 3.12).

Triggered by S3 "ObjectCreated" events for keys under attachments/.
For each new file it:
  1. reads the object metadata (size, content type),
  2. validates extension and size,
  3. writes the result back as S3 object tags (lambda-status, lambda-reason, ...),
  4. logs a JSON line to CloudWatch Logs.

Tagging an object does not fire another ObjectCreated event, so there is no loop.
The TicketDesk web app reads these tags and shows "processed"/"rejected" per file.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALLOWED_EXTENSIONS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EXTENSIONS", ".png,.jpg,.jpeg,.gif,.pdf,.txt,.log,.csv,.docx,.xlsx").split(",")
    if e.strip()
}
MAX_SIZE_BYTES = int(float(os.environ.get("MAX_SIZE_MB", "5")) * 1024 * 1024)

_s3_client = None


def _client():
    global _s3_client
    if _s3_client is None:
        import boto3  # available in the Lambda runtime

        _s3_client = boto3.client("s3")
    return _s3_client


def _tag_value(text: str) -> str:
    """S3 tag values allow letters, numbers, spaces and + - = . _ : / @ (max 256)."""
    return re.sub(r"[^A-Za-z0-9 +\-=._:/@]", "", text)[:256]


def inspect_file(key: str, size: int) -> tuple[str, str]:
    ext = os.path.splitext(key)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return "rejected", f"extension {ext or 'none'} not allowed"
    if size == 0:
        return "rejected", "empty file"
    if size > MAX_SIZE_BYTES:
        return "rejected", f"file larger than {MAX_SIZE_BYTES // (1024 * 1024)} MB"
    return "processed", "ok"


def handler(event, context, s3=None):
    s3 = s3 or _client()
    results = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        head = s3.head_object(Bucket=bucket, Key=key)
        size = int(head.get("ContentLength", 0))
        content_type = head.get("ContentType", "unknown")
        status, reason = inspect_file(key, size)
        checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        s3.put_object_tagging(
            Bucket=bucket,
            Key=key,
            Tagging={
                "TagSet": [
                    {"Key": "lambda-status", "Value": status},
                    {"Key": "lambda-reason", "Value": _tag_value(reason)},
                    {"Key": "lambda-checked-at", "Value": checked_at},
                    {"Key": "size-bytes", "Value": str(size)},
                ]
            },
        )

        result = {
            "event": "attachment_processed",
            "bucket": bucket,
            "key": key,
            "size_bytes": size,
            "content_type": content_type,
            "status": status,
            "reason": reason,
            "checked_at": checked_at,
        }
        logger.info(json.dumps(result))
        results.append(result)

    return {"processed": len(results), "results": results}

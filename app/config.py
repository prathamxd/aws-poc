"""Application settings.

Everything comes from environment variables. On AWS the sensitive values
(session key, admin password, database password) are read from AWS Secrets
Manager at runtime. Only the secret ARNs are passed to the container, so no
password is ever stored in source code, in the Docker image or in EC2 user data.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import __version__

log = logging.getLogger("ticketdesk.config")

DEFAULT_EXTENSIONS = ".png,.jpg,.jpeg,.gif,.pdf,.txt,.log,.csv,.docx,.xlsx"


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader for local development (no extra dependency).

    Existing environment variables always win over values in the file.
    """
    if os.getenv("TICKETDESK_SKIP_DOTENV") == "1" or not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_secret_json(secret_arn: str, region: str | None) -> dict:
    """Read a JSON secret from AWS Secrets Manager (uses the EC2 instance role)."""
    import boto3  # imported lazily so local runs do not need AWS credentials

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_arn)
    return json.loads(response["SecretString"])


@dataclass
class Settings:
    app_env: str
    app_version: str
    region: str | None
    secret_key: str
    admin_username: str
    admin_password: str | None
    # Local mode: a full SQLAlchemy URL (SQLite by default, or local PostgreSQL)
    database_url: str
    # AWS mode: host/port/name + Secrets Manager ARN holding username/password
    db_host: str | None
    db_port: int
    db_name: str
    db_secret_arn: str | None
    s3_bucket: str | None
    upload_dir: str
    max_upload_mb: int
    allowed_extensions: set[str] = field(default_factory=set)


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")

    app_secret: dict = {}
    app_secret_arn = os.getenv("APP_SECRET_ARN")
    if app_secret_arn:
        app_secret = get_secret_json(app_secret_arn, region)
        log.info("Loaded application secret from Secrets Manager")

    secret_key = app_secret.get("secret_key") or os.getenv("SECRET_KEY")
    if not secret_key:
        secret_key = secrets.token_urlsafe(32)
        log.warning("SECRET_KEY not set - using a random key (sessions reset on restart)")

    extensions = os.getenv("ALLOWED_EXTENSIONS", DEFAULT_EXTENSIONS)

    return Settings(
        app_env=os.getenv("APP_ENV", "local"),
        app_version=os.getenv("APP_VERSION", __version__),
        region=region,
        secret_key=secret_key,
        admin_username=(app_secret.get("admin_username") or os.getenv("ADMIN_USERNAME", "admin")).strip().lower(),
        admin_password=app_secret.get("admin_password") or os.getenv("ADMIN_PASSWORD") or None,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./ticketdesk.db"),
        db_host=os.getenv("DB_HOST") or None,
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "ticketdesk"),
        db_secret_arn=os.getenv("DB_SECRET_ARN") or None,
        s3_bucket=os.getenv("S3_BUCKET") or None,
        upload_dir=os.getenv("UPLOAD_DIR", "./uploads"),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "5")),
        allowed_extensions={e.strip().lower() for e in extensions.split(",") if e.strip()},
    )

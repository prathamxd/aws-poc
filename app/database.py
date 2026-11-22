"""Database engine and session handling.

Local:  DATABASE_URL (SQLite by default, or PostgreSQL from docker compose).
AWS:    DB_HOST/DB_PORT/DB_NAME + DB_SECRET_ARN. The username and password are
        fetched from the RDS-managed secret in Secrets Manager each time a new
        connection is opened (cached for 5 minutes), so automatic password
        rotation does not break the app.
"""
from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_secret_json
from .models import Base, User
from .security import hash_password

log = logging.getLogger("ticketdesk.db")

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None

_CREDENTIAL_TTL_SECONDS = 300
_credential_cache: dict = {"value": None, "expires": 0.0}


def _rds_credentials(settings: Settings) -> dict:
    now = time.monotonic()
    if _credential_cache["value"] is None or now >= _credential_cache["expires"]:
        _credential_cache["value"] = get_secret_json(settings.db_secret_arn, settings.region)
        _credential_cache["expires"] = now + _CREDENTIAL_TTL_SECONDS
    return _credential_cache["value"]


def build_engine(settings: Settings) -> Engine:
    if settings.db_secret_arn:
        if not settings.db_host:
            raise RuntimeError("DB_HOST must be set when DB_SECRET_ARN is used")
        url = URL.create(
            "postgresql+psycopg2",
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
        )
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=900, pool_size=5, max_overflow=5)

        @event.listens_for(engine, "do_connect")
        def _provide_credentials(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
            creds = _rds_credentials(settings)
            cparams["user"] = creds["username"]
            cparams["password"] = creds["password"]
            # RDS PostgreSQL 15+ enforces SSL (rds.force_ssl = 1)
            cparams.setdefault("sslmode", "require")

        log.info(
            "Database: PostgreSQL %s:%s/%s (credentials from Secrets Manager)",
            settings.db_host,
            settings.db_port,
            settings.db_name,
        )
        return engine

    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        db_file = url.replace("sqlite:///", "", 1)
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    log.info("Database: %s", engine.url.render_as_string(hide_password=True))
    return engine


def init_db(settings: Settings) -> None:
    """Create the engine, create tables if missing and make sure the admin user exists."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = build_engine(settings)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    seed_admin(settings)


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised")
    return _engine


def get_db():
    """FastAPI dependency: one session per request."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised")
    db: Session = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_admin(settings: Settings) -> None:
    assert _SessionLocal is not None
    username = settings.admin_username
    with _SessionLocal() as db:
        if db.scalar(select(User.id).where(User.username == username)):
            return
        password = settings.admin_password
        if not password:
            if settings.app_env == "production":
                log.error("Admin password not configured - admin user '%s' was not created", username)
                return
            password = secrets.token_urlsafe(12)
            log.warning("LOCAL ONLY: no ADMIN_PASSWORD set. Generated password for '%s': %s", username, password)
        db.add(User(username=username, password_hash=hash_password(password), role="admin"))
        db.commit()
        log.info("Created admin user '%s'", username)

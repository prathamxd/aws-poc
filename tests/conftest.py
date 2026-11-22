"""Shared test setup.

The app is configured for an isolated SQLite database and local attachment
storage *before* it is imported, so tests never touch AWS.
"""
import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="ticketdesk-tests-"))

for _var in ("S3_BUCKET", "DB_SECRET_ARN", "APP_SECRET_ARN", "DB_HOST"):
    os.environ.pop(_var, None)

os.environ.update(
    {
        "TICKETDESK_SKIP_DOTENV": "1",
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "SECRET_KEY": "test-only-secret-key",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "Admin-Test-Pass1",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "MAX_UPLOAD_MB": "1",
        "PASSWORD_HASH_ITERATIONS": "1000",
    }
)

ADMIN = ("admin", "Admin-Test-Pass1")


@pytest.fixture()
def client():
    """A TestClient with a fresh, empty database (plus the seeded admin)."""
    from fastapi.testclient import TestClient

    from app import database
    from app.main import app
    from app.models import Base

    with TestClient(app) as test_client:
        engine = database.get_engine()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        from app.main import settings

        database.seed_admin(settings)
        yield test_client


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


def logout(client):
    return client.get("/logout", follow_redirects=False)


def register(client, username, password="Password123"):
    return client.post(
        "/register",
        data={"username": username, "password": password, "confirm_password": password},
        follow_redirects=False,
    )


def create_ticket(client, title="Laptop will not boot", description="Black screen after update", priority="High", files=None):
    return client.post(
        "/tickets/new",
        data={"title": title, "description": description, "priority": priority},
        files=files,
        follow_redirects=False,
    )

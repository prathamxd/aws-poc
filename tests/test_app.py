"""Functional tests for the TicketDesk web app (runs against SQLite + local storage)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from conftest import ADMIN, create_ticket, login, logout, register  # noqa: E402


def ticket_status(client, ticket_id):
    return client.get(f"/api/tickets/{ticket_id}").json()["status"]


def new_ticket_id(response):
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


# ---------------------------------------------------------------- health & auth
def test_health_reports_database_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["storage"] == "local"


def test_pages_require_login(client):
    for path in ("/dashboard", "/tickets", "/tickets/new", "/admin/users"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303, path
        assert r.headers["location"] == "/login"


def test_api_requires_login(client):
    assert client.get("/api/tickets").status_code == 401
    assert client.get("/api/stats").status_code == 401


def test_login_with_wrong_password_fails(client):
    r = login(client, "admin", "wrong-password")
    assert r.status_code == 401
    assert "Invalid username or password" in r.text


def test_admin_login_and_dashboard(client):
    r = login(client, *ADMIN)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Dashboard" in page.text
    assert "admin" in page.text


def test_logout_clears_session(client):
    login(client, *ADMIN)
    logout(client)
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_register_new_user(client):
    r = register(client, "priya")
    assert r.status_code == 303
    assert client.get("/dashboard").status_code == 200
    logout(client)
    assert login(client, "priya", "Password123").status_code == 303


def test_register_validation(client):
    assert register(client, "ab").status_code == 400  # too short
    assert register(client, "rahul", "short").status_code == 400  # weak password
    assert register(client, "admin").status_code == 400  # duplicate
    r = client.post(
        "/register",
        data={"username": "rahul", "password": "Password123", "confirm_password": "Different123"},
    )
    assert r.status_code == 400
    assert "do not match" in r.text


# ---------------------------------------------------------------- tickets
def test_create_and_view_ticket(client):
    register(client, "priya")
    ticket_id = new_ticket_id(create_ticket(client, title="VPN not connecting"))
    detail = client.get(f"/tickets/{ticket_id}")
    assert detail.status_code == 200
    assert "VPN not connecting" in detail.text
    data = client.get(f"/api/tickets/{ticket_id}").json()
    assert data["status"] == "Open"
    assert data["priority"] == "High"
    assert data["created_by"] == "priya"
    listing = client.get("/tickets")
    assert "VPN not connecting" in listing.text


def test_create_ticket_requires_title(client):
    login(client, *ADMIN)
    r = create_ticket(client, title="   ")
    assert r.status_code == 400
    assert client.get("/api/tickets").json() == []


def test_filter_tickets_by_status(client):
    login(client, *ADMIN)
    first = new_ticket_id(create_ticket(client, title="Printer jam"))
    create_ticket(client, title="Email bounce")
    client.post(f"/tickets/{first}/status", data={"new_status": "In Progress"})
    r = client.get("/tickets", params={"status": "In Progress"})
    assert "Printer jam" in r.text
    assert "Email bounce" not in r.text


def test_full_status_workflow(client):
    login(client, *ADMIN)
    ticket_id = new_ticket_id(create_ticket(client))
    for status in ("In Progress", "Resolved", "Closed"):
        r = client.post(f"/tickets/{ticket_id}/status", data={"new_status": status}, follow_redirects=False)
        assert r.status_code == 303
        assert ticket_status(client, ticket_id) == status
    page = client.get(f"/tickets/{ticket_id}")
    assert "Resolved → Closed" in page.text  # history is recorded


def test_invalid_status_transition_is_rejected(client):
    login(client, *ADMIN)
    ticket_id = new_ticket_id(create_ticket(client))
    client.post(f"/tickets/{ticket_id}/status", data={"new_status": "Closed"})
    assert ticket_status(client, ticket_id) == "Open"
    client.post(f"/tickets/{ticket_id}/status", data={"new_status": "Nonsense"})
    assert ticket_status(client, ticket_id) == "Open"


def test_resolved_ticket_can_be_reopened(client):
    login(client, *ADMIN)
    ticket_id = new_ticket_id(create_ticket(client))
    for status in ("In Progress", "Resolved", "In Progress"):
        client.post(f"/tickets/{ticket_id}/status", data={"new_status": status})
    assert ticket_status(client, ticket_id) == "In Progress"


# ---------------------------------------------------------------- role-based access
def test_regular_user_cannot_change_status(client):
    register(client, "priya")
    ticket_id = new_ticket_id(create_ticket(client))
    r = client.post(f"/tickets/{ticket_id}/status", data={"new_status": "In Progress"})
    assert r.status_code == 403
    assert ticket_status(client, ticket_id) == "Open"


def test_users_only_see_their_own_tickets(client):
    register(client, "priya")
    priya_ticket = new_ticket_id(create_ticket(client, title="Priya's issue"))
    logout(client)
    register(client, "rahul")
    create_ticket(client, title="Rahul's issue")
    titles = [t["title"] for t in client.get("/api/tickets").json()]
    assert titles == ["Rahul's issue"]
    assert client.get(f"/tickets/{priya_ticket}").status_code == 404
    logout(client)
    login(client, *ADMIN)
    assert len(client.get("/api/tickets").json()) == 2  # admin sees everything


def test_admin_can_promote_user_to_agent(client):
    register(client, "priya")
    logout(client)
    login(client, *ADMIN)
    assert client.get("/admin/users").status_code == 200
    client.post("/admin/users/2/role", data={"role": "agent"})
    logout(client)
    login(client, "priya", "Password123")
    ticket_id = new_ticket_id(create_ticket(client))
    client.post(f"/tickets/{ticket_id}/status", data={"new_status": "In Progress"})
    assert ticket_status(client, ticket_id) == "In Progress"


def test_non_admin_cannot_manage_users(client):
    register(client, "priya")
    assert client.get("/admin/users").status_code == 403
    assert client.post("/admin/users/1/role", data={"role": "user"}).status_code == 403


# ---------------------------------------------------------------- dashboard
def test_dashboard_counts(client):
    login(client, *ADMIN)
    first = new_ticket_id(create_ticket(client, priority="Critical"))
    create_ticket(client, priority="Low")
    create_ticket(client, priority="Low")
    client.post(f"/tickets/{first}/status", data={"new_status": "In Progress"})
    stats = client.get("/api/stats").json()
    assert stats["total"] == 3
    assert stats["by_status"] == {"Open": 2, "In Progress": 1, "Resolved": 0, "Closed": 0}
    assert stats["by_priority"]["Low"] == 2
    assert stats["by_priority"]["Critical"] == 1


# ---------------------------------------------------------------- attachments
def test_ticket_with_attachment_upload_and_download(client):
    login(client, *ADMIN)
    files = {"attachment": ("error screenshot.png", b"\x89PNG fake image bytes", "image/png")}
    ticket_id = new_ticket_id(create_ticket(client, files=files))
    data = client.get(f"/api/tickets/{ticket_id}").json()
    assert data["attachment_count"] == 1
    att = data["attachments"][0]
    assert att["name"] == "error_screenshot.png"
    assert att["storage_key"].startswith(f"attachments/ticket-{ticket_id}/")
    assert att["processing"]["status"] == "local"
    download = client.get(f"/attachments/{att['id']}/download")
    assert download.status_code == 200
    assert download.content == b"\x89PNG fake image bytes"


def test_add_attachment_to_existing_ticket(client):
    login(client, *ADMIN)
    ticket_id = new_ticket_id(create_ticket(client))
    r = client.post(
        f"/tickets/{ticket_id}/attachments",
        files={"file": ("logs.txt", b"error line 1\nerror line 2", "text/plain")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert client.get(f"/api/tickets/{ticket_id}").json()["attachment_count"] == 1


def test_disallowed_file_type_is_rejected(client):
    login(client, *ADMIN)
    files = {"attachment": ("virus.exe", b"MZ...", "application/octet-stream")}
    r = create_ticket(client, files=files)
    assert r.status_code == 400
    assert "not allowed" in r.text
    assert client.get("/api/tickets").json() == []


def test_oversized_file_is_rejected(client):
    login(client, *ADMIN)
    ticket_id = new_ticket_id(create_ticket(client))
    big = b"x" * (1024 * 1024 + 1)  # MAX_UPLOAD_MB is 1 in tests
    client.post(f"/tickets/{ticket_id}/attachments", files={"file": ("big.txt", big, "text/plain")})
    assert client.get(f"/api/tickets/{ticket_id}").json()["attachment_count"] == 0


def test_cannot_download_other_users_attachment(client):
    register(client, "priya")
    files = {"attachment": ("note.txt", b"private", "text/plain")}
    ticket_id = new_ticket_id(create_ticket(client, files=files))
    att_id = client.get(f"/api/tickets/{ticket_id}").json()["attachments"][0]["id"]
    logout(client)
    register(client, "rahul")
    assert client.get(f"/attachments/{att_id}/download").status_code == 404

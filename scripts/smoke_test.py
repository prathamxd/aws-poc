"""End-to-end smoke test against the deployed TicketDesk.

Covers login, ticket creation, status workflow, dashboard API, S3 upload,
Lambda processing (object tags) and presigned download. Prints a PASS/FAIL
table and saves it to docs/evidence/ for the POC document.

Usage (from the repository root):
    python scripts/smoke_test.py                      # URL + admin password from Terraform/Secrets Manager
    python scripts/smoke_test.py --url http://1.2.3.4 --password <admin-password>
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class Client:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())

    def request(self, method: str, path: str, data: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            resp = self.opener.open(req, timeout=20)
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as err:  # 3xx/4xx/5xx arrive here because redirects are not followed
            return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()

    def get(self, path: str):
        return self.request("GET", path)

    def post_form(self, path: str, fields: dict):
        body = urllib.parse.urlencode(fields).encode()
        return self.request("POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"})

    def post_multipart(self, path: str, fields: dict, files: dict):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for name, (filename, content, ctype) in files.items():
            head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {ctype}\r\n\r\n").encode()
            parts.append(head + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request("POST", path, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def json(self, path: str):
        status, _, body = self.get(path)
        return status, (json.loads(body) if body else None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="Base URL, e.g. http://13.200.1.2")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", help="Admin password (default: read from Secrets Manager)")
    parser.add_argument("--lambda-timeout", type=int, default=90, help="Seconds to wait for Lambda tags")
    args = parser.parse_args()

    if not args.url or not args.password:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _common import admin_password, terraform_outputs

        outputs = terraform_outputs()
        args.url = args.url or outputs["app_url"]
        args.password = args.password or admin_password(outputs)

    c = Client(args.url)
    results: list[tuple[str, str, bool, str]] = []

    def check(test_id: str, name: str, ok: bool, detail: str = "") -> bool:
        results.append((test_id, name, bool(ok), detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {test_id} {name} {('- ' + detail) if detail else ''}", flush=True)
        return ok

    # 1. Health
    status, body = c.json("/health")
    check("ST-01", "Health endpoint: app + database up", status == 200 and body.get("database") == "ok",
          f"HTTP {status} {body}")
    check("ST-02", "Attachments configured for S3", (body or {}).get("storage") == "s3", f"storage={(body or {}).get('storage')}")

    # 2. Auth
    status, headers, _ = c.get("/dashboard")
    check("ST-03", "Anonymous user redirected to login", status == 303 and headers.get("location") == "/login", f"HTTP {status}")
    status, _, _ = c.post_form("/login", {"username": args.username, "password": "definitely-wrong"})
    check("ST-04", "Wrong password rejected", status == 401, f"HTTP {status}")
    status, headers, _ = c.post_form("/login", {"username": args.username, "password": args.password})
    if not check("ST-05", "Admin login", status == 303 and headers.get("location") == "/dashboard", f"HTTP {status}"):
        finish(args.url, results)

    # 3. Create ticket with an attachment (goes to S3 -> triggers Lambda)
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    content = f"TicketDesk smoke test file {uuid.uuid4()}\n".encode()
    status, headers, _ = c.post_multipart(
        "/tickets/new",
        {"title": f"Smoke test {stamp}", "description": "Created by scripts/smoke_test.py", "priority": "High"},
        {"attachment": ("smoke-test.txt", content, "text/plain")},
    )
    created = status == 303 and headers.get("location", "").startswith("/tickets/")
    check("ST-06", "Create ticket with attachment", created, f"HTTP {status} -> {headers.get('location')}")
    if not created:
        finish(args.url, results)
    ticket_id = int(headers["location"].rsplit("/", 1)[1])

    status, ticket = c.json(f"/api/tickets/{ticket_id}")
    check("ST-07", "Ticket stored in RDS with status Open", status == 200 and ticket["status"] == "Open",
          f"ticket #{ticket_id} status={ticket.get('status') if ticket else None}")
    attachments = (ticket or {}).get("attachments", [])
    check("ST-08", "Attachment stored in S3", len(attachments) == 1 and attachments[0]["storage_key"].startswith("attachments/"),
          attachments[0]["storage_key"] if attachments else "no attachment")

    # 4. Status workflow
    for i, new_status in enumerate(["In Progress", "Resolved", "Closed"], start=9):
        c.post_form(f"/tickets/{ticket_id}/status", {"new_status": new_status, "note": "smoke test"})
        _, t = c.json(f"/api/tickets/{ticket_id}")
        check(f"ST-{i:02d}", f"Status update -> {new_status}", t and t["status"] == new_status, f"status={t and t['status']}")
    c.post_form(f"/tickets/{ticket_id}/status", {"new_status": "Open"})
    _, t = c.json(f"/api/tickets/{ticket_id}")
    check("ST-12", "Invalid transition Closed -> Open blocked", t and t["status"] == "Closed", f"status={t and t['status']}")

    # 5. Lambda processing (reads object tags written by the Lambda)
    processing = {}
    deadline = time.time() + args.lambda_timeout
    while time.time() < deadline:
        _, t = c.json(f"/api/tickets/{ticket_id}")
        processing = t["attachments"][0]["processing"] if t and t.get("attachments") else {}
        if processing.get("status") in ("processed", "rejected"):
            break
        time.sleep(3)
    check("ST-13", "S3 event triggered Lambda (object tagged)", processing.get("status") == "processed", json.dumps(processing))

    # 6. Download through presigned URL
    if attachments:
        status, headers, _ = c.get(f"/attachments/{attachments[0]['id']}/download")
        location = headers.get("location", "")
        ok = status == 302 and ".amazonaws.com" in location
        if ok:
            with urllib.request.urlopen(location, timeout=20) as resp:
                ok = resp.read() == content
        check("ST-14", "Download via S3 presigned URL", ok, f"HTTP {status}")

    # 7. File validation
    status, _, _ = c.post_multipart(
        "/tickets/new",
        {"title": "Should be rejected", "description": "exe upload", "priority": "Low"},
        {"attachment": ("tool.exe", b"MZ fake", "application/octet-stream")},
    )
    check("ST-15", "Disallowed file type rejected", status == 400, f"HTTP {status}")

    # 8. Dashboard API
    status, stats = c.json("/api/stats")
    check("ST-16", "Dashboard summary available", status == 200 and stats["total"] >= 1, json.dumps(stats))

    finish(args.url, results)


def finish(url: str, results: list) -> None:
    passed = sum(1 for r in results if r[2])
    total = len(results)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# Smoke test results - {stamp}",
        "",
        f"Target: {url}  ",
        f"Result: **{passed}/{total} passed**",
        "",
        "| ID | Test | Result | Detail |",
        "|----|------|--------|--------|",
    ]
    lines += [f"| {i} | {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')[:150]} |" for i, n, ok, d in results]
    out_dir = REPO_ROOT / "docs" / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"smoke-test-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{total} passed. Report saved to {out_file.relative_to(REPO_ROOT)}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

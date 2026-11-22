# TicketDesk – Manual Test Cases

Environment: deployed app (`terraform output app_url`), AWS console. Fill **Actual** and **Status** (PASS/FAIL) while testing and attach screenshots in the POC document.

Tester: ____________  Date: ____________  App version (`/health`): ____________

| ID | Area | Steps | Expected result | Actual | Status |
|----|------|-------|-----------------|--------|--------|
| TC-01 | Login | Log in as `admin` with the password from Secrets Manager | Redirected to Dashboard; username and role shown top right | | |
| TC-02 | Login | Log in with a wrong password | "Invalid username or password", stays on login page; a `Failed login attempt` line appears in CloudWatch | | |
| TC-03 | Access control | Log out, open `/dashboard` directly | Redirected to `/login` | | |
| TC-04 | Registration | Register `testuser1` with an 8+ character password | Account created, logged in, role `user` | | |
| TC-05 | Registration | Register `testuser1` again | "That username is already taken." | | |
| TC-06 | Create ticket | As `testuser1`, create a ticket without attachment, priority High | Ticket page shows status **Open**; History shows "Open by testuser1 – Ticket created" | | |
| TC-07 | Attachment → S3 | Create a ticket with a PNG/PDF under 5 MB | File listed on the ticket; object exists in S3 under `attachments/ticket-<id>/` | | |
| TC-08 | Lambda | Refresh the ticket after ~5 seconds | Lambda column shows **processed**; S3 object tags `lambda-status=processed`; Lambda log has `attachment_processed` | | |
| TC-09 | Download | Click the attachment name | File downloads through a presigned S3 URL (valid 5 minutes) | | |
| TC-10 | Validation | Upload `test.exe` | "File type '.exe' is not allowed…"; nothing stored | | |
| TC-11 | Validation | Upload a file larger than 5 MB | "The file is larger than 5 MB." | | |
| TC-12 | RBAC | As `testuser1`, open own ticket | No status form ("A support agent will update the status") | | |
| TC-13 | RBAC | As `testuser1`, list tickets | Only own tickets visible; another user's ticket URL shows "Ticket not found" | | |
| TC-14 | Workflow | As admin, move a ticket Open → In Progress → Resolved → Closed | Each change saved; History shows every transition with user and time | | |
| TC-15 | Workflow | On a Resolved ticket choose In Progress (re-open) | Status In Progress | | |
| TC-16 | Workflow | On an Open ticket, check the "Move to" list | Only "In Progress" offered (no skipping to Closed); a forged POST is refused (smoke test ST-12) | | |
| TC-17 | Admin | Admin → Users → set `testuser1` to `agent` | `testuser1` now sees all tickets and can change status | | |
| TC-18 | Dashboard | Compare Dashboard counts with the Tickets list filtered by each status | Counts match | | |
| TC-19 | Persistence (RDS) | Run `sudo systemctl restart ticketdesk` via Session Manager, then reload | App back within ~20 s; all tickets still present | | |
| TC-20 | Monitoring | Open the CloudWatch dashboard and log group `/ticketdesk-poc/app` | Metrics and recent log lines for the actions above | | |

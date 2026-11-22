"""TicketDesk web application (FastAPI + server-rendered Jinja2 pages).

Pages : /login /register /dashboard /tickets /tickets/new /tickets/{id} /admin/users
API   : /health /api/tickets /api/tickets/{id} /api/stats   (OpenAPI docs at /docs outside production)
"""
from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import get_db, init_db
from .models import Attachment, Ticket, TicketEvent, User, utcnow
from .security import hash_password, verify_password
from .storage import KEY_PREFIX, StorageError, get_storage, safe_filename
from .workflow import PRIORITIES, STATUSES, can_transition, next_statuses

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ticketdesk")

BASE_DIR = Path(__file__).resolve().parent
ROLES = ["user", "agent", "admin"]
STAFF_ROLES = {"agent", "admin"}
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")

settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(settings)
    log.info("TicketDesk %s started (env=%s)", settings.app_version, settings.app_env)
    yield


app = FastAPI(
    title="TicketDesk",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None,
)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", max_age=8 * 3600)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# --------------------------------------------------------------------------- helpers
def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("flashes", []).append([category, message])


def render(request: Request, template: str, context: dict | None = None, status_code: int = 200):
    ctx = {
        "current_user": getattr(request.state, "user", None),
        "flashes": request.session.pop("flashes", []),
        "version": settings.app_version,
        "app_env": settings.app_env,
    }
    ctx.update(context or {})
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def error_page(request: Request, status_code: int, title: str, message: str):
    return render(request, "error.html", {"title": title, "message": message}, status_code=status_code)


def is_staff(user: User) -> bool:
    return user.role in STAFF_ROLES


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id else None
    request.state.user = user
    return user


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=303, detail="Login required", headers={"Location": "/login"})
    return user


def require_api_user(user: Optional[User] = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def visible_tickets(user: User):
    stmt = select(Ticket)
    if not is_staff(user):
        stmt = stmt.where(Ticket.created_by_id == user.id)
    return stmt


def get_visible_ticket(db: Session, ticket_id: int, user: User) -> Optional[Ticket]:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (not is_staff(user) and ticket.created_by_id != user.id):
        return None
    return ticket


def ticket_counts(db: Session, user: User, column) -> dict:
    stmt = select(column, func.count(Ticket.id)).group_by(column)
    if not is_staff(user):
        stmt = stmt.where(Ticket.created_by_id == user.id)
    return {key: count for key, count in db.execute(stmt).all()}


def validate_upload(upload: UploadFile) -> tuple[str, int, str]:
    name = safe_filename(upload.filename or "")
    ext = Path(name).suffix.lower()
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise ValueError(f"File type '{ext or 'none'}' is not allowed. Allowed types: {allowed}")
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size == 0:
        raise ValueError("The file is empty.")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(f"The file is larger than {settings.max_upload_mb} MB.")
    content_type = upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return name, size, content_type


def save_attachment(db: Session, ticket: Ticket, upload: UploadFile, user: User) -> Attachment:
    name, size, content_type = validate_upload(upload)
    key = f"{KEY_PREFIX}ticket-{ticket.id}/{uuid.uuid4().hex[:12]}-{name}"
    get_storage(settings).save(key, upload.file, content_type)
    attachment = Attachment(
        ticket_id=ticket.id,
        original_name=name,
        storage_key=key,
        content_type=content_type,
        size_bytes=size,
        uploaded_by_id=user.id,
    )
    db.add(attachment)
    ticket.updated_at = utcnow()
    log.info("Attachment %s (%d bytes) uploaded to ticket %s by %s", key, size, ticket.id, user.username)
    return attachment


def ticket_to_dict(ticket: Ticket, with_attachments: bool = False) -> dict:
    data = {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_by": ticket.created_by.username,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "attachment_count": len(ticket.attachments),
    }
    if with_attachments:
        storage = get_storage(settings)
        data["attachments"] = [
            {
                "id": a.id,
                "name": a.original_name,
                "size_bytes": a.size_bytes,
                "content_type": a.content_type,
                "storage_key": a.storage_key,
                "processing": storage.processing_status(a.storage_key),
            }
            for a in ticket.attachments
        ]
    return data


# --------------------------------------------------------------------------- health
@app.get("/health")
def health(db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        log.exception("Health check: database unreachable")
        db_ok = False
    body = {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
        "storage": "s3" if settings.s3_bucket else "local",
        "version": settings.app_version,
        "environment": settings.app_env,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


# --------------------------------------------------------------------------- auth
@app.get("/")
def index(user: Optional[User] = Depends(get_current_user)):
    return RedirectResponse("/dashboard" if user else "/login", status_code=303)


@app.get("/login")
def login_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "login.html")


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    clean = username.strip().lower()
    user = db.scalar(select(User).where(User.username == clean))
    if user is None or not verify_password(password, user.password_hash):
        log.warning("Failed login attempt for username '%s'", clean[:50])
        return render(request, "login.html", {"error": "Invalid username or password.", "username": clean}, 401)
    request.session.clear()
    request.session["user_id"] = user.id
    log.info("User '%s' logged in", user.username)
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/register")
def register_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "register.html")


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    clean = username.strip().lower()
    error = None
    if not USERNAME_RE.match(clean):
        error = "Username must be 3-30 characters: lowercase letters, numbers, dot, dash or underscore."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != confirm_password:
        error = "Passwords do not match."
    elif db.scalar(select(User.id).where(User.username == clean)):
        error = "That username is already taken."
    if error:
        return render(request, "register.html", {"error": error, "username": clean}, 400)

    user = User(username=clean, password_hash=hash_password(password), role="user")
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    flash(request, f"Welcome, {clean}! Your account is ready.", "success")
    log.info("New user registered: '%s'", clean)
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# --------------------------------------------------------------------------- dashboard
@app.get("/dashboard")
def dashboard(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    by_status = {s: 0 for s in STATUSES}
    by_status.update(ticket_counts(db, user, Ticket.status))
    by_priority = {p: 0 for p in PRIORITIES}
    by_priority.update(ticket_counts(db, user, Ticket.priority))
    recent = db.scalars(visible_tickets(user).order_by(Ticket.updated_at.desc()).limit(5)).all()
    return render(
        request,
        "dashboard.html",
        {
            "by_status": by_status,
            "by_priority": by_priority,
            "total": sum(by_status.values()),
            "recent": recent,
            "storage_kind": get_storage(settings).kind,
        },
    )


# --------------------------------------------------------------------------- tickets
@app.get("/tickets")
def list_tickets(
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    stmt = visible_tickets(user)
    if status in STATUSES:
        stmt = stmt.where(Ticket.status == status)
    if q and q.strip():
        stmt = stmt.where(Ticket.title.ilike(f"%{q.strip()}%"))
    tickets = db.scalars(stmt.order_by(Ticket.id.desc())).all()
    return render(
        request,
        "tickets.html",
        {"tickets": tickets, "statuses": STATUSES, "selected_status": status or "", "q": q or ""},
    )


@app.get("/tickets/new")
def new_ticket_page(request: Request, user: User = Depends(require_user)):
    return render(request, "ticket_new.html", {"priorities": PRIORITIES, "form": {}, **upload_rules()})


def upload_rules() -> dict:
    return {
        "allowed_extensions": ", ".join(sorted(settings.allowed_extensions)),
        "max_upload_mb": settings.max_upload_mb,
    }


@app.post("/tickets/new")
def create_ticket(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    priority: str = Form("Medium"),
    attachment: Optional[UploadFile] = File(None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    title, description = title.strip(), description.strip()
    form = {"title": title, "description": description, "priority": priority}
    error = None
    if not title or len(title) > 200:
        error = "Title is required (max 200 characters)."
    elif not description:
        error = "Description is required."
    has_file = attachment is not None and bool(attachment.filename)
    if error is None and has_file:
        try:
            validate_upload(attachment)
        except ValueError as exc:
            error = str(exc)
    if error:
        context = {"priorities": PRIORITIES, "form": form, "error": error, **upload_rules()}
        return render(request, "ticket_new.html", context, 400)

    ticket = Ticket(
        title=title,
        description=description,
        priority=priority if priority in PRIORITIES else "Medium",
        status="Open",
        created_by_id=user.id,
    )
    db.add(ticket)
    db.flush()  # assigns ticket.id
    db.add(TicketEvent(ticket_id=ticket.id, from_status=None, to_status="Open", changed_by_id=user.id, note="Ticket created"))
    if has_file:
        try:
            save_attachment(db, ticket, attachment, user)
        except StorageError:
            db.rollback()
            context = {
                "priorities": PRIORITIES,
                "form": form,
                "error": "The attachment could not be stored. Please try again.",
                **upload_rules(),
            }
            return render(request, "ticket_new.html", context, 502)
    db.commit()
    log.info("Ticket %s created by %s (priority=%s)", ticket.id, user.username, ticket.priority)
    flash(request, f"Ticket #{ticket.id} created.", "success")
    return RedirectResponse(f"/tickets/{ticket.id}", status_code=303)


@app.get("/tickets/{ticket_id}")
def ticket_detail(request: Request, ticket_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ticket = get_visible_ticket(db, ticket_id, user)
    if ticket is None:
        return error_page(request, 404, "Ticket not found", f"Ticket #{ticket_id} does not exist or you cannot see it.")
    storage = get_storage(settings)
    attachments = [{"item": a, "processing": storage.processing_status(a.storage_key)} for a in ticket.attachments]
    return render(
        request,
        "ticket_detail.html",
        {
            "ticket": ticket,
            "attachments": attachments,
            "events": ticket.events,
            "next_statuses": next_statuses(ticket.status) if is_staff(user) else [],
            "can_upload": ticket.status != "Closed",
            **upload_rules(),
        },
    )


@app.post("/tickets/{ticket_id}/status")
def update_status(
    request: Request,
    ticket_id: int,
    new_status: str = Form(...),
    note: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not is_staff(user):
        log.warning("User '%s' tried to change status of ticket %s", user.username, ticket_id)
        return error_page(request, 403, "Not allowed", "Only support agents and admins can change ticket status.")
    ticket = get_visible_ticket(db, ticket_id, user)
    if ticket is None:
        return error_page(request, 404, "Ticket not found", f"Ticket #{ticket_id} does not exist.")
    if not can_transition(ticket.status, new_status):
        flash(request, f"A ticket cannot move from '{ticket.status}' to '{new_status}'.", "error")
        return RedirectResponse(f"/tickets/{ticket.id}", status_code=303)

    old_status = ticket.status
    ticket.status = new_status
    ticket.updated_at = utcnow()
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            from_status=old_status,
            to_status=new_status,
            changed_by_id=user.id,
            note=note.strip()[:500] or None,
        )
    )
    db.commit()
    log.info("Ticket %s status %s -> %s by %s", ticket.id, old_status, new_status, user.username)
    flash(request, f"Status changed to {new_status}.", "success")
    return RedirectResponse(f"/tickets/{ticket.id}", status_code=303)


@app.post("/tickets/{ticket_id}/attachments")
def upload_attachment(
    request: Request,
    ticket_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    ticket = get_visible_ticket(db, ticket_id, user)
    if ticket is None:
        return error_page(request, 404, "Ticket not found", f"Ticket #{ticket_id} does not exist.")
    if ticket.status == "Closed":
        flash(request, "Closed tickets cannot receive new attachments.", "error")
    elif not file.filename:
        flash(request, "Choose a file to upload.", "error")
    else:
        try:
            save_attachment(db, ticket, file, user)
            db.commit()
            flash(request, f"Uploaded {safe_filename(file.filename)}.", "success")
        except ValueError as exc:
            db.rollback()
            flash(request, str(exc), "error")
        except StorageError:
            db.rollback()
            flash(request, "The attachment could not be stored. Please try again.", "error")
    return RedirectResponse(f"/tickets/{ticket.id}", status_code=303)


@app.get("/attachments/{attachment_id}/download")
def download_attachment(
    request: Request,
    attachment_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or get_visible_ticket(db, attachment.ticket_id, user) is None:
        return error_page(request, 404, "Attachment not found", "This attachment does not exist or you cannot see it.")
    return get_storage(settings).download_response(
        attachment.storage_key, attachment.original_name, attachment.content_type
    )


# --------------------------------------------------------------------------- admin
@app.get("/admin/users")
def admin_users(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        return error_page(request, 403, "Not allowed", "Only admins can manage users.")
    counts = dict(db.execute(select(Ticket.created_by_id, func.count(Ticket.id)).group_by(Ticket.created_by_id)).all())
    users = db.scalars(select(User).order_by(User.id)).all()
    return render(request, "admin_users.html", {"users": users, "counts": counts, "roles": ROLES})


@app.post("/admin/users/{user_id}/role")
def change_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if user.role != "admin":
        return error_page(request, 403, "Not allowed", "Only admins can manage users.")
    target = db.get(User, user_id)
    if target is None or role not in ROLES:
        flash(request, "Unknown user or role.", "error")
    elif target.id == user.id:
        flash(request, "You cannot change your own role.", "error")
    else:
        target.role = role
        db.commit()
        log.info("Admin %s changed role of %s to %s", user.username, target.username, role)
        flash(request, f"{target.username} is now {role}.", "success")
    return RedirectResponse("/admin/users", status_code=303)


# --------------------------------------------------------------------------- JSON API
@app.get("/api/tickets")
def api_tickets(user: User = Depends(require_api_user), db: Session = Depends(get_db)):
    tickets = db.scalars(visible_tickets(user).order_by(Ticket.id)).unique().all()
    return [ticket_to_dict(t) for t in tickets]


@app.get("/api/tickets/{ticket_id}")
def api_ticket(ticket_id: int, user: User = Depends(require_api_user), db: Session = Depends(get_db)):
    ticket = get_visible_ticket(db, ticket_id, user)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket_to_dict(ticket, with_attachments=True)


@app.get("/api/stats")
def api_stats(user: User = Depends(require_api_user), db: Session = Depends(get_db)):
    by_status = {s: 0 for s in STATUSES}
    by_status.update(ticket_counts(db, user, Ticket.status))
    by_priority = {p: 0 for p in PRIORITIES}
    by_priority.update(ticket_counts(db, user, Ticket.priority))
    return {"total": sum(by_status.values()), "by_status": by_status, "by_priority": by_priority}

"""FreeTools Hub optional backend.

The tools themselves run entirely in the browser. This service only provides:
  * GET  /api/health   — health check for hosting platforms
  * POST /api/contact  — receives contact-form messages (stored to a file and optionally emailed)
"""

import json
import logging
import smtplib
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from .config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("freetools")

VERSION = "1.0.0"


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    subject: str = Field(default="", max_length=150)
    message: str = Field(min_length=10, max_length=5000)
    website: str = Field(default="", max_length=200)  # honeypot: real users leave it empty

    @field_validator("name", "subject", "message")
    @classmethod
    def strip_and_clean(cls, v: str) -> str:
        # strip control characters except newlines/tabs
        return "".join(ch for ch in v.strip() if ch in "\n\t" or ord(ch) >= 32)

    @field_validator("name", "subject")
    @classmethod
    def single_line(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("must be a single line")
        return v


class RateLimiter:
    """In-memory sliding-window limiter. Adequate for a single small instance."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:  # bound memory
                self._hits.clear()
            return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="FreeTools Hub API",
        version=VERSION,
        docs_url="/api/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.app_env != "production" else None,
    )
    app.state.settings = settings
    app.state.limiter = RateLimiter()
    store_lock = threading.Lock()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def limit_body_and_headers(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return JSONResponse({"detail": "Request body too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # Return field names and reasons only — never echo the submitted values back.
        errors = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
        return JSONResponse({"detail": "Invalid input. " + "; ".join(errors)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    def client_ip(request: Request) -> str:
        if settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def send_email(msg: ContactIn) -> None:
        if not (settings.smtp_host and settings.contact_to_email):
            return
        em = EmailMessage()
        em["Subject"] = f"[FreeTools Hub] {msg.subject or 'Contact form message'}"
        em["From"] = settings.smtp_from or settings.smtp_username
        em["To"] = settings.contact_to_email
        em["Reply-To"] = msg.email
        em.set_content(f"From: {msg.name} <{msg.email}>\n\n{msg.message}")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls()
            if settings.smtp_username:
                s.login(settings.smtp_username, settings.smtp_password)
            s.send_message(em)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION}

    @app.post("/api/contact", status_code=201)
    def contact(payload: ContactIn, request: Request):
        if payload.website:
            # Honeypot filled: pretend success so bots learn nothing.
            log.info("Contact honeypot triggered")
            return {"ok": True}
        ip = client_ip(request)
        if not request.app.state.limiter.allow(f"contact:{ip}", settings.contact_rate_limit, settings.contact_rate_window_seconds):
            raise HTTPException(status_code=429, detail="Too many messages. Please try again later or use email.")
        record = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "name": payload.name,
            "email": payload.email,
            "subject": payload.subject,
            "message": payload.message,
        }
        path = Path(settings.contact_store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with store_lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Log the event only — never the message contents or email address.
        log.info("Contact message stored (%d chars)", len(payload.message))
        try:
            send_email(payload)
        except Exception as e:  # message is already stored; email is best-effort
            log.warning("Email forwarding failed: %s", type(e).__name__)
        return {"ok": True}

    return app


app = create_app()

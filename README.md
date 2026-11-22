# FreeTools Hub — Backend (optional)

A tiny FastAPI service. **The website works without it** — all 47 tools run in the browser.
It exists only to provide an on-site contact form without paid services.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Health check (`{"status":"ok"}`) |
| `POST /api/contact` | Validates and stores a contact message to `CONTACT_STORE_PATH` (JSON lines); optionally forwards it by SMTP |

Security: strict CORS allow-list, 16 KB body limit, per-IP rate limit, honeypot field, control-character stripping, no message content in logs, docs disabled in production.

## Run locally
```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt
cp .env.example .env          # then set APP_ENV=development, CORS_ORIGINS=http://localhost:3000
uvicorn app.main:app --reload --port 8000
pytest -q
```
Reading messages: `data/messages.jsonl` (one JSON object per line).

See `../DEPLOYMENT.md` for hosting.

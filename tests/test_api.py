import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def store(tmp_path):
    return tmp_path / "messages.jsonl"


@pytest.fixture
def client(store):
    settings = Settings(
        cors_origins="https://example.com",
        contact_store_path=str(store),
        contact_rate_limit=3,
        smtp_host="",
        _env_file=None,
    )
    return TestClient(create_app(settings))


VALID = {"name": "Ana", "email": "ana@example.com", "subject": "Bug", "message": "The GPA tool shows a wrong value."}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_contact_stores_message(client, store):
    r = client.post("/api/contact", json=VALID)
    assert r.status_code == 201
    rec = json.loads(store.read_text(encoding="utf-8").strip())
    assert rec["email"] == "ana@example.com" and rec["message"] == VALID["message"]


@pytest.mark.parametrize(
    "patch",
    [
        {"email": "not-an-email"},
        {"message": "short"},
        {"name": ""},
        {"message": "x" * 5001},
        {"name": "a\nb"},
    ],
)
def test_contact_validation(client, store, patch):
    r = client.post("/api/contact", json={**VALID, **patch})
    assert r.status_code == 422
    assert not store.exists()
    # submitted values are not echoed back
    assert "not-an-email" not in r.text


def test_honeypot_silently_drops(client, store):
    r = client.post("/api/contact", json={**VALID, "website": "http://spam"})
    assert r.status_code == 201
    assert not store.exists()


def test_rate_limit(client):
    for _ in range(3):
        assert client.post("/api/contact", json=VALID).status_code == 201
    r = client.post("/api/contact", json=VALID)
    assert r.status_code == 429


def test_body_size_limit(client):
    r = client.post("/api/contact", content=b"{" + b" " * 20000 + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_cors_allowed_and_blocked(client):
    ok = client.options("/api/contact", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://example.com"
    bad = client.options("/api/contact", headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_control_characters_stripped(client, store):
    client.post("/api/contact", json={**VALID, "message": "Hello\x00\x07 there, this is fine"})
    rec = json.loads(store.read_text(encoding="utf-8"))
    assert rec["message"] == "Hello there, this is fine"


def test_unknown_route_404(client):
    assert client.get("/api/nope").status_code == 404

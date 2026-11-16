"""F6 webhook signature tests. Offline — FastAPI TestClient, no background triage is triggered
(empty payloads add no tasks, so Gemini is never called).

Run from the project root:  python -m pytest tests/test_webhook.py
"""
import hashlib
import hmac

import redteam.harness  # noqa: F401  stub app.sheets before app.main -> app.router loads it
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(settings.META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_unsigned_post_is_rejected():
    settings.ENVIRONMENT = "production"
    assert client.post("/webhook", content=b"{}").status_code == 403


def test_bad_signature_is_rejected():
    settings.ENVIRONMENT = "production"
    r = client.post("/webhook", content=b"{}",
                    headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 403


def test_unknown_environment_fails_closed():
    settings.ENVIRONMENT = "staging-typo"  # not "test" -> must still verify
    assert client.post("/webhook", content=b"{}").status_code == 403


def test_valid_signature_is_accepted():
    settings.ENVIRONMENT = "production"
    body = b'{"entry": []}'
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200


def test_test_environment_skips_verification():
    settings.ENVIRONMENT = "test"
    assert client.post("/webhook", content=b'{"entry": []}').status_code == 200


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

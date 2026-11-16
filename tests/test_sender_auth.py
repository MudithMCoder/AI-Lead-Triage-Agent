"""F10 sender authentication (DMARC) flagging. Offline — no Gemini, no network.

Run from the project root:  python -m pytest tests/test_sender_auth.py
"""
from pathlib import Path

from app.config import settings
from app.email_client import parse_email

CASES = Path(__file__).resolve().parent.parent / "redteam" / "cases"


def _mail(auth: str | None, body: str = "Hi, I'd like a quote for a photoshoot.") -> bytes:
    hdr = f"Authentication-Results: {auth}\r\n" if auth is not None else ""
    return (f"From: Kamal <k@example.com>\r\nTo: shop@example.com\r\nSubject: Booking\r\n"
            f"Message-ID: <auth@mail>\r\n{hdr}\r\n{body}").encode()


def test_dmarc_pass_is_not_flagged():
    settings.REQUIRE_SENDER_AUTH = True
    m = parse_email(_mail("mx.google.com; spf=pass; dmarc=pass header.from=example.com"))
    assert "sender_unauthenticated" not in m.flags


def test_dmarc_fail_is_flagged():
    settings.REQUIRE_SENDER_AUTH = True
    m = parse_email(_mail("mx.google.com; spf=fail; dmarc=fail header.from=example.com"))
    assert "sender_unauthenticated" in m.flags


def test_missing_auth_header_is_flagged():
    settings.REQUIRE_SENDER_AUTH = True
    m = parse_email(_mail(None))
    assert "sender_unauthenticated" in m.flags


def test_untrusted_authserv_claiming_pass_does_not_count():
    settings.REQUIRE_SENDER_AUTH = True
    # authserv-id is not our trusted MX, so its dmarc=pass must be ignored → flagged.
    m = parse_email(_mail("evil.attacker.test; dmarc=pass header.from=example.com"))
    assert "sender_unauthenticated" in m.flags


def test_disabled_when_require_sender_auth_false():
    settings.REQUIRE_SENDER_AUTH = False
    assert "sender_unauthenticated" not in parse_email(_mail(None)).flags


def test_case_files_pass_and_fail():
    settings.REQUIRE_SENDER_AUTH = True
    passed = parse_email((CASES / "benign_dmarc_pass.eml").read_bytes())
    failed = parse_email((CASES / "f10_dmarc_fail.eml").read_bytes())
    assert "sender_unauthenticated" not in passed.flags
    assert "sender_unauthenticated" in failed.flags
    settings.REQUIRE_SENDER_AUTH = False  # restore the harness/offline default


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

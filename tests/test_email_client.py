"""Run from the project root:  python -m tests.test_email_client"""
from app.config import settings
from app.email_client import parse_email


def _mail(sender: str, extra_headers: str = "", body: str = "Hi, I want to book a photoshoot.") -> bytes:
    return (f"From: Kamal <{sender}>\r\nTo: shop@example.com\r\nSubject: Booking\r\n"
            f"Message-ID: <abc@mail>\r\n{extra_headers}\r\n{body}").encode()


def test_normal_email_is_parsed():
    m = parse_email(_mail("Kamal@Example.com"))
    assert m.platform == "email"
    assert m.sender_id == "kamal@example.com"
    assert m.text == "Subject: Booking\n\nHi, I want to book a photoshoot."
    assert m.raw_event == {"subject": "Booking", "message_id": "<abc@mail>"}


def test_html_only_email_is_stripped():
    html = "Content-Type: text/html\r\n"
    m = parse_email(_mail("a@b.com", html, "<p>Need a <b>quote</b></p>"))
    assert "Need a" in m.text and "<b>" not in m.text


def test_loop_protection_skips_machines_lists_and_self():
    settings.EMAIL_ADDRESS = "shop@example.com"
    assert parse_email(_mail("noreply@service.com")) is None
    assert parse_email(_mail("MAILER-DAEMON@gmail.com")) is None
    assert parse_email(_mail("shop@example.com")) is None
    assert parse_email(_mail("a@b.com", "Auto-Submitted: auto-replied\r\n")) is None
    assert parse_email(_mail("a@b.com", "Precedence: bulk\r\n")) is None
    assert parse_email(_mail("a@b.com", "List-Id: <news.example.com>\r\n")) is None
    assert parse_email(_mail("a@b.com", "Auto-Submitted: no\r\n")) is not None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

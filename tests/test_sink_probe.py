"""D4 sink probe (the deferred F2/F3 end-to-end test), offline — no Gemini, no network.

Run from the project root:  python -m tests.test_sink_probe
Feeds hand-built TriageResult objects straight into route_triaged_message with the harness
fakes, proving the reply and CRM sinks are safe in code regardless of what the model emits.
"""
import asyncio

from redteam import harness  # installs fake app.sheets, patches router senders
from app import router
from app.config import settings
from app.models import (ExtractedEntities, IncomingMessage, MessageCategory, TriageResult)


def _route(suggested_reply="hello", category=MessageCategory.LEAD, urgency=3,
           requires_human=False, flags=None, name=None, phone=None, summary="s",
           allowed_domains=None, allowed_phones=None):
    settings.URGENCY_ALERT_THRESHOLD = 7
    settings.MAX_REPLY_CHARS = 600
    settings.BUSINESS_ALLOWED_DOMAINS = allowed_domains or []
    settings.BUSINESS_PHONES = allowed_phones or []
    harness._current = harness.ActionLog(case="t", run=1, model="m", commit="c", timestamp="t")
    incoming = IncomingMessage(platform="email", sender_id="x@example.com", text="hi",
                               raw_event={}, flags=flags or [])
    result = TriageResult(category=category, urgency_score=urgency, summary=summary,
                          entities=ExtractedEntities(name=name, phone=phone),
                          suggested_reply=suggested_reply, requires_human=requires_human)
    asyncio.run(router.route_triaged_message(incoming, result))
    return harness._current


# --- F2: reply relay blocked at the sink ---

def test_reply_with_non_allowlisted_url_is_blocked():
    log = _route(suggested_reply="Please pay at https://evil.example/pay")
    assert not log.replied and log.held
    assert "evil.example" in log.held_text


def test_reply_with_allowlisted_url_is_sent():
    log = _route(suggested_reply="Book here: https://studio.example/book",
                 allowed_domains=["studio.example"])
    assert log.replied and not log.held


def test_reply_with_non_allowlisted_email_is_blocked():
    log = _route(suggested_reply="Email me at attacker@evil.example")
    assert not log.replied and log.held


def test_reply_with_allowlisted_email_is_sent():
    log = _route(suggested_reply="Reach us at info@studio.example",
                 allowed_domains=["studio.example"])
    assert log.replied and not log.held


def test_reply_with_unlisted_phone_is_blocked():
    log = _route(suggested_reply="Call 0712223334 to confirm")
    assert not log.replied and log.held


def test_overlong_reply_is_blocked():
    log = _route(suggested_reply="x" * 601)
    assert not log.replied and log.held


# --- F3: CRM formula injection neutralised at the sink ---

def test_formula_leading_name_stored_neutralised_and_raw():
    log = _route(name='=HYPERLINK("http://evil.example","clickme")')
    [row] = log.sheet_rows
    assert row[3].startswith("'=")            # name cell defanged
    assert log.crm_value_input_option == "RAW"  # never USER_ENTERED


def test_formula_leading_summary_neutralised_in_alert():
    log = _route(summary="=cmd()", urgency=9, requires_human=True)
    assert log.alerted and "'=cmd()" in log.alert_text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

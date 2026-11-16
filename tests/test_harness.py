"""Run from the project root:  python -m tests.test_harness   (never calls Gemini)"""
import asyncio

from redteam import harness  # must be imported first: it installs the fake app.sheets
from app.config import settings
from app.models import ExtractedEntities, MessageCategory, TriageResult

RAW = (b"From: Kamal <kamal@example.com>\r\nTo: shop@example.com\r\nSubject: Booking\r\n"
       b"Message-ID: <abc@mail>\r\n\r\nHi, I want to book a photoshoot. 0771234567")


def _run(raw=RAW, **triage) -> tuple[harness.ActionLog, list]:
    """Runs one email through the harness with triage replaced by a fixed TriageResult."""
    result = TriageResult(
        category=triage.get("category", MessageCategory.LEAD),
        urgency_score=triage.get("urgency_score", 5),
        summary="test",
        entities=ExtractedEntities(name="Kamal", phone="0771234567"),
        suggested_reply=triage.get("suggested_reply", "Thanks, we'll be in touch!"),
        requires_human=triage.get("requires_human", False),
    )
    calls = []

    async def fake_triage(text):
        calls.append(text)
        return result

    harness.triage_message = fake_triage
    settings.URGENCY_ALERT_THRESHOLD = 7
    settings.EMAIL_ADDRESS = "shop@example.com"
    [log] = asyncio.run(harness.run_email(raw, "t", runs=1, delay=0))
    return log, calls


def test_spam_has_no_side_effects():
    log, _ = _run(category=MessageCategory.SPAM, suggested_reply="")
    assert not log.replied and not log.alerted and log.sheet_rows == []


def test_lead_gets_sheet_row_and_reply():
    log, _ = _run(category=MessageCategory.LEAD, requires_human=False)
    assert log.replied and log.reply_to == "kamal@example.com"
    assert log.reply_text == "Thanks, we'll be in touch!"
    [row] = log.sheet_rows
    assert row[1:] == ["email", "kamal@example.com", "Kamal", "0771234567", "lead", 5,
                       "Subject: Booking\n\nHi, I want to book a photoshoot. 0771234567", ""]
    assert not log.alerted and not log.messenger_sent


def test_requires_human_blocks_reply_but_logs_row():
    log, _ = _run(category=MessageCategory.SUPPORT, requires_human=True)
    assert not log.replied
    assert len(log.sheet_rows) == 1


def test_high_urgency_alerts_owner():
    log, _ = _run(urgency_score=9)
    assert log.alerted and "9/10" in log.alert_text


def test_parser_drop_skips_triage():
    log, calls = _run(raw=RAW.replace(b"kamal@example.com", b"noreply@example.com"))
    assert not log.parsed and log.triage is None and calls == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

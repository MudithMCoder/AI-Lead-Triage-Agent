"""Offline tests for the D3 deterministic router policy (F1, F4). No Gemini, no network.

Run from the project root:  python -m tests.test_router_policy
Imports redteam.harness first so app.sheets is faked and router's senders are patched to
record into an ActionLog instead of sending. Drives route_triaged_message directly.
"""
import asyncio

from redteam import harness  # installs fake app.sheets, patches router senders
from app import router
from app.config import settings
from app.models import (ExtractedEntities, IncomingMessage, MessageCategory, TriageResult)


def _route(category=MessageCategory.LEAD, urgency=3, requires_human=False, flags=None):
    settings.URGENCY_ALERT_THRESHOLD = 7
    harness._current = harness.ActionLog(case="t", run=1, model="m", commit="c", timestamp="t")
    incoming = IncomingMessage(platform="email", sender_id="x@example.com", text="hi",
                               raw_event={}, flags=flags or [])
    result = TriageResult(category=category, urgency_score=urgency, summary="s",
                          entities=ExtractedEntities(), suggested_reply="hello",
                          requires_human=requires_human)
    asyncio.run(router.route_triaged_message(incoming, result))
    return harness._current


def test_baseline_lead_auto_replies():
    log = _route()
    assert log.replied and not log.alerted and not log.held


def test_each_condition_alone_blocks_the_auto_reply():
    # flip exactly one of the four auto-reply conditions; each must stop the reply.
    for kwargs in (
        {"requires_human": True},
        {"flags": ["control_language"]},
        {"urgency": 7},  # == threshold, not below it
        {"category": MessageCategory.SUPPORT},
    ):
        log = _route(**kwargs)
        assert not log.replied, kwargs


def test_flagged_message_held_not_alerted():
    log = _route(category=MessageCategory.LEAD, urgency=10, flags=["control_language"])
    assert log.held and not log.alerted and not log.replied
    assert "control_language" in log.held_text
    assert len(log.sheet_rows) == 1  # flagged lead still logged to CRM
    assert log.sheet_rows[0][-1] == "control_language"  # 9th column records the flag


def test_unflagged_urgent_alerts_with_provenance():
    log = _route(category=MessageCategory.LEAD, urgency=9, requires_human=True)
    assert log.alerted and not log.held and not log.replied
    assert "model-assessed" in log.alert_text and "unverified" in log.alert_text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

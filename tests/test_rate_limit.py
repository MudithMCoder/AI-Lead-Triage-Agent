"""F9 per-sender rate limit. Offline, fake clock — no Gemini, no network.

Run from the project root:  python -m pytest tests/test_rate_limit.py
"""
import asyncio

import redteam.harness  # noqa: F401  stub app.sheets before app.main -> app.router loads it
from app import main
from app.config import settings
from app.models import IncomingMessage


def _reset():
    main._sender_hits.clear()
    main._notified.clear()
    settings.RATE_LIMIT_PER_SENDER = 5
    settings.RATE_LIMIT_WINDOW_SECONDS = 3600


def test_allows_up_to_limit_then_blocks():
    _reset()
    s = "flood@example.com"
    for i in range(5):
        assert main._rate_limited(s, 1000.0 + i) is False  # first 5 allowed
    assert main._rate_limited(s, 1005.0) is True            # 6th blocked


def test_window_slides():
    _reset()
    s = "slow@example.com"
    for i in range(5):
        main._rate_limited(s, i)
    assert main._rate_limited(s, 10) is True        # still inside the window
    assert main._rate_limited(s, 100000) is False   # old hits expired


def test_notice_fires_once_per_window():
    _reset()
    s = "x@example.com"
    assert main._should_notify(s, 0.0) is True
    assert main._should_notify(s, 100.0) is False       # same window
    assert main._should_notify(s, 3600.0) is True       # new window


def test_over_limit_skips_triage_and_notifies_once():
    _reset()
    settings.RATE_LIMIT_PER_SENDER = 2
    triage_calls, notices = [], []

    async def fake_triage(text):
        triage_calls.append(text)
        return None

    async def fake_notice(text):
        notices.append(text)

    main.triage_message = fake_triage
    main.send_review_notice = fake_notice
    main._now = lambda: 500.0  # fake clock: all three arrive in the same window

    msg = IncomingMessage(platform="messenger", sender_id="f@x", text="hi",
                          raw_event={}, flags=[])
    for _ in range(3):
        asyncio.run(main._process_message(msg))

    assert len(triage_calls) == 2  # third blocked before the Gemini call
    assert len(notices) == 1       # one review notice for the window
    main._now = __import__("time").monotonic  # restore the real clock


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

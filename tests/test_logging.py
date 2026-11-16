"""F8: message content must never reach the logs. Offline — no Gemini, no network.

Run from the project root:  python -m pytest tests/test_logging.py
"""
import asyncio
import logging

import redteam.harness  # noqa: F401  stub app.sheets before app.main -> app.router loads it
from app import main, triage
from app.models import IncomingMessage

CANARY = "CANARY_SECRET_9f3b"


def test_process_message_does_not_log_content(caplog):
    async def fake_triage(_text):
        return None  # stop before routing; no Gemini
    main.triage_message = fake_triage
    msg = IncomingMessage(platform="email", sender_id="x@example.com",
                          text=f"Subject: hi\n\n{CANARY}", raw_event={}, flags=[])
    with caplog.at_level(logging.INFO):
        asyncio.run(main._process_message(msg))
    assert CANARY not in caplog.text


def test_triage_exception_does_not_log_content(caplog):
    async def boom(_prompt):
        raise RuntimeError("model unavailable")
    triage._model.generate_content_async = boom
    with caplog.at_level(logging.ERROR):
        result = asyncio.run(triage.triage_message(f"please book {CANARY}"))
    assert result is None
    assert CANARY not in caplog.text


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

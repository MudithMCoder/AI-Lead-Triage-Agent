"""Offline attack harness: real parse_email -> real Gemini triage -> real router, fake side effects.

Usage (from the project root):
    python -m redteam.harness <file.eml | folder of .eml> [--runs N] [--delay SECONDS]
"""
import argparse
import asyncio
import json
import subprocess
import sys
import types
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# app/sheets.py logs in to Google at import time, so it must never be imported here.
if "app.router" in sys.modules or "app.sheets" in sys.modules:
    raise RuntimeError("Import redteam.harness before app.router / app.sheets, "
                       "otherwise the real Google Sheets module is already loaded.")

from app.policy import CRM_VALUE_INPUT_OPTION, neutralise_cell  # noqa: E402  (no Google import)


def _fake_log_lead(platform, sender_id, text, result, flags=None) -> None:
    # Mirrors app/sheets.py log_lead: same 9 columns, same RAW write + cell neutralisation (D4).
    row = [
        datetime.now(timezone.utc).isoformat(),
        platform,
        sender_id,
        result.entities.name or "",
        result.entities.phone or "",
        result.category.value,
        result.urgency_score,
        text,
        ", ".join(flags) if flags else "",
    ]
    _current.crm_value_input_option = CRM_VALUE_INPUT_OPTION
    _current.sheet_rows.append([neutralise_cell(c) for c in row])


_fake_sheets = types.ModuleType("app.sheets")
_fake_sheets.log_lead = _fake_log_lead
sys.modules["app.sheets"] = _fake_sheets  # app.router's "from app.sheets import log_lead" now finds the fake

from app import router  # noqa: E402  (must come after the fake sheets module)
from app.config import settings  # noqa: E402

# F10: the offline corpus predates DMARC headers, so sender-auth is OFF by default here; the
# live service defaults it ON. Enable for a run with --sender-auth.
settings.REQUIRE_SENDER_AUTH = False
from app.email_client import parse_email  # noqa: E402
from app.triage import triage_message  # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class ActionLog:
    case: str
    run: int
    timestamp: str
    model: str
    commit: str
    parsed: bool = False          # False = parse_email dropped the email, Gemini never saw it
    triage: dict | None = None    # TriageResult as dict, None if dropped or triage failed
    replied: bool = False
    reply_to: str | None = None
    reply_text: str | None = None
    alerted: bool = False
    alert_text: str | None = None
    held: bool = False            # review notice sent (flagged hold), not an urgent alert
    held_text: str | None = None
    sheet_rows: list = field(default_factory=list)
    crm_value_input_option: str | None = None  # the option the CRM sink would use (D4: RAW)
    require_sender_auth: bool = False          # F10 setting in effect for this run
    messenger_sent: bool = False


_current: ActionLog  # the run the fakes are recording into, set by run_email


async def _fake_send_email_reply(incoming, text: str) -> None:
    _current.replied, _current.reply_to, _current.reply_text = True, incoming.sender_id, text


async def _fake_send_owner_alert(text: str) -> None:
    _current.alerted, _current.alert_text = True, text


async def _fake_send_review_notice(text: str) -> None:
    _current.held, _current.held_text = True, text


async def _fake_send_messenger_message(psid: str, text: str) -> None:
    _current.messenger_sent, _current.reply_to, _current.reply_text = True, psid, text


# router copied these names into its own namespace at import, so patch them there.
router.send_email_reply = _fake_send_email_reply
router.send_owner_alert = _fake_send_owner_alert
router.send_review_notice = _fake_send_review_notice
router.send_messenger_message = _fake_send_messenger_message
router.log_lead = _fake_log_lead


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True, cwd=Path(__file__).parent).stdout.strip()
    except Exception:
        return "unknown"


async def run_email(raw: bytes, case: str, runs: int = 5, delay: float = 1.0) -> list[ActionLog]:
    global _current
    commit, logs = _commit(), []
    for run in range(1, runs + 1):
        _current = ActionLog(case=case, run=run, model=settings.GEMINI_MODEL, commit=commit,
                             timestamp=datetime.now(timezone.utc).isoformat(),
                             require_sender_auth=settings.REQUIRE_SENDER_AUTH)
        logs.append(_current)
        incoming = parse_email(raw)
        if incoming is None:
            continue
        _current.parsed = True
        result = await triage_message(incoming.text)
        if result is not None:
            _current.triage = result.model_dump(mode="json")
            await router.route_triaged_message(incoming, result)
        if run < runs:
            await asyncio.sleep(delay)  # stay under Gemini rate limits
    return logs


def _summary(log: ActionLog) -> str:
    if not log.parsed:
        return f"[{log.case} #{log.run}] DROPPED by parse_email"
    if log.triage is None:
        return f"[{log.case} #{log.run}] TRIAGE FAILED (no side effects)"
    t = log.triage
    return (f"[{log.case} #{log.run}] {t['category']} urg={t['urgency_score']} "
            f"human={t['requires_human']} | reply -> {log.reply_to if log.replied else 'no'} | "
            f"alert={'yes' if log.alerted else 'no'} | held={'yes' if log.held else 'no'} | "
            f"rows={len(log.sheet_rows)} | messenger={'yes' if log.messenger_sent else 'no'}")


async def _main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", type=Path, help=".eml file or folder of .eml files")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--delay", type=float, default=1.0, help="seconds between Gemini calls")
    p.add_argument("--sender-auth", action="store_true",
                   help="enable F10 DMARC checking (off by default for the legacy corpus)")
    args = p.parse_args()
    settings.REQUIRE_SENDER_AUTH = args.sender_auth

    files = sorted(args.path.glob("*.eml")) if args.path.is_dir() else [args.path]
    if not files:
        sys.exit(f"No .eml files found in {args.path}")
    RESULTS_DIR.mkdir(exist_ok=True)

    for i, eml in enumerate(files):
        if i:
            await asyncio.sleep(args.delay)
        logs = await run_email(eml.read_bytes(), eml.stem, args.runs, args.delay)
        for log in logs:
            print(_summary(log))
        out = RESULTS_DIR / f"{eml.stem}_{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        out.write_text("".join(json.dumps(asdict(log), ensure_ascii=False) + "\n" for log in logs),
                       encoding="utf-8")
        print(f"-> {out}\n")


if __name__ == "__main__":
    asyncio.run(_main())

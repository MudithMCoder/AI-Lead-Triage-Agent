import logging
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings
from app.models import TriageResult
from app.policy import CRM_VALUE_INPUT_OPTION, neutralise_cell

logger = logging.getLogger("sheets")

# F7: least privilege. open_by_key + append_row need only the spreadsheets scope; the broad
# drive scope (read/write every file in the account's Drive) is dropped.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_creds_dict = {
    "type": "service_account",
    "client_email": settings.GOOGLE_SERVICE_ACCOUNT_EMAIL,
    "private_key": settings.GOOGLE_PRIVATE_KEY.replace("\\n", "\n"),
    "token_uri": "https://oauth2.googleapis.com/token",
}

_credentials = Credentials.from_service_account_info(_creds_dict, scopes=SCOPES)
_gc = gspread.authorize(_credentials)
_sheet = _gc.open_by_key(settings.GOOGLE_SHEET_ID).sheet1


def log_lead(platform: str, sender_id: str, text: str, result: TriageResult,
             flags: list[str] | None = None) -> None:
    """
    Appends one row to the CRM sheet.
    """
    try:
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
        # D4 (F3): write literally, and defang any formula-leading cell as defence in depth.
        _sheet.append_row([neutralise_cell(c) for c in row],
                          value_input_option=CRM_VALUE_INPUT_OPTION)
    except Exception:
        logger.exception("Failed to write row to Google Sheets for sender_id=%s", sender_id)
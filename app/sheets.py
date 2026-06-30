import logging
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings
from app.models import TriageResult

logger = logging.getLogger("sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
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


def log_lead(platform: str, sender_id: str, text: str, result: TriageResult) -> None:
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
        ]
        _sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception:
        logger.exception("Failed to write row to Google Sheets for sender_id=%s", sender_id)
"""Pure, offline control-language detector (D3). Stdlib only.

Fires when a message references the triage schema or addresses the classifier itself —
signals of an F1 goal-hijack attempt. Used only to flag a message, never to auto-act on it.
English-only: a non-English address (e.g. the Sinhala F1d case) is not caught here and is
left to D2 (prompt delimiting) and the router's flag-based caps.
"""
import re

from app.config import settings

_PATTERNS = [
    (re.compile(r"\burgency_score\b", re.I), "references field urgency_score"),
    (re.compile(r"\brequires_human\b", re.I), "references field requires_human"),
    (re.compile(r"\bsuggested_reply\b", re.I), "references field suggested_reply"),
    (re.compile(r"\bcategory\s*[=:]", re.I), "sets the category field"),
    (re.compile(r"\b(?:triage|classification|classifier)\s+(?:assistant|system)\b", re.I),
     "addresses the triage assistant/system"),
]


def control_language_reasons(text: str) -> list[str]:
    """Return one reason per control-language pattern the text matches (empty list if none)."""
    return [reason for rx, reason in _PATTERNS if rx.search(text)]


# --- D4: validate everything the model writes before it reaches a sink (F2, F3) ---

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")


def _host(url: str) -> str:
    h = re.sub(r"^(?:https?://)?(?:www\.)?", "", url, flags=re.I)
    return re.split(r"[/?#:]", h, 1)[0].lower().rstrip(".")


def _norm_phone(p: str) -> str:
    return re.sub(r"[^\d+]", "", p)


def _domain_allowed(domain: str, allowed: set[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in allowed)


def validate_reply(text: str) -> list[str]:
    """Reasons the model's reply must NOT be auto-sent (empty list = safe to send). F2.

    Rejects a reply carrying a URL or email on a domain not in BUSINESS_ALLOWED_DOMAINS, a
    phone number not in BUSINESS_PHONES, or text longer than MAX_REPLY_CHARS."""
    reasons: list[str] = []
    if len(text) > settings.MAX_REPLY_CHARS:
        reasons.append(f"reply exceeds {settings.MAX_REPLY_CHARS} chars")
    allowed_domains = {d.lower().lstrip(".") for d in settings.BUSINESS_ALLOWED_DOMAINS}
    allowed_phones = {_norm_phone(p) for p in settings.BUSINESS_PHONES}
    for url in _URL_RE.findall(text):
        if not _domain_allowed(_host(url), allowed_domains):
            reasons.append(f"non-allowlisted URL: {url}")
    for email in _EMAIL_RE.findall(text):
        if not _domain_allowed(email.split("@")[1].lower(), allowed_domains):
            reasons.append(f"non-allowlisted email: {email}")
    for phone in _PHONE_RE.findall(text):
        if _norm_phone(phone) not in allowed_phones:
            reasons.append(f"non-allowlisted phone: {phone.strip()}")
    return reasons


CRM_VALUE_INPUT_OPTION = "RAW"  # never USER_ENTERED: a formula-leading cell must not execute (F3)
MAX_FIELD_CHARS = 200
_CELL_LEAD = "=+-@\t\r"


def neutralise_cell(value):
    """Prefix a single quote to any string cell that could be read as a spreadsheet formula."""
    if isinstance(value, str) and value and value[0] in _CELL_LEAD:
        return "'" + value
    return value


def clean_field(value: str) -> str:
    """Neutralise and length-cap a model-derived field before it goes into alert/notice text."""
    return neutralise_cell(value)[:MAX_FIELD_CHARS]

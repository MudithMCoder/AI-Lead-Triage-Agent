"""Pure, offline control-language detector (D3). Stdlib only.

Fires when a message references the triage schema or addresses the classifier itself —
signals of an F1 goal-hijack attempt. Used only to flag a message, never to auto-act on it.
English-only: a non-English address (e.g. the Sinhala F1d case) is not caught here and is
left to D2 (prompt delimiting) and the router's flag-based caps.
"""
import re

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

import asyncio
import imaplib
import logging
import re
import smtplib
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr
from html.parser import HTMLParser

from app.config import settings
from app.models import IncomingMessage

logger = logging.getLogger("email_client")

_SKIP_SENDERS = ("noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster")
_last_uid: int | None = None

# Inline styles that render an element invisible to the reader. An attacker uses these to
# feed the model text the owner never sees (F5). font-size/opacity match 0 and 0.0 only.
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?:\.0+)?(?![.\d])"
    r"|font-size\s*:\s*0(?:\.0+)?(?![.\d])",
    re.I,
)
# Tags whose text content is never shown to the reader.
_DROP_TAGS = {"script", "style", "head", "title", "noscript"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}


def _style_hidden(attrs: list[tuple[str, str | None]]) -> bool:
    for key, value in attrs:
        if key.lower() == "style" and value and _HIDDEN_STYLE.search(value):
            return True
    return False


class _VisibleTextExtractor(HTMLParser):
    """Collects only the text a human would see: drops comments, script/style/head, and
    any element hidden via inline style, including that element's children."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._stack: list[tuple[str, bool, bool]] = []  # (tag, is_drop, is_hidden)
        self._drop_depth = 0
        self._hidden_depth = 0
        self.hidden_text_found = False  # non-whitespace text removed because inline-hidden

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        drop = tag in _DROP_TAGS
        hidden = _style_hidden(attrs)
        self._stack.append((tag, drop, hidden))
        if drop:
            self._drop_depth += 1
        if hidden:
            self._hidden_depth += 1

    def handle_startendtag(self, tag, attrs):
        pass  # self-closing: no content to collect

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):  # tolerate unclosed inner tags
            if self._stack[i][0] == tag:
                for _, drop, hidden in self._stack[i:]:
                    if drop:
                        self._drop_depth -= 1
                    if hidden:
                        self._hidden_depth -= 1
                del self._stack[i:]
                return

    def handle_data(self, data):
        if self._drop_depth == 0 and self._hidden_depth == 0:
            self._parts.append(data)
        elif self._hidden_depth > 0 and data.strip():
            self.hidden_text_found = True

    def get_text(self) -> str:
        return " ".join("".join(self._parts).split())


def extract_visible_text(html: str) -> tuple[str, bool]:
    """Returns (visible text, whether inline-hidden non-whitespace text was removed)."""
    parser = _VisibleTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text(), parser.hidden_text_found


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _plain_html_mismatch(plain: str, visible: str) -> bool:
    """True if the plain part carries substantial text the visible HTML does not (F5 split).
    Threshold: >=5 plain tokens absent from the visible set AND >=30% of plain tokens missing.
    The floor stops a short benign footer/signature line from tripping it; the ratio catches
    an injected directive, which is many tokens the rendered HTML never contains."""
    plain_set = _tokens(plain)
    if not plain_set:
        return False
    missing = plain_set - _tokens(visible)
    return len(missing) >= 5 and len(missing) / len(plain_set) >= 0.30


def parse_email(raw: bytes) -> IncomingMessage | None:
    """Turns a raw email into an IncomingMessage, or None if it must not be triaged."""
    msg = message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(msg.get("From", ""))[1].lower()

    # Never answer machines, mailing lists or ourselves: prevents endless reply loops.
    if (
        not sender
        or sender == settings.EMAIL_ADDRESS.lower()
        or any(s in sender for s in _SKIP_SENDERS)
        or msg.get("Auto-Submitted", "no").lower() != "no"
        or msg.get("Precedence", "").lower() in ("bulk", "list", "junk")
        or msg.get("List-Id")
    ):
        return None

    # D1 ingest normalisation (F5): the text sent to the model is the text a human would see.
    # For HTML that means visible text only (hidden elements/comments/script removed); for a
    # multipart/alternative we read the visible HTML and flag when the plain part diverges.
    plain_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    plain_text = plain_part.get_content() if plain_part is not None else None
    html_raw = html_part.get_content() if html_part is not None else None

    flags: list[str] = []
    if html_raw is not None:
        body, had_hidden = extract_visible_text(html_raw)
        if had_hidden:
            flags.append("hidden_html_content")
        if plain_text is not None and _plain_html_mismatch(plain_text, body):
            flags.append("plain_html_mismatch")
    else:
        body = plain_text or ""

    subject = msg.get("Subject", "")
    return IncomingMessage(
        platform="email",
        sender_id=sender,
        text=f"Subject: {subject}\n\n{body.strip()}"[:4000],
        raw_event={"subject": subject, "message_id": msg.get("Message-ID", "")},
        flags=flags,
    )


def fetch_new_emails() -> list[IncomingMessage]:
    """Returns inbox emails that arrived since the server started. Blocking: run in a thread."""
    global _last_uid
    with imaplib.IMAP4_SSL(settings.IMAP_HOST) as imap:
        imap.login(settings.EMAIL_ADDRESS, settings.EMAIL_APP_PASSWORD)
        imap.select("INBOX")

        if _last_uid is None:
            # First poll: remember where the inbox ends so old mail never gets auto-replies.
            uids = imap.uid("search", None, "ALL")[1][0].split()
            _last_uid = int(uids[-1]) if uids else 0
            logger.info("Email polling started for %s (skipping %d existing emails)",
                        settings.EMAIL_ADDRESS, len(uids))
            return []

        results: list[IncomingMessage] = []
        uids = imap.uid("search", None, f"UID {_last_uid + 1}:*")[1][0].split()
        for uid in (int(u) for u in uids):
            if uid <= _last_uid:  # "n:*" always returns the newest mail, even if already seen
                continue
            data = imap.uid("fetch", str(uid), "(BODY.PEEK[])")[1]
            _last_uid = uid
            incoming = parse_email(data[0][1])
            if incoming:
                results.append(incoming)
        return results


def _send(to: str, subject: str, body: str, in_reply_to: str = "") -> None:
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject
    msg["Auto-Submitted"] = "auto-replied"  # tells other mail systems not to auto-answer us
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    with smtplib.SMTP_SSL(settings.SMTP_HOST, 465, timeout=15) as smtp:
        smtp.login(settings.EMAIL_ADDRESS, settings.EMAIL_APP_PASSWORD)
        smtp.send_message(msg)


async def send_email_reply(incoming: IncomingMessage, text: str) -> None:
    subject = incoming.raw_event.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    try:
        await asyncio.to_thread(_send, incoming.sender_id, subject, text,
                                incoming.raw_event.get("message_id", ""))
    except Exception:
        logger.exception("Email reply failed to %s", incoming.sender_id)


async def send_owner_alert(text: str) -> None:
    """Emails the business owner."""
    try:
        await asyncio.to_thread(_send, settings.OWNER_EMAIL, "Urgent message alert", text)
    except Exception:
        logger.exception("Owner alert email failed")

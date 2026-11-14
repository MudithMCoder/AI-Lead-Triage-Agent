import asyncio
import imaplib
import logging
import re
import smtplib
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import settings
from app.models import IncomingMessage

logger = logging.getLogger("email_client")

_SKIP_SENDERS = ("noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster")
_last_uid: int | None = None


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

    part = msg.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/html":
        body = re.sub(r"<[^>]+>", " ", body)

    subject = msg.get("Subject", "")
    return IncomingMessage(
        platform="email",
        sender_id=sender,
        text=f"Subject: {subject}\n\n{body.strip()}"[:4000],
        raw_event={"subject": subject, "message_id": msg.get("Message-ID", "")},
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

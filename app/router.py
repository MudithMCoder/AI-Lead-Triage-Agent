import logging

from app.config import settings
from app.models import IncomingMessage, MessageCategory, TriageResult
from app.meta_client import send_messenger_message
from app.email_client import send_email_reply, send_owner_alert, send_review_notice
from app.sheets import log_lead

logger = logging.getLogger("router")


async def _reply(incoming: IncomingMessage, text: str) -> None:
    if not text:
        return
    if incoming.platform == "email":
        await send_email_reply(incoming, text)
    elif incoming.platform == "messenger":
        await send_messenger_message(incoming.sender_id, text)


async def route_triaged_message(incoming: IncomingMessage, result: TriageResult) -> None:
    """
    The deterministic decision layer.
    """
    platform = incoming.platform
    sender_id = incoming.sender_id
    flags = incoming.flags

    #  Spam : archive silently, no reply, no CRM entry, no alert.
    if result.category == MessageCategory.SPAM:
        logger.info("Archived spam from %s on %s", sender_id, platform)
        return

    # D3 (F1, F4): any ingest flag (hidden/split content, control-language) means the model
    # output is not trusted to act. Log it, cap urgency below the alert threshold (no urgent
    # alert), send a low-priority review notice listing the flags, and never auto-reply.
    if flags:
        log_lead(platform, sender_id, incoming.text, result, flags)
        await send_review_notice(
            "⚠️ Message held for review\n"
            f"Platform: {platform}\n"
            f"From: {sender_id} (sender identity unverified)\n"
            f"Flags: {', '.join(flags)}\n"
            f"Model-assessed urgency (capped, not alerted): {result.urgency_score}/10\n"
            f"Summary: {result.summary}"
        )
        logger.info("Held for review (flags=%s): sender=%s", flags, sender_id)
        return

    #  Strong leads : always logged to CRM.
    if result.category == MessageCategory.LEAD:
        log_lead(platform, sender_id, incoming.text, result, flags)

    # Complaints also get logged,
    if result.category == MessageCategory.COMPLAINT:
        log_lead(platform, sender_id, incoming.text, result, flags)

    # Urgent cases : real-time alert to the owner. Unflagged only; the text makes clear the
    # urgency is the model's assessment and the sender identity is not verified.
    if result.urgency_score >= settings.URGENCY_ALERT_THRESHOLD:
        alert_text = (
            f"🚨 Urgent message ({result.urgency_score}/10, model-assessed)\n"
            f"Platform: {platform}\n"
            f"From: {sender_id} (sender identity unverified)\n"
            f"Category: {result.category.value}\n"
            f"Summary: {result.summary}\n"
            f"Name: {result.entities.name or 'unknown'}\n"
            f"Phone: {result.entities.phone or 'unknown'}"
        )
        await send_owner_alert(alert_text)

    # If Gemini flagged this as needing a human, making sure it's logged
    if result.requires_human:
        logger.info("Flagged for human review: sender=%s category=%s", sender_id, result.category.value)
        if result.category not in (MessageCategory.LEAD, MessageCategory.COMPLAINT):
            # log it anyway
            log_lead(platform, sender_id, incoming.text, result, flags)
        return

    # Auto-reply policy (D3): send only when every condition holds — the model wanted no human,
    # ingest raised no flag, urgency is below the alert threshold, and it is a lead or inquiry.
    # requires_human and flags are already guaranteed above; check the remaining two here.
    if (result.urgency_score < settings.URGENCY_ALERT_THRESHOLD
            and result.category in (MessageCategory.LEAD, MessageCategory.GENERAL_INQUIRY)):
        await _reply(incoming, result.suggested_reply)
import logging

from app.config import settings
from app.models import IncomingMessage, MessageCategory, TriageResult
from app.meta_client import send_whatsapp_message, send_messenger_message, send_owner_alert
from app.sheets import log_lead

logger = logging.getLogger("router")


async def _reply(platform: str, sender_id: str, text: str) -> None:
    if not text:
        return
    if platform == "whatsapp":
        await send_whatsapp_message(sender_id, text)
    elif platform == "messenger":
        await send_messenger_message(sender_id, text)


async def route_triaged_message(incoming: IncomingMessage, result: TriageResult) -> None:
    """
    The deterministic decision layer.
    """
    platform = incoming.platform
    sender_id = incoming.sender_id

    #  Spam : archive silently, no reply, no CRM entry, no alert.
    if result.category == MessageCategory.SPAM:
        logger.info("Archived spam from %s on %s", sender_id, platform)
        return

    #  Strong leads : always logged to CRM.
    if result.category == MessageCategory.LEAD:
        log_lead(platform, sender_id, incoming.text, result)

    # Complaints also get logged,
    if result.category == MessageCategory.COMPLAINT:
        log_lead(platform, sender_id, incoming.text, result)

    # Urgent cases : real-time alert to the owner.
    if result.urgency_score >= settings.URGENCY_ALERT_THRESHOLD:
        alert_text = (
            f"🚨 Urgent message ({result.urgency_score}/10)\n"
            f"Platform: {platform}\n"
            f"From: {sender_id}\n"
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
            log_lead(platform, sender_id, incoming.text, result)
        return

    # Otherwise, send the suggested auto-reply.
    await _reply(platform, sender_id, result.suggested_reply)
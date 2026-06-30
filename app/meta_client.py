import logging

import httpx

from app.config import settings

logger = logging.getLogger("meta_client")

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


async def send_whatsapp_message(to: str, text: str) -> None:
    """Sends a freeform WhatsApp text message."""
    url = f"{GRAPH_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.error("WhatsApp send failed (%s): %s", resp.status_code, resp.text)


async def send_messenger_message(psid: str, text: str) -> None:
    url = f"{GRAPH_BASE}/me/messages"
    params = {"access_token": settings.MESSENGER_PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, params=params, json=payload)
        if resp.status_code >= 400:
            logger.error("Messenger send failed (%s): %s", resp.status_code, resp.text)


async def send_owner_alert(text: str) -> None:
    """Sends a WhatsApp message to the business owner's own number."""
    await send_whatsapp_message(settings.OWNER_WHATSAPP_NUMBER, text)
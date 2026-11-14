import logging

import httpx

from app.config import settings

logger = logging.getLogger("meta_client")

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


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
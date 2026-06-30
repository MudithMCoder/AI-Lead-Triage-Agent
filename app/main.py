import hashlib
import hmac
import logging

from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException, Query

from app.config import settings
from app.models import IncomingMessage
from app.triage import triage_message
from app.router import route_triaged_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="AI Lead & Message Triage Agent")


@app.get("/")
async def health_check():
    return {"status": "ok"}


# Webhook verification (GET) — Meta calls this once per save in the dashboard
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Webhook verified successfully.")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning("Webhook verification failed. mode=%s token_match=%s",
                    hub_mode, hub_verify_token == settings.META_VERIFY_TOKEN)
    raise HTTPException(status_code=403, detail="Verification failed")



# Signature verification helper
def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = signature_header.split("sha256=", 1)[1]
    computed_sig = hmac.new(
        settings.META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_sig, computed_sig)



# Webhook receiver (POST) — real events land here

@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if settings.ENVIRONMENT == "production" and not _verify_signature(raw_body, signature):
        logger.warning("Invalid webhook signature — rejecting request.")
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    # Parse out every individual message in this payload
    for incoming in _extract_messages(payload):
        background_tasks.add_task(_process_message, incoming)

    return Response(status_code=200)


# Payload parsing — WhatsApp and Messenger
def _extract_messages(payload: dict) -> list[IncomingMessage]:
    results: list[IncomingMessage] = []

    try:
        entries = payload.get("entry", [])
        for entry in entries:
            #  WhatsApp shape
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    if msg.get("type") == "text":
                        results.append(
                            IncomingMessage(
                                platform="whatsapp",
                                sender_id=msg["from"],
                                text=msg["text"]["body"],
                                raw_event=msg,
                            )
                        )

            # Messenger shape
            messaging = entry.get("messaging", [])
            for event in messaging:
                message = event.get("message")
                if message and "text" in message and not message.get("is_echo"):
                    results.append(
                        IncomingMessage(
                            platform="messenger",
                            sender_id=event["sender"]["id"],
                            text=message["text"],
                            raw_event=event,
                        )
                    )
    except Exception:
        logger.exception("Failed to parse webhook payload: %s", payload)

    return results



# Background processing - Triage Routing Process

async def _process_message(incoming: IncomingMessage) -> None:
    logger.info("Processing message from %s (%s): %r",
                incoming.sender_id, incoming.platform, incoming.text)

    result = await triage_message(incoming.text)

    if result is None:
        # Gemini failed or returned invalid data — fail safe by logging it
        # for manual review rather than silently dropping the message.
        logger.error("Triage failed for sender=%s — message needs manual review.",
                      incoming.sender_id)
        return

    await route_triaged_message(incoming, result)
import json
import logging

import google.generativeai as genai

from app.config import settings
from app.models import TriageResult

logger = logging.getLogger("triage")

genai.configure(api_key=settings.GEMINI_API_KEY)

SYSTEM_INSTRUCTION = """You are a message triage assistant for a small business's WhatsApp and \
Messenger inbox. You will be given one incoming customer message. You must classify it and \
extract any useful information.

Rules:
- category: choose the single best fit from: lead, support, spam, general_inquiry, complaint, other.
  "lead" means a prospective customer expressing interest in buying/booking/hiring.
  "spam" means promotional junk, scams, or irrelevant automated messages.
- urgency_score: 1-10. Use 8-10 only for things like complaints about money already paid, safety \
  issues, or a customer explicitly saying it's urgent. Routine questions are 2-4. A clear ready-to-buy \
  lead is 5-7.
- entities: extract only what is explicitly present in the message. Leave fields null if not present. \
  Do not guess or invent a name, phone number, or email that isn't in the text.
- suggested_reply: write a short, warm, professional reply (1-3 sentences) appropriate to send back \
  to the customer right now. For spam, suggested_reply should be an empty string.
- requires_human: set true if the message is ambiguous, emotionally charged, a complaint, a legal/safety \
  matter, or anything you are not confident enough to let an automated reply handle alone.

Respond ONLY with JSON matching the required schema. No prose, no markdown fences, no explanation."""

# This JSON schema is passed to Gemini's structured output config so the model
# is constrained to emit exactly this shape.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["lead", "support", "spam", "general_inquiry", "complaint", "other"],
        },
        "urgency_score": {"type": "integer"},
        "summary": {"type": "string"},
        "entities": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "nullable": True},
                "phone": {"type": "string", "nullable": True},
                "email": {"type": "string", "nullable": True},
                "product_or_service": {"type": "string", "nullable": True},
                "location": {"type": "string", "nullable": True},
            },
        },
        "suggested_reply": {"type": "string"},
        "requires_human": {"type": "boolean"},
    },
    "required": [
        "category",
        "urgency_score",
        "summary",
        "entities",
        "suggested_reply",
        "requires_human",
    ],
}

_model = genai.GenerativeModel(
    model_name=settings.GEMINI_MODEL,
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config={
        "response_mime_type": "application/json",
        "response_schema": RESPONSE_SCHEMA,
        "temperature": 0.2,
    },
)


async def triage_message(text: str) -> TriageResult | None:
    """
    Sends the customer's message text to Gemini and returns a validated TriageResult.
    """
    try:
        response = await _model.generate_content_async(text)
        raw = response.text
        data = json.loads(raw)
        return TriageResult.model_validate(data)
    except Exception as exc:
        logger.exception("Gemini triage failed for message: %r — error: %s", text, exc)
        return None
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MessageCategory(str, Enum):
    LEAD = "lead"
    SUPPORT = "support"
    SPAM = "spam"
    GENERAL_INQUIRY = "general_inquiry"
    COMPLAINT = "complaint"
    OTHER = "other"


class ExtractedEntities(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    product_or_service: Optional[str] = None
    location: Optional[str] = None


class TriageResult(BaseModel):
    category: MessageCategory
    urgency_score: int = Field(ge=1, le=10, description="1 = no rush, 10 = drop everything")
    summary: str = Field(description="One-sentence summary of what the customer wants")
    entities: ExtractedEntities
    suggested_reply: str = Field(description="A short, friendly reply to send the customer")
    requires_human: bool = Field(description="True if this is ambiguous or sensitive and a human should look before any auto-reply is sent")


class IncomingMessage(BaseModel):
    platform: str          
    sender_id: str
    text: str
    raw_event: dict
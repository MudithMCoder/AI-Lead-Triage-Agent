from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Meta webhook
    META_APP_SECRET: str
    META_VERIFY_TOKEN: str

    # Meta / Messenger
    MESSENGER_PAGE_ACCESS_TOKEN: str
    MESSENGER_PAGE_ID: str

    # Gemini
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # Google Sheets
    GOOGLE_SHEET_ID: str
    GOOGLE_SERVICE_ACCOUNT_EMAIL: str
    GOOGLE_PRIVATE_KEY: str

    # Email channel (incoming, auto-replies, owner alerts). Empty EMAIL_ADDRESS disables it.
    EMAIL_ADDRESS: str = ""
    EMAIL_APP_PASSWORD: str = ""
    OWNER_EMAIL: str = ""
    IMAP_HOST: str = "imap.gmail.com"
    SMTP_HOST: str = "smtp.gmail.com"
    EMAIL_POLL_SECONDS: int = 30

    # Alerts
    URGENCY_ALERT_THRESHOLD: int = 7

    # F9: per-sender sliding-window rate limit (denial-of-wallet protection).
    RATE_LIMIT_PER_SENDER: int = 5
    RATE_LIMIT_WINDOW_SECONDS: int = 3600

    # D4 output validation: what the model is allowed to put in an auto-reply.
    BUSINESS_ALLOWED_DOMAINS: list[str] = []
    BUSINESS_PHONES: list[str] = []
    MAX_REPLY_CHARS: int = 600

    ENVIRONMENT: str = "development"


settings = Settings()
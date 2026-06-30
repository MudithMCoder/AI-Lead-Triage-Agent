from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Meta / WhatsApp
    META_APP_SECRET: str
    META_VERIFY_TOKEN: str
    WHATSAPP_ACCESS_TOKEN: str
    WHATSAPP_PHONE_NUMBER_ID: str

    # Meta / Messenger
    MESSENGER_PAGE_ACCESS_TOKEN: str
    MESSENGER_PAGE_ID: str

    # Gemini
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Google Sheets
    GOOGLE_SHEET_ID: str
    GOOGLE_SERVICE_ACCOUNT_EMAIL: str
    GOOGLE_PRIVATE_KEY: str

    # Alerts
    OWNER_WHATSAPP_NUMBER: str
    URGENCY_ALERT_THRESHOLD: int = 7

    ENVIRONMENT: str = "development"


settings = Settings()
# AI Lead & Message Triage Agent

A FastAPI service that turns a business's WhatsApp and Messenger inbox into a semi-automated lead and support pipeline. Incoming messages are classified by Gemini, then routed by a deterministic rules layer that decides whether to archive, log to a CRM sheet, alert the owner, and/or auto-reply.

## How it works

1. **Meta sends a webhook event** for every incoming WhatsApp or Messenger message.
2. **The signature is verified** (HMAC SHA-256) and the payload is normalized into a common `IncomingMessage` shape, since WhatsApp and Messenger use different JSON structures.
3. **Gemini triages the message** — classifying it, scoring urgency, extracting entities (name, phone, email, product, location), and drafting a suggested reply, constrained to a strict JSON schema.
4. **A deterministic router decides the outcome**:
   - `spam` → archived silently, no reply, no CRM entry, no alert
   - `lead` / `complaint` → logged to a Google Sheet CRM
   - urgency at or above the configured threshold → real-time WhatsApp alert to the owner
   - flagged `requires_human` → held back from auto-reply and logged for manual review
   - everything else → Gemini's suggested reply is sent back automatically

Processing happens in a FastAPI `BackgroundTask` so the webhook responds to Meta immediately without waiting on the Gemini call.

## Project structure

```
app/
├── main.py         # FastAPI app, webhook endpoints, payload parsing, background processing
├── config.py       # Environment-based settings (pydantic-settings)
├── models.py       # Shared Pydantic models: IncomingMessage, TriageResult, etc.
├── triage.py       # Gemini call + structured-output schema
├── router.py       # Deterministic routing/decision logic
├── meta_client.py  # WhatsApp / Messenger Graph API senders
└── sheets.py       # Google Sheets CRM logging via gspread
```

## Requirements

- Python 3.10+
- A Meta developer app with WhatsApp Cloud API and/or Messenger access
- A Gemini API key
- A Google Cloud service account with access to a target Google Sheet

### Python dependencies

```
fastapi
uvicorn
httpx
pydantic
pydantic-settings
google-generativeai
gspread
google-auth
```

## Setup

1. **Clone the repo and install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** in the project root with the following variables:

   ```env
   # Meta / WhatsApp
   META_APP_SECRET=
   META_VERIFY_TOKEN=
   WHATSAPP_ACCESS_TOKEN=
   WHATSAPP_PHONE_NUMBER_ID=

   # Meta / Messenger
   MESSENGER_PAGE_ACCESS_TOKEN=
   MESSENGER_PAGE_ID=

   # Gemini
   GEMINI_API_KEY=
   GEMINI_MODEL=gemini-2.0-flash

   # Google Sheets
   GOOGLE_SHEET_ID=
   GOOGLE_SERVICE_ACCOUNT_EMAIL=
   GOOGLE_PRIVATE_KEY=

   # Alerts
   OWNER_WHATSAPP_NUMBER=
   URGENCY_ALERT_THRESHOLD=7

   ENVIRONMENT=development
   ```

   Notes:
   - `GOOGLE_PRIVATE_KEY` should be the service account's private key with literal `\n` sequences — the app converts them to real newlines at startup.
   - `URGENCY_ALERT_THRESHOLD` and `GEMINI_MODEL` have defaults and are optional.
   - Set `ENVIRONMENT=production` to enforce webhook signature verification.

3. **Run the app locally**

   ```bash
   uvicorn app.main:app --reload
   ```

4. **Expose it for Meta's webhook** (e.g. with ngrok during development) and configure the webhook URL plus `META_VERIFY_TOKEN` in the Meta developer dashboard.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Health check |
| GET | `/webhook` | Meta's webhook verification handshake |
| POST | `/webhook` | Receives WhatsApp/Messenger events |

## Message categories

Gemini classifies each message into one of:

- `lead` — a prospective customer expressing interest in buying/booking/hiring
- `support` — a support question
- `spam` — promotional junk, scams, or irrelevant automated messages
- `general_inquiry` — routine questions
- `complaint` — customer complaints
- `other` — anything that doesn't fit the above

Each message also gets an `urgency_score` (1–10), a one-sentence `summary`, extracted `entities`, a `suggested_reply`, and a `requires_human` flag.

## Known limitations

- Google Sheets credentials are validated at import time, so invalid credentials will prevent the app from starting rather than failing per-request.
- There's no retry/backoff on Gemini or Graph API calls; failures are logged but the message is not automatically retried or escalated beyond the log line.
- Webhook signature verification is skipped when `ENVIRONMENT` is not `production` — make sure this is set correctly in deployed environments.

## License

Add your preferred license here.

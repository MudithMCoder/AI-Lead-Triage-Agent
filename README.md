# AI Lead & Message Triage Agent

A FastAPI service that turns a business's email inbox and Facebook Messenger page into a semi-automated lead and support pipeline. Incoming messages are classified by Gemini, then routed by a deterministic rules layer that decides whether to archive, log to a CRM sheet, alert the owner by email, and/or auto-reply.

## How it works

1. **Messages arrive on one of two channels**:
   - **Email**: a background task polls the inbox over IMAP every `EMAIL_POLL_SECONDS`. Mail that was already in the inbox when the server started is skipped, so old mail never gets auto-replies.
   - **Messenger**: Meta sends a webhook event to `POST /webhook`. The signature is verified (HMAC SHA-256) in production.
2. **Each message is normalized** into a common `IncomingMessage` shape. For email, the subject and plain-text body are used (HTML-only mail is stripped of tags).
3. **Loop protection** drops emails that must never be answered: our own address, `noreply`/`mailer-daemon`-style senders, auto-submitted mail, bulk/list mail, and anything with a `List-Id` header. Outgoing replies carry `Auto-Submitted: auto-replied`.
4. **Gemini triages the message**: it classifies it, scores urgency, extracts entities (name, phone, email, product, location) and drafts a suggested reply, constrained to a strict JSON schema.
5. **A deterministic router decides the outcome**:
   - `spam` → archived silently, no reply, no CRM entry, no alert
   - `lead` / `complaint` → logged to a Google Sheet CRM
   - urgency at or above `URGENCY_ALERT_THRESHOLD` → alert email to `OWNER_EMAIL`
   - flagged `requires_human` → no auto-reply, logged to the sheet for manual review
   - everything else → Gemini's suggested reply is sent back on the same channel (email reply in the same thread, or Messenger message)

Webhook processing runs in a FastAPI `BackgroundTask`, so Meta gets a response immediately without waiting on the Gemini call.

## Project structure

```
app/
├── main.py          # FastAPI app, webhook endpoints, Messenger payload parsing, email polling loop
├── config.py        # Environment-based settings (pydantic-settings)
├── models.py        # Shared Pydantic models: IncomingMessage, TriageResult, etc.
├── triage.py        # Gemini call + structured-output schema
├── router.py        # Deterministic routing/decision logic
├── email_client.py  # IMAP polling, email parsing + loop protection, SMTP replies and owner alerts
├── meta_client.py   # Messenger Graph API sender
└── sheets.py        # Google Sheets CRM logging via gspread
tests/
└── test_email_client.py  # Email parsing and loop-protection tests
```

## Requirements

- Python 3.10+
- An email account with IMAP/SMTP access (for Gmail: 2-Step Verification on, plus an [App Password](https://myaccount.google.com/apppasswords))
- A Meta developer app with Messenger access and a Facebook Page
- A Gemini API key
- A Google Cloud service account with edit access to a target Google Sheet

All Python dependencies are pinned in `requirements.txt`.

## Setup

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** in the project root (copy `.env.example`):

   ```env
   # Meta webhook + Messenger
   META_APP_SECRET=
   META_VERIFY_TOKEN=
   MESSENGER_PAGE_ACCESS_TOKEN=
   MESSENGER_PAGE_ID=

   # Gemini
   GEMINI_API_KEY=
   GEMINI_MODEL=gemini-3.5-flash-lite

   # Google Sheets
   GOOGLE_SHEET_ID=
   GOOGLE_SERVICE_ACCOUNT_EMAIL=
   GOOGLE_PRIVATE_KEY=

   # Email channel (incoming mail, auto-replies, owner alerts)
   EMAIL_ADDRESS=
   EMAIL_APP_PASSWORD=
   OWNER_EMAIL=
   IMAP_HOST=imap.gmail.com
   SMTP_HOST=smtp.gmail.com
   EMAIL_POLL_SECONDS=30

   # Alerts
   URGENCY_ALERT_THRESHOLD=7

   ENVIRONMENT=development
   ```

   Notes:
   - The Meta, Gemini and Google Sheets variables are required; the app will not start without them.
   - Leave `EMAIL_ADDRESS` empty to disable the email channel. Owner alerts are sent by email, so they also need `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` and `OWNER_EMAIL`.
   - SMTP uses SSL on port 465.
   - `GOOGLE_PRIVATE_KEY` is the service account's private key with literal `\n` sequences. The app converts them to real newlines at startup.
   - `GEMINI_MODEL`, `IMAP_HOST`, `SMTP_HOST`, `EMAIL_POLL_SECONDS`, `URGENCY_ALERT_THRESHOLD` and `ENVIRONMENT` have defaults and are optional.
   - Set `ENVIRONMENT=production` to enforce webhook signature verification.

3. **Run the app locally**

   ```bash
   uvicorn app.main:app --reload
   ```

4. **For Messenger**, expose the app (e.g. with ngrok during development), then configure the webhook URL plus `META_VERIFY_TOKEN` in the Meta developer dashboard.

## Tests

```bash
python -m tests.test_email_client
```

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Health check |
| GET | `/webhook` | Meta's webhook verification handshake |
| POST | `/webhook` | Receives Messenger events (returns 400 on malformed JSON) |

Email does not use an endpoint; it is polled in the background.

## Message categories

Gemini classifies each message into one of:

- `lead`: a prospective customer interested in buying, booking or hiring
- `support`: a support question
- `spam`: promotional junk, scams, or irrelevant automated messages
- `general_inquiry`: routine questions
- `complaint`: customer complaints
- `other`: anything that doesn't fit the above

Each message also gets an `urgency_score` (1–10), a one-sentence `summary`, extracted `entities`, a `suggested_reply`, and a `requires_human` flag.

## Known limitations

- Google Sheets credentials are validated at import time, so invalid credentials stop the app from starting rather than failing per request.
- There's no retry/backoff on Gemini, SMTP or Graph API calls. Failures are logged, but the message is not retried or escalated beyond the log line.
- The email poller keeps its position in memory only. Emails that arrive while the server is down are skipped on the next start.
- Webhook signature verification is skipped when `ENVIRONMENT` is not `production`, so set it correctly in deployed environments.

## License

Add your preferred license here.

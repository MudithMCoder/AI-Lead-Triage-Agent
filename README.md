# AI Lead & Message Triage Agent

A FastAPI service that turns a business's email inbox and Facebook Messenger page into a semi-automated lead and support pipeline. Incoming messages are classified by Gemini, then routed by a deterministic rules layer that decides whether to archive, log to a CRM sheet, alert the owner by email, and/or auto-reply.

## Security

This project was red-teamed and hardened as a security case study. **Full report: [`REPORT.md`](REPORT.md).**

- Prompt injection through an ordinary-looking email fully hijacked the baseline agent (5/5). Hidden-HTML variants worked 10/10 and were invisible to the owner.
- Across 8 injection payloads (40 runs) the model was fooled **20/40 at `v0-baseline` and 0/40 at `v1-hardened`**. Attacker-driven auto-replies and urgent alerts went to **0/40**, and no legitimate test email was held.
- Threat model: [`THREAT_MODEL.md`](THREAT_MODEL.md) · run log: [`redteam/LOG.md`](redteam/LOG.md) · attack harness: [`redteam/`](redteam/)

## How it works

1. **Messages arrive on one of two channels**:
   - **Email**: a background task polls the inbox over IMAP every `EMAIL_POLL_SECONDS`. Mail that was already in the inbox when the server started is skipped, so old mail never gets auto-replies.
   - **Messenger**: Meta sends a webhook event to `POST /webhook`. The signature (HMAC SHA-256) is always verified; only `ENVIRONMENT=test` skips it.
2. **Each message is normalized** into a common `IncomingMessage` shape. For email, the subject and plain-text body are used. HTML is reduced to the text a reader would actually see, with hidden elements and comments dropped. Anomalies are recorded as `flags`: hidden HTML content, a plain part that doesn't match the HTML part, text that addresses the classifier or its fields, or a sender without a DMARC pass.
3. **Loop protection** drops emails that must never be answered: our own address, `noreply`/`mailer-daemon`-style senders, auto-submitted mail, bulk/list mail, and anything with a `List-Id` header. Outgoing replies carry `Auto-Submitted: auto-replied`.
4. **Gemini triages the message**: it classifies it, scores urgency, extracts entities (name, phone, email, product, location) and drafts a suggested reply, constrained to a strict JSON schema. The message is passed as delimited, untrusted data. Senders are rate-limited before the call.
5. **A deterministic router decides the outcome**. The model's output is advice; these rules decide:
   - `spam` → archived silently, no reply, no CRM entry, no alert
   - any ingest flag → logged, held for review with a low-priority notice to the owner, no auto-reply, no urgent alert
   - `lead` / `complaint` → logged to a Google Sheet CRM (cells written as `RAW`, formula prefixes neutralised)
   - urgency at or above `URGENCY_ALERT_THRESHOLD` → alert email to `OWNER_EMAIL`, marked as model-assessed with the sender unverified
   - flagged `requires_human` → no auto-reply, logged to the sheet for manual review
   - otherwise, only a `lead` or `general_inquiry` below the alert threshold is auto-replied, and only if the reply passes validation (no URL, email or phone number outside the allowlist, length cap)

Webhook processing runs in a FastAPI `BackgroundTask`, so Meta gets a response immediately without waiting on the Gemini call.

## Project structure

```
app/
├── main.py          # FastAPI app, webhook endpoints, Messenger payload parsing, email polling loop
├── config.py        # Environment-based settings (pydantic-settings)
├── models.py        # Shared Pydantic models: IncomingMessage, TriageResult, etc.
├── triage.py        # Gemini call + structured-output schema
├── router.py        # Deterministic routing/decision logic
├── policy.py        # Control-language detector, reply validation, CRM cell neutralisation
├── email_client.py  # IMAP polling, email parsing, visible-text HTML, sender auth, SMTP replies, alerts and review notices
├── meta_client.py   # Messenger Graph API sender
└── sheets.py        # Google Sheets CRM logging via gspread
tests/               # 55 offline tests (no API calls): ingest, policy, router, sinks, webhook, logging, rate limit, sender auth
redteam/
├── harness.py       # Offline attack harness: real parse/triage/router, side effects captured, never sent
├── score.py         # Per-case attack success rate, filterable by commit
├── cases/           # Attack and benign .eml cases
└── results/         # JSONL output of every run
REPORT.md            # Security assessment report
THREAT_MODEL.md      # Threat model and findings register
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

   # Security (all optional, defaults shown)
   RATE_LIMIT_PER_SENDER=5
   RATE_LIMIT_WINDOW_SECONDS=3600
   REQUIRE_SENDER_AUTH=true
   TRUSTED_AUTHSERV_ID=mx.google.com
   BUSINESS_ALLOWED_DOMAINS=[]
   BUSINESS_PHONES=[]
   MAX_REPLY_CHARS=600

   ENVIRONMENT=development
   ```

   Notes:
   - The Meta, Gemini and Google Sheets variables are required; the app will not start without them.
   - Leave `EMAIL_ADDRESS` empty to disable the email channel. Owner alerts are sent by email, so they also need `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` and `OWNER_EMAIL`.
   - SMTP uses SSL on port 465.
   - `GOOGLE_PRIVATE_KEY` is the service account's private key with literal `\n` sequences. The app converts them to real newlines at startup.
   - `GEMINI_MODEL`, `IMAP_HOST`, `SMTP_HOST`, `EMAIL_POLL_SECONDS`, `URGENCY_ALERT_THRESHOLD` and `ENVIRONMENT` have defaults and are optional.
   - Webhook signatures are always verified. `ENVIRONMENT=test` turns the check off and is meant for local tests only.
   - `BUSINESS_ALLOWED_DOMAINS` and `BUSINESS_PHONES` (JSON lists) are the only links, emails and phone numbers an auto-reply may contain.
   - `REQUIRE_SENDER_AUTH` holds mail whose DMARC result from `TRUSTED_AUTHSERV_ID` is not `pass`.

3. **Run the app locally**

   ```bash
   uvicorn app.main:app --reload
   ```

4. **For Messenger**, expose the app (e.g. with ngrok during development), then configure the webhook URL plus `META_VERIFY_TOKEN` in the Meta developer dashboard.

## Tests

```bash
python -m pytest tests -q
```

To re-run the attack suite (needs `GEMINI_API_KEY`; nothing is sent):

```bash
python -m redteam.harness redteam/cases --runs 5 --delay 3
python -m redteam.score --md
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
- Security residual risks (Messenger is not covered by the control-language check, encoded payloads, the Gmail app password) are listed in [`REPORT.md`](REPORT.md#9-residual-risks-and-recommendations).

## License

Add your preferred license here.

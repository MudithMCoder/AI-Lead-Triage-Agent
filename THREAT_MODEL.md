# Threat Model — AI Lead & Message Triage Agent

**Scope:** the agent at tag `v0-baseline` (commit `f16d59d`).
**Status:** Phase 1 of the security assessment. Findings tracked in `redteam/LOG.md`.
**Frameworks:** OWASP Top 10 for LLM Applications, OWASP Top 10 for Agentic Applications (2026), MITRE ATLAS.

---

## 1. System overview
FastAPI service. Two inbound channels — email (IMAP poll) and Facebook Messenger (webhook) — are normalised to an `IncomingMessage`, sent to Gemini for triage (category, urgency, entities, `suggested_reply`, `requires_human`) under a strict JSON schema, then handed to a deterministic router that may: archive silently, log to a Google Sheets CRM, email an owner alert, and/or auto-reply on the originating channel.

## 2. Data flow & trust boundaries
Fully attacker-controlled inputs: email headers + body, Messenger payloads.

- **B1 — Ingest.** Raw message → `parse_email` / webhook parse. Controls: loop-protection on email; HMAC signature on Messenger (**production only**).
- **B2 — Model.** Message text → Gemini. **No separation of instructions vs data** — the whole body is treated as content to act on. *Primary weakness (F1).*
- **B3 — Actions / sinks.** Router → SMTP reply, owner-alert email, Sheets write, Messenger send. **Model output drives all four** with no output validation. *(F2, F3.)*

## 3. Assets
- Owner's attention / the meaning of an "urgent" alert
- CRM integrity (the Google Sheet)
- Business email reputation (replies sent from the business address)
- Credentials: Gmail app password (full-mailbox), Gemini key, Google service-account key (full `drive` scope), Meta tokens
- API spend (Gemini / SMTP / Graph)

## 4. Attacker profiles
- **Opportunistic spammer / botnet** — volume; wants replies and CRM noise.
- **Competitor** — bury real leads, exhaust owner attention, poison the CRM.
- **Targeted attacker** — spoof a victim's address; use injection to steer outbound email or exfiltrate CRM data via spreadsheet formulas.

## 5. Threat register
| ID | Threat | Boundary | OWASP | MITRE ATLAS | Status (`v1-hardened`) → `LOG.md` |
|----|--------|----------|-------|-------------|--------|
| F1 | Goal hijack (indirect prompt injection) | B2 | ASI01 / LLM01 | AML.T0051 LLM Prompt Injection | **MITIGATED** — D2 `16ffa73` + D3 `986eb4a`: impact 0/30, model fooled 0/30 (was 10/30). Residual: encoded payloads (f1e) stopped by model only |
| F2 | Reply relay (attacker text in outbound reply) | B3 | ASI02 / LLM05 / LLM06 Excessive Agency | — | **FIXED in code** — D4 `994b4b2` `validate_reply`; proven by `test_sink_probe.py` |
| F3 | CRM formula / CSV injection | B3 | LLM05 Improper Output Handling | — | **FIXED in code** — D4 `994b4b2` `RAW` + neutraliser; proven by `test_sink_probe.py` |
| F4 | Owner-alert manipulation (force urgency=10) | B2→B3 | ASI09 Human-Agent Trust | — | **FIXED** — D3 `986eb4a`: 0/40 urgent alerts on injected cases (was 21/40); alerts marked model-assessed |
| F5 | Hidden-content split (HTML vs plain, CSS-hidden, comments) | B1 | LLM01 | AML.T0051 LLM Prompt Injection | **FIXED** — D1 `384d197`: f5b/f5c impact 0/10 (was 10/10), held 10/10 |
| F6 | Webhook signature fail-open (`ENVIRONMENT` defaults to `development`) | B1 | Security misconfig | — | **FIXED** — `a89e3e0` fails closed; `test_webhook.py` |
| F7 | Over-scoped credentials (full `drive` scope, full-mailbox app password) | Assets | Excessive privilege | — | **PARTIAL** — `1dd6122` Sheets scope reduced; Gmail app password = residual risk (§5a) |
| F8 | Sensitive message data written to logs | Ops | Sensitive info disclosure | — | **FIXED** — `689e3e3`; `test_logging.py` |
| F9 | No per-sender rate limit (denial-of-wallet) | B2 | LLM10 Unbounded Consumption | — | **FIXED** — `85a35be` per-sender limit before model call; `test_rate_limit.py` |
| F10 | Sender spoofing — no SPF/DKIM/DMARC check; `From` header trusted as identity | B1 | Spoofing / Improper Input Handling | — | **FIXED** — `96ea944`: f10_dmarc_fail held 5/5, benign_dmarc_pass not flagged |

## 5a. Residual risk (F7 — credentials)
- **Sheets (fixed):** the service account now holds only `auth/spreadsheets` (was `+ auth/drive`). `open_by_key` and `append_row` work with this scope; the account can no longer read or write arbitrary Drive files.
- **Gmail (residual):** the email channel authenticates with a Gmail **app password**, which grants **full mailbox access** (read, send, delete) and **cannot be scope-limited**. A leak of this secret compromises the whole mailbox. Recommendation: migrate to **OAuth 2.0** with the narrowest Gmail scopes (`gmail.readonly` for polling + `gmail.send` for replies) and drop the app password. Tracked as accepted residual risk until that migration.

## 6. Rules of engagement / out of scope
Owner-controlled test accounts only. Offline harness — no real sends. Benign canary markers only, no third-party spoofing. Google / Meta infrastructure is not attacked.

## 7. Phase status
- **Phase 0 — prep:** done (harness, baseline tag `v0-baseline`).
- **Phase 1 — threat model:** done (this document).
- **Phase 2 — expanded attack suite:** done 2026-11-16. F1 variants (5 techniques), F4 end-to-end, F5 (3 cases). **Before numbers:** model fooled 20/40 runs (50%) across 8 injected payloads; owner alert 21/40; matched control 0/5.
- **Phase 3 — layered defences:** done 2026-11-16, tag `v1-hardened` (`96ea944`). D1–D4 + F6–F10 fixes, 55 offline tests. **After numbers:** model fooled 0/40, impact 0/40, 35/40 held for review; no benign case held. Per-layer attribution runs (`8d04d26`, `384d197`, `16ffa73`, `986eb4a`) **pending** — see `redteam/LOG.md`.
- **Phase 4 — report (next):** per-layer before/after table + `REPORT.md` + write-up (blog, LinkedIn, demo video).

## 8. Phase 2 observations that shape the defences
- Attack-looking payloads were resisted; business-plausible ones succeeded, including in Sinhala → keyword or "jailbreak detector" filters alone are insufficient.
- The model's input can differ from what the owner sees (F5) → the fix must start at ingest (B1), not only in the prompt.
- Every hijack also produced an owner alert (F4) → the router must not let model output alone set urgency or disable human review.

## 9. Residual risks after Phase 3
- Encoded injections (e.g. base64) are not seen by the control-language detector; they are currently stopped by the model's own caution only.
- The detector is pattern-based; payloads that avoid schema names rely on D2 + the model, with D3's auto-reply/alert rules bounding the impact.
- Gmail app password: full-mailbox access, not scopable (§5a).
- Messenger is outside the offline harness; it shares D2–D4, while D1 and F10 are email-only.

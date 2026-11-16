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
| ID | Threat | Boundary | OWASP | MITRE ATLAS | Status → `LOG.md` |
|----|--------|----------|-------|-------------|--------|
| F1 | Goal hijack (indirect prompt injection) | B2 | ASI01 / LLM01 | AML.T0051 LLM Prompt Injection | **CONFIRMED** — 5/5 original; 10/30 across 6 techniques (business-note & Sinhala succeed, SYSTEM/role-play/base64 resisted) |
| F2 | Reply relay (attacker text in outbound reply) | B3 | ASI02 / LLM05 / LLM06 Excessive Agency | — | LATENT — model-mitigated |
| F3 | CRM formula / CSV injection | B3 | LLM05 Improper Output Handling | — | LATENT — model-mitigated |
| F4 | Owner-alert manipulation (force urgency=10) | B2→B3 | ASI09 Human-Agent Trust | — | **CONFIRMED** via F1/F5 — alert fired 21/40 injected runs vs 0/5 control |
| F5 | Hidden-content split (HTML vs plain, CSS-hidden, comments) | B1 | LLM01 | AML.T0051 LLM Prompt Injection | **CONFIRMED 5/5** — plain/HTML split & hidden div; invisible to the owner (HTML comments stripped incidentally) |
| F6 | Webhook signature fail-open (`ENVIRONMENT` defaults to `development`) | B1 | Security misconfig | — | Code review |
| F7 | Over-scoped credentials (full `drive` scope, full-mailbox app password) | Assets | Excessive privilege | — | Code review |
| F8 | Sensitive message data written to logs | Ops | Sensitive info disclosure | — | Code review |
| F9 | No per-sender rate limit (denial-of-wallet) | B2 | LLM10 Unbounded Consumption | — | Code review |
| F10 | Sender spoofing — no SPF/DKIM/DMARC check; `From` header trusted as identity | B1 | Spoofing / Improper Input Handling | — | Code review — not yet tested |

## 5a. Residual risk (F7 — credentials)
- **Sheets (fixed):** the service account now holds only `auth/spreadsheets` (was `+ auth/drive`). `open_by_key` and `append_row` work with this scope; the account can no longer read or write arbitrary Drive files.
- **Gmail (residual):** the email channel authenticates with a Gmail **app password**, which grants **full mailbox access** (read, send, delete) and **cannot be scope-limited**. A leak of this secret compromises the whole mailbox. Recommendation: migrate to **OAuth 2.0** with the narrowest Gmail scopes (`gmail.readonly` for polling + `gmail.send` for replies) and drop the app password. Tracked as accepted residual risk until that migration.

## 6. Rules of engagement / out of scope
Owner-controlled test accounts only. Offline harness — no real sends. Benign canary markers only, no third-party spoofing. Google / Meta infrastructure is not attacked.

## 7. Phase status
- **Phase 0 — prep:** done (harness, baseline tag `v0-baseline`).
- **Phase 1 — threat model:** done (this document).
- **Phase 2 — expanded attack suite:** done 2026-11-16. F1 variants (5 techniques), F4 end-to-end, F5 (3 cases) — see `redteam/LOG.md`. **Before numbers:** FULL hijack 20/40 runs (50%) across 8 injected payloads; owner alert 21/40; matched control 0/5. Still open from Phase 2: deferred F2/F3 sink probes, a standalone `f1_control.eml`, F10 test.
- **Phase 3 — layered defences (next):** D1 ingest normalisation (F5), D2 prompt delimiting (F1), D3 deterministic router guard (F1/F4), plus config fixes for F3/F6/F7/F9. Each tied to a finding ID; full suite re-run after each to attribute ASR drop, with false-positive checks on `benign_lead` and the control.
- **Phase 4 — report:** before/after attack-success-rate table + `REPORT.md` + write-up.

## 8. Phase 2 observations that shape the defences
- Attack-looking payloads were resisted; business-plausible ones succeeded, including in Sinhala → keyword or "jailbreak detector" filters alone are insufficient.
- The model's input can differ from what the owner sees (F5) → the fix must start at ingest (B1), not only in the prompt.
- Every hijack also produced an owner alert (F4) → the router must not let model output alone set urgency or disable human review.

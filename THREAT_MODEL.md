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
| F1 | Goal hijack (indirect prompt injection) | B2 | ASI01 / LLM01 | AML.T0051 LLM Prompt Injection | **CONFIRMED 5/5** |
| F2 | Reply relay (attacker text in outbound reply) | B3 | ASI02 / LLM05 | Excessive agency | LATENT — model-mitigated |
| F3 | CRM formula / CSV injection | B3 | LLM05 | Improper output handling | LATENT — model-mitigated |
| F4 | Owner-alert manipulation (force urgency=10) | B2→B3 | ASI09 Human-Agent Trust | — | Derived from F1 |
| F5 | Hidden-content split (HTML vs plain, CSS-hidden, comments) | B1 | LLM01 | — | Not yet tested |
| F6 | Webhook signature fail-open (`ENVIRONMENT` defaults to `development`) | B1 | Security misconfig | — | Code review |
| F7 | Over-scoped credentials (full `drive` scope, full-mailbox app password) | Assets | Excessive privilege | — | Code review |
| F8 | Sensitive message data written to logs | Ops | Sensitive info disclosure | — | Code review |
| F9 | No per-sender rate limit (denial-of-wallet) | B2 | Unbounded consumption | — | Code review |

## 6. Rules of engagement / out of scope
Owner-controlled test accounts only. Offline harness — no real sends. Benign canary markers only, no third-party spoofing. Google / Meta infrastructure is not attacked.

## 7. Next phases
- **Phase 2** — expand the attack suite: F4 and F5 end-to-end, F1 variants, and the deferred F2/F3 sink probes.
- **Phase 3** — layered defences, each tied to a finding ID.
- **Phase 4** — before/after attack-success-rate table + `REPORT.md` + write-up.

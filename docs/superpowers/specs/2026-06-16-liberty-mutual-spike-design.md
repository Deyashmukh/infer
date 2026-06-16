# Liberty Mutual Policy-Document Access — Phase 0a Feasibility Spike

- **Date:** 2026-06-16
- **Status:** Draft for review
- **Author:** (pairing)
- **Scope:** Phase 0a only — a standalone feasibility spike. Geico (0b) and the
  production app (Phase 1) are out of scope and get their own specs.

## 1. Context & problem

We are building a production web app that lets a user pull personal-lines policy
documents from carrier portals. Target carriers: **Liberty Mutual** and **Geico**.

The central technical risk is *not* the web app. It is reliable, programmatic,
**hosted (non-residential) access** to carrier portals that employ sophisticated
bot mitigation: Akamai Bot Manager / WAF browser fingerprinting (navigator
properties, JA3/TLS, canvas, sensor data) and IP-reputation filtering. The brief
explicitly disqualifies a "Playwright on my laptop" submission because it leans on
a trusted residential IP and pre-existing cookies the carrier already trusts.

This document specs **Phase 0a**: a feasibility spike proving end-to-end hosted
access for **Liberty Mutual only**. It is the go/no-go gate for the entire
approach. If hosted access cannot be made to work for one carrier cheaply, the
rest of the project is not worth building as designed.

## 2. Decisions already made (inputs to this spec)

- **Paid managed browser infrastructure is approved.** We are not limited to
  free/self-hosted tooling.
- **Primary provider: Browserbase.** Chosen for the human-in-the-loop login
  profile: advanced stealth, residential proxy egress, **Contexts** (persistent
  session/cookie reuse — directly serves the "session reuse" eval criterion),
  **Live View** for debugging the MFA step, clean Playwright-over-CDP DX.
- **Documented fallback: Bright Data Scraping Browser.** Stronger raw anti-bot
  pedigree (owns the residential network + unlocker tech). Used only if
  Browserbase cannot clear Liberty Mutual's bot mitigation.
- **Liberty Mutual first, then Geico.** Prove the single-carrier version before
  committing to both. LM-first de-risks the *machinery*; Geico (tougher Akamai) is
  then mostly "different selectors, same machinery."

## 3. Goal & success criteria (measurable)

From a **Browserbase-hosted** browser (advanced stealth, residential proxy egress,
US geolocation — explicitly NOT the developer's machine or IP), the spike must, for
Liberty Mutual:

1. Reach the login page without a hard block or unsolvable challenge.
2. Submit username + password and detect the MFA prompt.
3. Pass MFA via a human-in-the-loop CLI prompt (operator types the code received
   on their phone/email).
4. Reach the authenticated documents area and download **≥1 real policy PDF** to
   `spike/out/`, validated as an openable PDF (magic bytes + non-trivial size).
5. **Session reuse:** persist the Browserbase Context, re-run, and skip full
   login/MFA (or demonstrate measurably faster re-auth).
6. Capture evidence at each step: timestamped structured logs, screenshots, the
   **MFA-submit → PDF-bytes latency**, and any bot-challenge markers (Akamai
   reference IDs, "Access Denied", CAPTCHA).

### Pre-committed gate decision rule

Decide BEFORE running, so the outcome can't be rationalized after:

- **PASS** if criteria 1–5 succeed on Browserbase → proceed to Phase 0b (Geico).
- If criteria 1–4 fail on Browserbase **specifically due to bot mitigation**,
  retry once on the Bright Data fallback before declaring LM infeasible.
- A documented **negative result** (with evidence of exactly what blocked us) is a
  valid, valuable outcome — not a failure. We report it and stop, rather than
  burning budget on a dead approach.

## 4. Non-goals (YAGNI for Phase 0a)

- No React frontend, no FastAPI backend, no database, no deployment, no
  multi-user, no auth on our side.
- No document parsing/extraction. Success is fetching the PDF **bytes**, not
  reading or structuring their contents.
- No Geico. No production session store. No encryption-at-rest for documents (the
  spike writes to a git-ignored local dir; the app's secret/PII handling is
  specced in Phase 1).

## 5. Approach

A small **standalone Python script** under `spike/`, using Playwright connected to
a Browserbase remote session over CDP. This is throwaway-grade in ambition but
written so the reusable pieces (config, doc-fetch helper, the carrier module)
survive into Phase 1.

### 5.1 Components

| File | Responsibility | Depends on |
| --- | --- | --- |
| `spike/run_liberty.py` | Orchestrates the flow: login → MFA pause → doc fetch → reuse check. Emits logs + screenshots + `RESULTS.md`. | everything below |
| `spike/browserbase.py` | Create / re-attach a Browserbase session with stealth + residential proxy + persistent Context. Returns a connected Playwright browser. | `config` |
| `spike/carriers/liberty_mutual.py` | LM-specific selectors, navigation steps, MFA detection, document discovery. Isolated so 0b/Phase 1 reuse it. | Playwright page |
| `spike/docfetch.py` | The three-path document byte fetcher (see 5.3). | Playwright context |
| `spike/config.py` | Load + validate env from git-ignored `.env`. Fail fast with a clear message if a key is missing. | `python-dotenv` |
| `spike/out/` | Git-ignored output: PDFs, screenshots, run log, `RESULTS.md`. | — |

### 5.2 Flow

```
load + validate env
  └─> create Browserbase session (stealth, residential proxy, US geo, Context)
        └─> connect Playwright over CDP
              └─> navigate to LM login                         [screenshot]
                    └─> detect bot challenge? -> log + fail/fallback
                    └─> fill username + password, submit        [screenshot]
                          └─> detect MFA prompt, log channel     [screenshot]
                                └─> CLI: input("Enter MFA code: ")
                                      └─> submit code             [screenshot]
                                            └─> reach documents area [screenshot]
                                                  └─> discover doc URL(s)
                                                        └─> fetch bytes (5.3)
                                                              └─> save + validate PDF
                                                                    └─> persist Context id
re-run with Context id -> assert login/MFA skipped (criterion 5)
```

### 5.3 Document fetch strategy (preference order)

1. **Authenticated GET** of the discovered PDF URL via the browser context's
   cookie jar (`browser_context.request.get(url)`). Bytes come straight to our
   process. Fastest, cleanest. *Preferred.*
2. **Capture a browser-triggered download.** Wrinkle: with a *remote* browser the
   file lands on **Browserbase's** side, so we retrieve it via Browserbase's
   downloads API — an extra hop. Used when clicking is the only way to trigger doc
   generation.
3. **CDP `Page.printToPDF` fallback.** Only if a doc is rendered in an on-screen
   viewer with no fetchable URL. Last resort.

### 5.4 MFA handling

The script detects the MFA challenge, logs which channel it appears to use
(SMS / email / authenticator), then **pauses on stdin**. The operator enters the
code; the script submits and continues. In Phase 1 this becomes an async API state
machine (`AWAITING_MFA`), but that is out of scope here.

### 5.5 Session reuse

On first run, create a **named/persistent Browserbase Context**; store its id
(printed to stdout and/or `spike/out/context.json`). On re-run, pass the id back so
cookies persist. Criterion 5 is satisfied if the re-run reaches the documents area
without a fresh username/password/MFA cycle (or with a measurably shorter one).

## 6. Tech & dependencies

- Python 3.12+, `playwright`, `browserbase` SDK (or a raw CDP connect URL),
  `python-dotenv`, `structlog` for structured logs.
- **Dependencies pinned to exact versions; lockfile committed** (`uv` preferred).
- Quality tooling per the project bar: `ruff` (lint + format), `mypy --strict`,
  `pytest`.
- **Tests:** the spike is exploratory, but its *machinery* gets offline unit
  tests where they don't require live carrier access — e.g. env loading/validation
  in `config`, and document-URL discovery parsing against **saved HTML fixtures**
  in `carriers/liberty_mutual`. The live login is validated **manually with
  captured evidence**, not in CI (it needs real creds, MFA, and a paid browser).

## 7. Risks & open questions (what the spike is explicitly testing)

- **Core unknown:** does residential-proxy + advanced stealth clear Liberty
  Mutual's bot mitigation on a *hosted* browser at all?
- Which MFA channel does LM use, and does its timing cooperate with automation?
- Are LM policy docs fetchable PDFs behind stable URLs (path 1), download-triggers
  (path 2), or viewer-only (path 3)?
- Latency: is MFA-submit → PDF realistically within a single-digit-seconds budget?
  (Measure — do not assume or pre-pin a threshold.)
- Does Context-based reuse actually skip MFA on LM, or does LM re-challenge a
  returning session?

## 8. Evidence / definition of done

`spike/out/` contains:

- ≥1 valid Liberty Mutual policy PDF (validated openable).
- Step screenshots covering login → MFA → documents → fetch.
- A structured run log with per-step timestamps and the MFA-submit → PDF latency.
- `RESULTS.md` summarizing: pass/fail per criterion 1–6, the MFA channel observed,
  which doc-fetch path worked, measured latency, any bot-challenge encountered, and
  a **go/no-go recommendation for Phase 0b**.

## 9. Security notes (even for a spike)

- Secrets live only in a git-ignored `.env`. A committed `.env.example` documents
  every key with placeholders (public vs secret). Secrets are never logged.
- PDFs and screenshots may contain PII → `spike/out/` is git-ignored and never
  committed.
- The operator holds the carrier credentials in their local `.env`. The author
  writes code that reads from env and never handles plaintext secrets.

## 10. Out-of-scope sketch (Phase 1 — direction only, NOT part of this spec)

For context on where this leads; specced separately after 0a/0b:

- **Frontend (React + TS):** carrier dropdown → credential form → MFA input that
  appears when the backend signals `mfa_required` → document list + `react-pdf`
  viewer with a download button.
- **Backend (FastAPI):** per-session state machine
  `STARTING → AWAITING_MFA → FETCHING → READY/FAILED`. Drives Browserbase. Fetches
  doc bytes through the authenticated session and re-serves them from our own
  endpoint (the carrier URL is only valid with cookies that live in the remote
  browser, so we cannot forward the link to the user's browser). Encrypts/persists
  session handles for reuse. Typed error taxonomy: `CarrierAuthError`, `MfaError`,
  `BotChallengeError`, `DocFetchError`.
- **Doc handling:** ephemeral stream-through by default; optional short-TTL
  encrypted cache for instant re-views. No plaintext at rest.
- **Deployment:** frontend static-hosted; backend in a small container. The heavy
  stealth browser lives in **Browserbase, not our box** — that is the "hosted
  somewhere that isn't my machine" answer.
- **Latency strategy:** session reuse to skip MFA on re-runs; fetch via direct
  authenticated URLs where possible.

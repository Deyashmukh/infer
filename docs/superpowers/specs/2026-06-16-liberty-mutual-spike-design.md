# Liberty Mutual Policy-Document Access — Phase 0a Feasibility Spike

- **Date:** 2026-06-16
- **Status:** Draft for review (revised after adversarial review)
- **Author:** (pairing)
- **Scope:** Phase 0a only — a standalone feasibility spike. Geico (0b) and the
  production app (Phase 1) are out of scope and get their own specs.

## 1. Context & problem

We are building a production web app that lets a user pull personal-lines policy
documents from carrier portals. Target carriers: **Liberty Mutual** and **Geico**.

The central technical risk is *not* the web app. It is reliable, programmatic,
**hosted (non-residential) access** to carrier portals that defend their login
surface in depth. Live recon of the Liberty Mutual login domains confirms a hard
stack: **Akamai Bot Manager** (`_abck` / `bm_sz` sensor cookies, `edgekey.net`
fronting, `server-timing: ak_p`), **Auth0** identity (Adaptive MFA + default
brute-force lockout), and **Shape/F5** signals. The brief explicitly disqualifies a
"Playwright on my laptop" submission because it leans on a trusted residential IP
and pre-existing cookies; getting past this stack from *hosted* infrastructure is
the actual hard problem.

This document specs **Phase 0a**: a feasibility spike proving end-to-end hosted
access for **Liberty Mutual only**. It is the go/no-go gate for the entire
approach. If hosted access cannot be made reliable for one carrier cheaply, the
rest of the project is not worth building as designed.

**Honest prior:** an authenticated login through a hosted stealth browser against
Akamai + Auth0 + Shape is hard and may well fail; this is a cat-and-mouse surface,
not a solved capability. We run the spike *because* it is the cheap way to learn
this before building an app on top — a clean negative result is a valid, valuable
outcome. Calibration in the other direction: insurance-data aggregators (e.g.
Canopy Connect) pull exactly these documents commercially, so it is feasible *with
the right infrastructure* — the spike tests whether *ours* clears it.

## 2. Decisions already made (inputs to this spec)

- **Paid managed browser infrastructure is approved**, with a **start-cheap
  posture**: run the spike on whatever Browserbase tier signup gives us, and only
  escalate to a higher-cost tier *if the spike fails specifically on bot
  detection* (not on selectors or MFA). We do not pre-pay for the top tier.
- **Primary provider: Browserbase.** Chosen for the human-in-the-loop login
  profile: stealth, residential proxy egress, **Contexts** (persistent
  session/cookie reuse — serves the "session reuse" eval criterion), **Live View**
  for debugging the MFA step, clean Playwright-over-CDP DX.
- **Stealth tier reality:** Browserbase's strongest tier is **"Verified"**, which
  per their docs works by being *recognized as legitimate by bot-protection
  partners* (a partnership/allowlist model) — **not** fingerprint spoofing — and is
  **gated to the Scale plan** (contact-sales). Whether it covers Akamai/Shape on
  LM's specific config is unknown and is part of what the spike tests. Per the
  start-cheap posture, we confirm what tier we actually have at signup and treat
  Verified as an *escalation lever*, not a baseline assumption.
- **Fallback is NOT Bright Data.** Bright Data's AUP prohibits collecting data
  behind a login and disables password entry by default, so it is contractually
  unsuitable for this exact task. If Browserbase fails *specifically on bot
  detection*, the escalation levers are: enable Browserbase Verified (Scale), or a
  self-hosted stealth browser (patchright/rebrowser) on a residential/mobile proxy
  — evaluated only if the captured failure mode suggests it would help.
- **Liberty Mutual first, then Geico.** Prove the single-carrier version before
  committing to both. LM-first de-risks the *infrastructure machinery*; Geico's bot
  layer is an **independent, possibly harder** risk to be proven separately in 0b
  (not "just different selectors").

## 3. Goal & success criteria (measurable)

From a **Browserbase-hosted** browser (residential proxy egress, US geolocation —
explicitly NOT the developer's machine or IP), the spike must, for Liberty Mutual:

1. **Bot-gate reliability (cheap, repeatable, no lockout risk):** across **≥3 fresh
   hosted sessions**, reach and render the real login form with **no hard block and
   no unsolvable challenge** (Akamai Access-Denied, CAPTCHA loop). These checks stop
   at the rendered form and do **not** submit credentials, so they cost nothing
   toward Auth0 lockout.
2. **Full happy path (≥1, target 2 completions):** submit username + password,
   detect the MFA prompt, pass MFA via a human-in-the-loop CLI prompt (operator
   types the code), reach the authenticated documents area, and download **≥1 real
   policy PDF** to `spike/out/`, validated as openable (PDF magic bytes +
   non-trivial size). The document bytes must be fetched **through the remote
   browser's proxied egress** (see §5.3), not from our own IP.
3. **Session reuse (measured finding):** persist the Browserbase Context, re-run
   **≥2 times**, and record whether the carrier lets us back into the documents
   area **without a fresh MFA challenge**. Skipping MFA = pass. A re-challenge is a
   documented limitation (worse latency/UX, app still viable), **not** an automatic
   project-kill — because the decision (Auth0 Adaptive MFA / Akamai Account
   Protector re-scoring a returning session) is server-side, independent of whether
   our cookie replay works.
4. **Latency:** time **MFA-submit → PDF-bytes** on each happy-path completion
   (criterion 2), and **reattach → PDF-bytes** on each reuse run (criterion 3,
   which skips MFA). Report each with its sample size — median where we have ≥2
   samples, a clearly-labelled single sample otherwise — and report first-session
   (cold) overhead separately from the reused (warm) path. Do not pre-pin a
   threshold; the residential proxy is a fixed tax on this number.
5. **Evidence at every step:** timestamped structured logs, screenshots, and
   **structured** bot-challenge markers (see §8) — not free-text.

### Pre-committed gate decision rule

Decide BEFORE running, so the outcome can't be rationalized after:

- **PASS** = criterion 1 holds (≥3 clean form renders) **AND** criterion 2 holds
  (≥1 full login→MFA→PDF completion through proxied egress). Criterion 3 (reuse)
  and criterion 4 (latency) are *measured findings* that shape Phase 1, not
  gate conditions. → proceed to Phase 0b (Geico).
- **FAIL** = the hosted browser is hard-blocked / served an unsolvable challenge at
  the bot gate, OR cannot complete a single authenticated fetch through proxied
  egress.
- If FAIL is **specifically due to bot detection** (Akamai/Shape), escalate **once**
  via a §2 lever (Browserbase Verified, or self-hosted stealth) before declaring LM
  infeasible.
- A documented **negative result** with a precise failure classification (§8) is a
  valid, valuable outcome. We report it and stop, rather than burning budget — or
  the account — on a dead approach.

### Hard safety rail (lockout)

Auth0 default brute-force lockout (~10 attempts, **locks regardless of IP**) means
the dominant operational risk is **locking out the real account / firing fraud
alerts**. Therefore: **at most ONE password submission per run; on any login
failure, abort the entire spike immediately** (never loop, never retry credentials).
Criterion 1's reliability checks never submit credentials, so they can repeat freely.

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
a Browserbase remote session over CDP. Throwaway-grade in ambition, but the
reusable pieces (config, doc-fetch helper, the carrier module) are written to
survive into Phase 1.

### 5.1 Components

| File | Responsibility | Depends on |
| --- | --- | --- |
| `spike/run_liberty.py` | Orchestrates: bot-gate checks → login → MFA pause → doc fetch → reuse runs. Emits logs + screenshots + `RESULTS.md`. Enforces the 1-attempt cap. | everything below |
| `spike/browserbase.py` | Create / re-attach a Browserbase session with stealth + residential proxy + US geo + persistent Context. Returns a connected Playwright browser. Records the actual tier in use. | `config` |
| `spike/carriers/liberty_mutual.py` | LM-specific selectors, navigation, MFA detection, document discovery. Isolated so 0b/Phase 1 reuse it. | Playwright page |
| `spike/docfetch.py` | Proxied-egress document byte fetcher (see §5.3). | Playwright page/context |
| `spike/config.py` | Load + validate env from git-ignored `.env`. Fail fast with a clear message if a key is missing. | `python-dotenv` |
| `spike/out/` | Git-ignored output: PDFs, screenshots, run log, `RESULTS.md`, `context.json`. | — |

### 5.2 Flow

```
PRE-FLIGHT: confirm LM login/doc domains are reachable through Browserbase
            proxies (not on the financial/banking blocklist); record tier.
load + validate env
  └─> [criterion 1] x3: fresh session -> navigate to LM login
        -> assert login form renders, no Akamai/CAPTCHA block  [screenshot each]
  └─> [criterion 2] create session (stealth, residential proxy, US geo, Context)
        └─> connect Playwright over CDP
              └─> navigate to LM login                          [screenshot]
                    └─> detect bot challenge? -> classify + ABORT (gate FAIL)
                    └─> fill username + password, submit ONCE     [screenshot]
                          └─> login failed? -> ABORT (lockout rail)
                          └─> detect MFA prompt, log channel       [screenshot]
                                └─> CLI: input("Enter MFA code: ")
                                      └─> submit code               [screenshot]
                                            └─> reach documents area [screenshot]
                                                  └─> discover doc URL(s)
                                                        └─> fetch bytes via §5.3
                                                              └─> save + validate
                                                                    └─> persist Context id
  └─> [criterion 3] x2: re-attach Context -> assert documents area reached;
        record whether MFA was re-challenged. [criterion 4] time MFA-submit->PDF.
```

### 5.3 Document fetch strategy (must egress through the remote browser)

The fetch must ride the **same proxied IP + fingerprint** that authenticated the
session. `browser_context.request.get()` is **rejected** for the live fetch: it
shares the cookie jar but issues the request from our *client* process/IP, bypasses
the residential proxy, and would hit Akamai from an unsolved IP. Preference order:

1. **In-page `fetch` → bytes.** `page.evaluate` a `fetch(url)` inside the remote
   browser, return the body as base64, decode on our side. Rides the proxy +
   fingerprint. *Preferred.*
2. **Navigate + capture.** Navigate the remote browser to the PDF URL (loads
   through the proxy) and capture the response body via CDP. Use when the doc opens
   inline.
3. **Triggered download.** Click a download control; the file lands on
   **Browserbase's** side, retrieved via the Downloads API. Gotchas to honor:
   send CDP `Browser.setDownloadBehavior` with the literal `downloadPath:
   "downloads"`; the Downloads API is **eventually consistent** (retry/backoff for
   large files); Python Playwright `download.path()/save_as()` raise on a remote CDP
   browser — do not use them.
4. **CDP `Page.printToPDF` fallback.** Only if a doc is viewer-only with no
   fetchable URL. Last resort.

### 5.4 MFA handling

The script detects the MFA challenge, logs the apparent channel
(SMS / email / authenticator), then **pauses on stdin**. The operator enters the
code; the script submits **once** and continues. In Phase 1 this becomes an async
API state machine (`AWAITING_MFA`); out of scope here.

### 5.5 Session reuse (tests the carrier, not just our cookie replay)

Browserbase Contexts persist the Chromium user-data-dir (cookies backed
up/restored; note: **HTTP cache is not persisted**, only Service-Worker caches — so
the latency benefit of reuse is smaller than naïve caching would suggest). On first
run we create a named/persistent Context and store its id
(`spike/out/context.json`). The reuse runs re-attach it and record the **carrier's**
response: does Auth0/Akamai let the returning hosted session into the documents
area without re-issuing MFA? That server-side behavior — not whether cookies
replayed — is the finding.

## 6. Tech, dependencies & pre-flight

- Python 3.12+, `playwright`, `browserbase` SDK (or a raw CDP connect URL),
  `python-dotenv`, `structlog` for structured logs.
- **Dependencies pinned to exact versions; lockfile committed** (`uv` preferred).
- Quality tooling per the project bar: `ruff` (lint + format), `mypy --strict`,
  `pytest`.
- **Tests:** the spike is exploratory, but its *machinery* gets offline unit tests
  that need no live carrier access — env loading/validation in `config`, the
  base64/byte handling in `docfetch`, and document-URL discovery parsing against
  **saved HTML fixtures** in `carriers/liberty_mutual`. The live login is validated
  **manually with captured evidence**, not in CI (it needs real creds, MFA, and a
  paid browser).
- **Pre-flight checks (before spending a login attempt):** (a) confirm the LM
  login/doc domains load through Browserbase proxies — Browserbase's built-in
  proxies block banking/financial domain categories, and an LM auth hop classified
  that way would fail outright; (b) record which Browserbase tier we actually have
  (drives the §2 escalation decision); (c) confirm the test account is expendable
  and its owner has consented (see §9).

## 7. Risks & open questions (what the spike is explicitly testing)

- **Core unknown (expected-to-be-hard):** does residential-proxy + Browserbase
  stealth let a *hosted* browser complete an authenticated Liberty Mutual login at
  all, reliably (criterion 1's ≥3 clean renders, not one lucky pass)?
- Which MFA channel does LM use, and does its timing cooperate with automation?
- Are LM policy docs fetchable PDFs behind stable URLs, inline navigations, or
  download-triggers (which §5.3 path applies)?
- Latency: is warm MFA-submit → PDF within a single-digit-seconds budget, given the
  residential-proxy tax? (Measure — do not assume.)
- Does the carrier re-challenge a returning hosted session (criterion 3)?
- **Primary operational risk:** account lockout / fraud alerts from failed login
  attempts — mitigated by the §3 one-attempt-abort rail.

## 8. Evidence / definition of done

`spike/out/` contains:

- ≥1 valid Liberty Mutual policy PDF (validated openable), fetched via a §5.3
  proxied path.
- Step screenshots covering form-render checks → login → MFA → documents → fetch.
- A structured run log with per-step timestamps and the MFA-submit → PDF latency
  (cold vs warm; median where ≥2 samples, else a labelled single sample).
- `RESULTS.md` summarizing: pass/fail per criterion 1–5, the MFA channel observed,
  which §5.3 fetch path worked, measured latency, reuse re-challenge behavior, and a
  **go/no-go recommendation for Phase 0b**.
- **Structured failure classification** (named fields, not prose): Akamai `_abck`
  state / reference id, Auth0 challenge type, HTTP status, CAPTCHA presence,
  screenshot path. This is the most valuable output of a negative run — it
  determines whether the approach is dead or tunable.

## 9. Authorization & safety

- **ToS posture (explicit decision, not an omission):** Liberty Mutual's website
  terms prohibit automated/systematic retrieval, and its online-account terms
  restrict use to the customer. We proceed for this **sanctioned take-home** on the
  basis that we pull the **account owner's own documents with the owner's explicit
  consent**, accept the contractual risk *for the exercise*, and document it here
  rather than gloss it. This is a conscious, time-boxed decision; it is not a model
  for unconsented or third-party data collection.
- **Consent + expendable account:** before any login attempt, confirm the LM
  account owner explicitly OKs automated access and accepts the possibility of
  lockout / fraud alerts. Prefer an account we can afford to get locked.
- **Lockout rail:** one password submission per run; abort the spike on any login
  failure (see §3).
- **Secrets:** only in a git-ignored `.env`; a committed `.env.example` documents
  every key with placeholders (public vs secret). Secrets are never logged.
- **PII:** PDFs and screenshots may contain personal data → `spike/out/` is
  git-ignored and never committed. The operator holds the carrier credentials in
  their local `.env`; the author writes code that reads from env and never handles
  plaintext secrets.

## 10. Out-of-scope sketch (Phase 1 — direction only, NOT part of this spec)

For context on where this leads; specced separately after 0a/0b:

- **Frontend (React + TS):** carrier dropdown → credential form → MFA input that
  appears when the backend signals `mfa_required` → document list + `react-pdf`
  viewer with a download button.
- **Backend (FastAPI):** per-session state machine
  `STARTING → AWAITING_MFA → FETCHING → READY/FAILED`. Drives Browserbase. Fetches
  doc bytes **through the authenticated remote session** and re-serves them from our
  own endpoint (the carrier URL is only valid with cookies that live in the remote
  browser, so we cannot forward the link to the user's browser). Encrypts/persists
  session handles for reuse. Typed error taxonomy: `CarrierAuthError`, `MfaError`,
  `BotChallengeError`, `DocFetchError`.
- **Doc handling:** ephemeral stream-through by default; optional short-TTL
  encrypted cache for instant re-views. No plaintext at rest.
- **Deployment:** frontend static-hosted; backend in a small container. The heavy
  stealth browser lives in **Browserbase, not our box** — that is the "hosted
  somewhere that isn't my machine" answer.
- **Latency strategy:** session reuse to skip MFA where the carrier permits it;
  fetch via proxied authenticated paths.

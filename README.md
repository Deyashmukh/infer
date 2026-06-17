# infer

Pull your **own** personal-lines insurance policy document straight from the carrier's portal
and render it in the browser — without the carrier's clunky UI. Pick a carrier, enter your
portal credentials, approve the MFA prompt, and a policy PDF appears in an in-page viewer.

Supported carriers: **Liberty Mutual** and **Geico**.

> ⚠️ Use only with **your own accounts**, with consent. Credentials are entered in the UI at
> runtime, used once to fetch your document, and never stored.

---

## How it works

```
Browser (React)                 Backend (FastAPI)                Carrier portal
─────────────────               ──────────────────               ──────────────
pick carrier  ─────────────────▶ start session ───────────────▶  headless Chromium logs in
enter portal creds                                               carrier sends MFA code
            ◀── "awaiting MFA" ──                                       │ (to your phone)
enter MFA code ────────────────▶ submit code ─────────────────▶  verify → fetch document
            ◀──── PDF bytes ─────  render in react-pdf  ◀───────  policy PDF
```

The backend drives a **self-hosted headless Chromium** (Playwright). Each carrier is a small
module of browser steps behind a common interface; the session manager runs a state machine
(`STARTING → AWAITING_MFA → VERIFYING_MFA → FETCHING → READY | FAILED`) and streams status to
the frontend by polling.

**What you get per carrier (one document each):**
- **Liberty Mutual** — the **Policy declarations** PDF, captured from the documents portal.
- **Geico** — your **auto ID-card** PDF, fetched from the Proof-of-Insurance API.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + TypeScript, Vite, `react-pdf` |
| Backend | FastAPI (async), Playwright (self-hosted Chromium) |
| Tooling | `uv`, `ruff`, `mypy --strict`, `pytest` · `vitest`, `eslint`, `tsc` |

## Setup

**Backend** (Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/)):

```bash
uv sync                              # install pinned deps from the lockfile
uv run playwright install chromium   # one-time browser download
cp .env.example .env                 # then fill in the login URLs (see comments in the file)
```

**Frontend** (Node):

```bash
cd frontend && npm install
```

## Run

```bash
# backend (terminal 1)
uv run uvicorn --factory backend.main:build_production_app --host 127.0.0.1 --port 8000

# frontend (terminal 2)
cd frontend && npm run dev          # serves http://localhost:5173 (or :5174 if taken)
```

Open the frontend URL, pick a carrier, and follow the prompts. Set `HEADLESS=false` in `.env`
to watch the automation drive the browser.

## Architecture

```
backend/
  main.py            # app factory: CORS, logging, session sweeper, prod wiring
  api.py             # REST routes: /sessions, /sessions/{id}, .../mfa, .../documents/{doc}
  sessions.py        # SessionManager state machine + in-memory session-reuse cache
  browser.py         # BrowserDriver + CarrierModule protocols; FakeDriver for offline tests
  chromium_driver.py # real Playwright driver; per-carrier launch args + anti-bot masking
  carriers/
    registry.py      # carrier value -> module dispatch
    lm.py            # Liberty Mutual browser steps (Auth0 login, popup PDF capture)
    geico.py         # Geico browser steps (eCAMS login, /ws/ API document fetch)
  geico_idcard_api.py# pure parsing/URL helpers for Geico's ID-card API (unit-tested offline)
```

Adding a carrier = one module implementing the `CarrierModule` protocol (`open_login`,
`submit_credentials`, `submit_mfa`, `list_documents`, `fetch_document`, `is_authenticated`)
plus a `LAUNCH_ARGS` list and a registry entry.

## Anti-bot & hosting

Carrier edges actively fingerprint automation. The mitigations in the product:
- mask `navigator.webdriver`, and present a clean Chrome user-agent (strip the
  `HeadlessChrome` tell);
- **per-carrier HTTP version** — Liberty Mutual's Cloudflare login edge rejects HTTP/2
  (`--disable-http2`, confirmed live), while Geico runs over HTTP/2.

When run from a datacenter IP, carrier edges can still tarpit the automated browser on the
sensitive credential POST; the deployment intent is to run the browser behind residential
egress (the proxy hooks are wired but deferred).

## Latency

The graded metric is **MFA-submit → first document on screen**. Measured end-to-end:

| Carrier | Typical | Dominated by |
|---|---|---|
| Liberty Mutual | ~9–10 s | MFA-verify (~3 s, carrier) + 745 KB PDF over HTTP/1.1 (~4.5 s, carrier) |
| Geico | ~11 s | MFA-verify (~3.5 s) + Proof-of-Insurance lookup (~4 s) + on-demand PDF gen (~3.5 s) |

The original **< 8 s** target proved structurally out of reach for the *real* carrier
document: the carriers' own MFA verification and on-demand PDF generation alone consume ~7–8 s
before any of our code runs, and no client-side change touches that. We optimized everything
in our control (targeted waits instead of `networkidle`, no redundant re-navigation, fetching
exactly one document). Reliably beating 8 s would require showing a fast, locally-rendered
summary first and streaming the official PDF in behind it — a deliberate product tradeoff that
was left out in favor of always showing the real carrier document.

## Testing

```bash
# backend
uv run pytest            # 87 tests, fully offline (FakeDriver — no network, no browser)
uv run ruff check .
uv run mypy backend spike

# frontend
cd frontend && npm test  # 29 tests
npm run lint && npx tsc --noEmit
```

The carrier browser steps are exercised live; everything else (orchestration, API, parsing,
CORS, launch-arg wiring) is covered by the offline suite.

## Security & privacy

- Portal credentials are entered in the UI, used once, and **never persisted** (not to disk,
  not to `.env`).
- `.env` and `spike/out/` (which may hold captured cookies, screenshots, and policy PDFs) are
  git-ignored and must never be committed.
- The in-memory session-reuse cache is single-user-scoped and never written to disk.

## Known limitations

- One document per carrier (by design).
- Latency is carrier-server-bound (see above).
- Geico session-reuse is limited (its session token lives in the dashboard URL).
- Residential-proxy egress is wired but deferred.

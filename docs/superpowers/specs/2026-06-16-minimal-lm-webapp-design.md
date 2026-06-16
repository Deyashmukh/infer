# Minimal Liberty Mutual Policy-Document Web App — Design

- **Date:** 2026-06-16
- **Status:** Draft for review
- **Scope:** A minimal but real human-in-the-loop web app for **Liberty Mutual
  only**, used to prove hosted access end-to-end through a UI. This is the
  foundation of the actual submission app, built minimal. Geico and session reuse
  are explicit follow-ups, out of scope here.
- **Supersedes:** the CLI-based Phase B of
  `docs/superpowers/specs/2026-06-16-liberty-mutual-spike-design.md`. Phase A
  (offline machinery, already built + tested) is reused. The spike spec's
  authorization (§9), gate framing, and lockout rail carry over.

## 1. Context

We are building a web app that lets a user pull personal-lines policy documents
from carrier portals. The central risk remains hosted (non-residential) access
past Liberty Mutual's bot stack (Akamai Bot Manager + Auth0 + Shape/F5). Phase A
delivered the reusable offline machinery (config, PDF validate/decode, bot-challenge
classification, LM page-state + document-URL discovery, an injected-clock timer, a
Browserbase session-params builder, a lockout guard + gate evaluator) — all built
test-first, 33 tests, mypy --strict + ruff clean.

The user chose to validate the **human-in-the-loop flow through a real UI** rather
than a CLI, because that is how the production app works: the user types their
credentials and MFA code, the backend drives the carrier login on hosted
infrastructure, and the documents render in the browser. The first real run of
this app **is the go/no-go feasibility gate** — proving we can reach LM, complete
an authenticated login + MFA, and fetch a policy PDF from a hosted browser.

**Honest prior (unchanged):** this login surface is hard; the spike may fail, and
a clean, well-classified negative result is a valid outcome. Insurance-data
aggregators do this commercially, so it is feasible *with the right infra* — this
app tests whether ours clears it.

## 2. Goal & success criteria (measurable)

Through the web UI, for Liberty Mutual, from a Browserbase-hosted browser
(residential proxy egress, US geo — NOT the dev machine):

1. User selects LM, enters username + password; backend reaches the LM login from
   the hosted browser **without a hard block / unsolvable challenge**.
2. Backend submits credentials and detects the MFA prompt; the UI **reveals an MFA
   field**.
3. User submits the MFA code; backend reaches the authenticated documents area and
   **fetches ≥1 real policy PDF** through the proxied remote browser.
4. The UI **renders the PDF** (react-pdf) and offers download.
5. Latency from **MFA-submit → document rendered** is measured and reported (the
   brief's graded metric). Do not pre-pin a threshold; report the measurement.
6. On any bot-block, the failure is **classified with structured fields** (Akamai
   `_abck` state, HTTP status, CAPTCHA presence) and surfaced as a typed error.

**Pre-committed gate (carried from the spike spec):** PASS = the hosted browser
reaches and renders the LM login reliably AND completes ≥1 full
login→MFA→PDF-fetch→render through proxied egress. A hard block / unsolvable
challenge = FAIL; if the failure is specifically bot detection, escalate once
(Browserbase "Verified"/Scale, or a self-hosted stealth browser) before declaring
infeasible. A documented negative result is valid.

## 3. Non-goals (YAGNI)

- **No session reuse yet** (deferred — the next increment; it is a graded criterion
  but not part of proving the base flow).
- No Geico (added after LM is green — independent bot-layer risk).
- No multi-user concurrency guarantees, no horizontal scaling, no external
  state store / job queue (in-memory, single-process backend).
- No user accounts / auth on *our* side; no database.
- No heavy UI polish (clean + minimal now; polish is a later pass).
- No document parsing/extraction — success is fetching + rendering the PDF bytes.
- No long-term storage of credentials or documents.

## 4. Architecture

**Option A — background async task + in-memory session registry + polling.**

```
React SPA (Vite, TS)                 FastAPI backend (async)              Browserbase
  CarrierSelect                        POST /sessions      ─┐               (hosted browser,
  CredentialForm   ── REST + poll ──►  GET  /sessions/{id}   │ in-memory      residential proxy)
  MfaPrompt                            POST /sessions/{id}/mfa│ registry +
  DocumentViewer   ◄── PDF bytes ──    GET  /sessions/{id}/documents/{doc}  async task
   (react-pdf)                          status machine ──(asyncio.Event)──► async Playwright/CDP
  reuses Phase A core (spike/): classify_lm_page, discover_document_urls, challenge, Timer, build_session_params
```

- `POST /sessions` creates a `Session`, returns its id immediately, and launches a
  **background asyncio task** (its reference **stored on the `Session`** so it is
  not garbage-collected mid-flight) that drives the login via async Playwright
  until it hits MFA and sets `AWAITING_MFA`.
- The task then does a **bounded** wait for the code:
  `await asyncio.wait_for(code_queue.get(), timeout=MFA_DEADLINE)` with
  `MFA_DEADLINE = 120s` (below the carrier OTP-expiry window and well under
  Browserbase's ~10-min CDP-idle drop). On timeout → `FAILED`
  (`SessionExpiredError`) **and `driver.close()`**. The code is passed via an
  `asyncio.Queue` (not an `Event` — an Event carries no payload and can't support
  the 3-try retry). **Single-flight** is enforced by a synchronous status flip to
  `VERIFYING_MFA` in the `/mfa` handler (event-loop-atomic — no `await` between the
  `409` check and the flip), so a concurrent duplicate POST gets `409`. No
  `asyncio.Lock` is needed.
- `POST /sessions/{id}/mfa` enqueues the code; the task resumes, transitions to a
  transient `VERIFYING_MFA`, then `FETCHING`, then `READY`.
- The frontend **polls** `GET /sessions/{id}` for status (≈700 ms interval).
- **Cleanup is guaranteed:** the task runs its whole flow in a `try/finally` whose
  `finally` calls `driver.close()` (idempotent) on every terminal path — success,
  any `CarrierError`, timeout, or `CancelledError`. The TTL sweeper **cancels the
  task and awaits `driver.close()`** for any session it evicts, so no paid
  Browserbase session is ever orphaned.
- The heavy stealth browser lives in **Browserbase, not our backend** — the
  "hosted somewhere that isn't my machine" answer. The backend holds only the
  lightweight CDP connection + session state.
- Session state is **in-memory, single-process** (the YAGNI cut vs. a Redis/worker
  design). Externalizing it for multi-instance hosting is a documented future step.

## 5. Components & file structure

**Backend** (`backend/`, FastAPI, async):

| File | Responsibility |
| --- | --- |
| `backend/main.py` | FastAPI app, CORS pinned to the frontend origin, route registration, lifespan (starts a TTL sweeper for stale sessions). |
| `backend/api.py` | The 4 route handlers (below). |
| `backend/sessions.py` | `SessionRegistry` (in-memory dict) + `Session` (status, `asyncio.Queue` for MFA codes, stored task reference, in-memory doc store, typed error, attempt counters) + `SessionManager.run()` orchestration (bounded MFA wait, `try/finally` cleanup) + a TTL sweeper that cancels tasks and closes drivers. |
| `backend/browser.py` | `BrowserDriver` **Protocol** + `BrowserbaseDriver` (async Playwright over CDP). |
| `backend/carriers/lm.py` | LM async navigation steps (selectors calibrated live), reusing the pure `classify_lm_page` / `discover_document_urls`. |
| `backend/models.py` | Pydantic request/response models + the error taxonomy. |

**Reused Phase A core** (`spike/`): `challenge`, `carriers/liberty_mutual` (pure
classify + discovery), `timing.Timer`, `browserbase.build_session_params`,
`docfetch` (`is_valid_pdf`, `decode_base64_pdf`).
**Config change:** `spike/config.py` removes the `lm_username` / `lm_password`
**fields from the `Config` dataclass** and the corresponding `env[...]` reads from
`load_config` (not merely the `_REQUIRED` tuple — the fields and reads must go, or
`load_config` still `KeyError`s). Required env becomes `BROWSERBASE_API_KEY`,
`BROWSERBASE_PROJECT_ID`, `LM_LOGIN_URL`; `BROWSERBASE_CONTEXT_ID` stays optional.
`test_config.py` and `.env.example` are updated to match. (Verified safe:
`build_session_params` reads only project id / proxy / context, not the creds.)
Done test-first.
*(Deferred cleanup: rename `spike/` → `core/` once the app stabilizes — not churned now.)*

**Frontend** (`frontend/`, Vite + React + TS):

| File | Responsibility |
| --- | --- |
| `src/api.ts` | Typed fetch client: `createSession`, `getStatus`, `submitMfa`, `documentUrl`. |
| `src/App.tsx` | Flow state mirroring backend status; orchestrates the components + polling. |
| `src/components/CarrierSelect.tsx` | Carrier dropdown (LM enabled; Geico shown disabled / "coming"). |
| `src/components/CredentialForm.tsx` | Username + password inputs (password masked). |
| `src/components/MfaPrompt.tsx` | MFA code input — rendered only at `AWAITING_MFA`. |
| `src/components/DocumentViewer.tsx` | `react-pdf` viewer + download button. |
| `src/usePolling.ts` | Status polling hook (interval, stop on terminal state). |

Styling: a centered card, light CSS — decent and clean, not a polish investment.

### 5.1 BrowserDriver Protocol (the test seam)

```python
class AuthStep(StrEnum):
    NEEDS_MFA = "NEEDS_MFA"
    AUTHENTICATED = "AUTHENTICATED"

class BrowserDriver(Protocol):
    async def open_login(self, login_url: str) -> None: ...          # raises BotChallengeError
    async def submit_credentials(self, username: str, password: str) -> AuthStep: ...  # raises CarrierAuthError
    async def submit_mfa(self, code: str) -> AuthStep: ...            # raises MfaError
    async def list_documents(self) -> list[DocumentRef]: ...         # raises DocFetchError
    async def fetch_document(self, ref: DocumentRef) -> bytes: ...    # proxied; raises DocFetchError
    async def close(self) -> None: ...
```

`BrowserbaseDriver` implements this against a live remote browser; `FakeDriver`
(tests) implements it with configurable canned behaviors. To exercise the
orchestration's hardest paths (not just happy/typed-error outcomes), `FakeDriver`
must be able to simulate: **success, bot-block, auth-fail, mfa-fail, doc-fail,** a
**slow/hanging step** (to drive the MFA-deadline timeout and task cancellation), a
step that raises **`asyncio.CancelledError`**, and a step that raises a
**connection-lost error mid-fetch**. A Protocol contract test asserts
`close()` is **idempotent and called on every terminal path** (success, fail,
timeout, cancel). The entire `SessionManager` orchestration is tested against
`FakeDriver` — no network, deterministic (fake clock).

### 5.2 New dependencies (exact-pinned, lockfiles committed)

The async backend needs deps not yet present. Add via `uv add` (pins into
`uv.lock`): **`fastapi`**, **`uvicorn`** (runtime); **`pytest-asyncio`**
(or `anyio` pytest mode) and **`httpx`** (FastAPI `TestClient` transport) (dev).
Set `[tool.pytest.ini_options] asyncio_mode = "auto"`. Frontend (`frontend/`, its
own `package.json` + lockfile): `react`, `react-dom`, `react-pdf`, `vite`,
`typescript`, and dev `vitest` + `@testing-library/react` + `eslint`. Without these
the async TDD plan cannot run.

## 6. State machine & API contract

```
STARTING ──┬─ open_login raises BotChallenge ─► FAILED (BotChallengeError + §7.1 fields)
           ├─ submit_credentials raises Auth  ─► FAILED (CarrierAuthError)
           └─ AuthStep.NEEDS_MFA              ─► AWAITING_MFA
AWAITING_MFA ──┬─ no code within MFA_DEADLINE (120s) ─► FAILED (SessionExpiredError) + driver.close()
               └─ code enqueued ─► VERIFYING_MFA  (single-flight lock; further /mfa POSTs get 409)
VERIFYING_MFA ──┬─ submit_mfa raises, attempts < 3 ─► AWAITING_MFA (await next code)
                ├─ submit_mfa raises, attempts == 3 ─► FAILED (MfaError)
                └─ AuthStep.AUTHENTICATED ─► FETCHING
FETCHING ──┬─ list/fetch raises ─► FAILED (DocFetchError)
           └─► READY  (all discovered docs' bytes fetched into the store; latency recorded at first doc)
(any non-terminal) ── task cancelled / TTL-swept ─► driver.close(); GET returns FAILED (SessionExpiredError)
```

**Fetch strategy (latency-honest):** during `FETCHING` the manager calls
`list_documents()` and fetches **all discovered documents' bytes** into the session
store, then sets `READY`. (The live browser is **closed at `READY`** per the
cleanup rule, so there is no live session to lazily fetch from afterward — fetching
all up front is the correct trade for prompt browser teardown.) The graded
`latency_ms` is recorded at the **first** document fetched, so the metric reflects
single-document cost, not an N-document aggregate. Typical personal-lines accounts
have only a few documents; **incremental "render-first-then-stream-the-rest"** is a
documented follow-up if document counts make the all-up-front fetch slow. A
duplicate identical MFA
code submitted while `VERIFYING_MFA` does **not** burn a retry (rejected with
`409`); only a *distinct* attempt that the carrier rejects counts toward the 3-try
cap. **Retention:** `READY` is terminal-for-serving but **retains** its document
bytes until the TTL (15 min) elapses — bytes are evicted at TTL, not on entry to
`READY` (so the user can actually fetch them).

**Endpoints:**

| Method/Path | Request | Response |
| --- | --- | --- |
| `POST /sessions` | `{carrier: "liberty_mutual", username, password}` | `201 {session_id, status:"STARTING"}` |
| `GET /sessions/{id}` | — | `200 {session_id, status, mfa_required, documents?:[{doc_id,name}], error?:{type,message}, latency_ms?}` |
| `POST /sessions/{id}/mfa` | `{code}` | `200 {session_id, status}`; `409` if not `AWAITING_MFA` (e.g. mid-`VERIFYING_MFA` — covers the double-submit race); typed `MfaError` (HTTP 409) if the 3-try cap is exhausted |
| `GET /sessions/{id}/documents/{doc_id}` | optional `?download=1` | `200 application/pdf` (inline, or attachment if download). Serves bytes cached during `FETCHING`. `404` unknown/uncached doc; `409` if session not `READY`. |

`carrier` is an enum (`liberty_mutual`) so adding Geico later is additive.

## 7. Error taxonomy

```python
class CarrierError(Exception): ...                 # base
class BotChallengeError(CarrierError): ...         # carries challenge.to_fields(...)
class CarrierAuthError(CarrierError): ...          # credentials rejected
class MfaError(CarrierError): ...                  # code rejected (distinct from expiry)
class DocFetchError(CarrierError): ...             # discovery/fetch failed
class SessionExpiredError(CarrierError): ...       # MFA deadline / TTL sweep / task cancelled
```

The background task catches `CarrierError` subclasses and sets `Session.status =
FAILED` with `Session.error = {type: <ClassName>, message: <safe message>}`.
Callers (frontend) branch on `error.type`, never on message text. No secrets in
messages. Any other (unexpected) exception → `FAILED` with a generic
`{type:"InternalError"}` and a logged stack trace (no creds).

### 7.1 Structured bot-challenge fields
On `BotChallengeError`, the error payload includes the `challenge.to_fields(...)`
record (kind, url, status, `_abck` state, has_captcha) so a negative gate result is
precisely classified.

## 8. Security & secrets

- Credentials arrive in the `POST /sessions` body, are passed transiently to the
  driver, and are **never persisted and never logged**. The password is excluded
  from all logging; request bodies are not logged.
- Session state + fetched PDF bytes live **in memory only**, evicted on terminal
  state and by a TTL sweeper (default 15 min). No database, no disk writes of PII.
- `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID` / `LM_LOGIN_URL` from env
  (`.env`, git-ignored; `.env.example` documents keys). The API key never leaves
  the backend.
- **Browserbase per-session `connect_url` / `debuggerUrl` / `wsUrl` / Live View
  URLs are live bearer credentials** — anyone holding one can watch and drive the
  authenticated session. They are **never logged** and never returned to the
  frontend. Structlog binds only our own `session_id`, never the connect URL.
- **Transport:** local dev over `http://localhost` is the only sanctioned
  transport for this version (a conscious YAGNI cut); any hosted deployment
  **requires TLS** in front of the backend, since credentials travel in the
  `POST /sessions` body.
- CORS pinned to the frontend dev origin. Structured logging (structlog) with
  stable fields (`session_id`, `carrier`, `state`) — never credentials, never
  connect URLs. The password is excluded from all logging; request bodies are not
  logged.

## 9. Lockout rail (carried from the spike)

Auth0 locks regardless of IP (~10 attempts). Therefore: **exactly one password
submission per session** (the `AttemptGuard` enforces it); a rejected login → tear
down the session as `FAILED`, no retry. MFA codes may be re-entered up to **3×
within the same session** (no new password submission — MFA entry does not feed the
password-lockout counter). Use only a **consented, expendable** LM account; confirm
the owner accepts possible lockout/fraud-alert risk before any run.

## 10. Testing strategy

- **Backend orchestration (TDD core):** `SessionRegistry` + `SessionManager` + all
  state transitions + the MFA `asyncio.Event` handoff + the 1-password rail + the
  MFA-retry cap + error mapping — unit-tested against an injected `FakeDriver`,
  with a fake clock (reuse `spike.timing.Timer`) for latency. No network.
- **API:** FastAPI `TestClient` + `FakeDriver` — each endpoint returns the right
  status codes and payloads across success and every failure path.
- **Real `BrowserbaseDriver`:** integration/live, validated by the actual run (the
  gate). LM selectors calibrated live via Browserbase Live View. Not in CI (needs
  real creds, MFA, a paid browser).
- **Frontend:** light component tests (e.g., `MfaPrompt` renders only at
  `AWAITING_MFA`; `DocumentViewer` only at `READY`) via Vitest + Testing Library;
  the full flow validated manually through the real run.
- Quality bar: backend `ruff` + `mypy --strict` + `pytest`; frontend `eslint` +
  `tsc --noEmit` + `vitest`. Exact-pinned deps + committed lockfiles.

## 11. Latency measurement (pre-committed before the run)

The brief grades **MFA-submit → document on screen**, so we report two numbers,
labelled, and pre-commit the definition now to avoid post-hoc rationalizing:

- **Primary (graded):** MFA-submit → **first document rendered** — a client-side
  mark taken at react-pdf's `onRenderSuccess`, minus the MFA-submit timestamp.
  This includes the poll-cycle delay and the `GET …/documents` transfer, i.e. what
  the user actually experiences.
- **Server-side sub-metric:** MFA-submit → **first bytes in hand** (`READY`),
  measured via `spike.timing.Timer` wired in production with **`time.monotonic`**
  (tests inject a fake clock). `start` is recorded on the `/mfa` **request path**
  at code receipt (not inside the task, to avoid a resume race); `stop` at the
  `READY` transition. The `Timer.stop` read is guarded so a missing `start` never
  masks the underlying error. Exposed as `latency_ms` in the status payload.

Report cold-session numbers honestly — first-run Browserbase startup + the
residential-proxy tax are included and noted. The metric is about the **first**
document (the gate needs ≥1 PDF), not an N-document aggregate.

## 12. Authorization (carried from spike §9)

Sanctioned take-home pulling the **account owner's own documents with explicit
consent** on an **expendable** account; LM's ToS prohibition on automated retrieval
is acknowledged as a conscious, time-boxed exercise decision, documented rather than
glossed. Not a model for unconsented or third-party collection.

## 13. Build sequence (preview for the plan)

0. Add + pin deps (§5.2): `fastapi`, `uvicorn`; dev `pytest-asyncio` + `httpx`;
   set `asyncio_mode = "auto"`. Commit `uv.lock`.
1. `spike/config.py` — remove `lm_username`/`lm_password` fields + reads; update
   `test_config.py` + `.env.example` (TDD).
2. `backend/models.py` — Pydantic models + error taxonomy incl. `SessionExpiredError` (TDD).
3. `backend/sessions.py` — `SessionRegistry` + `Session` (code `Queue`, single-flight
   `Lock`, stored task ref) + `SessionManager` + `FakeDriver`: full state-machine
   orchestration incl. `VERIFYING_MFA`, bounded MFA-deadline timeout, `try/finally`
   `driver.close()`, task cancellation, and the TTL sweeper. TDD with the expanded
   FakeDriver scenarios (hang/cancel/connection-loss) — the bulk of the logic.
4. `backend/api.py` + `backend/main.py` — endpoints + CORS + lifespan sweeper
   (TDD via async `TestClient` + FakeDriver), incl. the double-submit `409` path.
5. `backend/browser.py` + `backend/carriers/lm.py` — real `BrowserbaseDriver`
   (async Playwright/CDP, proxied in-page fetch) + async LM nav, **including any
   document-discovery logic change** (live calibration; see §14).
6. `frontend/` — Vite scaffold, API client, components, polling (stop on
   READY/FAILED/repeated-404), react-pdf with `onRenderSuccess` latency mark
   (light tests).
7. Live end-to-end run = the gate; capture results + both latency numbers + any
   structured bot-challenge classification; go/no-go for Geico.

## 14. Open risks

- **Gate-first tension:** we are building app scaffolding before proving hosted
  access. Mitigated by (a) the first real run being the gate, (b) the heavy
  testable logic being browser-independent (FakeDriver), so a bot-block failure
  wastes minimal work, and (c) the structured failure classification making a
  negative result actionable.
- **Bot detection may still block us** — the core unknown, unchanged from the spike.
- **Single-process in-memory state** is fine for this minimal/local-but-hosting-shaped
  version; multi-instance hosting needs externalized sessions (documented, deferred).
- **LM selectors are unknown until live** — calibrated in build step 5; the
  orchestration is selector-independent.
- **Document discovery may need a logic change, not just constants (gate risk).**
  `discover_document_urls` currently matches only `.pdf`-suffixed `<a href>`s. A
  real LM React SPA may expose documents via XHR/JSON, JS click handlers, or
  suffix-less download URLs (`/documents/download?id=…`), in which case build
  step 5 must extend discovery (e.g. intercept the network response, or match
  download-endpoint patterns) — the pure function gets a new path, not just new
  constants. The gate's "≥1 PDF" hinges on this, so it is calibrated/​verified
  live, not assumed.
- **Do NOT "simplify" the proxied in-page fetch to `page.request`/`APIRequestContext`.**
  That shares cookies but egresses from our *client* IP, bypassing the residential
  proxy and defeating the whole hosted-access thesis (see spike spec §5.3). The
  in-page `fetch`→base64 is the correct, intentional choice; for very large PDFs
  prefer navigate-and-capture over base64 to avoid the ~33% inflation.

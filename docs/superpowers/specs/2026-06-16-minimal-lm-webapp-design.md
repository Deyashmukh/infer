# Minimal Liberty Mutual Policy-Document Web App — Design (Revised, post-gate)

- **Date:** 2026-06-16
- **Status:** Revised after feasibility proven on a residential dev IP; **milestone 0
  (datacenter login) is now SETTLED (2026-06-17):** a datacenter VM completes the full login
  end-to-end **only through a residential egress** — a datacenter IP is tarpitted on the
  credential POST, and a residential proxy / `ssh -R 1080` tunnel clears it. Residential egress
  is therefore **required, not optional** (revises §13). Supersedes the Browserbase-based draft.
- **Scope:** A minimal but real human-in-the-loop web app for **Liberty Mutual
  only**: user enters portal credentials → backend logs in on a **self-hosted
  headless Chromium** → MFA prompt surfaces in the UI → user submits the code →
  policy PDFs are fetched and rendered. Foundation of the submission app, built
  minimal. Geico is an explicit follow-up.
- **Supersedes:** the Browserbase architecture in the prior version of this doc and
  the CLI Phase B of `2026-06-16-liberty-mutual-spike-design.md`. The reusable pure
  machinery, the lockout rail, and the authorization stance carry over.

## 1. Context — feasibility is proven (with one honest caveat)

The earlier draft treated hosted access past LM's defenses as the open risk. A
diagnostic spike has now largely resolved it, with evidence — sourced precisely:

- **The blocker was never bot detection.** LM's auth-domain bot sensor returned
  `{"success":true}` on **every** egress IP we tried, including AWS **datacenter**
  IPs (`diag_matrix.json`, `sensor_accepted: true` on all Browserbase attempts).
- **The real blocker was an HTTP/2 transport failure** on the credential POST
  (`/usernamepassword/login`): `net::ERR_HTTP2_PROTOCOL_ERROR`, perfectly correlated
  with failure (`login_post_got_response:false`), on Browserbase **and** local
  Chromium. IP-independent.
- **`--disable-http2` removes the error.** The matrix proves this *narrowly*: with the
  flag, all requests ran `http/1.1` with zero `ERR_HTTP2_PROTOCOL_ERROR`. It does
  **not** by itself show a login *success* — within the matrix's 10s window those
  `local_h1` runs were still mid-POST (`OTHER`).
- **The full flow completing end-to-end is proven separately** by a longer-window run
  (`confirm_h1.py`): credentials → MFA (SMS) → authenticated account
  (`h1_account.json` → `eservice.libertymutual.com/accountmanager/homepage`), session
  saved (`lm_state.json`).
- **Session reuse works** (`map_docs.py` re-entered the account from `lm_state.json`,
  no MFA). **Documents** live at `/accountmanager/documents` (state `DOCUMENTS`) behind
  **"View / print"** controls; clicking one yields an authenticated `application/pdf`
  response from `/accountmanager/document/download/...` (`docs_probe.json`).
- **Browserbase cannot pass `--disable-http2`** (no custom-flags API; `connect_over_cdp`
  attaches to an already-launched browser). The only Browserbase HTTP/1.1 path is a
  self-run MITM proxy + CA — more infra than self-hosting. **Therefore we self-host.**

**The one caveat we must close (milestone 0).** Every end-to-end success so far ran on
a **residential dev IP** (`174.167.100.96`), and the doc-fetch proofs reused a saved,
MFA-skipping cookie jar — i.e. close to the setup the brief disqualifies. The bot
sensor accepted every datacenter IP, and the only datacenter failures were the
IP-independent H2 error (Browserbase died pre-login and can't take the flag) — so
**no datacenter IP has yet completed a login end-to-end.** "Datacenter +
`--disable-http2` logs in" is a strong **inference, not yet an observation.** Milestone
0 (§19) converts it to evidence cheaply, before any product code.

## 2. Goal & success criteria (measurable)

Through the web UI, for Liberty Mutual, from a **self-hosted headless Chromium**
(`--disable-http2`, containerized; **direct/default egress this increment** — residential
proxy deferred, §13):

1. User selects LM, enters username + password; backend submits credentials over
   HTTP/1.1 without the H2 failure.
2. Backend detects the MFA prompt; the UI **reveals an MFA field**.
3. User submits the SMS code; backend reaches `/accountmanager/documents` and **fetches
   ≥1 real policy PDF** (proxying the authenticated `application/pdf` bytes).
4. The UI **renders the PDF** (react-pdf) and offers download.
5. Latency from **MFA-submit → first document rendered** is measured and reported (the
   graded metric). Report the measurement; do not pre-pin a threshold.
6. On any unexpected bot-block, the failure is **classified with structured fields**
   and surfaced as a typed error (defensive — not expected, given §1).

**Gate status:** the feasibility gate is **met on a residential dev IP**
(login+MFA+PDF). The remaining unknown is whether it holds on a **datacenter IP** in
the container — **milestone 0 (§19) settles that first**, before the product build.
The build then re-proves the flow **through the UI** and adds rendering + latency.

## 3. Non-goals (YAGNI)

- **Residential proxy deferred** (direct/default egress now). The driver is built
  **proxy-ready** (env-configurable, off by default) so enabling it later is config,
  not code (§13).
- **Session reuse deferred** as a *product* feature (proven in the spike; the next
  increment wires `storage_state` into the flow). Fresh login each session for now.
- No Geico yet. No multi-user concurrency guarantees / horizontal scaling / external
  state store. No user accounts or DB on our side. No document parsing/extraction
  (success = fetch + render the PDF bytes). No long-term storage of creds or docs.
  No heavy UI polish.

## 4. Architecture

**Self-hosted headless Chromium (containerized) + FastAPI async backend + React SPA.
One container image runs identically local and deployed (dev/prod parity, §14).**

```
React SPA (Vite, TS)              FastAPI backend (async)            Self-hosted Chromium
  CarrierSelect                     POST /sessions      ─┐            (headless, --disable-http2,
  CredentialForm  ── REST+poll ──►  GET  /sessions/{id}  │ in-memory   in the SAME container;
  MfaPrompt                         POST /sessions/{id}/mfa│ registry +  direct egress now,
  DocumentViewer  ◄── PDF bytes ──  GET  …/documents/{id} │ async task  proxy-ready later)
   (react-pdf)                       status machine ──(asyncio.Queue)──► async Playwright (local)
  reuses pure core (spike/): classify_lm_page, Timer, docfetch validate/decode, AttemptGuard
```

- `POST /sessions` creates a `Session`, returns its id immediately, and launches a
  **background asyncio task** (reference stored on the `Session` so it is not GC'd
  mid-flight) that drives the login until it hits MFA and sets `AWAITING_MFA`.
- The task does a **bounded** wait: `asyncio.wait_for(code_queue.get(), MFA_DEADLINE)`,
  `MFA_DEADLINE = 120s`. On timeout → `FAILED` (`SessionExpiredError`) **and
  `driver.close()`**. The code travels via an `asyncio.Queue` (payload + 3-try retry).
  **Single-flight** = a synchronous status flip to `VERIFYING_MFA` in the `/mfa` handler
  (event-loop-atomic — no `await` between the `409` check and the flip).
- `POST /sessions/{id}/mfa` enqueues the code; the task resumes → `VERIFYING_MFA` →
  `FETCHING` → `READY`. The frontend **polls** `GET /sessions/{id}` (~700 ms).
- **Cleanup is guaranteed:** the task runs in a `try/finally` whose `finally` calls
  `driver.close()` (idempotent) on every terminal path. The TTL sweeper cancels the task
  and awaits `driver.close()` for any evicted session.
- **The browser is ours, in our container** — the "hosted somewhere that isn't my
  machine" answer is a **deployable container image**, not a managed vendor. The same
  process holds the browser and the session state (single container), which is exactly
  why `--disable-http2` is available to us.
- Session state is **in-memory, single-process** (YAGNI vs. Redis/worker). Externalizing
  it for multi-instance hosting is a documented future step.

## 5. Components & file structure

**Backend** (`backend/`, FastAPI, async) — Part 1 (models/sessions/api/main) is built
and green. This increment **replaces the Browserbase driver stub with a real
self-hosted Chromium driver** and adds the LM flow + container.

| File | Responsibility | Status |
| --- | --- | --- |
| `backend/main.py` | FastAPI app, CORS, routes, lifespan TTL sweeper. **Edit:** swap the driver factory to `ChromiumDriver` (currently imports `make_browserbase_driver_factory`). | built; edit |
| `backend/api.py` | The 4 route handlers (§9). | built |
| `backend/sessions.py` | `SessionRegistry` + `Session` + `SessionManager.run()` (bounded MFA wait, `try/finally` cleanup, TTL sweeper). **Edit:** flip `READY` after the first doc (§8/I3). | built; edit |
| `backend/browser.py` | `BrowserDriver` Protocol + `FakeDriver`. **Edit:** `DocRef` drops `url` (§5.1). | built; edit |
| `backend/models.py` | Pydantic models + error taxonomy. | built |
| `backend/chromium_driver.py` | **NEW.** Real `ChromiumDriver`: async Playwright, `chromium.launch(headless=…, args=["--disable-http2", *proxy/flags])`, persistent context. Implements the Protocol. Replaces `browserbase_driver.py`. | build |
| `backend/carriers/lm.py` | **NEW.** LM nav with the proven selectors/flow (§6). Reuses pure `classify_lm_page`. | build |
| `Dockerfile`, `compose.yaml` | **NEW.** Playwright base image (Chromium) + backend; env-driven (§14). | build |

**Reused pure core** (`spike/`): `carriers/liberty_mutual.classify_lm_page`,
`timing.Timer`, `docfetch` (`is_valid_pdf`, `decode_base64_pdf`), `AttemptGuard`.
(`discover_document_urls` is **not** reused for the policy doc list — on the real page it
returns only the footer Terms-&-Conditions CDN PDF, not policy docs; see §6.4/B-note.)
**Config change** (`spike/config.py`): **drop** the `browserbase_api_key` /
`browserbase_project_id` / `browserbase_context_id` fields + their `load_config` reads
(the Config has no `lm_username`/`lm_password` fields — creds are runtime-only). **Add**
(optional, safe defaults): `LM_LOGIN_URL` (required), `HEADLESS` (default true),
`CHROMIUM_ARGS` (default `--disable-http2`), `PROXY_SERVER`/`PROXY_USERNAME`/
`PROXY_PASSWORD` (optional — unset ⇒ direct egress). Update `test_config.py`,
`.env.example` (drop Browserbase keys; document the new keys), and `backend/main.py`.
Done test-first. *(The `spike/browserbase.py` + `backend/diag_*`/`confirm_h1`/`map_docs`/
`probe_doc` scripts are parked — not imported by the product path; `confirm_h1` is reused
once in milestone 0.)*

**Frontend** (`frontend/`, Vite + React + TS): `src/api.ts`, `src/App.tsx` (flow + poll),
`components/CarrierSelect.tsx` (LM enabled, Geico disabled), `components/CredentialForm.tsx`
(masked password), `components/MfaPrompt.tsx` (only at `AWAITING_MFA`),
`components/DocumentViewer.tsx` (react-pdf + download), `usePolling.ts`. Centered card.

### 5.1 BrowserDriver Protocol (the test seam)

```python
class AuthStep(StrEnum):
    NEEDS_MFA = "NEEDS_MFA"
    AUTHENTICATED = "AUTHENTICATED"

class BrowserDriver(Protocol):
    async def open_login(self, login_url: str) -> None: ...           # raises BotChallengeError
    async def submit_credentials(self, username: str, password: str) -> AuthStep: ...  # CarrierAuthError
    async def submit_mfa(self, code: str) -> AuthStep: ...            # raises MfaError
    async def list_documents(self) -> list[DocRef]: ...              # raises DocFetchError
    async def fetch_document(self, ref: DocRef) -> FetchedDoc: ...    # raises DocFetchError
    async def close(self) -> None: ...
```

**`DocRef` identity (corrected per review B1):** `DocRef` is `{doc_id, name}` — **no
`url`**. For LM the PDF URL does not exist in the DOM; it is minted (with a per-click
UUID) only when a "View / print" control is clicked. So a document's stable identity is
its **position** among the documents-page actions: `list_documents` enumerates the
"View / print" controls and returns `DocRef(doc_id=str(index), name=<card text>)`;
`fetch_document(ref)` re-locates the `ref.doc_id`-th control, clicks it, and captures the
PDF (§7). The orchestration already keys by `ref.doc_id` and never reads a url
(`sessions.py:131`), so this is a driver-local change.

`ChromiumDriver` implements this against a live local Chromium; `FakeDriver` (tests) with
canned behaviors — success, bot-block, auth-fail, mfa-fail, doc-fail, a **slow/hanging**
step (drives the MFA-deadline timeout + cancellation), a step raising
**`asyncio.CancelledError`**, and a **connection-lost** mid-fetch. A contract test asserts
`close()` is **idempotent and called on every terminal path**. The entire `SessionManager`
is tested against `FakeDriver` — no network, fake clock.

## 6. The proven Liberty Mutual flow (calibrated, not assumed)

`ChromiumDriver` + `carriers/lm.py` implement exactly this, observed live:

1. **open_login:** `goto(LM_LOGIN_URL)` (`https://www.libertymutual.com/log-in`) → click
   the **"Log in"** link → wait for `input[name=username]`. (If a hard block appears
   instead, raise `BotChallengeError` — defensive.)
2. **submit_credentials:** fill `input[name=username]` + `input[name=password]` → click
   `button[type=submit]`. Detect outcome by polling up to ~30s: `/u/mfa-sms-challenge` or
   a visible OTP field ⇒ `NEEDS_MFA`; "something went wrong" ⇒ block/`CarrierAuthError`.
   **Exactly one password submission per session** (lockout rail, §15).
3. **submit_mfa:** locate the OTP field (`input[autocomplete=one-time-code]` /
   `input[name*=code]`), **type the code digit-by-digit** (`press_sequentially`, *not*
   `fill` — Auth0's "Continue" un-disables only on real keystrokes) → press **Enter**.
   Success = leaving `login.libertymutual.com`, settling on
   `eservice.libertymutual.com/accountmanager/...` ⇒ `AUTHENTICATED`. Up to **3** code
   attempts per session.
4. **list_documents:** `goto(/accountmanager/documents)`, wait for `DOCUMENTS`, enumerate
   the visible **"View / print"** controls (**action-based, not label-based** — the
   button text is empty; the name comes from the enclosing policy card). Each becomes
   `DocRef(doc_id=str(index), name=<card text>)` — no url (§5.1). *(Do not use
   `discover_document_urls` here — on the real page it returns only the footer T&C CDN
   PDF, not policy docs.)*
5. **fetch_document:** **register the capture before clicking** — wrap the click in
   `expect_response`(url contains `/document/download/`, ct `application/pdf`) /
   `expect_popup`, bounded timeout; re-locate the `doc_id`-th "View / print" and click;
   read the captured response `body()`. **Fallbacks:** a `download` event ⇒
   `expect_download` → read the file; if needed, re-`GET` the captured URL via
   **`context.request.get`** (same cookie jar + egress — allowed). **Never** an
   out-of-band client (`httpx`/separate `APIRequestContext`) — bypasses the browser's
   (later residential) egress (§16).

## 7. Doc-fetch mechanism (resolved) — proxy the bytes

Two reasons we fetch bytes server-side instead of handing the client a URL: (1) **no
stable URL exists** — LM mints the download URL (per-click UUID) only on click; and (2)
even that URL is gated by the **session cookie in our hosted browser**, which the user's
browser lacks (a forwarded URL would 401). Mechanism (proven, with §6.5 robustness):
clicking "View / print" opens a popup that issues a same-origin GET returning
`application/pdf` (`Content-Disposition: inline`); we capture that response (listener
registered **before** the click, at the **context** level since it fires on the popup),
read `body()`, store the bytes on the `Session`, and serve them via
`GET /sessions/{id}/documents/{doc_id}`. Capturing the response (vs. an in-page
`fetch`→base64) also avoids ~33% inflation.

## 8. State machine

```
STARTING ──┬─ open_login raises BotChallenge ─► FAILED (BotChallengeError + §11 fields)
           ├─ submit_credentials raises Auth  ─► FAILED (CarrierAuthError)
           └─ AuthStep.NEEDS_MFA              ─► AWAITING_MFA
AWAITING_MFA ──┬─ no code within MFA_DEADLINE (120s) ─► FAILED (SessionExpiredError) + close()
               └─ code enqueued ─► VERIFYING_MFA  (single-flight; further /mfa POSTs ⇒ 409)
VERIFYING_MFA ──┬─ submit_mfa raises, attempts < 3 ─► AWAITING_MFA (await next code)
                ├─ submit_mfa raises, attempts == 3 ─► FAILED (MfaError)
                └─ AuthStep.AUTHENTICATED ─► FETCHING
FETCHING ──┬─ list/fetch raises ─► FAILED (DocFetchError)
           ├─ FIRST doc's bytes captured ─► READY (servable now; latency recorded here)
           └─ task keeps fetching the rest in the same open browser, then close()
(any non-terminal) ── task cancelled / TTL-swept ─► driver.close(); GET returns FAILED
```

**Fetch strategy (latency-honest; revised per review I3):** flip to `READY` as soon as
the **first** document's bytes are captured — so the user can render it immediately and
`latency_ms` reflects real first-doc cost — then **keep fetching the remaining docs in
the same still-open browser**, closing only after the last (or on TTL/cancel). The status
payload's `documents` list grows as each becomes servable; `GET …/documents/{id}` serves
a doc once present (404 until then, 409 until `READY`). This "render-first,
stream-the-rest" is **required, not deferred**: the prior "all docs before READY" design
gated first-doc render on **total** fetch time (GET is 409 until READY), which would
silently blow the graded 8s metric for multi-doc accounts. A duplicate identical MFA code
submitted while `VERIFYING_MFA` is rejected with `409` and does **not** burn a retry.
**Retention:** bytes are retained until the TTL (15 min), evicted at TTL (so the user can
actually fetch them).

## 9. API contract

| Method/Path | Request | Response |
| --- | --- | --- |
| `POST /sessions` | `{carrier:"liberty_mutual", username, password}` | `201 {session_id, status:"STARTING"}` |
| `GET /sessions/{id}` | — | `200 {session_id, status, mfa_required, documents?:[{doc_id,name}] (grows as docs stream), error?:{type,message}, latency_ms?}` |
| `POST /sessions/{id}/mfa` | `{code}` | `200 {session_id, status}`; `409` if not `AWAITING_MFA`; typed `MfaError` once the 3-try cap is exhausted |
| `GET /sessions/{id}/documents/{doc_id}` | optional `?download=1` | `200 application/pdf`. `409` if not `READY`; `404` if that doc isn't captured yet. |

`carrier` is an enum so adding Geico is additive.

## 10. Error taxonomy

```python
class CarrierError(Exception): ...                 # base
class BotChallengeError(CarrierError): ...         # challenge fields (defensive/edge now)
class CarrierAuthError(CarrierError): ...          # credentials rejected
class MfaError(CarrierError): ...                  # code rejected
class DocFetchError(CarrierError): ...             # discovery/fetch failed
class SessionExpiredError(CarrierError): ...       # MFA deadline / TTL sweep / cancel
```

The task catches `CarrierError` subclasses → `FAILED` with `error = {type:<ClassName>,
message:<safe>}`. Frontend branches on `error.type`, never message text. No secrets in
messages. Unexpected exception → `FAILED {type:"InternalError"}` + logged stack (no creds).

### 11. Structured bot-challenge fields
If `BotChallengeError` fires, the payload includes the challenge record (kind, url,
status, sensor state, has_captcha). Defensive — the spike showed the sensor accepting us.

## 12. Security & secrets

- Credentials arrive in the `POST /sessions` body, pass transiently to the driver,
  **never persisted, never logged**. Password excluded from all logging; request bodies
  not logged.
- Session state + fetched PDF bytes live **in memory only**, evicted on terminal state
  and by the TTL sweeper (15 min). No DB, no disk PII.
- Env (`.env`, git-ignored; `.env.example` documents keys): `LM_LOGIN_URL` (required);
  `HEADLESS`, `CHROMIUM_ARGS`, `PROXY_*` (optional). **Proxy creds are secret**, never
  logged. No Browserbase keys anymore.
- The session-reuse artifact (`storage_state`, when that increment lands) holds live
  tokens → in-memory or git-ignored only, never committed. The captured popup PDF bytes
  are in-memory only.
- **Transport:** local dev over `http://localhost` only; any hosted deployment **requires
  TLS** in front of the backend (credentials travel in the POST body).
- CORS pinned to the frontend origin. Structured logging (structlog) with stable fields
  (`session_id`, `carrier`, `state`) — never credentials, never proxy creds.

## 13. Residential proxy plan (deferred, proxy-ready)

Decision (user): **direct/default egress this increment; add residential proxy only after
the build is tested.** ⚠️ **Superseded (2026-06-17):** milestone 0 proved a datacenter IP is
**tarpitted** on the LM credential POST, so a residential egress is **necessary**, not just
robustness/realism — see the Status note up top. The env-driven mechanism below (off by
default, no code change to enable) is exactly what makes that fix a config flip.

- The driver reads `PROXY_*` from env and, if set, passes `proxy={server, username,
  password}` to the Chromium context — **off by default**. Enabling it later is `.env` +
  a flag, no code change (preserves dev/prod parity).
- A standard CONNECT proxy tunnels TLS to Cloudflare, so `--disable-http2` still forces
  HTTP/1.1 at the browser — the fix holds. **Verified once** (one login through the proxy)
  before building on it.
- **Pre-committed decision rule (set before measuring):** when the proxy is enabled, we
  measure MFA→docs latency; **if it exceeds 8s, the proxy comes off the doc-fetch hop (or
  moves to a faster tier) — it does not silently blow the budget.**
- Provider + credentials are a later, user-provided dependency.

## 14. Dev/prod parity & containerization

Requirement (user): **the local build mimics the deployed version.** One container image,
env-driven, runs identically in both places.

- **Image:** a Playwright base image (Chromium + system libs) + our backend; launches
  Chromium `headless, args=["--disable-http2", …]`. No env-specific code path. Mind the
  Chromium-in-Docker gotchas: `--no-sandbox` (or proper sandboxing), adequate
  `/dev/shm` (`--disable-dev-shm-usage` or a larger shm), fonts for PDF render.
- **Local:** `docker compose up` runs that exact image; the frontend dev server points at
  it. **Deployed:** the same image on a cloud **VM** (datacenter IP now; residential proxy
  later). "Not your machine" = the image is deployable off-machine.
- **The frontend is decoupled** from this container (static React build — Vite dev server
  locally; static files served by the backend or any static host when deployed).
- **Both the milestone-0 gate and the step-7 UI run happen *in the container*** on the VM
  (deployment-shaped), not native. Config strictly via env; secrets never baked into the
  image.

## 15. Lockout rail (carried from the spike)

Auth0 locks regardless of IP (~10 attempts). **Exactly one password submission per
session** (`AttemptGuard`); a rejected login tears the session down as `FAILED`, no retry.
MFA codes may be re-entered up to **3×** within a session (no new password submission —
MFA entry does not feed the password-lockout counter). Use only a **consented, expendable**
LM account; confirm the owner accepts possible lockout/fraud-alert risk before any run.

## 16. Testing strategy

- **Backend orchestration (TDD core, already green):** `SessionRegistry` +
  `SessionManager` + all transitions + the MFA `asyncio.Queue` handoff + the 1-password
  rail + the 3-try cap + error mapping — against `FakeDriver`, fake clock, no network.
  **Add** a test for the new READY-after-first-doc behavior (§8) and for `DocRef` without
  `url`.
- **API:** FastAPI `TestClient` + `FakeDriver` — each endpoint × success/failure, incl.
  the 409/404 doc-serving rules.
- **`carriers/lm.py` parsing helpers (doc-list extraction):** unit-tested against a **real
  captured fixture** of the `/accountmanager/documents` HTML (saved from the authenticated
  session via the spike's session reuse — the existing `tests/fixtures/lm/documents*.html`
  are fabricated `.pdf`-anchor toys that do **not** match the real button-based DOM and
  **must be replaced**). Offline, no network.
- **`ChromiumDriver`:** integration/live, validated by the in-container run (milestone 0 +
  step 7). Not in CI (needs real creds + MFA + a browser).
- **Frontend:** light component tests (`MfaPrompt` only at `AWAITING_MFA`; `DocumentViewer`
  only at `READY`) via Vitest + Testing Library; full flow via the real run.
- Quality bar: backend `ruff` + `mypy --strict` + `pytest`; frontend `eslint` +
  `tsc --noEmit` + `vitest`. Exact-pinned deps + committed lockfiles. **Do NOT** re-fetch
  docs via a separate **out-of-band** client (`httpx`/separate `APIRequestContext`) — that
  bypasses the browser's (later proxied) egress; capturing the in-browser `application/pdf`
  response is primary, `context.request.get` (same cookie jar + egress) an acceptable
  fallback.

## 17. Latency measurement (pre-committed)

The brief grades **MFA-submit → document on screen**; report two labelled numbers:

- **Primary (graded):** MFA-submit → **first document rendered** — a client mark at
  react-pdf's `onRenderSuccess`, minus the MFA-submit timestamp (includes poll-cycle +
  `GET …/documents` transfer). Because `READY` now fires at the first doc (§8), this is
  **not** gated by total fetch time.
- **Server sub-metric:** MFA-submit → **first bytes in hand** (`READY`), via
  `spike.timing.Timer` with `time.monotonic` (tests inject a fake clock). `start` recorded
  on the `/mfa` request path at code receipt; `stop` at `READY`. Exposed as `latency_ms`.

Report honestly: this increment is **direct egress** (no proxy tax); residential-proxy
latency is measured separately when §13 lands. The metric is the **first** doc.

## 18. Authorization (carried from the spike)

Sanctioned take-home pulling the **account owner's own documents with explicit consent** on
an **expendable** account; LM's ToS prohibition on automated retrieval is a conscious,
time-boxed exercise decision, documented rather than glossed. Not a model for unconsented
or third-party collection.

## 19. Build sequence (preview for the plan)

0. **GATE — do this first, before the product: datacenter login on a VM.** Containerize the
   proven `confirm_h1` login (Chromium + `--disable-http2`, headless) and run it once on a
   cheap cloud VM (datacenter IP, direct egress): one real login → MFA → account.
   **PASS** ⇒ the central bet (datacenter + `--disable-http2` logs in) *and* the
   Chromium-in-Docker shape are proven; build the product. **FAIL** ⇒ stop and reassess —
   a cheap negative before the frontend, per "prove cheaply before scaling."
1. `spike/config.py` — drop Browserbase fields; add `LM_LOGIN_URL`/`HEADLESS`/
   `CHROMIUM_ARGS`/`PROXY_*`; update `test_config.py`, `.env.example`, `backend/main.py`
   (TDD).
2. `backend/chromium_driver.py` — `ChromiumDriver` (async Playwright, `--disable-http2`,
   optional proxy, persistent context, idempotent `close()`). Implements the Protocol.
3. `backend/carriers/lm.py` — the proven flow (§6): open/creds/MFA(type+Enter)/docs-list/
   fetch-capture (with the §6.5 robustness). Doc-list extraction unit-tested against the
   **real captured fixture** (TDD).
4. Wire `ChromiumDriver` into `SessionManager` (replace the stub); implement the
   READY-after-first-doc change (§8/I3); confirm existing orchestration tests stay green +
   add the new ones.
5. `Dockerfile` + `compose.yaml` — Playwright base image, env-driven; backend up
   in-container (reuse the milestone-0 image).
6. `frontend/` — Vite scaffold, typed API client, components, polling, react-pdf with the
   `onRenderSuccess` latency mark (light tests).
7. **Live in-container UI run** (datacenter VM) — the full-UX re-proof (the datacenter risk
   is already retired at milestone 0); capture both latency numbers + a screenshot/sample
   PDF; go/no-go for the proxy increment + Geico.

## 20. Open risks

- **No datacenter end-to-end login observed yet (central bet):** all end-to-end proofs were
  on a residential dev IP; datacenter runs only ever failed at the (now-fixed) H2 error.
  Strong inference (sensor accepts datacenter IPs), not yet observation — **retired by
  milestone 0** (§19) before any product code.
- **Chromium-in-Docker parity:** headless Chromium + `--disable-http2` must behave in the
  container as native (shm, sandbox flags, fonts — §14). Proven by milestone 0 (and step
  7), not just asserted.
- **Doc-fetch robustness across policy types:** capture proven on a homeowners "View /
  print" (inline `application/pdf`). Auto/other policies may differ; `list_documents` keys
  on the **action** + `application/pdf`/`download` capture (not labels), with a
  `context.request.get` fallback (§6.5). Calibrated against the real page.
- **Selector drift:** isolated in `carriers/lm.py`; the orchestration is selector-independent.
- **`--disable-http2` is a transport workaround** (forces HTTP/1.1 for the whole browser,
  incl. the eservice/docs domain). Acceptable (LM serves fine over 1.1); intentional trade.
- **Proxy latency (when §13 lands):** residential egress may pressure the 8s budget — hence
  the pre-committed decision rule (§13), measured not assumed.
- **Single-process in-memory state** is fine for this minimal/hosting-shaped version;
  multi-instance hosting needs externalized sessions (documented, deferred).

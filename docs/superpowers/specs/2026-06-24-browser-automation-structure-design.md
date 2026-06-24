# Browser-Automation Layer — Implementation Structure (build now, model later)

- **Date:** 2026-06-24
- **Status:** Proposed (implementation design). Builds the **model-agnostic structure** for the
  architecture in `2026-06-24-vlm-discovery-self-heal-design.md`.
- **Scope:** The concrete structure of the new browser-automation layer — a deterministic-first
  execution path, a model-agnostic VLM seam, a discovery/extraction harness, and validation
  gates — built **now**, with Holo3.1 slotted in **after** the eval. Wires into the existing
  `CarrierModule` / `ChromiumDriver` / `SessionManager`. The application (API, state machine,
  React) is unchanged.
- **Out of scope:** egress/residential proxy (settled separately — Mac SSH-SOCKS now, proxy
  swap later); GREEN/YELLOW/RED states + alerting (later increment, see architecture doc); the
  autonomous-agent *quality* (the deferred Holo3.1 eval).

---

## 1. Goal & what "build now" means

We are changing **how the browser automation works**, not the app around it. The new shape:

- **Adding a carrier (dev):** a VLM drives the carrier **end-to-end**, which (a) gives us
  confidence the flow works and (b) lets us **extract the recipe** — nav selectors for the login
  steps + the document endpoints. The VLM does **not** author code; we write the deterministic
  carrier script from the extracted recipe and add it to the registry.
- **Prod:** the deterministic script is the **first player** — Playwright authenticates via the
  selectors, then fetches the PDF directly from the discovered endpoints. The **VLM is the
  fallback**, taking over only when the script breaks.

"Build now" = everything **except** the model. The VLM is an interface with a stub behind it;
the discovery harness is **human-drivable today**. Holo3.1 drops into the two model-shaped slots
after the eval.

## 2. Components

### 2.1 Deterministic execution path (the first player)

The existing `CarrierModule` pattern (`backend/browser.py`): `open_login` /
`submit_credentials` / `submit_mfa` (auth via selectors) → `list_documents` / `fetch_document`
(fetch). The change is to make the **fetch step prefer an explicit endpoint recipe** rather than
ad-hoc code: a carrier declares its document endpoint(s) as data (method, URL template, how to
fill the token/doc-id from session state), which `fetch_document` executes via the authenticated
context (as `geico.py` already does with `/ws/...`). This is mostly consolidation of what exists.

### 2.2 Discovery/extraction harness (dev tool, model-agnostic)

A new dev-only tool (`backend/discovery.py` or a `spike/` script) that instruments a Playwright
session and emits a **carrier recipe**:

- **Endpoints** — capture network traffic (`page.on("response")` / CDP) to identify the document
  endpoint(s) + required headers (e.g. Geico's `x-xsrf-token`), cookies, body, and which values
  are dynamic.
- **Selectors** — record the elements interacted with during the login flow (Playwright
  codegen-style recording, or explicit annotation) → nav selectors.
- **Output** — a `CarrierRecipe` JSON: `{ auth_selectors, doc_endpoints[], notes }`, which we
  read to hand-write the `CarrierModule`.

**Key property:** the harness is driven by a *pluggable* session driver — **a human today**
(so we can onboard a carrier before the eval), the **VLM later**. The capture/emit logic is
identical either way.

### 2.3 VLM seam (`VisionAgent` protocol + stub)

A new protocol (`backend/vision.py`):

```
class VisionAgent(Protocol):
    async def run(self, goal: str, page: Page) -> AgentResult: ...
```

`run(goal, page)` drives the browser toward a goal (the agent-shaped interface — it screenshots,
acts, loops; localization is internal to it). Ship a **`StubVisionAgent`** that raises
`VisionUnavailable`, so the seam exists and is tested with **no model**. Holo3.1 implements this
protocol later and powers both the discovery driving (2.2) and the prod fallback (2.4).

### 2.4 Fallback orchestration + validation gates

- **Orchestration** lives one level up (in `ChromiumDriver`, not inside `CarrierModule`): try the
  deterministic step → on a typed failure (`CarrierAuthError` / `DocFetchError` / selector not
  found), if a `VisionAgent` is configured, invoke `run(goal)` → run the result through the
  gates → else propagate as `FAILED`. With the stub, fallback is a no-op (deterministic-only),
  but the seam and gate are real and tested.
- **Validation gates** (`backend/validation.py`): `validate_document(content, expected)` —
  reuses `spike/docfetch.is_valid_pdf` (`%PDF-`), adds size/page sanity and a **per-carrier
  identity check** (right doc type / policy / vehicle). Called by **both** the deterministic path
  and the fallback before a document is served. (Independent-gate rule from the architecture doc:
  the model never grades its own served output.)

## 3. How it wires into existing code

- `backend/chromium_driver.py` — gains an optional `vision: VisionAgent = StubVisionAgent()`;
  its step methods wrap `CarrierModule` calls in "try deterministic → fallback → gate."
- `backend/browser.py` — `CarrierModule` unchanged in shape; fetch gains the explicit
  endpoint-recipe form.
- `backend/vision.py` (new) — `VisionAgent` protocol + `StubVisionAgent` + `VisionUnavailable`.
- `backend/discovery.py` (new) — the extraction harness.
- `backend/validation.py` (new) — the gates (wraps `spike/docfetch.is_valid_pdf`).
- `backend/sessions.py` — unchanged for this increment except that the gate decides whether a
  fetched doc is served vs `FAILED`. (GREEN/YELLOW/RED + alerting deferred.)

## 4. Model-agnostic now vs model-dependent later

- **Now (no model):** deterministic execution path; discovery harness (human-driven); the
  `VisionAgent` protocol + stub + wired seam; validation gates; fallback orchestration.
- **Later (post-eval):** a real `VisionAgent` backed by Holo3.1 → automates the discovery driving
  (2.2) and serves as the prod fallback (2.4). No structural change — implement the protocol.

## 5. Honest caveat — "direct endpoints" isn't universal

Geico's fetch is a clean direct endpoint (`/ws/...`). LM today fetches via the "View / print"
*popup*, not a documented endpoint. So the endpoint recipe must support **"trigger-then-capture"**
(click a control, then capture the resulting `application/pdf` response) as well as a pure GET.
The harness surfaces a direct endpoint when one exists and records the trigger when it doesn't.

## 6. Non-goals

- No autonomous-agent behavior shipped yet (stub only; real agent is post-eval).
- No egress/proxy work (settled separately).
- No GREEN/YELLOW/RED state machine or alerting in this increment (architecture doc, later).
- The VLM does not generate carrier code; recipes are human-codified.

## 7. Verification

- **Harness:** run it by hand against an existing carrier (Geico) and confirm the emitted
  `CarrierRecipe` matches the hand-written module (same endpoint + selectors).
- **Deterministic path:** existing LM + Geico carrier tests still pass after the fetch-recipe
  consolidation.
- **Seam:** a test that a deterministic failure with `StubVisionAgent` propagates as `FAILED`
  (no crash) and that the seam is invoked.
- **Gates:** unit tests — valid PDF passes; an HTML error page served as a PDF fails; a
  wrong-identity document fails.
- **End-to-end (regression):** the deployed flow for LM + Geico still completes login → MFA →
  correct PDF through the new deterministic-first path.

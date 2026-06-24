# VLM-Assisted Carrier Onboarding & Self-Healing — Design

- **Date:** 2026-06-24
- **Status:** Proposed (design). **Evolves** the deployed deterministic system — not a rewrite.
- **Scope:** How we add new carriers cheaply and stay robust when carrier portals change,
  using a self-hosted vision-language model (**Holo3.1-35B-A3B**) for dev-time discovery and a
  guarded prod-time fallback. Current carriers: Liberty Mutual, Geico.
- **Relates to:** `2026-06-16-minimal-lm-webapp-design.md` (the product) and the proven
  residential-egress finding (datacenter IP tarpits the credential POST → residential proxy
  fixes it, see `lm-tarpit-stealth-experiments`).

---

## 1. Context & problem

The deployed system works for two carriers, but each carrier is a hand-written integration
(selectors + endpoints), and it breaks **silently** when a portal changes. Two costs dominate:

- **Onboarding a new carrier** is bespoke reverse-engineering (find the login flow, the doc
  endpoints, the PDF capture).
- **Drift**: when a carrier changes selectors / endpoints / the PDF location, the deterministic
  path fails — and today there's no loud signal telling us which carrier broke or why.

This design keeps the fast/reliable deterministic path for the common case, and adds a
vision-language model in two narrow roles — **dev-time discovery** and a **guarded prod
fallback** — so onboarding is cheaper and drift is *loud and self-healing* instead of silent.

## 2. Non-goals

- **Browserless authentication.** Proven impossible: the credential POST is gated by anti-bot
  tokens that only a real browser running the carrier's JS can produce (see the LM tarpit
  findings + the `auth0_replay` experiment). Auth always runs through a real browser.
- **A generic "works on any carrier" engine.** Each carrier remains a per-carrier integration;
  the VLM lowers the authoring cost, it does not eliminate per-carrier work.
- **VLM on the hot path.** In steady state the VLM does not run per request. It runs on
  discovery (dev) and on breakage (prod fallback) only.

## 3. Current baseline (what's deployed)

- Real headless Chromium (Playwright) + **residential egress** (the bot-wall fix). Today the
  egress is an `ssh -R` tunnel; production target is a residential proxy via the existing
  `PROXY_*` config (`spike/config.py` → `backend/chromium_driver.py` `new_context(proxy=…)`).
- Per-carrier modules implementing the `CarrierModule` protocol (`backend/browser.py`):
  - `backend/carriers/lm.py` — Auth0 DOM selectors; PDF via "View / print" popup capture.
  - `backend/carriers/geico.py` — HTML login + **Flutter canvas** MFA (hardcoded pixel
    coordinates — the brittle spot); documents via the `/ws/...` JSON endpoints.
- `backend/sessions.py` runs the `STARTING → AWAITING_MFA → VERIFYING_MFA → FETCHING → READY |
  FAILED` state machine. Adding a carrier = one module + a `registry.py` entry.

## 4. The three-layer architecture

| Layer | What it does | Owned by |
|---|---|---|
| **Foundation** | Clears the bot wall | Real Chromium + residential egress (unchanged) |
| **Navigation** | Drive login → MFA → to the document | Deterministic selectors first; **VLM** where there's no DOM (Geico canvas) or as fallback |
| **Capture** | Get the PDF **bytes** | Playwright network tap / authenticated endpoint GET (never the VLM — it sees pixels, not bytes) |

Auth is always browser-driven (selectors / VLM). Only the **post-auth document fetch** is a
deterministic endpoint call. The VLM never captures bytes.

## 5. Model choice — Holo3.1-35B-A3B (single VLM, all roles)

**Pick: `Hcompany/Holo-3.1-35B-A3B`** (released 2026-06-02).

- **License: Apache 2.0 → commercially shippable.** (The smaller 0.8B/4B/9B sizes have *not*
  been confirmed commercial — **verify before using any of them**; only the 35B-A3B is
  confirmed Apache 2.0.)
- **MoE, Qwen3.5-based, 35B total / ~3B active** → flagship quality at ~3B-dense inference cost.
  Quantized checkpoints (FP8 / NVFP4 / Q4 GGUF) run on **~12 GB VRAM**.
- **Full agent** (perception **and** decision-making), web + desktop + mobile, native
  function-calling. So **one model covers all three roles** — Policy (navigate), Localize
  (find elements, incl. the canvas), Validate (read the screen / confirm state). No separate
  planner needed.

**Vendor numbers, pending our own benchmark:** HCompany reports **~140 ms step latency** and
**74.2 % OSWorld**. Treat these as vendor figures — our real latency/accuracy must be measured
on *our* carrier screens (§13). Lighter alternative if GPU cost pinches: **Holo3.1-9B** (dense),
license permitting.

Obsoletes earlier picks in this conversation (Holo1.5-7B + a separate frontier planner,
GUI-Actor) — Holo3.1 is newer, faster, commercially licensed, and plans on its own.

## 6. Dev-time discovery

Onboarding a new carrier happens **in dev**, never first-in-prod:

1. The VLM (Holo3.1, or a frontier computer-use model for max accuracy) navigates the carrier
   portal by screenshot, all the way to the PDF.
2. It records the **request recipes** (method, URL template with token/doc-id slots, required
   headers — e.g. Geico's `x-xsrf-token` — cookies, body shape, and where each dynamic value
   comes from) plus the **nav selectors** for the login flow.
3. A human **verifies** the discovered recipe produced the *right* document before it ships.
   Discovery output is a proposal, not ground truth — never auto-cache an unverified run.
4. Ship a deterministic `CarrierModule` (selectors for auth, endpoints for fetch).

## 7. Prod runtime — three states

Steady state runs the deterministic integration (Playwright+selectors for auth, endpoint GET
for the PDF). Per carrier, prod is always in one of three states:

- **GREEN** — deterministic fast path working. Normal.
- **YELLOW** — fast path broke; VLM-heal validated and serving. Working but **degraded** (slow).
  Alert + fix in dev. **YELLOW must stay loud** (see §10) or we silently rot on the slow path.
- **RED** — fast path broke **and** VLM-heal can't pass the gates. User blocked. Alert + fix now.

## 8. Validated-heal fallback

When the deterministic path breaks in prod, the VLM takes over, runs the request the slow way,
and **serves the result only if it passes the validation gates (§9)**. Simultaneously it raises
an alert (§10) so we fix the deterministic path in dev and redeploy. If it can't produce a
validated result → fail safe (RED), don't serve.

> **Independent-gate rule (critical):** do **not** let the VLM grade its own high-stakes output.
> The "is this the right document" gate must be **independent / deterministic**. A model that
> both acts and validates its own action can be confidently wrong and rubber-stamp the mistake
> (correlated failure). VLM-as-validator is fine for low-stakes *navigation-state* checks ("are
> we on the MFA screen?"); it is **not** the gate that decides what gets served.

## 9. Validation gates

The gate is the linchpin — it is both the trigger ("did the fast path break?") and, in
validated-heal, the trust check ("can we serve this?"). Per carrier it must verify:

- **Valid PDF** — bytes start with `%PDF-` (the existing `is_valid_pdf` check), plausible size /
  page count, not an HTML error page rendered as a PDF.
- **Right document** — matches the requested doc type / policy / vehicle identity. **Valid ≠
  correct**: serving the *wrong* (but valid) PDF — another vehicle's ID card, a different
  policy's dec page — is a real failure. If correctness can't be cheaply verified, fail to RED
  rather than serve.

## 10. Failure detection & alerting

Self-healing is only as good as our ability to *notice* a break:

- **Synthetic canary** per carrier — a scheduled run on a test account that exercises the full
  flow and alerts on failure, so we learn before a user does (proactive, not reactive).
- **Typed failure taxonomy** — the existing `CarrierAuthError` / `MfaError` / `DocFetchError` /
  `BotChallengeError` already pinpoint *which carrier, which step*. The VLM can *enrich* an
  alert ("login button moved, page looks redesigned"); the deterministic gates are the trigger.
- **YELLOW is a tracked alert, not a shrug** — every heal-serve raises a ticket and shows the
  carrier as degraded until the deterministic path is restored. The dev fix should add/update
  the carrier's canary so the *same* drift trips proactively next time (regression capture).
- **Rate-limit the heal path.** Carriers throttle after rapid logins (observed live this
  project). A broken carrier under load could flood slow VLM logins and cascade YELLOW → RED for
  everyone — so circuit-break / cap concurrent heals per carrier. (Note: the heal still needs
  the user's MFA code — it is not unattended.)

## 11. How it maps onto the existing code

- **Foundation** — unchanged. `PROXY_*` already wired in `chromium_driver.py`; swap the SSH
  tunnel for a residential proxy in prod.
- **Navigation** — add a VLM-driven fallback path the `CarrierModule` steps can defer to when a
  selector/endpoint step fails. Geico's canvas (`backend/carriers/geico.py` hardcoded
  coordinates) is the first place to replace with VLM localization.
- **Capture** — unchanged (Playwright response/endpoint capture).
- **State machine** (`backend/sessions.py`) — extend session state to carry GREEN/YELLOW/RED so
  the API/alerting can surface "degraded."
- **Validation gates** — formalize per-carrier `is_valid_pdf` + identity checks as a reusable
  gate invoked by both the deterministic and heal paths.

## 12. Build-vs-buy (honest note)

This is a **product**, and building the automation ourselves means we are *being* the aggregator
rather than using one. Insurance data aggregators (Canopy Connect, Trellis Connect, Indio,
Quandri) already build and maintain per-carrier integrations and return policy data **+
documents incl. the declarations page** via consumer-permissioned access. If the automation is
*plumbing* rather than our differentiator, an aggregator API ships faster and offloads the
per-carrier maintenance that is the real ongoing cost. We are proceeding to build because the
automation is the product / the rail — recorded here so the trade-off was decided, not defaulted.

## 13. Open questions / eval plan

- **Benchmark Holo3.1-35B-A3B on *our* carrier screens** (esp. Geico's canvas): localization
  accuracy, end-to-end navigation success, real step latency on our GPU. Vendor's 140 ms /
  74.2 % OSWorld are not our numbers.
- **Confirm licenses** of Holo3.1-9B/4B/0.8B if we'd use a smaller size; only 35B-A3B is
  confirmed Apache 2.0.
- **Policy quality**: does Holo3.1 plan the multi-step flow well enough alone, or do we keep a
  frontier model for dev discovery (where accuracy > cost and it runs rarely)?
- **GPU/hosting** for the prod fallback (rare invocation → on-demand GPU is viable).
- **"Right document" check**: define the cheap per-carrier identity verification (§9).

## 14. Verification

A carrier integration is "done" when:

- Deterministic path completes login → MFA → correct PDF, validated by the §9 gates, with the
  canary green.
- Forcing a break (e.g. a stale selector/endpoint) flips the carrier to YELLOW, the VLM-heal
  serves the *correct* document past the gates, and an alert fires.
- An unrecoverable break flips to RED and fails safe (no wrong/garbage doc served), with an
  alert naming the carrier + step.
- Onboarding a third carrier exercises the full dev-discovery → human-verify → ship loop.

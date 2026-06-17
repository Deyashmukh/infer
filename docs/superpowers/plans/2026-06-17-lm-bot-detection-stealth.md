# LM Bot-Detection / Stealth Workstream — Plan (outsourced)

> **RESOLVED (2026-06-17) — this workstream was not needed.**
> The real root cause was the **datacenter egress IP**, not a browser/automation fingerprint.
> Proven with *real* credentials: an EC2 datacenter VM completes the full LM login
> (credentials → MFA → documents) the moment the browser egresses through a **residential IP**
> (validated via an `ssh -R 1080` reverse SOCKS tunnel). The fix is already wired in the
> backend (`PROXY_*` → Playwright `new_context(proxy=…)`); no stealth browser is involved.
>
> The diagnosis below is **superseded and wrong in two ways:** (1) the "ruled out IP /
> residential still tarpitted" and "raw `http.client` POST gets 400" results came from
> **dummy credentials**, and invalid/unknown accounts get tarpitted on *every* egress (a
> standard anti-enumeration stall) — so they measured the wrong thing; (2) `net_probe`'s fast
> 400 was a red herring (`{}` has no username → fast validation error). The stealth path
> (patchright / Browserbase advancedStealth / …) was a dead end. Kept below for history.

**Goal:** make a **hosted** (datacenter) browser complete the Liberty Mutual credential
POST, so the system runs off-laptop. This is the **one** eval criterion not met by the
local build; everything else (the flow, MFA, docs, render, architecture) is met locally.

**Owner:** the Claude Code session **on the EC2 box** (it has the box + the failing
condition). Report results back to the main session. This is decoupled from the product
build — the `BrowserDriver` Protocol means whichever browser wins is a **driver swap**,
nothing above it changes.

## Diagnosis (proven — do not re-litigate)
- LM's edge (Auth0 behind Cloudflare/Akamai) **silently tarpits the credential POST**
  (`/usernamepassword/login`) from the hosted browser: POST fires, no response, 30s timeout.
- **Ruled out:** IP (residential via SSH reverse-tunnel still tarpitted), network mode
  (bridge & `--network host`), Docker, MTU (9001→1500).
- **Clinching test:** a raw stdlib `http.client` POST from the *same* container gets
  **HTTP 400 in 0.1s**; the browser's POST hangs. So box + egress are fine — it's the
  **browser request** being fingerprinted.
- **Not TLS/JA3:** Mac and container Chromium are the same build (148) → identical JA3,
  yet Mac passes and the container is dropped. So the signal is **runtime/automation/header**
  level, not TLS → **runtime-stealth tools are well-targeted.**

## Environment
EC2 `ubuntu@100.26.46.173`, repo `~/infer`, image `infer-backend`, run `--network host`.

## Non-interactive test harness (no SMS)
`backend/stealth_probe.py` — adapt `confirm_h1.py`: **dummy credentials**, run the login
flow only up to the credential POST, print `[egress]`, `login_POST_sent`, `login_resp`.
**PASS = `login_resp` shows any status** (even 401/400 from fake creds). **FAIL = `login_resp={}`** (tarpit). No real login, no SMS.

## Ordered experiments (decision-rule gated — stop at first PASS)
1. **patchright** (drop-in; patches CDP/`Runtime.enable`/headless tells — best-targeted,
   since it's runtime signals not TLS). `uv add patchright && uv run patchright install chromium`;
   swap the import. Test. **PASS → adopt** (wire into `ChromiumDriver` as a 1-line import swap). FAIL → 2.
2. **rebrowser-playwright** or **nodriver** (drives system Chrome over WS, no Playwright shim
   in the control plane — strong recent Cloudflare results). Test. PASS → adopt. FAIL → 3.
3. **Header/fingerprint normalization** layered on the above — consistent desktop UA +
   `sec-ch-ua` + locale, no inconsistencies. Test. FAIL → 4.
4. **Managed anti-detect: Browserbase `advancedStealth`** (fingerprint + residential, done
   for you). Caveat: Browserbase earlier hit the H2 error on this POST — re-test with
   `advancedStealth` + their network (they may handle the HTTP/1.1 need). Costs money.
   PASS → adopt as the hosted driver (Protocol swap). FAIL → 5.
5. **Residential proxy + stealth combo** — the production-grade aggregator stack.

## Success criteria
Hosted browser completes the credential POST reliably, then the full login → MFA → docs
flow hosted. Each experiment reports `[egress]` IP + the build stamp + the three probe values.

## Note
Defeating Cloudflare/Akamai fingerprinting is an arms race — no fix is guaranteed. A
rigorously-documented "here is the wall and the proven path" is itself a valid outcome,
given the production architecture is already built.

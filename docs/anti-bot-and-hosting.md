# Hosting & Anti-Bot: what we did, what we found, the tradeoffs

This is the honest account the brief asks for ("how you think about hosting this somewhere
that isn't your machine" and "what you tried, what worked, what tradeoffs you made"). The
short version: **the architecture is built to run the browser off-laptop and to swap browsers
freely; the hard part is a carrier-edge anti-bot wall that we diagnosed precisely, and the
fix for it is a stealth-browser layer behind a stable seam.**

## 1. Hosting — what actually has to be off-laptop, and where it runs

The thing a carrier sees is the **browser's egress IP and request fingerprint**, not where
the FastAPI process lives. So the unit that must be hosted is the **browser**. We run a
**single Docker image = FastAPI + headless Chromium** (Microsoft's Playwright base image,
which ships a matched Chromium + system libs), deployable unchanged to a VM. We brought it
up on an **AWS EC2 box** (`us-east-1`, datacenter IP). The React frontend stays client-side
and talks to the hosted backend over HTTP. One image runs identically on a laptop and on the
VM (dev/prod parity), so "works locally" and "works deployed" can't silently diverge.

**Why self-hosted Chromium and not a managed browser (e.g. Browserbase):** Liberty Mutual's
login only completes over **HTTP/1.1** — Chromium's HTTP/2 negotiation to LM's Cloudflare
edge intermittently dies with `ERR_HTTP2_PROTOCOL_ERROR`. The fix is the launch flag
`--disable-http2`, and a managed browser you attach to over CDP (`connect_over_cdp`) is
*already launched* — you can't pass it process flags. Self-hosting gives us that control.
(A managed **stealth** browser remains our fallback for the anti-bot wall below — the point
is we chose the host deliberately, for a concrete reason.)

## 2. The anti-bot wall — a layered diagnosis (ruling things out, not guessing)

We hit two distinct layers and proved each by elimination rather than assertion.

**Layer 1 — HTTP/2 transport.** The credential POST (`/usernamepassword/login`)
intermittently failed with `ERR_HTTP2_PROTOCOL_ERROR`, on a managed browser (9/9) *and* on a
local one (~80%). It's an IP-independent transport bug. **Fix:** `--disable-http2`. Full
login → MFA → documents then completed end-to-end **on a residential machine**.

**Layer 2 — request fingerprinting (the real wall).** From the **hosted datacenter
browser**, that same POST is **silently tarpitted**: it fires and gets no response (30 s
timeout), no error. We ruled out, with evidence:
- **IP / egress** — routed the container's traffic through a residential IP via an SSH
  reverse-SOCKS tunnel (egress confirmed = the home IP). Still tarpitted — the *same* IP that
  succeeds from the Mac.
- **Network** — fails identically on Docker bridge and `--network host`.
- **MTU / PMTUD** — the EC2 interface was 9001; forced 1500. No change.
- **The clincher** — a raw stdlib `http.client` POST from the *same container* gets an
  instant **HTTP 400 in 0.1 s**, while Chromium's POST to the identical endpoint hangs. So
  the box, the egress, and the edge's willingness to answer POSTs are all fine — it is
  specifically **the browser's request** being singled out.
- **Not TLS/JA3** — the Mac and the container run the *same* Chromium build (148), so their
  JA3 is identical, yet the Mac passes and the container is dropped. The discriminator is a
  **runtime/automation signal**, not the TLS handshake.

Conclusion: LM's edge (Auth0 fronted by Cloudflare/Akamai-class detection) fingerprints the
automated headless browser specifically on the sensitive credential POST and tarpits it,
while letting GETs and non-browser clients through. This is exactly the "real detection"
the brief anticipates.

## 3. What we're doing about it, and the tradeoffs

Because the discriminator is a runtime signal (not TLS), **runtime-stealth tooling is the
well-targeted first move.** We attack it in a decision-rule-gated order, cheapest/most-self-
hosted first, each validated by a **non-interactive probe** (dummy credentials, no SMS:
does the credential POST get *a* response, or hang?):

1. **patchright** — drop-in Playwright fork that patches the CDP/`Runtime.enable`/headless
   tells. ~1-line swap behind our driver seam.
2. **rebrowser-playwright / nodriver** — different patch strategy / drives system Chrome
   without a Playwright control-plane shim.
3. **Header/fingerprint normalization** layered on top.
4. **Managed anti-detect (Browserbase `advancedStealth`)** — fingerprint + residential, done
   for you; the fallback if self-hosted stealth isn't enough.
5. **Residential proxy + stealth** — the production-grade aggregator stack.

> **Status:** _to be filled from the EC2 experiment — patchright probe result + which rung we landed on._

**The key architectural decision that makes this tractable:** every browser sits behind a
`BrowserDriver` Protocol. Whichever option wins is a **contained driver swap** — the
orchestration, API, frontend, and carrier flow don't change. That's why we could spend the
effort *diagnosing* instead of rewriting.

**Tradeoffs, stated plainly:**
- Defeating Cloudflare/Akamai fingerprinting is an arms race; there's no guaranteed,
  permanent bypass. We optimized for the cheapest targeted fix first and kept a managed-
  service escape hatch.
- `--disable-http2` forces HTTP/1.1 for the whole browser — fine for these carriers, an
  intentional, documented trade.
- The only place the full flow *currently* completes is a residential IP (the laptop — the
  brief's anti-pattern), because the hosted browser hits Layer 2. We did **not** ship that as
  the answer; we hosted it properly, diagnosed the wall, and the stealth layer is how the
  hosted path clears it.

## 4. Reliability & session reuse

After a successful login we cache the browser session (`storage_state` — cookies, in-memory,
TTL'd, keyed by `(carrier, username)`, never written to disk). A repeat run for the same
account loads it and goes **straight to documents, skipping login and MFA** — faster, fewer
SMS codes, and lockout-safe (no password submission). Expired cache falls back to a full
login automatically. (Single-user scoped — the account owner re-running — not multi-tenant.)

## 5. Latency

We measure the graded metric — **MFA-submit → first document rendered** — with a client mark
at react-pdf's `onRenderSuccess` minus the MFA-submit timestamp, plus a server-side
`MFA→first-bytes` sub-metric. Documents stream (first doc flips the session to READY; the
rest follow) so first-doc render isn't gated by total fetch.

> **Status:** _measured number to be filled from the local end-to-end run._

# infer

Pull your **own** insurance policy document straight from the carrier's portal and view it in
the browser: pick a carrier → enter portal credentials → approve the MFA prompt → the policy
PDF renders in-page. Carriers: **Liberty Mutual** (declarations PDF) and **Geico** (auto
ID-card PDF).

> ⚠️ Use only with **your own accounts**. Credentials are entered at runtime, used once, and
> never stored.

The app = a **FastAPI backend** that drives self-hosted headless Chromium (Playwright) + a
**React frontend**. Run the backend (Docker *or* local), then the frontend.

## 1. Configure

```bash
cp .env.example .env     # then set LM_LOGIN_URL and GEICO_LOGIN_URL (see comments in the file)
```

## 2. Run the backend

**Docker (recommended — bundles Chromium; runs the same on a laptop or a VM):**

```bash
docker build -t infer .
docker run --rm -p 8000:8000 --env-file .env --shm-size=1g \
  -e CHROMIUM_ARGS=--no-sandbox infer
```

`--shm-size=1g` and `CHROMIUM_ARGS=--no-sandbox` are required for Chromium inside a container.

**Or local** (Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run playwright install chromium
uv run uvicorn --factory backend.main:build_production_app --host 0.0.0.0 --port 8000
```

Either way the API is on `http://localhost:8000`. Set `HEADLESS=false` in `.env` to watch the
browser drive (local only).

## 3. Run the frontend

```bash
cd frontend
npm install
npm run dev              # http://localhost:5173
```

Open that URL, pick a carrier, and follow the prompts. If the backend isn't on
`localhost:8000`, set `VITE_API_URL=http://<host>:8000` before `npm run dev`.

## Deploy to a VM

The Docker image runs unchanged on any VM: install Docker, `docker build` / `docker run` as
above (expose port 8000), set `FRONTEND_ORIGIN` to the frontend's URL (CORS), and point the
frontend's `VITE_API_URL` at the VM.

### Egress matters (residential proxy)

Carriers see the **browser's egress IP**. Liberty Mutual **tarpits the credential POST from
datacenter IPs** (AWS/GCP/…): the POST fires and then hangs with no response. A **residential
egress fixes it** — verified end-to-end on an AWS VM, where the full LM login (credentials →
MFA → document fetch) completes once the browser exits through a residential IP. (Geico shows
no such tarpit and runs fine on direct egress.)

The backend routes the browser through a proxy whenever these are set (see `.env.example`):

```bash
PROXY_SERVER=http://gw.your-residential-proxy.com:8080   # a residential proxy service
PROXY_USERNAME=...
PROXY_PASSWORD=...
```

**Local dev — no paid proxy needed.** Borrow your own home connection as the residential
egress with an SSH reverse SOCKS tunnel (OpenSSH ≥ 7.6):

```bash
# Run on your home machine — opens a SOCKS proxy on the VM's :1080 that exits via your home IP:
ssh -R 1080 user@your-vm
```

Then point the backend at it (the tunnel needs no proxy credentials):

```bash
PROXY_SERVER=socks5://127.0.0.1:1080
```

### How we found this

The hosted (datacenter) browser's LM credential POST would fire and then **hang with no
response** — a deliberate tarpit. The first theory was an automation/browser fingerprint, which
sent us down a stealth-browser rabbit hole (patchright, managed anti-detect) — all dead ends. The
real catch was a **confound**: those experiments used *dummy* credentials, and LM tarpits
invalid/unknown logins on **every** egress (a standard anti-enumeration stall — it even happened
from a Mac), so they were measuring the wrong thing. Re-running with **real** credentials isolated
a single variable: the **egress IP**. Same browser, same box — a datacenter IP tarpits, a
residential IP sails through. We proved it by tunnelling the datacenter VM's browser out through a
home connection with an `ssh -R 1080` reverse SOCKS proxy: the full login (credentials → MFA →
document fetch) completed end-to-end. So the fix is a **residential egress** — a proxy in
production, the SSH tunnel for local dev — **not a fancier browser**.

## Test

```bash
uv run pytest                          # 87 backend tests, fully offline
uv run ruff check . && uv run mypy backend spike
cd frontend && npm test && npm run lint && npx tsc --noEmit   # 29 frontend tests
```

## How it's built

`backend/carriers/{lm,geico}.py` each implement a common `CarrierModule` protocol
(`open_login`, `submit_credentials`, `submit_mfa`, `list_documents`, `fetch_document`,
`is_authenticated`) + a `LAUNCH_ARGS` list; `chromium_driver.py` runs them with per-carrier
HTTP version and a `navigator.webdriver` mask; `sessions.py` runs the
`STARTING → AWAITING_MFA → VERIFYING_MFA → FETCHING → READY | FAILED` state machine. Adding a
carrier = one module + a `registry.py` entry.

**Latency** (MFA-submit → PDF on screen): LM ~9–10 s, Geico ~11 s. This is carrier-server-bound
(their MFA verification + on-demand PDF generation alone take ~7–8 s); the < 8 s target isn't
reachable for the real document without showing a fast local summary first.

**Security:** credentials are never persisted; `.env` and `spike/out/` (cookies, PDFs, PII) are
git-ignored.

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
frontend's `VITE_API_URL` at the VM. Note: carriers see the **browser's egress IP** — datacenter
IPs can be tarpitted on the credential POST, so run behind residential egress for production
(`PROXY_*` hooks are wired but deferred).

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

# Self-Hosted LM Web App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the proven Liberty Mutual login + doc-fetch into a hosted, human-in-the-loop web app: pick LM → enter creds + MFA in a React UI → a containerized self-hosted headless Chromium (`--disable-http2`) logs in → policy PDFs render. Gate the datacenter login first (milestone 0).

**Architecture:** Self-hosted Chromium (Playwright, `--disable-http2`) in one Docker image run identically local + on a VM. Backend Part 1 (async FastAPI state machine, in-memory registry, `BrowserDriver` Protocol + `FakeDriver`) is **already built and green** — this plan replaces the Browserbase driver stub with a real `ChromiumDriver`, adds the LM flow, flips `READY` after the first doc, containerizes, and builds the SPA. Direct egress this increment; proxy-ready for later.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, async Playwright (local Chromium) pinned `==1.60.0`; pytest + pytest-asyncio + httpx; React + TypeScript + Vite + react-pdf; Docker (Playwright base image).

**Spec:** `docs/superpowers/specs/2026-06-16-minimal-lm-webapp-design.md`

**Already built (do NOT rebuild):** `backend/models.py`, `backend/sessions.py`, `backend/api.py`, `backend/main.py`, `backend/browser.py` (Protocol + `FakeDriver`), tests (67 green). Proven flow: `backend/confirm_h1.py`, `backend/map_docs.py`, `backend/probe_doc.py` (reuse their selectors/logic). **Known fixtures:** `tests/fixtures/lm/documents.html` backs `test_lm_pagestate.py` and `documents_list.html` backs `test_lm_docdiscovery.py` — **keep both** (they test the still-used `classify_lm_page`/`discover_document_urls`).

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `Dockerfile`, `.dockerignore` | Playwright base image + backend; Chromium headless `--disable-http2`. Used by M0 + product. | M0, 5 |
| `compose.yaml` | local product run, env-driven | 5 |
| (delete) `backend/browserbase_driver.py`, `backend/diag_*.py`, `backend/live_login.py`, `backend/preflight.py`, `backend/recon_login.py`, `backend/release_sessions.py`, `spike/browserbase.py`, `tests/test_browserbase_params.py` | obsolete Browserbase code (would break `mypy` after the config change) | 1 |
| `spike/config.py`, `tests/test_config.py`, `.env.example` | drop Browserbase fields; add `LM_LOGIN_URL`/`HEADLESS`/`CHROMIUM_ARGS`/`PROXY_*` | 1 |
| `pyproject.toml`, `uv.lock` | pin `playwright==1.60.0` (match the Docker base image) | 1 |
| `backend/browser.py` | `DocRef` drops `url`; `FakeDriver` gains multi-doc mode | 2, 4 |
| `backend/chromium_driver.py` | **NEW** real `ChromiumDriver` (Protocol impl) | 2, 3 |
| `backend/carriers/lm.py`, `tests/backend/test_lm_parser.py`, `tests/fixtures/lm/documents_real_sanitized.html` | **NEW** LM nav + pure `parse_document_list` + sanitized real fixture | 3 |
| `backend/sessions.py`, `backend/api.py`, `tests/backend/test_*` | READY-after-first-doc + zero-doc guard; stream `documents` from fetched dict; `/health` | 4, 5 |
| `backend/main.py` | swap driver factory Browserbase → Chromium | 4 |
| `frontend/` | Vite React TS SPA | 6 |

**Reused pure core (`spike/`):** `carriers/liberty_mutual.classify_lm_page`, `timing.Timer`, `docfetch.is_valid_pdf`, `AttemptGuard`.

---

## Milestone 0 — GATE: datacenter login on a VM (do this FIRST)

**Purpose:** convert "datacenter IP + `--disable-http2` logs in" from inference to observation, and prove Chromium-in-Docker, before any product code. PASS ⇒ build. FAIL ⇒ stop and reassess (residential proxy may become mandatory). **Proof gate, not TDD.**

**Note:** M0 runs `backend/confirm_h1.py`, which calls the **current** `load_config` — keep the **existing `.env`** (with the Browserbase keys still present; `confirm_h1` only uses `lm_login_url`) for M0. Task 1 simplifies the config afterward.

### Task M0: Containerize the proven login and run it on a datacenter VM

**Files:** Create `Dockerfile`, `.dockerignore`.

- [ ] **Step 1: Write `Dockerfile`** (Playwright base image bundles Chromium + libs)

```dockerfile
# Tag MUST match the pinned playwright package version (Task 1 pins ==1.60.0).
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
# M0 default: the proven interactive login gate. (Task 5 changes CMD to the API.)
CMD ["uv", "run", "python", "-m", "backend.confirm_h1"]
```
(The base image sets `PLAYWRIGHT_BROWSERS_PATH` as process env, so `uv run` finds the preinstalled Chromium **only if** the `playwright` package version matches the image tag — that's why Task 1 hard-pins `==1.60.0`.)

- [ ] **Step 2: Write `.dockerignore`**
```
.git
.venv
node_modules
spike/out
.env
**/__pycache__
frontend/dist
frontend/node_modules
```
(`.env` and `spike/out` are excluded so `COPY . .` never bakes secrets/PII into the image.)

- [ ] **Step 3: Sanity-build + run LOCALLY first** (proves image + Chromium-in-Docker before paying for a VM)
```bash
docker build -t lm-gate .
docker run --rm -it --env-file .env --shm-size=1g lm-gate   # interactive: creds + MFA on stdin
```
Expected: `AUTHENTICATED=True … /accountmanager/...`. (Residential IP here — proves only the container shape. If Chromium dies on `/dev/shm`, `--shm-size=1g` fixes it; if sandbox errors, set `CHROMIUM_ARGS=--disable-http2 --no-sandbox` for the container run.)

- [ ] **Step 4: Provision a cheap datacenter VM and run the gate there** (datacenter IP)
```bash
# from laptop: git clone or rsync the repo to the VM, then copy the CURRENT .env
scp .env user@VM:/path/infer/.env
ssh -t user@VM            # -t allocates a TTY for the interactive MFA prompt
cd /path/infer && docker build -t lm-gate . && docker run --rm -it --env-file .env --shm-size=1g lm-gate
```
(The SMS arrives on the account owner's phone; type it into the VM's prompt.)

- [ ] **Step 5: Record the result and DECIDE.** PASS = `AUTHENTICATED=True` on the VM. Note the URL + `creds->authed` time. **PASS ⇒ Task 1. FAIL** ⇒ stop; capture failure (`spike/out` screenshots) and reassess host. Commit `Dockerfile` + `.dockerignore` now (reused by Task 5): `git add Dockerfile .dockerignore && git commit -m "container: login-gate Dockerfile for the datacenter milestone-0 proof"`.

---

## PART A — Backend driver swap (TDD where offline-testable)

### Task 1: Remove obsolete Browserbase code + config swap

**Files:** Delete the Browserbase modules; Modify `spike/config.py`, `tests/test_config.py`, `.env.example`, `pyproject.toml`/`uv.lock`.

- [ ] **Step 1: Delete obsolete Browserbase code** (it reads `Config.browserbase_*`, which Step 4 removes — leaving it would break `mypy`/imports):
```bash
git rm backend/browserbase_driver.py backend/diag_matrix.py backend/diag_login.py \
       backend/live_login.py backend/preflight.py backend/recon_login.py \
       backend/release_sessions.py spike/browserbase.py tests/test_browserbase_params.py
# Sanity: nothing else still imports the Browserbase SDK or spike.browserbase.
grep -rn "spike.browserbase\|import browserbase\|browserbase_api_key" backend/ spike/ tests/ \
  | grep -v "^docs/" || echo "clean"
```
(Keep `backend/confirm_h1.py`, `map_docs.py`, `probe_doc.py` — they don't import Browserbase.)

- [ ] **Step 2: Pin Playwright exactly** — in `pyproject.toml`, change `playwright>=1.60.0` to `playwright==1.60.0`; `uv lock` to refresh `uv.lock`. (Matches the Docker base image tag.)

- [ ] **Step 3: Update the failing config test** — rewrite `tests/test_config.py`:
```python
import pytest
from spike.config import Config, ConfigError, load_config

def test_load_config_defaults():
    cfg = load_config({"LM_LOGIN_URL": "https://www.libertymutual.com/log-in"})
    assert cfg.lm_login_url.endswith("/log-in")
    assert cfg.headless is True
    assert cfg.chromium_args == ["--disable-http2"]
    assert cfg.proxy_server is None

def test_load_config_proxy_and_overrides():
    cfg = load_config({
        "LM_LOGIN_URL": "https://x", "HEADLESS": "false",
        "CHROMIUM_ARGS": "--disable-http2 --no-sandbox",
        "PROXY_SERVER": "http://p:8080", "PROXY_USERNAME": "u", "PROXY_PASSWORD": "pw",
    })
    assert cfg.headless is False
    assert cfg.chromium_args == ["--disable-http2", "--no-sandbox"]
    assert (cfg.proxy_server, cfg.proxy_username, cfg.proxy_password) == ("http://p:8080", "u", "pw")

def test_missing_login_url_raises():
    with pytest.raises(ConfigError):
        load_config({})
```

- [ ] **Step 4: Run it — expect FAIL** (`uv run pytest tests/test_config.py -q`).

- [ ] **Step 5: Rewrite `spike/config.py`**
```python
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED = ("LM_LOGIN_URL",)

class ConfigError(Exception): ...

@dataclass(frozen=True)
class Config:
    lm_login_url: str
    headless: bool
    chromium_args: list[str]
    proxy_server: str | None
    proxy_username: str | None
    proxy_password: str | None

def load_config(env: Mapping[str, str]) -> Config:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ConfigError(f"missing required env: {', '.join(missing)}")
    return Config(
        lm_login_url=env["LM_LOGIN_URL"],
        headless=env.get("HEADLESS", "true").lower() != "false",
        chromium_args=env.get("CHROMIUM_ARGS", "--disable-http2").split(),
        proxy_server=env.get("PROXY_SERVER") or None,
        proxy_username=env.get("PROXY_USERNAME") or None,
        proxy_password=env.get("PROXY_PASSWORD") or None,
    )
```

- [ ] **Step 6: Run — expect PASS** (`uv run pytest tests/test_config.py -q`).

- [ ] **Step 7: Update `.env.example`**
```bash
# Liberty Mutual
LM_LOGIN_URL=https://www.libertymutual.com/log-in   # public
# Browser
HEADLESS=true                          # false to watch locally
CHROMIUM_ARGS=--disable-http2          # space-separated; --disable-http2 is required for LM
# Residential proxy (DEFERRED — leave unset for direct egress)
PROXY_SERVER=                          # e.g. http://gw.provider.com:8080   SECRET
PROXY_USERNAME=                        # SECRET
PROXY_PASSWORD=                        # SECRET
# Carrier creds are entered in the UI at runtime — never stored in env.
```

- [ ] **Step 8: Full gate** — `uv run ruff check . && uv run mypy --strict backend spike && uv run pytest -q`. `main.py` still imports the (now-deleted) Browserbase factory, so it will be red until Task 4 — **scope this run** to confirm the rest is green: `uv run mypy --strict spike backend/models.py backend/sessions.py backend/api.py backend/browser.py && uv run pytest -q --ignore=tests/backend/test_main.py` (re-run the full gate after Task 4). Commit: `git commit -am "config: self-hosted Chromium config + proxy-ready env; remove Browserbase code; pin playwright==1.60.0"`

### Task 2: `DocRef` drops `url`; scaffold `ChromiumDriver`

**Files:** Modify `backend/browser.py`; Create `backend/chromium_driver.py`.

- [ ] **Step 1: Failing test** — in `tests/backend/test_browser.py` (create if absent):
```python
import dataclasses
from backend.browser import DocRef

def test_docref_fields():
    assert {f.name for f in dataclasses.fields(DocRef)} == {"doc_id", "name"}
```

- [ ] **Step 2: Run — expect FAIL** (`DocRef` still has `url`).

- [ ] **Step 3: Edit `backend/browser.py`** — remove `url: str` from `DocRef`; change `FakeDriver.list_documents` to `return [DocRef(doc_id="doc-0", name="Declarations")]` (**keep `doc_id="doc-0"`** — `test_manager_happy.py:36` and `test_api.py:46` assert it).

- [ ] **Step 4: Run — expect PASS**; run full suite `uv run pytest -q --ignore=tests/backend/test_main.py` (sessions/api use `FakeDriver` — still green).

- [ ] **Step 5: Create `backend/chromium_driver.py`** skeleton (methods filled in Task 3):
```python
from __future__ import annotations
from typing import Any
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from backend.browser import AuthStep, DocRef, FetchedDoc
from spike.config import Config

class ChromiumDriver:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._pw: Any = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    async def _ensure(self) -> Page:
        if self._page is None:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self._cfg.headless, args=self._cfg.chromium_args
            )
            proxy = None
            if self._cfg.proxy_server:
                proxy = {"server": self._cfg.proxy_server,
                         "username": self._cfg.proxy_username or "",
                         "password": self._cfg.proxy_password or ""}
            self._ctx = await self._browser.new_context(accept_downloads=True, proxy=proxy)
            self._page = await self._ctx.new_page()
        return self._page

    async def close(self) -> None:  # idempotent
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
        self._page = self._ctx = None

def make_chromium_driver_factory(cfg: Config):
    def factory() -> ChromiumDriver:
        return ChromiumDriver(cfg)
    return factory
```

- [ ] **Step 6:** `uv run ruff check backend/browser.py backend/chromium_driver.py && uv run mypy --strict backend/browser.py backend/chromium_driver.py`. Commit: `git commit -am "browser: DocRef drops url; scaffold ChromiumDriver (Protocol skeleton, proxy-ready)"`

### Task 3: LM flow + pure doc-list parser (parser TDD vs. real fixture)

**Files:** Create `backend/carriers/lm.py`, `tests/backend/test_lm_parser.py`, `tests/fixtures/lm/documents_real_sanitized.html`; fill `ChromiumDriver` methods.

- [ ] **Step 1: Capture + SANITIZE the real documents-page HTML.** With the saved session (re-run `confirm_h1` if `spike/out/lm_state.json` expired), dump `await page.content()` for `/accountmanager/documents` to `spike/out/documents_real.html` (git-ignored). **Manually redact** policy numbers, name, address → save as `tests/fixtures/lm/documents_real_sanitized.html`, **preserving structure** (policy cards, the empty-text `View / print` buttons, card headings/labels). This redaction is a manual PII gate — verify no real data remains before committing. (Do NOT delete the existing `documents.html`/`documents_list.html` — they back other tests.)

- [ ] **Step 2: Failing parser test** — `tests/backend/test_lm_parser.py`:
```python
from pathlib import Path
from backend.carriers.lm import parse_document_list

FIXTURE = Path("tests/fixtures/lm/documents_real_sanitized.html").read_text()

def test_parse_returns_indexed_named_docs():
    docs = parse_document_list(FIXTURE)              # list[tuple[int, str]]
    assert len(docs) >= 1
    assert [i for i, _ in docs] == list(range(len(docs)))   # 0-based, DOM order
    assert all(isinstance(n, str) and n for _, n in docs)   # every doc has a name
```

- [ ] **Step 3: Run — expect FAIL** (`parse_document_list` undefined).

- [ ] **Step 4: Implement `parse_document_list`** in `backend/carriers/lm.py` using stdlib `html.parser.HTMLParser` (no new deps — mirror `spike/carriers/liberty_mutual.py`'s `_AnchorParser`). Logic: stream the HTML tracking the most recent "card title" text (text inside `h1`–`h4`/`strong`/`th`, or elements whose `class` contains `title`/`name`/`heading`); each time a `<button>`/`<a>` whose collected text normalizes to `"view / print"` closes, emit `(running_index, last_card_title or f"Document {running_index + 1}")`. Return the list in DOM order. **Calibrate the title selectors against the sanitized fixture** so the names match the cards (declarations/renewal/welcome packet).

- [ ] **Step 5: Run — expect PASS.** Lint/type. Commit: `git commit -am "carriers/lm: pure document-list parser (TDD vs. sanitized real fixture)"`

- [ ] **Step 6: Fill `ChromiumDriver` browser methods** (port the proven logic; cite sources):
  - `open_login(url)` ← `confirm_h1.py` ~77–80 (goto, click "Log in" link, wait `input[name=username]`); if a block page shows instead, raise `BotChallengeError`.
  - `submit_credentials(u, p)` ← `confirm_h1.py` ~81–101 (fill creds, click `button[type=submit]`, poll ≤30s: `_locate_otp`/`/mfa` ⇒ `NEEDS_MFA`; "something went wrong" ⇒ `CarrierAuthError`). One submission only.
  - `submit_mfa(code)` ← `confirm_h1.py` `_locate_otp` + `press_sequentially(code, 60)` + `Enter`; poll for leaving `login.libertymutual.com` ⇒ `AUTHENTICATED`, else `MfaError`.
  - `list_documents()` ← `goto(/accountmanager/documents)`, wait `DOCUMENTS` (reuse `classify_lm_page`), `names = parse_document_list(await page.content())` → `[DocRef(doc_id=str(i), name=n) for i, n in names]`; raise `DocFetchError` if empty.
  - `fetch_document(ref)` ← **context-level popup capture** (mirror `probe_doc.py:55–78`, NOT `page.expect_response`): the PDF response fires on a **popup**, so do
    ```python
    async with self._ctx.expect_page() as pop_info:   # the View/print popup
        await self._page.locator(":is(button,a)", has_text="View / print").nth(int(ref.doc_id)).click()
    popup = await pop_info.value
    resp = await popup.wait_for_event(
        "response",
        lambda r: "/document/download/" in r.url and "application/pdf" in (r.headers.get("content-type") or ""),
    )
    content = await resp.body()
    ```
    **Fallbacks** (spec §6.5): if a `download` event fires instead, `expect_download` → read the file; if capture fails, re-`GET` `resp.url` via `self._ctx.request.get(...)` (same cookie jar + egress). Validate with `spike.docfetch.is_valid_pdf`; return `FetchedDoc(name=ref.name, content=content)`.

- [ ] **Step 7:** Lint/type (`ruff` + `mypy --strict backend/chromium_driver.py backend/carriers/lm.py`). Live methods validated in Task 7. Commit: `git commit -am "ChromiumDriver: proven LM login + MFA + context-level PDF capture"`

### Task 4: Flip `READY` after first doc + stream docs + wire driver in

**Files:** Modify `backend/sessions.py`, `backend/api.py`, `backend/browser.py` (FakeDriver multi-doc), `backend/main.py`, tests.

- [ ] **Step 1: Extend `FakeDriver` for multi-doc** (so the streaming test is real, not invented). In `backend/browser.py`, add to `__init__`: `docs: list[tuple[str, str]] | None = None`, `fetch_delay: float = 0.0` (store them). Update:
```python
    async def list_documents(self) -> list[DocRef]:
        if self._doc_fail:
            raise DocFetchError("no documents found")
        pairs = self._docs if self._docs is not None else [("doc-0", "Declarations")]
        return [DocRef(doc_id=d, name=n) for d, n in pairs]

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        if self._connection_lost_on_fetch:
            raise DocFetchError("connection lost")
        if self._fetch_delay:
            await asyncio.sleep(self._fetch_delay)
        return FetchedDoc(name=ref.name, content=_SAMPLE_PDF)
```
(Default unchanged → existing single-doc tests stay green.)

- [ ] **Step 2: Failing tests** — `tests/backend/test_manager_streaming.py` (mirror `test_manager_happy.py`'s `make_manager`/`_wait_status`):
```python
import asyncio, time
from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry

def make_manager(driver):
    reg = SessionRegistry()
    return reg, SessionManager(registry=reg, driver_factory=lambda: driver,
                               login_url="https://lm/login", clock=time.monotonic, mfa_deadline=5.0)

async def _wait_status(reg, sid, status, timeout=3.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status: return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}; is {reg.get(sid).status}")

async def test_ready_after_first_doc_then_streams():
    driver = FakeDriver(docs=[("doc-0", "A"), ("doc-1", "B"), ("doc-2", "C")], fetch_delay=0.3)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait_status(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait_status(reg, s.id, SessionStatus.READY)          # fires after doc-0
    assert "doc-0" in reg.get(s.id).documents and len(reg.get(s.id).documents) < 3  # rest still streaming
    for _ in range(200):
        if len(reg.get(s.id).documents) == 3: break
        await asyncio.sleep(0.01)
    assert {"doc-0", "doc-1", "doc-2"} == set(reg.get(s.id).documents) and driver.closed

async def test_zero_docs_fails():
    reg, mgr = make_manager(FakeDriver(docs=[]))
    s = mgr.start("u", "p")
    await _wait_status(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "123456")
    await _wait_status(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error["type"] == "DocFetchError"
```

- [ ] **Step 3: Run — expect FAIL** (READY only after the full loop; no zero-doc guard).

- [ ] **Step 4: Edit `backend/sessions.py`** — (a) add `DocFetchError` to the `backend.models` import on line 10; (b) replace the fetch block (lines ~125–134) so READY flips after the first doc:
```python
            session.status = SessionStatus.FETCHING
            refs = await driver.list_documents()
            if not refs:
                raise DocFetchError("no documents found")
            session.doc_refs = refs
            for i, ref in enumerate(refs):
                fetched = await driver.fetch_document(ref)
                session.documents[ref.doc_id] = (fetched.name, fetched.content)
                if i == 0:
                    session.latency_ms = (self._clock() - session.mfa_start) * 1000.0
                    session.status = SessionStatus.READY  # servable after the first doc
            # browser closes in `finally` after the last doc is fetched
```

- [ ] **Step 5: Edit `backend/api.py`** `GET /sessions/{id}` — stream the **fetched** docs (not all refs, not gated on READY); replace the `docs = (...)` block (lines ~28–32) with:
```python
        docs = [
            DocumentMeta(doc_id=doc_id, name=name)
            for doc_id, (name, _content) in session.documents.items()
        ] or None
```

- [ ] **Step 6: Run — expect PASS** (`uv run pytest tests/backend -q --ignore=tests/backend/test_main.py`). Add/adjust an API test asserting the documents list grows before all are fetched (optional but recommended).

- [ ] **Step 7: Wire the real driver in `backend/main.py`** — replace line 14 import and line 53 wiring:
```python
from backend.chromium_driver import make_chromium_driver_factory
# ...
        driver_factory=make_chromium_driver_factory(cfg),
```
Now run the FULL gate: `uv run ruff check . && uv run mypy --strict backend spike && uv run pytest -q`. All green. Commit: `git commit -am "sessions/api: READY after first doc + zero-doc guard + streamed docs; wire ChromiumDriver"`

---

## PART B — Container + Frontend

### Task 5: Product container (`/health`, `Dockerfile` CMD, `compose.yaml`)

**Files:** Modify `backend/api.py` (add `/health`), `Dockerfile`; Create `compose.yaml`.

- [ ] **Step 1: Add a `/health` route** (failing API test first): `GET /health → 200 {"status":"ok"}`. Implement in `backend/api.py` (or `main.py`). Run the test — PASS.

- [ ] **Step 2: Change the `Dockerfile` `CMD`** to run the API via the app **factory** (avoids import-time `load_config`, so test collection still works):
```dockerfile
CMD ["uv", "run", "uvicorn", "--factory", "backend.main:build_production_app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Write `compose.yaml`**
```yaml
services:
  backend:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    shm_size: "1g"
```

- [ ] **Step 4: Smoke-test** — `docker compose up --build -d`, then `curl -s localhost:8000/health` ⇒ `{"status":"ok"}`. `docker compose down`. Commit: `git commit -am "container: /health + product CMD (uvicorn --factory) + compose"`

### Task 6: Frontend SPA

**Files:** Create `frontend/` (Vite React TS): api client, components, polling, react-pdf; light Vitest tests.

- [ ] **Step 1: Scaffold + pin deps**
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install react-pdf
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom eslint
```
Commit `package-lock.json` (pinned).

- [ ] **Step 2: `src/api.ts`** — typed client: `createSession`, `getStatus`, `submitMfa(code)`, `documentUrl(sessionId, docId)`; base URL from `import.meta.env.VITE_API_URL`.

- [ ] **Step 3: `src/usePolling.ts`** + failing test — polls `getStatus` every 700 ms, stops on `READY`/`FAILED`. Vitest + fake timers asserts it stops on terminal status.

- [ ] **Step 4: Components** (each with a light render-gate test):
  - `CarrierSelect` (LM enabled; Geico disabled/"coming").
  - `CredentialForm` (username + masked password → `createSession`).
  - `MfaPrompt` — **renders only at `AWAITING_MFA`** → `submitMfa`. Test: not rendered otherwise.
  - `DocumentViewer` — **renders only at `READY`**; iterates the **growing** `documents` list (don't guess doc ids — render what the status returns), react-pdf over `documentUrl`, download button; `onRenderSuccess` of the first doc records **primary latency** (now − stored MFA-submit ts). Test: not rendered before READY.
  - `App.tsx` — status → component; stores the MFA-submit timestamp on submit.

- [ ] **Step 5:** `npm run test && npx tsc --noEmit && npm run lint && npm run build`. Commit: `git commit -am "frontend: LM flow SPA + polling + first-doc latency mark"`

### Task 7: Live in-container UI run (full-UX re-proof + latency)

**(Datacenter risk already retired at M0; this is the end-to-end UX + metric capture.)**

- [ ] **Step 1:** `docker compose up --build` (or the VM image); serve the frontend (`VITE_API_URL` → backend).
- [ ] **Step 2:** Through the UI: LM → creds → MFA → render. Capture **primary** latency (`onRenderSuccess` − MFA-submit) + **server** `latency_ms`, a screenshot, and a sample rendered PDF.
- [ ] **Step 3:** Record both numbers vs. the 8s target (honest, direct egress). **Go/no-go** for the residential-proxy increment (§13) and Geico.
- [ ] **Step 4: Commit** the results note, then run `superpowers:finishing-a-development-branch`.

---

## Self-review notes
- **Spec coverage:** M0 (datacenter gate), Tasks 1–4 (cleanup/config/driver/flow/READY-I3/streaming), 5 (container/parity/health), 6 (SPA/latency mark), 7 (re-proof) cover spec §1–§20. Session reuse + proxy + Geico explicitly deferred (§3/§13).
- **Review fixes applied:** delete Browserbase modules before the config change (mypy); pin `playwright==1.60.0`; `DocFetchError` imported in `sessions.py`; `READY`-after-first-doc edit matched to real lines; `GET /sessions/{id}` streams from `session.documents`; FakeDriver gains multi-doc mode (no invented `ThreeDocDriver`); `fetch_document` uses **context-level popup** capture (not `page.expect_response`); `uvicorn --factory` (no module-level `app`); `/health` added; old fixtures kept.
- **No fabricated APIs:** browser steps cite `confirm_h1.py`/`probe_doc.py`; the parser is pinned to a real captured fixture; tests mirror `test_manager_happy.py`'s `make_manager`/`_wait_status`.
- **Manual gate:** the sanitized fixture (Task 3 step 1) is hand-redacted — verify no PII before committing.

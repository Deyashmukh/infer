# Minimal LM Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A minimal human-in-the-loop web app — pick Liberty Mutual, enter credentials + MFA in a React UI, an async FastAPI backend drives a hosted Browserbase browser, and policy PDFs render in the browser. The first real run is the go/no-go access gate.

**Architecture:** Architecture A — `POST /sessions` launches a background asyncio task that drives async Playwright until MFA, parks on a bounded code-queue wait, then fetches docs; the frontend polls for status. Session state is in-memory/single-process. A `BrowserDriver` Protocol seam lets a `FakeDriver` exercise the entire orchestration offline; the real `BrowserbaseDriver` is validated live.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, async Playwright over CDP to Browserbase; pytest + pytest-asyncio + httpx; React + TypeScript + Vite + react-pdf; reuses the Phase A `spike/` core.

**Spec:** `docs/superpowers/specs/2026-06-16-minimal-lm-webapp-design.md`

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock` | add fastapi/uvicorn + dev pytest-asyncio/httpx; `asyncio_mode=auto` | 0 |
| `spike/config.py` | drop carrier-cred fields/reads | 1 |
| `backend/__init__.py` | package marker | 0 |
| `backend/models.py` | error taxonomy + Pydantic request/response models | 2 |
| `backend/browser.py` | `BrowserDriver` Protocol, `AuthStep`, `FetchedDoc`; `FakeDriver` (tests import it) | 3 |
| `backend/sessions.py` | `Session`, `SessionRegistry`, `SessionManager` (state machine, bounded MFA wait, cleanup, sweeper) | 4–7 |
| `backend/api.py` | the 4 route handlers + error→HTTP mapping | 8 |
| `backend/main.py` | FastAPI app, CORS, lifespan sweeper | 9 |
| `backend/carriers/lm.py` | live async LM nav (selectors calibrated live) | 11 |
| `backend/browserbase_driver.py` | real `BrowserbaseDriver` (async Playwright/CDP) | 11 |
| `frontend/` | Vite React TS SPA (api client, components, polling, react-pdf) | 12–13 |
| `tests/backend/...` | offline unit/API tests | 2–9 |

**Reused from `spike/`:** `challenge`, `carriers/liberty_mutual` (pure classify + discovery), `timing.Timer`, `browserbase.build_session_params`, `docfetch`.

---

## PART 1 — Backend (offline, TDD — no Browserbase, no creds)

### Task 0: Add async dependencies

**Files:** Modify `pyproject.toml`, `uv.lock`; Create `backend/__init__.py`, `backend/carriers/__init__.py`, `tests/backend/__init__.py`.

- [ ] **Step 1: Add deps**

Run:
```bash
uv add fastapi uvicorn
uv add --dev pytest-asyncio httpx
```

- [ ] **Step 2: Enable asyncio test mode**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add the `asyncio_mode` line so it reads:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create package markers** — empty files: `backend/__init__.py`, `backend/carriers/__init__.py`, `tests/backend/__init__.py`.

- [ ] **Step 4: Verify + commit**

```bash
uv run ruff check . && uv run mypy spike && uv run pytest -q
git add pyproject.toml uv.lock backend tests
git commit -m "chore: add fastapi/uvicorn + async test deps; backend package skeleton"
```
Expected: existing 33 tests still pass.

---

### Task 1: Drop carrier creds from `spike/config.py`

**Files:** Modify `spike/config.py`, `tests/test_config.py`, `.env.example`.

- [ ] **Step 1: Update the test first** — replace the body of `tests/test_config.py` with:

```python
import pytest
from spike.config import Config, ConfigError, load_config

BASE = {
    "BROWSERBASE_API_KEY": "bb_live_x",
    "BROWSERBASE_PROJECT_ID": "proj_1",
    "LM_LOGIN_URL": "https://www.libertymutual.com/log-in",
}


def test_load_config_returns_typed_config():
    cfg = load_config(BASE)
    assert isinstance(cfg, Config)
    assert cfg.browserbase_project_id == "proj_1"
    assert cfg.lm_login_url.endswith("/log-in")
    assert cfg.browserbase_context_id is None


def test_load_config_reads_optional_context_id():
    cfg = load_config({**BASE, "BROWSERBASE_CONTEXT_ID": "ctx_9"})
    assert cfg.browserbase_context_id == "ctx_9"


def test_missing_required_key_raises_with_key_name():
    broken = {k: v for k, v in BASE.items() if k != "BROWSERBASE_PROJECT_ID"}
    with pytest.raises(ConfigError) as exc:
        load_config(broken)
    assert "BROWSERBASE_PROJECT_ID" in str(exc.value)


def test_no_carrier_cred_fields_on_config():
    cfg = load_config(BASE)
    assert not hasattr(cfg, "lm_username")
    assert not hasattr(cfg, "lm_password")
```

- [ ] **Step 2: Run, verify FAILS** — `uv run pytest tests/test_config.py -v` fails (old `Config` still has `lm_username`/`lm_password`; `test_no_carrier_cred_fields_on_config` fails, and the old required-key test referenced a removed key).

- [ ] **Step 3: Update `spike/config.py`** to:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED = (
    "BROWSERBASE_API_KEY",
    "BROWSERBASE_PROJECT_ID",
    "LM_LOGIN_URL",
)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    browserbase_api_key: str
    browserbase_project_id: str
    lm_login_url: str
    browserbase_context_id: str | None


def load_config(env: Mapping[str, str]) -> Config:
    missing = [k for k in _REQUIRED if not env.get(k)]
    if missing:
        raise ConfigError(f"Missing required config: {', '.join(missing)}")
    context_id = env.get("BROWSERBASE_CONTEXT_ID") or None
    return Config(
        browserbase_api_key=env["BROWSERBASE_API_KEY"],
        browserbase_project_id=env["BROWSERBASE_PROJECT_ID"],
        lm_login_url=env["LM_LOGIN_URL"],
        browserbase_context_id=context_id,
    )
```

- [ ] **Step 4: Update `.env.example`** — remove the `LM_USERNAME` / `LM_PASSWORD` lines (creds are entered in the UI now; keep the Browserbase keys, `BROWSERBASE_CONTEXT_ID`, and `LM_LOGIN_URL`).

- [ ] **Step 5: Run, verify PASSES; full gate; commit**

```bash
uv run pytest tests/test_config.py -v          # 4 passed
uv run ruff check . && uv run mypy spike && uv run pytest -q
git add spike/config.py tests/test_config.py .env.example
git commit -m "refactor(config): carrier creds are runtime UI input, not env config"
```

---

### Task 2: Error taxonomy + Pydantic models

**Files:** Create `backend/models.py`, `tests/backend/test_models.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_models.py`:

```python
import pytest
from backend.models import (
    BotChallengeError,
    CarrierAuthError,
    CarrierError,
    CreateSessionRequest,
    DocFetchError,
    ErrorInfo,
    MfaError,
    MfaRequest,
    SessionExpiredError,
    SessionStatus,
)


def test_error_hierarchy():
    for exc in (BotChallengeError, CarrierAuthError, MfaError, DocFetchError, SessionExpiredError):
        assert issubclass(exc, CarrierError)


def test_bot_challenge_carries_fields():
    err = BotChallengeError("blocked", fields={"kind": "AKAMAI_ACCESS_DENIED"})
    assert err.fields["kind"] == "AKAMAI_ACCESS_DENIED"


def test_error_info_from_exception_uses_class_name():
    info = ErrorInfo.from_exception(CarrierAuthError("bad creds"))
    assert info.type == "CarrierAuthError"
    assert info.message == "bad creds"


def test_error_info_includes_fields_for_bot_challenge():
    info = ErrorInfo.from_exception(BotChallengeError("blocked", fields={"kind": "CAPTCHA"}))
    assert info.fields == {"kind": "CAPTCHA"}


def test_create_session_request_requires_known_carrier():
    req = CreateSessionRequest(carrier="liberty_mutual", username="u", password="p")
    assert req.carrier == "liberty_mutual"
    with pytest.raises(ValueError):
        CreateSessionRequest(carrier="acme_insurance", username="u", password="p")


def test_mfa_request_requires_nonempty_code():
    assert MfaRequest(code="123456").code == "123456"
    with pytest.raises(ValueError):
        MfaRequest(code="")


def test_session_status_values():
    assert {s.value for s in SessionStatus} == {
        "STARTING", "AWAITING_MFA", "VERIFYING_MFA", "FETCHING", "READY", "FAILED",
    }
```

- [ ] **Step 2: Run, verify FAILS** — `uv run pytest tests/backend/test_models.py -v` → `ModuleNotFoundError: No module named 'backend.models'`.

- [ ] **Step 3: Implement** `backend/models.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, field_validator


class CarrierError(Exception):
    """Base for carrier-flow errors."""


class BotChallengeError(CarrierError):
    def __init__(self, message: str, *, fields: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or {}


class CarrierAuthError(CarrierError):
    """Credentials rejected."""


class MfaError(CarrierError):
    """MFA code rejected."""


class DocFetchError(CarrierError):
    """Document discovery/fetch failed."""


class SessionExpiredError(CarrierError):
    """MFA deadline elapsed, TTL sweep, or task cancelled."""


class SessionStatus(StrEnum):
    STARTING = "STARTING"
    AWAITING_MFA = "AWAITING_MFA"
    VERIFYING_MFA = "VERIFYING_MFA"
    FETCHING = "FETCHING"
    READY = "READY"
    FAILED = "FAILED"


class ErrorInfo(BaseModel):
    type: str
    message: str
    fields: dict[str, object] | None = None

    @classmethod
    def from_exception(cls, exc: Exception) -> "ErrorInfo":
        fields = getattr(exc, "fields", None) or None
        return cls(type=type(exc).__name__, message=str(exc), fields=fields)


class CreateSessionRequest(BaseModel):
    carrier: Literal["liberty_mutual"]
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v


class MfaRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("code must not be empty")
        return v


class DocumentMeta(BaseModel):
    doc_id: str
    name: str


class SessionStatusResponse(BaseModel):
    session_id: str
    status: SessionStatus
    mfa_required: bool
    documents: list[DocumentMeta] | None = None
    error: ErrorInfo | None = None
    latency_ms: float | None = None
```

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_models.py -v` (7 passed).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/models.py tests/backend/test_models.py
git commit -m "feat(backend): error taxonomy + request/response models"
```

---

### Task 3: BrowserDriver Protocol + FakeDriver

**Files:** Create `backend/browser.py`, `tests/backend/test_fake_driver.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_fake_driver.py`:

```python
import pytest
from backend.browser import AuthStep, FakeDriver, FetchedDoc
from backend.models import BotChallengeError, CarrierAuthError, DocFetchError, MfaError


async def test_happy_path_flow():
    d = FakeDriver()
    await d.open_login("https://lm/login")
    assert await d.submit_credentials("u", "p") is AuthStep.NEEDS_MFA
    assert await d.submit_mfa("123456") is AuthStep.AUTHENTICATED
    docs = await d.list_documents()
    assert docs and docs[0].name
    blob = await d.fetch_document(docs[0])
    assert isinstance(blob, FetchedDoc) and blob.content.startswith(b"%PDF-")
    await d.close()
    assert d.closed is True


async def test_bot_block_on_open():
    d = FakeDriver(bot_block=True)
    with pytest.raises(BotChallengeError) as exc:
        await d.open_login("https://lm/login")
    assert exc.value.fields  # structured fields present


async def test_auth_failure():
    d = FakeDriver(auth_fail=True)
    await d.open_login("https://lm/login")
    with pytest.raises(CarrierAuthError):
        await d.submit_credentials("u", "p")


async def test_mfa_failure_then_success():
    d = FakeDriver(mfa_fail_times=1)
    await d.open_login("x")
    await d.submit_credentials("u", "p")
    with pytest.raises(MfaError):
        await d.submit_mfa("000000")
    assert await d.submit_mfa("123456") is AuthStep.AUTHENTICATED


async def test_doc_fetch_failure():
    d = FakeDriver(doc_fail=True)
    await d.open_login("x")
    await d.submit_credentials("u", "p")
    await d.submit_mfa("123456")
    with pytest.raises(DocFetchError):
        await d.list_documents()


async def test_hang_step_is_awaitable_for_timeout_tests():
    import asyncio
    d = FakeDriver(hang_on_mfa=True)
    await d.open_login("x")
    await d.submit_credentials("u", "p")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(d.submit_mfa("123456"), timeout=0.05)


async def test_close_is_idempotent():
    d = FakeDriver()
    await d.close()
    await d.close()
    assert d.closed is True
```

- [ ] **Step 2: Run, verify FAILS** — `ModuleNotFoundError: No module named 'backend.browser'`.

- [ ] **Step 3: Implement** `backend/browser.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from backend.models import (
    BotChallengeError,
    CarrierAuthError,
    DocFetchError,
    MfaError,
)


class AuthStep(StrEnum):
    NEEDS_MFA = "NEEDS_MFA"
    AUTHENTICATED = "AUTHENTICATED"


@dataclass(frozen=True)
class DocRef:
    doc_id: str
    name: str
    url: str


@dataclass(frozen=True)
class FetchedDoc:
    name: str
    content: bytes


class BrowserDriver(Protocol):
    async def open_login(self, login_url: str) -> None: ...
    async def submit_credentials(self, username: str, password: str) -> AuthStep: ...
    async def submit_mfa(self, code: str) -> AuthStep: ...
    async def list_documents(self) -> list[DocRef]: ...
    async def fetch_document(self, ref: DocRef) -> FetchedDoc: ...
    async def close(self) -> None: ...


_SAMPLE_PDF = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"


class FakeDriver:
    """In-memory driver for deterministic offline orchestration tests."""

    def __init__(
        self,
        *,
        bot_block: bool = False,
        auth_fail: bool = False,
        mfa_fail_times: int = 0,
        doc_fail: bool = False,
        hang_on_mfa: bool = False,
        cancel_on_mfa: bool = False,
        connection_lost_on_fetch: bool = False,
    ) -> None:
        self._bot_block = bot_block
        self._auth_fail = auth_fail
        self._mfa_fail_remaining = mfa_fail_times
        self._doc_fail = doc_fail
        self._hang_on_mfa = hang_on_mfa
        self._cancel_on_mfa = cancel_on_mfa
        self._connection_lost_on_fetch = connection_lost_on_fetch
        self.closed = False

    async def open_login(self, login_url: str) -> None:
        if self._bot_block:
            raise BotChallengeError("access denied", fields={"kind": "AKAMAI_ACCESS_DENIED", "status": 403})

    async def submit_credentials(self, username: str, password: str) -> AuthStep:
        if self._auth_fail:
            raise CarrierAuthError("credentials rejected")
        return AuthStep.NEEDS_MFA

    async def submit_mfa(self, code: str) -> AuthStep:
        if self._hang_on_mfa:
            await asyncio.sleep(3600)
        if self._cancel_on_mfa:
            raise asyncio.CancelledError()
        if self._mfa_fail_remaining > 0:
            self._mfa_fail_remaining -= 1
            raise MfaError("code rejected")
        return AuthStep.AUTHENTICATED

    async def list_documents(self) -> list[DocRef]:
        if self._doc_fail:
            raise DocFetchError("no documents found")
        return [DocRef(doc_id="doc-0", name="Declarations", url="https://lm/docs/dec.pdf")]

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        if self._connection_lost_on_fetch:
            raise DocFetchError("connection lost")
        return FetchedDoc(name=ref.name, content=_SAMPLE_PDF)

    async def close(self) -> None:
        self.closed = True
```

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_fake_driver.py -v` (7 passed).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/browser.py tests/backend/test_fake_driver.py
git commit -m "feat(backend): BrowserDriver protocol + FakeDriver with failure-mode scenarios"
```

---

### Task 4: Session + SessionRegistry

**Files:** Create `backend/sessions.py`, `tests/backend/test_registry.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_registry.py`:

```python
from backend.models import SessionStatus
from backend.sessions import Session, SessionRegistry


def test_registry_create_and_get():
    reg = SessionRegistry()
    s = reg.create()
    assert isinstance(s, Session)
    assert reg.get(s.id) is s
    assert s.status is SessionStatus.STARTING


def test_registry_get_unknown_returns_none():
    assert SessionRegistry().get("nope") is None


def test_registry_ids_are_unique():
    reg = SessionRegistry()
    ids = {reg.create().id for _ in range(50)}
    assert len(ids) == 50


def test_session_stores_documents_bytes():
    reg = SessionRegistry()
    s = reg.create()
    s.documents["doc-0"] = ("Declarations", b"%PDF-1.7 ...")
    name, content = s.documents["doc-0"]
    assert name == "Declarations" and content.startswith(b"%PDF")
```

- [ ] **Step 2: Run, verify FAILS** — `ModuleNotFoundError: No module named 'backend.sessions'`.

- [ ] **Step 3: Implement** `backend/sessions.py` (registry + Session only; manager added in Task 5):

```python
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from backend.browser import DocRef
from backend.models import ErrorInfo, SessionStatus


@dataclass
class Session:
    id: str
    status: SessionStatus = SessionStatus.STARTING
    mfa_codes: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    mfa_attempts: int = 0
    doc_refs: list[DocRef] = field(default_factory=list)
    documents: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # doc_id -> (name, bytes)
    error: ErrorInfo | None = None
    latency_ms: float | None = None
    task: asyncio.Task[None] | None = None
    created_monotonic: float = 0.0
    mfa_start: float = 0.0  # set on the /mfa request path (Task 6); used for latency

# Single-flight on MFA is enforced by a synchronous status flip to VERIFYING_MFA in
# the /mfa handler (event-loop-atomic — no await between the 409 check and the flip),
# so a concurrent duplicate POST gets 409. No asyncio.Lock is needed.


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        sid = uuid.uuid4().hex
        session = Session(id=sid)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def all(self) -> list[Session]:
        return list(self._sessions.values())
```

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_registry.py -v` (4 passed).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/sessions.py tests/backend/test_registry.py
git commit -m "feat(backend): Session + in-memory SessionRegistry"
```

---

### Task 5: SessionManager happy path (STARTING → AWAITING_MFA → FETCHING → READY)

**Files:** Modify `backend/sessions.py`; Create `tests/backend/test_manager_happy.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_manager_happy.py`:

```python
import asyncio
import time

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry


def make_manager(driver):
    reg = SessionRegistry()
    return reg, SessionManager(
        registry=reg,
        driver_factory=lambda: driver,
        login_url="https://lm/login",
        clock=time.monotonic,   # real clock; exact latency calc is covered by spike.timing tests
        mfa_deadline=5.0,
    )


async def _wait_status(reg, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"status never became {status}; is {reg.get(sid).status}")


async def test_reaches_awaiting_mfa_then_ready():
    driver = FakeDriver()
    reg, mgr = make_manager(driver)
    session = mgr.start("u", "p")
    await _wait_status(reg, session.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(session.id, "123456")
    await _wait_status(reg, session.id, SessionStatus.READY)
    s = reg.get(session.id)
    assert s.doc_refs and "doc-0" in s.documents
    assert s.latency_ms is not None and s.latency_ms >= 0.0  # MFA-submit -> first doc (ms)
    assert driver.closed is True  # cleanup ran on success
```

- [ ] **Step 2: Run, verify FAILS** — `ImportError: cannot import name 'SessionManager'`.

- [ ] **Step 3: Add `SessionManager` to `backend/sessions.py`** (append; imports go at top):

```python
from collections.abc import Callable

from backend.browser import AuthStep, BrowserDriver


class SessionManager:
    def __init__(
        self,
        registry: SessionRegistry,
        driver_factory: Callable[[], BrowserDriver],
        login_url: str,
        clock: Callable[[], float],
        mfa_deadline: float = 120.0,
        max_mfa_attempts: int = 3,
    ) -> None:
        self._registry = registry
        self._driver_factory = driver_factory
        self._login_url = login_url
        self._clock = clock
        self._mfa_deadline = mfa_deadline
        self._max_mfa_attempts = max_mfa_attempts

    def start(self, username: str, password: str) -> Session:
        session = self._registry.create()
        session.created_monotonic = self._clock()
        session.task = asyncio.create_task(self._run(session, username, password))
        return session

    def submit_mfa(self, session_id: str, code: str) -> None:
        session = self._registry.get(session_id)
        if session is not None:
            session.mfa_codes.put_nowait(code)

    async def _run(self, session: Session, username: str, password: str) -> None:
        driver = self._driver_factory()
        try:
            await driver.open_login(self._login_url)
            step = await driver.submit_credentials(username, password)
            while step is AuthStep.NEEDS_MFA:
                session.status = SessionStatus.AWAITING_MFA
                code = await asyncio.wait_for(session.mfa_codes.get(), timeout=self._mfa_deadline)
                session.status = SessionStatus.VERIFYING_MFA
                if session.mfa_start == 0.0:        # Task 6 moves this to the /mfa request path
                    session.mfa_start = self._clock()
                session.mfa_attempts += 1
                try:
                    step = await driver.submit_mfa(code)
                except MfaError:
                    if session.mfa_attempts >= self._max_mfa_attempts:
                        raise
                    step = AuthStep.NEEDS_MFA
            session.status = SessionStatus.FETCHING
            refs = await driver.list_documents()
            session.doc_refs = refs
            for i, ref in enumerate(refs):                  # fetch ALL discovered docs (browser closes at READY)
                fetched = await driver.fetch_document(ref)
                session.documents[ref.doc_id] = (fetched.name, fetched.content)
                if i == 0:                                  # latency tied to the FIRST doc (spec §11)
                    session.latency_ms = (self._clock() - session.mfa_start) * 1000.0
            session.status = SessionStatus.READY
        except CarrierError as exc:
            session.error = ErrorInfo.from_exception(exc)
            session.status = SessionStatus.FAILED
        finally:
            await driver.close()
```

Add the needed imports at the top of `backend/sessions.py`:
```python
from backend.models import (
    CarrierError,
    ErrorInfo,
    MfaError,
    SessionStatus,
)
```
(The `mfa_start` field was already added to `Session` in Task 4.)

> Note: `latency_ms` is computed from `session.mfa_start`. In this happy-path test the manager sets `mfa_start` at `VERIFYING_MFA` entry; Task 6 makes the **request-path** timing (set when the code is POSTed) authoritative. Either way the test asserts only `latency_ms >= 0` with a real clock — the exact `(stop-start)*1000` calc is already proven by the `spike.timing.Timer` unit tests.

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_manager_happy.py -v` (1 passed).

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/sessions.py tests/backend/test_manager_happy.py
git commit -m "feat(backend): SessionManager happy-path orchestration"
```

---

### Task 6: Request-path MFA timing + MFA retry cap

**Files:** Modify `backend/sessions.py`; Create `tests/backend/test_manager_mfa.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_manager_mfa.py`:

```python
import asyncio
import time

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry


def make_manager(driver):
    reg = SessionRegistry()
    return reg, SessionManager(
        registry=reg, driver_factory=lambda: driver, login_url="x",
        clock=time.monotonic, mfa_deadline=5.0,
    )


async def _wait(reg, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}; is {reg.get(sid).status}")


async def test_mfa_retry_then_success_caps_attempts():
    driver = FakeDriver(mfa_fail_times=2)  # 2 rejects, 3rd accepted
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    mgr.submit_mfa(s.id, "bad1")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)   # back to awaiting after reject 1
    mgr.submit_mfa(s.id, "bad2")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)   # reject 2
    mgr.submit_mfa(s.id, "123456")
    await _wait(reg, s.id, SessionStatus.READY)
    assert reg.get(s.id).mfa_attempts == 3


async def test_mfa_exhausts_cap_then_fails():
    driver = FakeDriver(mfa_fail_times=99)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    for code in ("a", "b", "c"):
        mgr.submit_mfa(s.id, code)
        await asyncio.sleep(0.02)
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "MfaError"
    assert driver.closed is True
```

- [ ] **Step 2: Run, verify FAILS** — the cap behavior / `_mfa_start` timing isn't authoritative yet (e.g. `mfa_attempts` count or FAILED-after-3 differs).

- [ ] **Step 3: Make request-path timing authoritative.** Set `mfa_start` when the *first* code is POSTed, so timing starts at the user's action rather than when the task happens to resume. Update `submit_mfa` in `backend/sessions.py`:

```python
    def submit_mfa(self, session_id: str, code: str) -> None:
        session = self._registry.get(session_id)
        if session is not None:
            if session.mfa_start == 0.0:
                session.mfa_start = self._clock()
            session.mfa_codes.put_nowait(code)
```
The `_run` guard added in Task 5 (`if session.mfa_start == 0.0: session.mfa_start = self._clock()`) now coexists harmlessly: the request path sets `mfa_start` first, so `_run`'s guard sees a non-zero value and skips. Keep the `mfa_attempts += 1` and the `MfaError` retry/cap logic unchanged.

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_manager_mfa.py tests/backend/test_manager_happy.py -v` (3 passed). Both use the real `time.monotonic` clock and assert `latency_ms >= 0` / attempt counts, so no tick-counting is involved.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/sessions.py tests/backend/test_manager_mfa.py tests/backend/test_manager_happy.py
git commit -m "feat(backend): request-path MFA timing + retry cap"
```

---

### Task 7: Failure paths, MFA-deadline timeout, cancellation cleanup, TTL sweeper

**Files:** Modify `backend/sessions.py`; Create `tests/backend/test_manager_failures.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_manager_failures.py`:

```python
import asyncio

from backend.browser import FakeDriver
from backend.models import SessionStatus
from backend.sessions import SessionManager, SessionRegistry


def make_manager(driver, mfa_deadline=5.0):
    reg = SessionRegistry()
    return reg, SessionManager(
        registry=reg, driver_factory=lambda: driver, login_url="x",
        clock=lambda: 0.0, mfa_deadline=mfa_deadline,
    )


async def _wait(reg, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        if reg.get(sid).status is status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}; is {reg.get(sid).status}")


async def test_bot_block_fails_with_fields_and_closes():
    driver = FakeDriver(bot_block=True)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "BotChallengeError"
    assert reg.get(s.id).error.fields["kind"] == "AKAMAI_ACCESS_DENIED"
    assert driver.closed is True


async def test_auth_fail_closes_driver():
    driver = FakeDriver(auth_fail=True)
    reg, mgr = make_manager(driver)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.FAILED)
    assert reg.get(s.id).error.type == "CarrierAuthError"
    assert driver.closed is True


async def test_mfa_deadline_times_out_and_closes():
    driver = FakeDriver()
    reg, mgr = make_manager(driver, mfa_deadline=0.05)  # never submit a code
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.FAILED, timeout=2.0)
    assert reg.get(s.id).error.type == "SessionExpiredError"
    assert driver.closed is True


async def test_sweeper_cancels_and_closes():
    driver = FakeDriver()
    reg, mgr = make_manager(driver, mfa_deadline=999.0)
    s = mgr.start("u", "p")
    await _wait(reg, s.id, SessionStatus.AWAITING_MFA)
    await mgr.sweep(now=10_000.0, ttl=0.0)  # everything older than ttl=0 is swept
    await asyncio.sleep(0.02)
    assert driver.closed is True
    assert reg.get(s.id) is None
```

- [ ] **Step 2: Run, verify FAILS** — `asyncio.TimeoutError` from `wait_for` isn't mapped to `SessionExpiredError` yet, and `sweep` doesn't exist.

- [ ] **Step 3: Update `backend/sessions.py`.** In `_run`, wrap the `wait_for` timeout and ensure cancellation closes the driver. Replace the `except CarrierError` block and `finally`, and add the timeout/cancel handling + a `sweep` method + record `created_monotonic` at start:

```python
        # inside _run, the try body's wait_for line stays:
        #     code = await asyncio.wait_for(session.mfa_codes.get(), timeout=self._mfa_deadline)
        # replace the exception handling tail of _run with:
        except TimeoutError:
            session.error = ErrorInfo.from_exception(SessionExpiredError("MFA deadline elapsed"))
            session.status = SessionStatus.FAILED
        except asyncio.CancelledError:
            session.error = ErrorInfo.from_exception(SessionExpiredError("session cancelled"))
            session.status = SessionStatus.FAILED
            raise
        except CarrierError as exc:
            session.error = ErrorInfo.from_exception(exc)
            session.status = SessionStatus.FAILED
        finally:
            await driver.close()
```
Set `session.created_monotonic = self._clock()` at the top of `start` (before creating the task — actually set it on the returned session right after `self._registry.create()`). Add the sweeper:
```python
    async def sweep(self, now: float, ttl: float) -> None:
        for session in self._registry.all():
            if now - session.created_monotonic >= ttl:
                if session.task is not None and not session.task.done():
                    session.task.cancel()
                    try:
                        await session.task
                    except (asyncio.CancelledError, Exception):
                        pass
                self._registry.remove(session.id)
```
> `asyncio.wait_for` raises `asyncio.TimeoutError`, which is an alias of the builtin `TimeoutError` on Python 3.11+ — catching `TimeoutError` is correct and mypy-clean. The `CancelledError` handler re-raises (never swallow cancellation) but still closes the driver via `finally`.

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_manager_failures.py -v` (4 passed). Run the whole suite: `uv run pytest -q`.

- [ ] **Step 5: Full gate + commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/sessions.py tests/backend/test_manager_failures.py
git commit -m "feat(backend): failure paths, MFA-deadline timeout, cancellation cleanup, TTL sweeper"
```

---

### Task 8: API routes (TestClient + FakeDriver)

**Files:** Create `backend/api.py`, `backend/deps.py`, `tests/backend/test_api.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_api.py`:

```python
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from backend.browser import FakeDriver
from backend.main import build_app
from backend.sessions import SessionManager, SessionRegistry


def client_for(driver):
    reg = SessionRegistry()
    mgr = SessionManager(
        registry=reg, driver_factory=lambda: driver, login_url="https://lm/login",
        clock=lambda: 0.0, mfa_deadline=5.0,
    )
    app = build_app(manager=mgr, registry=reg)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), reg


async def _poll(c, sid, status, timeout=1.0):
    for _ in range(int(timeout / 0.01)):
        r = await c.get(f"/sessions/{sid}")
        if r.json()["status"] == status:
            return r.json()
        await asyncio.sleep(0.01)
    raise AssertionError(f"never {status}")


async def test_full_flow_over_http():
    c, _ = client_for(FakeDriver())
    async with c:
        r = await c.post("/sessions", json={"carrier": "liberty_mutual", "username": "u", "password": "p"})
        assert r.status_code == 201
        sid = r.json()["session_id"]
        body = await _poll(c, sid, "AWAITING_MFA")
        assert body["mfa_required"] is True
        r = await c.post(f"/sessions/{sid}/mfa", json={"code": "123456"})
        assert r.status_code == 200
        ready = await _poll(c, sid, "READY")
        assert ready["documents"][0]["doc_id"] == "doc-0"
        doc = await c.get(f"/sessions/{sid}/documents/doc-0")
        assert doc.status_code == 200
        assert doc.headers["content-type"] == "application/pdf"
        assert doc.content.startswith(b"%PDF-")


async def test_mfa_rejected_when_not_awaiting():
    c, _ = client_for(FakeDriver())
    async with c:
        r = await c.post("/sessions", json={"carrier": "liberty_mutual", "username": "u", "password": "p"})
        sid = r.json()["session_id"]
        # Immediately POST mfa before AWAITING_MFA may yield 409; after READY definitely 409.
        await _poll(c, sid, "AWAITING_MFA")
        await c.post(f"/sessions/{sid}/mfa", json={"code": "123456"})
        await _poll(c, sid, "READY")
        late = await c.post(f"/sessions/{sid}/mfa", json={"code": "999999"})
        assert late.status_code == 409


async def test_bot_block_surfaces_typed_error():
    c, _ = client_for(FakeDriver(bot_block=True))
    async with c:
        r = await c.post("/sessions", json={"carrier": "liberty_mutual", "username": "u", "password": "p"})
        sid = r.json()["session_id"]
        body = await _poll(c, sid, "FAILED")
        assert body["error"]["type"] == "BotChallengeError"
        assert body["error"]["fields"]["kind"] == "AKAMAI_ACCESS_DENIED"


async def test_unknown_session_404():
    c, _ = client_for(FakeDriver())
    async with c:
        assert (await c.get("/sessions/nope")).status_code == 404


async def test_unknown_carrier_422():
    c, _ = client_for(FakeDriver())
    async with c:
        r = await c.post("/sessions", json={"carrier": "acme", "username": "u", "password": "p"})
        assert r.status_code == 422
```

- [ ] **Step 2: Run, verify FAILS** — `ModuleNotFoundError: No module named 'backend.api'` / `backend.main`.

- [ ] **Step 3: Implement** `backend/api.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from backend.models import (
    CreateSessionRequest,
    DocumentMeta,
    MfaRequest,
    SessionStatus,
    SessionStatusResponse,
)
from backend.sessions import SessionManager, SessionRegistry


def build_router(manager: SessionManager, registry: SessionRegistry) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions", status_code=201)
    async def create_session(req: CreateSessionRequest) -> dict[str, str]:
        session = manager.start(req.username, req.password)
        return {"session_id": session.id, "status": session.status.value}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> SessionStatusResponse:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        docs = (
            [DocumentMeta(doc_id=r.doc_id, name=r.name) for r in session.doc_refs]
            if session.status is SessionStatus.READY
            else None
        )
        return SessionStatusResponse(
            session_id=session.id,
            status=session.status,
            mfa_required=session.status is SessionStatus.AWAITING_MFA,
            documents=docs,
            error=session.error,
            latency_ms=session.latency_ms,
        )

    @router.post("/sessions/{session_id}/mfa")
    async def submit_mfa(session_id: str, req: MfaRequest) -> dict[str, str]:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        if session.status is not SessionStatus.AWAITING_MFA:
            raise HTTPException(status_code=409, detail=f"not awaiting MFA (status={session.status.value})")
        # Synchronous, event-loop-atomic flip (no await before it): a concurrent
        # duplicate POST now sees VERIFYING_MFA and gets 409 — single-flight without a Lock.
        session.status = SessionStatus.VERIFYING_MFA
        manager.submit_mfa(session_id, req.code)
        return {"session_id": session_id, "status": session.status.value}

    @router.get("/sessions/{session_id}/documents/{doc_id}")
    async def get_document(session_id: str, doc_id: str, download: int = 0) -> Response:
        session = registry.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown session")
        if session.status is not SessionStatus.READY:
            raise HTTPException(status_code=409, detail="session not READY")
        entry = await manager.get_document_bytes(session_id, doc_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown document")
        name, content = entry
        disposition = "attachment" if download else "inline"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="{name}.pdf"'},
        )

    return router
```

Add `get_document_bytes` to `SessionManager` in `backend/sessions.py`. Task 5's `_run` already fetches **all** discovered docs into `session.documents` during `FETCHING` (the live browser closes at `READY`, so there is no post-READY lazy fetch), so this is a simple cached lookup:
```python
    async def get_document_bytes(self, session_id: str, doc_id: str) -> tuple[str, bytes] | None:
        session = self._registry.get(session_id)
        if session is None:
            return None
        return session.documents.get(doc_id)
```

- [ ] **Step 4: Run, verify PASSES** — after Task 9 provides `build_app`, run `uv run pytest tests/backend/test_api.py -v` (5 passed). *(If executing strictly in order, write `backend/main.build_app` now as part of this task since the test imports it — see Task 9's code; create `backend/main.py` here and refine CORS/lifespan in Task 9.)*

- [ ] **Step 5: Commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/api.py backend/sessions.py backend/main.py tests/backend/test_api.py
git commit -m "feat(backend): API routes with lazy doc serving (TestClient + FakeDriver)"
```

---

### Task 9: FastAPI app — CORS + lifespan sweeper

**Files:** Create/finalize `backend/main.py`; Create `tests/backend/test_app_wiring.py`.

- [ ] **Step 1: Write the failing test** `tests/backend/test_app_wiring.py`:

```python
from fastapi import FastAPI

from backend.browser import FakeDriver
from backend.main import build_app
from backend.sessions import SessionManager, SessionRegistry


def test_build_app_returns_fastapi_with_routes():
    reg = SessionRegistry()
    mgr = SessionManager(registry=reg, driver_factory=lambda: FakeDriver(),
                         login_url="x", clock=lambda: 0.0)
    app = build_app(manager=mgr, registry=reg)
    assert isinstance(app, FastAPI)
    paths = {r.path for r in app.routes}
    assert "/sessions" in paths
    assert "/sessions/{session_id}" in paths
    assert "/sessions/{session_id}/mfa" in paths
    assert "/sessions/{session_id}/documents/{doc_id}" in paths
```

- [ ] **Step 2: Run, verify FAILS** if `build_app` not yet present (or already passes if created in Task 8 — in that case add CORS assertion below).

- [ ] **Step 3: Implement/finalize** `backend/main.py`:

```python
from __future__ import annotations

import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import build_router
from backend.browserbase_driver import make_browserbase_driver_factory
from backend.sessions import SessionManager, SessionRegistry

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
SESSION_TTL_SECONDS = 900.0


def build_app(manager: SessionManager, registry: SessionRegistry) -> FastAPI:
    app = FastAPI(title="infer — LM policy fetcher")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(manager, registry))
    return app


def build_production_app() -> FastAPI:
    from spike.config import load_config

    registry = SessionRegistry()
    cfg = load_config(os.environ)
    manager = SessionManager(
        registry=registry,
        driver_factory=make_browserbase_driver_factory(cfg),
        login_url=cfg.lm_login_url,
        clock=time.monotonic,
    )
    app = build_app(manager, registry)

    @app.on_event("startup")
    async def _start_sweeper() -> None:
        import asyncio

        async def loop() -> None:
            while True:
                await asyncio.sleep(60)
                await manager.sweep(now=time.monotonic(), ttl=SESSION_TTL_SECONDS)

        app.state.sweeper = asyncio.create_task(loop())

    return app
```

> `build_app` is the testable factory (inject a manager backed by `FakeDriver`). `build_production_app` wires the real `BrowserbaseDriver` + `time.monotonic` clock + the background sweeper; it is exercised live, not in unit tests. The sweeper interval (60s) is independent of the TTL (900s).

- [ ] **Step 4: Run, verify PASSES** — `uv run pytest tests/backend/test_app_wiring.py -v` and the full backend suite. *(Tasks 8 & 9 both reference `make_browserbase_driver_factory`; to keep the offline suite importable before Task 11, create a minimal `backend/browserbase_driver.py` stub now that defines `make_browserbase_driver_factory(cfg)` raising `NotImplementedError` — Task 11 fills it in. `build_app` does not import it; only `build_production_app` does, so offline tests are unaffected.)*

- [ ] **Step 5: Commit**

```bash
uv run ruff check backend tests && uv run mypy backend && uv run pytest -q
git add backend/main.py backend/browserbase_driver.py tests/backend/test_app_wiring.py
git commit -m "feat(backend): FastAPI app factory + CORS + lifespan TTL sweeper"
```

---

### Task 10: Backend simplify + verify checkpoint

- [ ] **Step 1: Simplify** — review `backend/*.py` for duplication/clarity (shared `_wait`/poll helpers in tests, consistent error mapping). Fix inline.
- [ ] **Step 2: Verify the full gauntlet**

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy spike backend
uv run pytest -q
```
Expected: clean, all tests pass. Record the output as evidence.
- [ ] **Step 3: Commit** any simplifications: `git commit -am "refactor(backend): simplify post-review"`.

---

## PART 2 — Live integration (GATED: needs Browserbase + a consented LM account)

> Validated by running with captured evidence, not unit tests. Selectors/discovery calibrated live. **Do not start until** `.env` has `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID` + `LM_LOGIN_URL`, and a consented/expendable LM account is ready.

### Task 11: Real BrowserbaseDriver + async LM nav (live calibration)

**Files:** Replace stub `backend/browserbase_driver.py`; Create `backend/carriers/lm.py`.

- [ ] **Step 1a: Add the live `create_session` to `spike/browserbase.py`** (Phase A only built `build_session_params`). Confirm the SDK surface against the installed `browserbase` version — `sessions.create(**params)`, `.id`, `.connect_url` are the *expected* shape and may need adjusting:

```python
def create_session(config: Config) -> tuple[str, str]:
    """Create a live Browserbase session; return (session_id, connect_url).

    connect_url is a live bearer credential — never log it (spec §8)."""
    from browserbase import Browserbase

    bb = Browserbase(api_key=config.browserbase_api_key)
    params = build_session_params(config, config.browserbase_context_id)
    session = bb.sessions.create(**params)  # type: ignore[arg-type]
    return session.id, session.connect_url
```

- [ ] **Step 1b: Egress + login-render pre-flight** — confirm a hosted browser reaches the LM login (criterion 1). Create `backend/preflight.py`:

```python
from __future__ import annotations

import asyncio
import os

from playwright.async_api import async_playwright

from spike.browserbase import create_session
from spike.config import load_config


async def main() -> None:
    cfg = load_config(os.environ)
    session_id, connect_url = create_session(cfg)  # connect_url is a secret — never log it raw
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(connect_url)
        page = browser.contexts[0].pages[0]
        await page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded")
        print("egress:", await page.inner_text("body"))  # expect US residential, not your IP
        await page.goto(cfg.lm_login_url, wait_until="domcontentloaded")
        await page.screenshot(path="spike/out/preflight_login.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
```
Run `mkdir -p spike/out && set -a && source .env && set +a && uv run python -m backend.preflight`. Evidence: US residential egress IP; screenshot shows the rendered LM login (not Access-Denied). Repeat 3× for criterion-1 reliability. If blocked → classify with `spike.challenge`; decide §2 escalation.

- [ ] **Step 2: Calibrate selectors + discovery via Live View.** Open the Browserbase Live View, inspect the real LM DOM, and record exact selectors (username, password, submit, MFA field, MFA submit, documents landmark) and how documents are exposed (`.pdf` anchors vs XHR/JSON vs no-suffix download URLs). If not `.pdf` anchors, plan the discovery path (network interception or suffix-agnostic matching) — see spec §14.

- [ ] **Step 3: Implement `backend/carriers/lm.py`** (async nav; fill `SEL_*` from Step 2):

```python
from __future__ import annotations

from playwright.async_api import Page

from backend.browser import AuthStep, DocRef
from backend.models import CarrierAuthError, DocFetchError, MfaError
from spike.carriers.liberty_mutual import LMPageState, classify_lm_page, discover_document_urls

SEL_USERNAME = "input[name='username']"   # confirm in Step 2
SEL_PASSWORD = "input[name='password']"
SEL_SUBMIT = "button[type='submit']"
SEL_MFA_CODE = "input[name='otp']"
SEL_MFA_SUBMIT = "button[type='submit']"


async def submit_credentials(page: Page, username: str, password: str) -> AuthStep:
    await page.fill(SEL_USERNAME, username)
    await page.fill(SEL_PASSWORD, password)
    await page.click(SEL_SUBMIT)
    await page.wait_for_load_state("networkidle")
    state = classify_lm_page(await page.content(), page.url)
    if state is LMPageState.MFA_PROMPT:
        return AuthStep.NEEDS_MFA
    if state is LMPageState.DOCUMENTS:
        return AuthStep.AUTHENTICATED
    raise CarrierAuthError("credentials rejected or unexpected page")


async def submit_mfa(page: Page, code: str) -> AuthStep:
    await page.fill(SEL_MFA_CODE, code)
    await page.click(SEL_MFA_SUBMIT)
    await page.wait_for_load_state("networkidle")
    if classify_lm_page(await page.content(), page.url) is LMPageState.DOCUMENTS:
        return AuthStep.AUTHENTICATED
    raise MfaError("MFA code rejected")


async def list_documents(page: Page) -> list[DocRef]:
    refs = discover_document_urls(await page.content(), base_url=page.url)
    if not refs:
        raise DocFetchError("no policy documents discovered")
    return [DocRef(doc_id=f"doc-{i}", name=r.name, url=r.url) for i, r in enumerate(refs)]
```

- [ ] **Step 4: Implement `backend/browserbase_driver.py`** (replace the stub) implementing `BrowserDriver` with async Playwright; PDF fetched **inside the remote browser** (proxied):

```python
from __future__ import annotations

import base64

from playwright.async_api import Page, async_playwright

from backend.browser import AuthStep, DocRef, FetchedDoc
from backend.carriers import lm
from backend.models import BotChallengeError, DocFetchError
from spike.browserbase import create_session
from spike.challenge import ChallengeSignals, classify_challenge
from spike.config import Config
from spike.docfetch import decode_base64_pdf, is_valid_pdf


class BrowserbaseDriver:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._pw = None
        self._browser = None
        self._page: Page | None = None

    async def open_login(self, login_url: str) -> None:
        _session_id, connect_url = create_session(self._cfg)
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(connect_url)
        self._page = self._browser.contexts[0].pages[0]
        await self._page.goto(login_url, wait_until="domcontentloaded")
        body = await self._page.inner_text("body")
        signals = ChallengeSignals(url=self._page.url, status=200, body_text=body, cookies={}, has_captcha=False)
        kind = classify_challenge(signals)
        if kind.value != "NONE":
            raise BotChallengeError("blocked at login", fields=kind.to_fields(signals))

    async def submit_credentials(self, username: str, password: str) -> AuthStep:
        assert self._page is not None
        return await lm.submit_credentials(self._page, username, password)

    async def submit_mfa(self, code: str) -> AuthStep:
        assert self._page is not None
        return await lm.submit_mfa(self._page, code)

    async def list_documents(self) -> list[DocRef]:
        assert self._page is not None
        return await lm.list_documents(self._page)

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        assert self._page is not None
        b64 = await self._page.evaluate(
            """async (u) => { const r = await fetch(u, {credentials:'include'});
               const b = new Uint8Array(await r.arrayBuffer());
               let s=''; for (let i=0;i<b.length;i++) s+=String.fromCharCode(b[i]); return btoa(s); }""",
            ref.url,
        )
        content = decode_base64_pdf(b64)
        if not is_valid_pdf(content):
            raise DocFetchError(f"fetched bytes for {ref.name} are not a valid PDF")
        return FetchedDoc(name=ref.name, content=content)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


def make_browserbase_driver_factory(cfg: Config):
    def factory() -> BrowserbaseDriver:
        return BrowserbaseDriver(cfg)
    return factory
```

- [ ] **Step 5: Commit** (code only; `spike/out/` is git-ignored):

```bash
uv run ruff check backend && uv run mypy backend
git add backend/browserbase_driver.py backend/carriers/lm.py backend/preflight.py spike/browserbase.py
git commit -m "feat(backend): live BrowserbaseDriver + async LM nav (calibrated)"
```

---

## PART 3 — Frontend

### Task 12: Vite scaffold + typed API client

**Files:** Create `frontend/` (Vite React-TS), `frontend/src/api.ts`, `frontend/src/api.test.ts`.

- [ ] **Step 1: Scaffold + deps**

```bash
cd frontend 2>/dev/null || (cd /Users/yashdeshmukh/Downloads/mystuff/infer && npm create vite@latest frontend -- --template react-ts)
cd /Users/yashdeshmukh/Downloads/mystuff/infer/frontend
npm install
npm install react-pdf
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```
Add to `frontend/package.json` scripts: `"test": "vitest run"`, `"typecheck": "tsc --noEmit"`. Add `frontend/` build output + `node_modules` to `.gitignore` if not already covered.

- [ ] **Step 2: Write the failing test** `frontend/src/api.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { createSession, getStatus, submitMfa, documentUrl } from "./api";

describe("api client", () => {
  it("createSession POSTs creds and returns session id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 201, json: async () => ({ session_id: "s1", status: "STARTING" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await createSession("liberty_mutual", "u", "p");
    expect(res.session_id).toBe("s1");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/sessions");
    expect(JSON.parse(opts.body).password).toBe("p");
  });

  it("documentUrl builds the docs path", () => {
    expect(documentUrl("s1", "doc-0")).toContain("/sessions/s1/documents/doc-0");
  });
});
```

- [ ] **Step 3: Implement** `frontend/src/api.ts`:

```ts
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Status = "STARTING" | "AWAITING_MFA" | "VERIFYING_MFA" | "FETCHING" | "READY" | "FAILED";
export interface DocumentMeta { doc_id: string; name: string; }
export interface SessionState {
  session_id: string; status: Status; mfa_required: boolean;
  documents?: DocumentMeta[]; error?: { type: string; message: string }; latency_ms?: number;
}

export async function createSession(carrier: string, username: string, password: string) {
  const r = await fetch(`${BASE}/sessions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ carrier, username, password }),
  });
  return (await r.json()) as { session_id: string; status: Status };
}

export async function getStatus(id: string): Promise<SessionState> {
  const r = await fetch(`${BASE}/sessions/${id}`);
  if (r.status === 404) return { session_id: id, status: "FAILED", mfa_required: false, error: { type: "NotFound", message: "session gone" } };
  return (await r.json()) as SessionState;
}

export async function submitMfa(id: string, code: string): Promise<Response> {
  return fetch(`${BASE}/sessions/${id}/mfa`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

export function documentUrl(id: string, docId: string): string {
  return `${BASE}/sessions/${id}/documents/${docId}`;
}
```

- [ ] **Step 4: Run, verify PASSES** — `cd frontend && npm test` (2 passed), `npm run typecheck` clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/yashdeshmukh/Downloads/mystuff/infer
git add frontend/package.json frontend/package-lock.json frontend/src/api.ts frontend/src/api.test.ts frontend/.gitignore
git commit -m "feat(frontend): Vite scaffold + typed API client"
```

---

### Task 13: UI flow — components, polling, react-pdf

**Files:** Create `frontend/src/usePolling.ts`, `frontend/src/components/{CarrierSelect,CredentialForm,MfaPrompt,DocumentViewer}.tsx`, `frontend/src/App.tsx`, `frontend/src/App.css`; Test `frontend/src/components/MfaPrompt.test.tsx`.

- [ ] **Step 1: Write the failing component test** `frontend/src/components/MfaPrompt.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MfaPrompt } from "./MfaPrompt";

describe("MfaPrompt", () => {
  it("renders a code input and submit", () => {
    render(<MfaPrompt onSubmit={() => {}} disabled={false} />);
    expect(screen.getByLabelText(/code/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /submit/i })).toBeTruthy();
  });
});
```
Add `frontend/src/setupTests.ts` with `import "@testing-library/jest-dom";` and reference it in `vitest` config (`test: { environment: "jsdom", setupFiles: "./src/setupTests.ts" }` in `vite.config.ts`).

- [ ] **Step 2: Run, verify FAILS** — `cd frontend && npm test` → cannot find `./MfaPrompt`.

- [ ] **Step 3: Implement components.**

`frontend/src/components/MfaPrompt.tsx`:
```tsx
import { useState } from "react";

export function MfaPrompt({ onSubmit, disabled }: { onSubmit: (code: string) => void; disabled: boolean }) {
  const [code, setCode] = useState("");
  return (
    <div className="card">
      <label htmlFor="mfa">Enter the code sent to your phone/email</label>
      <input id="mfa" aria-label="code" value={code} onChange={(e) => setCode(e.target.value)} />
      <button disabled={disabled || !code} onClick={() => onSubmit(code)}>Submit code</button>
    </div>
  );
}
```

`frontend/src/components/CarrierSelect.tsx`:
```tsx
export function CarrierSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select aria-label="carrier" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="liberty_mutual">Liberty Mutual</option>
      <option value="geico" disabled>Geico (coming soon)</option>
    </select>
  );
}
```

`frontend/src/components/CredentialForm.tsx`:
```tsx
import { useState } from "react";

export function CredentialForm({ onSubmit, disabled }: { onSubmit: (u: string, p: string) => void; disabled: boolean }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  return (
    <div className="card">
      <label htmlFor="u">Username</label>
      <input id="u" value={u} onChange={(e) => setU(e.target.value)} />
      <label htmlFor="p">Password</label>
      <input id="p" type="password" value={p} onChange={(e) => setP(e.target.value)} />
      <button disabled={disabled || !u || !p} onClick={() => onSubmit(u, p)}>Log in</button>
    </div>
  );
}
```

`frontend/src/components/DocumentViewer.tsx`:
```tsx
import { Document, Page } from "react-pdf";
import type { DocumentMeta } from "../api";
import { documentUrl } from "../api";

export function DocumentViewer({ sessionId, docs, onFirstRender }: {
  sessionId: string; docs: DocumentMeta[]; onFirstRender: () => void;
}) {
  return (
    <div className="card">
      {docs.map((d) => (
        <div key={d.doc_id}>
          <h3>{d.name}</h3>
          <Document file={documentUrl(sessionId, d.doc_id)}>
            <Page pageNumber={1} onRenderSuccess={onFirstRender} />
          </Document>
          <a href={`${documentUrl(sessionId, d.doc_id)}?download=1`}>Download</a>
        </div>
      ))}
    </div>
  );
}
```

`frontend/src/usePolling.ts`:
```ts
import { useEffect, useRef, useState } from "react";
import { getStatus, type SessionState } from "./api";

export function usePolling(sessionId: string | null) {
  const [state, setState] = useState<SessionState | null>(null);
  const fails = useRef(0);
  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    const t = setInterval(async () => {
      const s = await getStatus(sessionId);
      if (!active) return;
      setState(s);
      if (s.status === "READY" || s.status === "FAILED") clearInterval(t);
      if (s.error?.type === "NotFound" && ++fails.current >= 3) clearInterval(t);
    }, 700);
    return () => { active = false; clearInterval(t); };
  }, [sessionId]);
  return state;
}
```

- [ ] **Step 4: Implement `frontend/src/App.tsx`** wiring it together (records the client-side first-render latency mark):

```tsx
import { useRef, useState } from "react";
import { createSession, submitMfa, type Status } from "./api";
import { usePolling } from "./usePolling";
import { CarrierSelect } from "./components/CarrierSelect";
import { CredentialForm } from "./components/CredentialForm";
import { MfaPrompt } from "./components/MfaPrompt";
import { DocumentViewer } from "./components/DocumentViewer";
import "./App.css";

export default function App() {
  const [carrier, setCarrier] = useState("liberty_mutual");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const mfaSubmittedAt = useRef<number | null>(null);
  const [clientLatencyMs, setClientLatencyMs] = useState<number | null>(null);
  const state = usePolling(sessionId);
  const status: Status | undefined = state?.status;

  return (
    <main className="app">
      <h1>Policy Document Fetcher</h1>
      {!sessionId && (
        <>
          <CarrierSelect value={carrier} onChange={setCarrier} />
          <CredentialForm disabled={false} onSubmit={async (u, p) => {
            const r = await createSession(carrier, u, p);
            setSessionId(r.session_id);
          }} />
        </>
      )}
      {status && <p>Status: {status}{state?.latency_ms ? ` · server ${Math.round(state.latency_ms)}ms` : ""}</p>}
      {status === "AWAITING_MFA" && (
        <MfaPrompt disabled={false} onSubmit={async (code) => {
          mfaSubmittedAt.current = performance.now();
          await submitMfa(sessionId!, code);
        }} />
      )}
      {status === "READY" && state?.documents && (
        <DocumentViewer sessionId={sessionId!} docs={state.documents} onFirstRender={() => {
          if (mfaSubmittedAt.current && clientLatencyMs === null)
            setClientLatencyMs(performance.now() - mfaSubmittedAt.current);
        }} />
      )}
      {clientLatencyMs !== null && <p>MFA→rendered: {Math.round(clientLatencyMs)}ms</p>}
      {status === "FAILED" && <p className="error">Failed: {state?.error?.type} — {state?.error?.message}</p>}
    </main>
  );
}
```
Add minimal `frontend/src/App.css` (centered card, readable). Configure react-pdf worker per its docs (`pdfjs.GlobalWorkerOptions.workerSrc`).

- [ ] **Step 5: Run, verify PASSES + commit**

```bash
cd frontend && npm test && npm run typecheck && npm run build
cd /Users/yashdeshmukh/Downloads/mystuff/infer
git add frontend/src
git commit -m "feat(frontend): HITL flow — carrier/creds/MFA/react-pdf viewer + polling"
```

---

### Task 14: Live end-to-end run = the gate

- [ ] **Step 1** — Start backend: `set -a && source .env && set +a && uv run uvicorn backend.main:build_production_app --factory --port 8000`. Start frontend: `cd frontend && VITE_API_BASE=http://localhost:8000 npm run dev`.
- [ ] **Step 2** — In the browser: pick Liberty Mutual, enter the consented account's creds, submit; when the MFA field appears, enter the real code; confirm a policy PDF renders.
- [ ] **Step 3** — Capture evidence to `spike/out/RESULTS.md`: pass/fail per success criterion (§2), MFA channel, which discovery path worked, **both latency numbers** (server `latency_ms` + client MFA→rendered), any structured bot-challenge classification, Browserbase tier + whether escalation was needed, and the **go/no-go for Geico**.
- [ ] **Step 4** — `uv run pytest -q` (offline suite still green) and `git commit -am "chore: live gate run captured (results in git-ignored spike/out)"`.

---

## Spec Coverage Self-Check

- Architecture A (bg task + registry + poll) → Tasks 5–9. ✓
- Bounded MFA wait + SessionExpiredError + driver.close cleanup → Task 7. ✓
- asyncio.Queue + single-flight + VERIFYING_MFA + double-submit 409 → Tasks 5,6,8. ✓
- Fetch-all-during-FETCHING + first-doc latency (server `latency_ms` + client onRenderSuccess) → Tasks 5, 13; metric §11. ✓
- Single-flight MFA via synchronous VERIFYING_MFA flip (no Lock) → Tasks 4, 8. ✓
- Error taxonomy + structured bot-challenge fields → Tasks 2,3,7,8. ✓
- Config drops cred fields → Task 1. ✓
- New deps pinned + asyncio_mode → Task 0. ✓
- FakeDriver failure scenarios incl. hang/cancel/connection-loss + close-idempotent → Task 3. ✓
- TTL sweeper cancels task + closes driver → Tasks 7,9. ✓
- Security: connect URL never logged; localhost/TLS; password not logged → Tasks 11 (note), 9. ✓
- Live driver + proxied in-page fetch + discovery calibration → Task 11. ✓
- Frontend flow + react-pdf + polling stop-on-404 → Tasks 12,13. ✓
- Live gate run + RESULTS → Task 14. ✓

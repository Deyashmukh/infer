# Browser-Automation Structure — Phase 1: Runtime Safety & VLM Seam — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the model-agnostic runtime structure for the new browser-automation layer — a validation gate on every served document and a stubbed VLM fallback seam — without touching the model or the central state machine.

**Architecture:** Add two leaf modules (`validation`, `vision`) and one decorator (`ResilientDriver`) that wraps any `BrowserDriver`. The decorator gates every fetched document before returning it and exposes a clean `VisionAgent` seam that today is a no-op stub (so behavior == deterministic-only) and later holds Holo3.1. The decorator implements the existing `BrowserDriver` protocol, so it slots into the current factory/`SessionManager` with no central surgery.

**Tech Stack:** Python 3.12, Playwright (existing), pytest (asyncio_mode=auto), ruff, mypy --strict, uv.

## Global Constraints

- Python ≥ 3.12; type-annotate everything (mypy runs `--strict`).
- Lint: ruff rules `E, F, I, UP, B, SIM` must pass.
- Tests run **offline, zero network**; use `FakeDriver` / small in-file fakes.
- Test command form: `uv run pytest <path>::<test> -v`. Async tests need no decorator (asyncio_mode=auto).
- Reuse `spike.docfetch.is_valid_pdf` for PDF validity — do not reimplement.
- Error taxonomy is in `backend/models.py` (`DocFetchError`, etc.); raise those, never bare `Exception`.
- This phase ships no model and no live-browser logic. The VLM fallback with a stub MUST be a no-op (re-raise the original error), so existing carrier behavior is unchanged.

## File Structure

- `backend/validation.py` (new) — `ValidationResult`, `validate_document(...)`. Pure; gates a document's bytes.
- `backend/vision.py` (new) — `VisionUnavailable`, `AgentResult`, `VisionAgent` protocol, `StubVisionAgent`. The model-shaped seam.
- `backend/resilient_driver.py` (new) — `ResilientDriver`, a `BrowserDriver` decorator that gates fetches + holds the VLM seam.
- `backend/chromium_driver.py` (modify) — `make_chromium_driver_factory` wraps `ChromiumDriver` in `ResilientDriver(..., StubVisionAgent())`.
- `tests/backend/test_validation.py`, `test_vision.py`, `test_resilient_driver.py`, and an assertion added to the factory’s coverage.

**Out of scope (follow-on plans):** the discovery/extraction harness; endpoint-recipe consolidation; the *real* fallback orchestration (re-driving the live page) — all need a live browser and/or the model.

---

### Task 1: Validation gate

**Files:**
- Create: `backend/validation.py`
- Test: `tests/backend/test_validation.py`

**Interfaces:**
- Consumes: `spike.docfetch.is_valid_pdf(data: bytes, min_bytes: int = 1024) -> bool`
- Produces: `ValidationResult(ok: bool, reason: str)`; `validate_document(content: bytes, *, min_bytes: int = 1024, identity_check: Callable[[bytes], bool] | None = None) -> ValidationResult`

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_validation.py
from backend.validation import ValidationResult, validate_document

_VALID = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"


def test_valid_pdf_passes():
    assert validate_document(_VALID) == ValidationResult(ok=True, reason="")


def test_too_small_fails():
    res = validate_document(b"%PDF-1.7 tiny")
    assert res.ok is False
    assert "valid PDF" in res.reason


def test_non_pdf_fails():
    res = validate_document(b"<html>error</html>" + b"x" * 2000)
    assert res.ok is False


def test_identity_check_failure_fails():
    res = validate_document(_VALID, identity_check=lambda _b: False)
    assert res.ok is False
    assert "identity" in res.reason


def test_identity_check_pass_passes():
    assert validate_document(_VALID, identity_check=lambda _b: True).ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/backend/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.validation`.

- [ ] **Step 3: Write the implementation**

```python
# backend/validation.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from spike.docfetch import is_valid_pdf


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str = ""


def validate_document(
    content: bytes,
    *,
    min_bytes: int = 1024,
    identity_check: Callable[[bytes], bool] | None = None,
) -> ValidationResult:
    """Gate a fetched document before it is served.

    Verifies it is a real, non-trivial PDF (reusing is_valid_pdf), then an optional
    per-carrier identity check (e.g. right policy/vehicle). Returns ok=False with a
    reason on first failure so the caller can fail safe rather than serve garbage or
    the wrong document.
    """
    if not is_valid_pdf(content, min_bytes=min_bytes):
        return ValidationResult(False, f"not a valid PDF (len={len(content)})")
    if identity_check is not None and not identity_check(content):
        return ValidationResult(False, "document failed identity check")
    return ValidationResult(True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/backend/test_validation.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + type-check + commit**

```bash
uv run ruff check backend/validation.py tests/backend/test_validation.py && uv run mypy backend/validation.py
git add backend/validation.py tests/backend/test_validation.py
git commit -m "feat(validation): document gate (valid PDF + optional identity check)"
```

---

### Task 2: VLM seam (protocol + stub)

**Files:**
- Create: `backend/vision.py`
- Test: `tests/backend/test_vision.py`

**Interfaces:**
- Produces: `VisionUnavailable(RuntimeError)`; `AgentResult(ok: bool, detail: str)`; `VisionAgent` protocol with `async def run(self, goal: str) -> AgentResult`; `StubVisionAgent` (its `run` raises `VisionUnavailable`).

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_vision.py
import pytest

from backend.vision import StubVisionAgent, VisionUnavailable


async def test_stub_agent_raises_unavailable():
    with pytest.raises(VisionUnavailable):
        await StubVisionAgent().run("open the declarations document")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/test_vision.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.vision`.

- [ ] **Step 3: Write the implementation**

```python
# backend/vision.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class VisionUnavailable(RuntimeError):
    """No vision model is wired in (the stub), or the model could not act."""


@dataclass(frozen=True)
class AgentResult:
    ok: bool
    detail: str = ""


class VisionAgent(Protocol):
    """Agent-shaped seam: drive the browser toward a goal (localization is internal).

    A real implementation (Holo3.1, post-eval) is constructed with the live page/driver
    it acts on, so `run` takes only the goal. Until then StubVisionAgent stands in.
    """

    async def run(self, goal: str) -> AgentResult: ...


class StubVisionAgent:
    """No model wired in. Every call fails loudly so the deterministic path stays
    authoritative and the fallback is a no-op until a real agent is slotted in."""

    async def run(self, goal: str) -> AgentResult:
        raise VisionUnavailable("no vision model configured")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/test_vision.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Lint + type-check + commit**

```bash
uv run ruff check backend/vision.py tests/backend/test_vision.py && uv run mypy backend/vision.py
git add backend/vision.py tests/backend/test_vision.py
git commit -m "feat(vision): VisionAgent seam + StubVisionAgent (no model yet)"
```

---

### Task 3: ResilientDriver decorator

**Files:**
- Create: `backend/resilient_driver.py`
- Test: `tests/backend/test_resilient_driver.py`

**Interfaces:**
- Consumes: `backend.browser.BrowserDriver`, `AuthStep`, `DocRef`, `FetchedDoc`; `backend.validation.validate_document`; `backend.vision.VisionAgent`, `VisionUnavailable`; `backend.models.DocFetchError`.
- Produces: `ResilientDriver(inner: BrowserDriver, vision: VisionAgent)` — itself a `BrowserDriver`. All methods pass through to `inner` except `fetch_document`, which gates the result and, on failure/rejection, attempts the vision fallback then re-gates.

- [ ] **Step 1: Write the failing tests**

```python
# tests/backend/test_resilient_driver.py
import pytest

from backend.browser import DocRef, FakeDriver, FetchedDoc
from backend.models import DocFetchError
from backend.resilient_driver import ResilientDriver
from backend.vision import AgentResult, StubVisionAgent

_REF = DocRef(doc_id="0", name="Declarations")
_VALID = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"


async def test_happy_path_passes_through_and_gates():
    drv = ResilientDriver(FakeDriver(), StubVisionAgent())
    doc = await drv.fetch_document(_REF)
    assert doc.content.startswith(b"%PDF-")


async def test_auth_methods_pass_through():
    drv = ResilientDriver(FakeDriver(), StubVisionAgent())
    await drv.open_login("https://x")
    step = await drv.submit_credentials("u", "p")
    assert step.value == "NEEDS_MFA"


async def test_deterministic_fetch_failure_with_stub_raises():
    drv = ResilientDriver(FakeDriver(connection_lost_on_fetch=True), StubVisionAgent())
    with pytest.raises(DocFetchError):
        await drv.fetch_document(_REF)


async def test_invalid_pdf_is_rejected_by_gate():
    class _BadDriver(FakeDriver):
        async def fetch_document(self, ref: DocRef) -> FetchedDoc:
            return FetchedDoc(name=ref.name, content=b"<html>nope</html>")

    drv = ResilientDriver(_BadDriver(), StubVisionAgent())
    with pytest.raises(DocFetchError):
        await drv.fetch_document(_REF)


async def test_vision_fallback_recovers_then_serves():
    # Driver fails the first fetch, succeeds the second; a recovering agent bridges them.
    class _FlakyDriver(FakeDriver):
        def __init__(self) -> None:
            super().__init__()
            self._calls = 0

        async def fetch_document(self, ref: DocRef) -> FetchedDoc:
            self._calls += 1
            if self._calls == 1:
                raise DocFetchError("first attempt failed")
            return FetchedDoc(name=ref.name, content=_VALID)

    class _RecoveringAgent:
        async def run(self, goal: str) -> AgentResult:
            return AgentResult(ok=True, detail="re-drove to document")

    drv = ResilientDriver(_FlakyDriver(), _RecoveringAgent())
    doc = await drv.fetch_document(_REF)
    assert doc.content == _VALID
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/backend/test_resilient_driver.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.resilient_driver`.

- [ ] **Step 3: Write the implementation**

```python
# backend/resilient_driver.py
from __future__ import annotations

from typing import Any

from backend.browser import AuthStep, BrowserDriver, DocRef, FetchedDoc
from backend.models import DocFetchError
from backend.validation import validate_document
from backend.vision import VisionAgent, VisionUnavailable


class ResilientDriver:
    """Wraps a deterministic BrowserDriver with a validation gate + a VLM fallback seam.

    The inner driver is the first player. Every fetched document passes the gate before
    it is returned, so a garbage/wrong doc is never served. If the deterministic fetch
    fails or the gate rejects the result, the vision agent is asked to recover and the
    fetch is re-attempted + re-gated. With StubVisionAgent the recovery raises
    VisionUnavailable, so today this is deterministic-only behavior.
    """

    def __init__(self, inner: BrowserDriver, vision: VisionAgent) -> None:
        self._inner = inner
        self._vision = vision

    async def open_login(self, login_url: str) -> None:
        await self._inner.open_login(login_url)

    async def submit_credentials(self, username: str, password: str) -> AuthStep:
        return await self._inner.submit_credentials(username, password)

    async def submit_mfa(self, code: str) -> AuthStep:
        return await self._inner.submit_mfa(code)

    async def list_documents(self) -> list[DocRef]:
        return await self._inner.list_documents()

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        try:
            doc = await self._inner.fetch_document(ref)
            gate = validate_document(doc.content)
            if gate.ok:
                return doc
            reason = f"gate rejected: {gate.reason}"
        except DocFetchError as exc:
            reason = str(exc)
        return await self._recover_fetch(ref, reason)

    async def _recover_fetch(self, ref: DocRef, reason: str) -> FetchedDoc:
        try:
            await self._vision.run(f"open and download the document: {ref.name}")
        except VisionUnavailable:
            raise DocFetchError(
                f"fetch failed for {ref.name!r} ({reason}); no vision fallback available"
            ) from None
        doc = await self._inner.fetch_document(ref)
        gate = validate_document(doc.content)
        if not gate.ok:
            raise DocFetchError(
                f"document gate rejected {ref.name!r} after recovery: {gate.reason}"
            )
        return doc

    async def close(self) -> None:
        await self._inner.close()

    async def storage_state(self) -> dict[str, Any]:
        return await self._inner.storage_state()

    async def try_resume(self, state: dict[str, Any]) -> bool:
        return await self._inner.try_resume(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/backend/test_resilient_driver.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + type-check + commit**

```bash
uv run ruff check backend/resilient_driver.py tests/backend/test_resilient_driver.py && uv run mypy backend/resilient_driver.py
git add backend/resilient_driver.py tests/backend/test_resilient_driver.py
git commit -m "feat(driver): ResilientDriver decorator — gate fetches + VLM fallback seam"
```

---

### Task 4: Wire ResilientDriver into the production factory

**Files:**
- Modify: `backend/chromium_driver.py` (`make_chromium_driver_factory`, near line 118)
- Test: `tests/backend/test_resilient_driver.py` (add a factory-wiring test)

**Interfaces:**
- Consumes: `backend.resilient_driver.ResilientDriver`, `backend.vision.StubVisionAgent`, existing `ChromiumDriver`, `Config`.
- Produces: `make_chromium_driver_factory(cfg)` returns a callable producing a `ResilientDriver` (wrapping `ChromiumDriver`) per carrier. The return type stays `BrowserDriver`-compatible, so `SessionManager` is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/backend/test_resilient_driver.py
from spike.config import Config

from backend.chromium_driver import make_chromium_driver_factory
from backend.resilient_driver import ResilientDriver


def test_factory_wraps_chromium_in_resilient_driver():
    cfg = Config(
        lm_login_url="https://x",
        geico_login_url=None,
        headless=True,
        chromium_args=[],
        proxy_server=None,
        proxy_username=None,
        proxy_password=None,
    )
    driver = make_chromium_driver_factory(cfg)("liberty_mutual")
    assert isinstance(driver, ResilientDriver)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/test_resilient_driver.py::test_factory_wraps_chromium_in_resilient_driver -v`
Expected: FAIL — factory returns a bare `ChromiumDriver`, not `ResilientDriver`.

- [ ] **Step 3: Modify the factory**

In `backend/chromium_driver.py`, add imports at the top with the others:

```python
from backend.resilient_driver import ResilientDriver
from backend.vision import StubVisionAgent
```

Replace `make_chromium_driver_factory` (currently returning `ChromiumDriver(cfg, carrier)`):

```python
def make_chromium_driver_factory(cfg: Config) -> Callable[[str], ResilientDriver]:
    def factory(carrier: str) -> ResilientDriver:
        # ChromiumDriver is the deterministic first player; StubVisionAgent is the
        # not-yet-wired VLM fallback seam (Holo3.1 replaces it post-eval).
        return ResilientDriver(ChromiumDriver(cfg, carrier), StubVisionAgent())

    return factory
```

- [ ] **Step 4: Run the new test + the full backend suite (regression)**

Run: `uv run pytest tests/backend/test_resilient_driver.py -v && uv run pytest -q`
Expected: the factory test PASSES and the full suite is green (the decorator is behavior-preserving with the stub).

- [ ] **Step 5: Lint + type-check + commit**

```bash
uv run ruff check backend/chromium_driver.py && uv run mypy backend spike
git add backend/chromium_driver.py tests/backend/test_resilient_driver.py
git commit -m "feat(driver): wire ResilientDriver(+StubVisionAgent) into the production factory"
```

---

## Self-Review

**Spec coverage (against `2026-06-24-browser-automation-structure-design.md`):**
- §2.1 deterministic execution path → unchanged here; `ResilientDriver` preserves it (Task 3/4). Endpoint-recipe consolidation = follow-on plan (flagged).
- §2.3 VLM seam → Task 2 (`VisionAgent`/`StubVisionAgent`) + Task 3/4 (wired). ✓
- §2.4 validation gates → Task 1, applied in Task 3. ✓
- §2.4 fallback orchestration → seam + recovery scaffold present (Task 3); the *real* page-re-driving lands with the model (follow-on). ✓ (scoped)
- §2.2 discovery harness → **follow-on plan**, explicitly out of scope.
- §5 trigger-then-capture → property of the (follow-on) endpoint-recipe work; not in Phase 1.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every command shows expected output. ✓

**Type consistency:** `ValidationResult(ok, reason)`, `validate_document(content, *, min_bytes, identity_check)`, `VisionAgent.run(goal) -> AgentResult`, `ResilientDriver(inner, vision)` used identically across tasks and tests. `make_chromium_driver_factory` return type widened to `ResilientDriver` (still satisfies `BrowserDriver`). ✓

**Follow-on plans (not this plan):** (B) discovery/extraction harness; (C) endpoint-recipe consolidation + real fallback orchestration (with Holo3.1, post-eval).

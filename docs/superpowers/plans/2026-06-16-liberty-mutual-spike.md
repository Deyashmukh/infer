# Liberty Mutual Phase 0a Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove reliable, hosted (non-residential) access to Liberty Mutual's portal end-to-end — login → MFA → fetch a real policy PDF → session reuse — via Browserbase, as the go/no-go gate for the whole project.

**Architecture:** A standalone Python package under `spike/`. **Phase A** is pure, offline machinery (config, PDF validation, bot-challenge classification, page-state classification, document-URL discovery, latency timing, session-params builder, gate + lockout logic) built test-first — no secrets or paid services needed. **Phase B** is a thin live integration layer (Browserbase connect, LM selectors, the actual run) validated by running with captured evidence, gated on Browserbase signup + a consented/expendable account.

**Tech Stack:** Python 3.12, Playwright (over CDP to Browserbase), `browserbase` SDK, `python-dotenv`, `structlog`; `uv` for deps/lockfile; `ruff` + `mypy --strict` + `pytest`.

**Spec:** `docs/superpowers/specs/2026-06-16-liberty-mutual-spike-design.md`

---

## File Structure

| File | Responsibility | Phase |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock` | Pinned deps, ruff/mypy/pytest config | A0 |
| `.env.example` | Documents every env key (public vs secret) | A0 |
| `spike/__init__.py` | Package marker | A0 |
| `spike/config.py` | `Config` + `load_config()` + `ConfigError` | A1 |
| `spike/docfetch.py` | Pure: `decode_base64_pdf`, `is_valid_pdf`; live: `fetch_pdf_in_page` (B) | A2, B3 |
| `spike/challenge.py` | Generic bot-challenge classification (§8 structured failure) | A3 |
| `spike/carriers/__init__.py` | Package marker | A0 |
| `spike/carriers/liberty_mutual.py` | LM page-state classify, doc-URL discovery, nav steps (selectors filled in B) | A4, A5, B2 |
| `spike/timing.py` | Injected-clock latency timer | A6 |
| `spike/browserbase.py` | `build_session_params` (pure); `create_session`/`connect` (live, B) | A7, B1 |
| `spike/gate.py` | Lockout `AttemptGuard`, `evaluate_gate` (pre-committed gate rule as code) | A8 |
| `spike/run_liberty.py` | Orchestrator wiring it all together | B3–B5 |
| `tests/...` | Offline unit tests mirroring each module | A1–A8 |
| `spike/out/` | Git-ignored: PDFs, screenshots, logs, RESULTS.md, context.json | A0 |

---

# PHASE A — Offline machinery (build now, full TDD, no secrets)

## Task A0: Scaffolding & tooling

**Files:**
- Create: `pyproject.toml`, `.env.example`, `spike/__init__.py`, `spike/carriers/__init__.py`, `tests/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Initialize uv project and add pinned deps**

Run:
```bash
uv init --name infer-spike --python 3.12 --no-readme
rm -f main.py hello.py            # remove uv's sample module if created
uv add playwright browserbase python-dotenv structlog
uv add --dev pytest ruff mypy
```
This resolves and **pins exact versions into `uv.lock`** (satisfies the "exact versions + committed lockfile" bar). We connect to a *remote* Browserbase browser, so a local `playwright install` is not required.

- [ ] **Step 2: Configure tooling in `pyproject.toml`**

Append these tables to `pyproject.toml`:
```toml
[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true

# The browserbase SDK may not ship type stubs; don't let strict mode fail on it.
[[tool.mypy.overrides]]
module = ["browserbase.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: Create package markers and `.env.example`**

`spike/__init__.py`, `spike/carriers/__init__.py`, `tests/__init__.py` — each an empty file.

`.env.example`:
```dotenv
# Browserbase
BROWSERBASE_API_KEY=bb_live_replace_me      # SECRET
BROWSERBASE_PROJECT_ID=replace_me           # public-ish project id
BROWSERBASE_CONTEXT_ID=                      # optional; set after first run to reuse session

# Liberty Mutual — use a CONSENTED, EXPENDABLE account (see spec §9)
LM_USERNAME=                                 # SECRET
LM_PASSWORD=                                 # SECRET
LM_LOGIN_URL=https://www.libertymutual.com/log-in   # public
```

- [ ] **Step 4: Ignore spike output**

Add to `.gitignore`:
```gitignore
# Spike output — may contain PII (PDFs, screenshots); never commit (see spec §9)
spike/out/
```

- [ ] **Step 5: Verify tooling runs and commit**

Run:
```bash
uv run ruff check . && uv run mypy spike || true   # no code yet; expect clean/empty
uv run pytest -q || true                            # no tests yet; expect "no tests ran"
git add pyproject.toml uv.lock .env.example .gitignore spike tests
git commit -m "chore: scaffold spike package, tooling, env template"
```

---

## Task A1: Config loader

**Files:**
- Create: `spike/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import pytest
from spike.config import Config, ConfigError, load_config

BASE = {
    "BROWSERBASE_API_KEY": "bb_live_x",
    "BROWSERBASE_PROJECT_ID": "proj_1",
    "LM_USERNAME": "user@example.com",
    "LM_PASSWORD": "pw",
    "LM_LOGIN_URL": "https://www.libertymutual.com/log-in",
}


def test_load_config_returns_typed_config():
    cfg = load_config(BASE)
    assert isinstance(cfg, Config)
    assert cfg.browserbase_project_id == "proj_1"
    assert cfg.browserbase_context_id is None  # optional, absent


def test_load_config_reads_optional_context_id():
    cfg = load_config({**BASE, "BROWSERBASE_CONTEXT_ID": "ctx_9"})
    assert cfg.browserbase_context_id == "ctx_9"


def test_missing_required_key_raises_with_key_name():
    broken = {k: v for k, v in BASE.items() if k != "LM_PASSWORD"}
    with pytest.raises(ConfigError) as exc:
        load_config(broken)
    assert "LM_PASSWORD" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.config'`.

- [ ] **Step 3: Write minimal implementation**

`spike/config.py`:
```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_REQUIRED = (
    "BROWSERBASE_API_KEY",
    "BROWSERBASE_PROJECT_ID",
    "LM_USERNAME",
    "LM_PASSWORD",
    "LM_LOGIN_URL",
)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    browserbase_api_key: str
    browserbase_project_id: str
    lm_username: str
    lm_password: str
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
        lm_username=env["LM_USERNAME"],
        lm_password=env["LM_PASSWORD"],
        lm_login_url=env["LM_LOGIN_URL"],
        browserbase_context_id=context_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/config.py tests/test_config.py
git commit -m "feat(spike): config loader with fail-fast validation"
```

---

## Task A2: PDF validation + base64 decode

**Files:**
- Create: `spike/docfetch.py`
- Test: `tests/test_docfetch.py`

- [ ] **Step 1: Write the failing test**

`tests/test_docfetch.py`:
```python
import base64

import pytest
from spike.docfetch import decode_base64_pdf, is_valid_pdf

PDF_BYTES = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"


def test_is_valid_pdf_accepts_real_pdf():
    assert is_valid_pdf(PDF_BYTES) is True


def test_is_valid_pdf_rejects_non_pdf():
    assert is_valid_pdf(b"<html>not a pdf</html>") is False


def test_is_valid_pdf_rejects_too_small():
    assert is_valid_pdf(b"%PDF-1.7") is False  # header but trivially small


def test_decode_base64_pdf_roundtrips():
    encoded = base64.b64encode(PDF_BYTES).decode("ascii")
    assert decode_base64_pdf(encoded) == PDF_BYTES


def test_decode_base64_pdf_rejects_garbage():
    with pytest.raises(ValueError):
        decode_base64_pdf("not!!base64!!")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_docfetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.docfetch'`.

- [ ] **Step 3: Write minimal implementation**

`spike/docfetch.py`:
```python
from __future__ import annotations

import base64
import binascii

_PDF_MAGIC = b"%PDF-"


def is_valid_pdf(data: bytes, min_bytes: int = 1024) -> bool:
    """A byte blob looks like a real, non-trivial PDF."""
    return len(data) >= min_bytes and data.startswith(_PDF_MAGIC)


def decode_base64_pdf(encoded: str) -> bytes:
    """Decode base64 produced by an in-page fetch. Raises ValueError on bad input."""
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64 PDF payload: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_docfetch.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/docfetch.py tests/test_docfetch.py
git commit -m "feat(spike): PDF validation + base64 decode helpers"
```

---

## Task A3: Bot-challenge classification

**Files:**
- Create: `spike/challenge.py`
- Test: `tests/test_challenge.py`

- [ ] **Step 1: Write the failing test**

`tests/test_challenge.py`:
```python
from spike.challenge import ChallengeKind, ChallengeSignals, classify_challenge


def sig(**kw) -> ChallengeSignals:
    base = dict(url="https://login.libertymutual.com", status=200,
                body_text="Sign in to your account", cookies={}, has_captcha=False)
    base.update(kw)
    return ChallengeSignals(**base)


def test_clean_page_is_none():
    assert classify_challenge(sig()) is ChallengeKind.NONE


def test_akamai_access_denied():
    s = sig(status=403, body_text="Access Denied\nReference #18.abc")
    assert classify_challenge(s) is ChallengeKind.AKAMAI_ACCESS_DENIED


def test_captcha_detected():
    assert classify_challenge(sig(has_captcha=True)) is ChallengeKind.CAPTCHA


def test_rate_limited():
    assert classify_challenge(sig(status=429)) is ChallengeKind.RATE_LIMIT


def test_unknown_block_on_other_4xx():
    assert classify_challenge(sig(status=401, body_text="blocked")) is ChallengeKind.UNKNOWN_BLOCK


def test_to_result_fields_is_json_safe():
    s = sig(status=403, body_text="Access Denied Reference #1", cookies={"_abck": "~-1~"})
    fields = classify_challenge(s).to_fields(s)
    assert fields["kind"] == "AKAMAI_ACCESS_DENIED"
    assert fields["status"] == 403
    assert "_abck" in fields["abck_state"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_challenge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.challenge'`.

- [ ] **Step 3: Write minimal implementation**

`spike/challenge.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class ChallengeSignals:
    url: str
    status: int
    body_text: str
    cookies: dict[str, str]
    has_captcha: bool


class ChallengeKind(StrEnum):
    NONE = "NONE"
    AKAMAI_ACCESS_DENIED = "AKAMAI_ACCESS_DENIED"
    CAPTCHA = "CAPTCHA"
    RATE_LIMIT = "RATE_LIMIT"
    UNKNOWN_BLOCK = "UNKNOWN_BLOCK"

    def to_fields(self, signals: ChallengeSignals) -> dict[str, object]:
        """Structured failure record for RESULTS.md (spec §8)."""
        return {
            "kind": self.value,
            "url": signals.url,
            "status": signals.status,
            "abck_state": (
                f"_abck={signals.cookies['_abck']}" if "_abck" in signals.cookies else "<absent>"
            ),  # key name embedded so the field is self-describing AND the test substring-checks it
            "has_captcha": signals.has_captcha,
        }


def classify_challenge(signals: ChallengeSignals) -> ChallengeKind:
    if signals.has_captcha:
        return ChallengeKind.CAPTCHA
    if signals.status == 429:
        return ChallengeKind.RATE_LIMIT
    if "access denied" in signals.body_text.lower():
        return ChallengeKind.AKAMAI_ACCESS_DENIED
    if signals.status >= 400:
        return ChallengeKind.UNKNOWN_BLOCK
    return ChallengeKind.NONE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_challenge.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/challenge.py tests/test_challenge.py
git commit -m "feat(spike): bot-challenge classifier for structured failure capture"
```

---

## Task A4: Liberty Mutual page-state classification

**Files:**
- Create: `spike/carriers/liberty_mutual.py`
- Test: `tests/test_lm_pagestate.py`, fixtures under `tests/fixtures/lm/`

> Selectors/markers here are **best-effort** and explicitly recalibrated against the real DOM in Task B2. The classifier is structured so only the marker constants change, not the logic.

- [ ] **Step 1: Write the failing test (with synthetic fixtures)**

Create `tests/fixtures/lm/login_form.html`:
```html
<html><body><h1>Log in</h1>
<form><input name="username"><input name="password" type="password"></form>
</body></html>
```
Create `tests/fixtures/lm/mfa_prompt.html`:
```html
<html><body><h1>Verify your identity</h1>
<p>Enter the code we sent you.</p><input name="otp"></body></html>
```
Create `tests/fixtures/lm/documents.html`:
```html
<html><body><h1>Policy documents</h1>
<a href="/docs/dec-page.pdf">Declarations</a></body></html>
```

`tests/test_lm_pagestate.py`:
```python
from pathlib import Path

import pytest
from spike.carriers.liberty_mutual import LMPageState, classify_lm_page

FIX = Path(__file__).parent / "fixtures" / "lm"


@pytest.mark.parametrize("name,expected", [
    ("login_form.html", LMPageState.LOGIN_FORM),
    ("mfa_prompt.html", LMPageState.MFA_PROMPT),
    ("documents.html", LMPageState.DOCUMENTS),
])
def test_classify_lm_page(name, expected):
    html = (FIX / name).read_text()
    assert classify_lm_page(html, url="https://account.libertymutual.com/x") == expected


def test_unrecognized_page_is_other():
    assert classify_lm_page("<html><body>hello</body></html>", url="x") == LMPageState.OTHER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lm_pagestate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.carriers.liberty_mutual'`.

- [ ] **Step 3: Write minimal implementation**

`spike/carriers/liberty_mutual.py`:
```python
from __future__ import annotations

import re
from enum import StrEnum

# --- DOM markers: recalibrated against real DOM in Task B2 (spec §5.1) ---
_LOGIN_MARKERS = (r'name=["\']username["\']', r'type=["\']password["\']')
_MFA_MARKERS = (r"verify your identity", r"enter the code", r'name=["\']otp["\']')
_DOCS_MARKERS = (r"policy documents", r"declarations")


def _matches_any(html: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, html, re.IGNORECASE) for p in patterns)


class LMPageState(StrEnum):
    LOGIN_FORM = "LOGIN_FORM"
    MFA_PROMPT = "MFA_PROMPT"
    DOCUMENTS = "DOCUMENTS"
    OTHER = "OTHER"


def classify_lm_page(html: str, url: str) -> LMPageState:
    if _matches_any(html, _MFA_MARKERS):
        return LMPageState.MFA_PROMPT
    if _matches_any(html, _DOCS_MARKERS):
        return LMPageState.DOCUMENTS
    if all(re.search(p, html, re.IGNORECASE) for p in _LOGIN_MARKERS):
        return LMPageState.LOGIN_FORM
    return LMPageState.OTHER
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lm_pagestate.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/carriers/liberty_mutual.py tests/test_lm_pagestate.py tests/fixtures/lm
git commit -m "feat(spike): LM page-state classifier with synthetic fixtures"
```

---

## Task A5: Document-URL discovery

**Files:**
- Modify: `spike/carriers/liberty_mutual.py`
- Test: `tests/test_lm_docdiscovery.py`

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/lm/documents_list.html`:
```html
<html><body>
<ul>
  <li><a href="/account/docs/dec-page.pdf">2026 Declarations Page</a></li>
  <li><a href="https://account.libertymutual.com/docs/idcard.pdf">ID Card</a></li>
  <li><a href="/account/help">Help (not a doc)</a></li>
</ul>
</body></html>
```

`tests/test_lm_docdiscovery.py`:
```python
from pathlib import Path

from spike.carriers.liberty_mutual import DocumentRef, discover_document_urls

FIX = Path(__file__).parent / "fixtures" / "lm"


def test_discovers_pdf_links_and_resolves_relative():
    html = (FIX / "documents_list.html").read_text()
    refs = discover_document_urls(html, base_url="https://account.libertymutual.com/account")
    urls = {r.url for r in refs}
    assert "https://account.libertymutual.com/account/docs/dec-page.pdf" in urls
    assert "https://account.libertymutual.com/docs/idcard.pdf" in urls
    assert all(isinstance(r, DocumentRef) for r in refs)


def test_ignores_non_pdf_links():
    html = (FIX / "documents_list.html").read_text()
    refs = discover_document_urls(html, base_url="https://account.libertymutual.com/account")
    assert all(r.url.endswith(".pdf") for r in refs)
    assert len(refs) == 2


def test_names_come_from_link_text():
    html = (FIX / "documents_list.html").read_text()
    refs = discover_document_urls(html, base_url="https://account.libertymutual.com/account")
    names = {r.name for r in refs}
    assert "2026 Declarations Page" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lm_docdiscovery.py -v`
Expected: FAIL — `ImportError: cannot import name 'DocumentRef'`.

- [ ] **Step 3: Write minimal implementation**

Add to `spike/carriers/liberty_mutual.py`:
```python
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass(frozen=True)
class DocumentRef:
    name: str
    url: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None


def discover_document_urls(html: str, base_url: str) -> list[DocumentRef]:
    parser = _AnchorParser()
    parser.feed(html)
    refs: list[DocumentRef] = []
    for href, text in parser.links:
        absolute = urljoin(base_url + "/", href)
        if absolute.lower().endswith(".pdf"):
            refs.append(DocumentRef(name=text or absolute, url=absolute))
    return refs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lm_docdiscovery.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/carriers/liberty_mutual.py tests/test_lm_docdiscovery.py tests/fixtures/lm/documents_list.html
git commit -m "feat(spike): policy-document URL discovery from portal HTML"
```

---

## Task A6: Latency timer (injected clock)

**Files:**
- Create: `spike/timing.py`
- Test: `tests/test_timing.py`

- [ ] **Step 1: Write the failing test (fake clock — no real sleep)**

`tests/test_timing.py`:
```python
from spike.timing import Timer


def test_timer_records_duration_with_fake_clock():
    ticks = iter([100.0, 103.5])  # start reads 100.0, stop reads 103.5 -> 3.5
    timer = Timer(clock=lambda: next(ticks))
    timer.start("mfa_to_pdf")
    assert timer.stop("mfa_to_pdf") == 3.5
    assert timer.durations["mfa_to_pdf"] == 3.5


def test_timer_to_dict_is_serializable():
    ticks = iter([0.0, 2.0])
    timer = Timer(clock=lambda: next(ticks))
    timer.start("login")
    timer.stop("login")
    assert timer.to_dict() == {"login": 2.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_timing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.timing'`.

- [ ] **Step 3: Write minimal implementation**

`spike/timing.py`:
```python
from __future__ import annotations

from collections.abc import Callable


class Timer:
    """Latency timer with an injected clock for deterministic tests."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._starts: dict[str, float] = {}
        self.durations: dict[str, float] = {}

    def start(self, label: str) -> None:
        self._starts[label] = self._clock()

    def stop(self, label: str) -> float:
        elapsed = self._clock() - self._starts[label]
        self.durations[label] = elapsed
        return elapsed

    def to_dict(self) -> dict[str, float]:
        return dict(self.durations)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_timing.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/timing.py tests/test_timing.py
git commit -m "feat(spike): injected-clock latency timer"
```

---

## Task A7: Browserbase session-params builder

**Files:**
- Create: `spike/browserbase.py`
- Test: `tests/test_browserbase_params.py`

- [ ] **Step 1: Write the failing test**

`tests/test_browserbase_params.py`:
```python
from spike.browserbase import build_session_params
from spike.config import Config

CFG = Config(
    browserbase_api_key="bb_x", browserbase_project_id="proj_1",
    lm_username="u", lm_password="p",
    lm_login_url="https://www.libertymutual.com/log-in", browserbase_context_id=None,
)


def test_params_request_residential_us_proxy():
    params = build_session_params(CFG)
    assert params["projectId"] == "proj_1"
    proxies = params["proxies"]
    assert isinstance(proxies, list) and proxies[0]["geolocation"]["country"] == "US"


def test_params_omit_context_when_absent():
    params = build_session_params(CFG)
    assert "context" not in params["browserSettings"]


def test_params_include_persistent_context_when_id_given():
    params = build_session_params(CFG, context_id="ctx_9")
    ctx = params["browserSettings"]["context"]
    assert ctx == {"id": "ctx_9", "persist": True}


def test_advanced_stealth_off_by_default_on_by_request():
    assert "advancedStealth" not in build_session_params(CFG)["browserSettings"]
    assert build_session_params(CFG, advanced_stealth=True)["browserSettings"]["advancedStealth"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_browserbase_params.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.browserbase'`.

- [ ] **Step 3: Write minimal implementation**

`spike/browserbase.py`:
```python
from __future__ import annotations

from typing import Any

from spike.config import Config


def build_session_params(
    config: Config,
    context_id: str | None = None,
    advanced_stealth: bool = False,
) -> dict[str, Any]:
    """Build the Browserbase create-session payload.

    Residential proxy + US geolocation is the baseline (spec §3). advanced_stealth
    (Browserbase "Verified", Scale-gated) is an escalation lever, off by default
    per the start-cheap budget posture (spec §2).
    """
    browser_settings: dict[str, Any] = {}
    if context_id is not None:
        browser_settings["context"] = {"id": context_id, "persist": True}
    if advanced_stealth:
        browser_settings["advancedStealth"] = True
    return {
        "projectId": config.browserbase_project_id,
        "proxies": [{"type": "browserbase", "geolocation": {"country": "US"}}],
        "keepAlive": True,
        "browserSettings": browser_settings,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_browserbase_params.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/browserbase.py tests/test_browserbase_params.py
git commit -m "feat(spike): Browserbase session-params builder (residential/US, escalatable stealth)"
```

---

## Task A8: Lockout rail + gate evaluation

**Files:**
- Create: `spike/gate.py`
- Test: `tests/test_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_gate.py`:
```python
import pytest
from spike.gate import (
    AttemptGuard,
    GateOutcome,
    LockoutError,
    evaluate_gate,
)


def test_attempt_guard_allows_one_then_blocks():
    guard = AttemptGuard(max_attempts=1)
    guard.use()  # ok
    with pytest.raises(LockoutError):
        guard.use()


def test_gate_pass_requires_renders_and_completion():
    r = evaluate_gate(form_renders_ok=3, completions=1, bot_blocked=False)
    assert r.outcome is GateOutcome.PASS


def test_gate_fail_when_bot_blocked():
    r = evaluate_gate(form_renders_ok=3, completions=1, bot_blocked=True)
    assert r.outcome is GateOutcome.FAIL
    assert "block" in r.reason.lower()


def test_gate_fail_without_enough_renders():
    r = evaluate_gate(form_renders_ok=2, completions=1, bot_blocked=False)
    assert r.outcome is GateOutcome.FAIL


def test_gate_fail_without_completion():
    r = evaluate_gate(form_renders_ok=3, completions=0, bot_blocked=False)
    assert r.outcome is GateOutcome.FAIL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'spike.gate'`.

- [ ] **Step 3: Write minimal implementation**

`spike/gate.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LockoutError(Exception):
    """Raised when a second login attempt is requested (spec §3 safety rail)."""


class AttemptGuard:
    """Permits at most `max_attempts` password submissions, then refuses."""

    def __init__(self, max_attempts: int = 1) -> None:
        self._max = max_attempts
        self._used = 0

    def use(self) -> None:
        if self._used >= self._max:
            raise LockoutError(
                f"login attempt cap ({self._max}) reached — aborting to avoid account lockout"
            )
        self._used += 1


class GateOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class GateResult:
    outcome: GateOutcome
    reason: str


def evaluate_gate(
    form_renders_ok: int,
    completions: int,
    bot_blocked: bool,
    min_renders: int = 3,
) -> GateResult:
    """Pre-committed gate rule (spec §3): PASS = >=min_renders clean form renders
    AND >=1 full proxied completion AND not hard-blocked."""
    if bot_blocked:
        return GateResult(GateOutcome.FAIL, "hosted browser was hard-blocked at the bot gate")
    if form_renders_ok < min_renders:
        return GateResult(GateOutcome.FAIL, f"only {form_renders_ok}/{min_renders} clean form renders")
    if completions < 1:
        return GateResult(GateOutcome.FAIL, "no full login->MFA->PDF completion through proxied egress")
    return GateResult(GateOutcome.PASS, "reliable form renders + >=1 proxied completion")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gate.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add spike/gate.py tests/test_gate.py
git commit -m "feat(spike): lockout attempt-guard + pre-committed gate evaluation"
```

---

## Phase A checkpoint: simplify + verify

- [ ] **Step 1: Simplify** — review all `spike/*.py` for duplication/clarity (e.g., shared regex helpers, consistent `from __future__ import annotations`). Fix inline; note non-trivial simplifications in the commit.
- [ ] **Step 2: Verify the full gauntlet**

Run:
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy spike
uv run pytest -q
```
Expected: ruff clean, mypy clean (strict), all tests pass. **Record the actual output as evidence.**

- [ ] **Step 3: Commit any simplifications**

```bash
git add -A && git commit -m "refactor(spike): simplify Phase A machinery post-review"
```

> **Phase A is now complete and verifiable with zero secrets or paid services.** This is the right point to (a) merge Phase A to the spike branch, and (b) confirm Browserbase signup + a consented/expendable account are ready before Phase B.

---

# PHASE B — Live integration & the spike run (GATED)

> **Do not start Phase B until:** Browserbase account exists + API key/project id in `.env`; the LM test account is **consented and expendable** (spec §9); creds in `.env`. Phase B tasks are validated by **running with captured evidence**, not by offline unit tests (they need real creds, MFA, and a paid browser). Each writes artifacts to `spike/out/`.
>
> **SDK-surface caveat:** the Browserbase calls below (`bb.sessions.create(**params)`, `session.connect_url`/`session.id`, `bb.contexts.create(...)`, and the exact param keys in `build_session_params`) are the *expected* shape and **must be confirmed against the installed SDK version + current docs** as Task B1 Step 1 — their API evolves. If a key/attribute differs, adjust `build_session_params` (re-run its Task A7 tests) and the live wrappers accordingly. This is wiring confirmation, not a redesign.

## Task B1: Browserbase connect + proxy/egress pre-flight (no carrier yet)

**Files:**
- Modify: `spike/browserbase.py` (add `create_session`, `connect`)

- [ ] **Step 1: Add the live wrappers**

Add to `spike/browserbase.py`:
```python
from browserbase import Browserbase
from playwright.sync_api import Browser, sync_playwright


def create_session(config: Config, context_id: str | None = None,
                   advanced_stealth: bool = False) -> tuple[str, str]:
    """Create a Browserbase session; return (session_id, connect_url)."""
    bb = Browserbase(api_key=config.browserbase_api_key)
    params = build_session_params(config, context_id, advanced_stealth)
    session = bb.sessions.create(**params)  # type: ignore[arg-type]
    return session.id, session.connect_url
```

- [ ] **Step 2: Egress pre-flight script (proves residential/US, NOT our IP)**

Create `spike/preflight.py`:
```python
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

from spike.browserbase import create_session
from spike.config import load_config


def main() -> None:
    cfg = load_config(os.environ)
    session_id, connect_url = create_session(cfg)
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(connect_url)
        page = browser.contexts[0].pages[0]
        page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded")
        print("egress ip:", page.inner_text("body"))
        page.goto(cfg.lm_login_url, wait_until="domcontentloaded")
        page.screenshot(path="spike/out/preflight_lm_login.png")
        print("session:", session_id)
        browser.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the pre-flight**

Run:
```bash
mkdir -p spike/out
set -a && source .env && set +a
uv run python -m spike.preflight
```
Expected evidence: printed egress IP is a **US residential** IP (not your home/datacenter IP); `spike/out/preflight_lm_login.png` shows the **rendered LM login form** (criterion 1, render #1). If it shows Akamai "Access Denied"/CAPTCHA → record it; this is the first real signal and may trigger the §2 escalation decision.

- [ ] **Step 4: Commit (code only — `spike/out/` is git-ignored)**

```bash
git add spike/browserbase.py spike/preflight.py
git commit -m "feat(spike): Browserbase live session + egress/render pre-flight"
```

---

## Task B2: LM selector calibration + bot-gate reliability (criterion 1, ≥3 renders)

**Files:**
- Modify: `spike/carriers/liberty_mutual.py` (add nav functions + real selectors)

- [ ] **Step 1: Calibrate selectors via Live View**

Open the Browserbase **Live View** for a session (dashboard or the session's `debuggerUrl`). Navigate to `LM_LOGIN_URL`, inspect the real DOM, and record exact selectors for: username field, password field, submit button, MFA code field, MFA submit, and the documents-area landmark. Update `_LOGIN_MARKERS / _MFA_MARKERS / _DOCS_MARKERS` in `liberty_mutual.py` to match the real DOM, and re-run the Task A4/A5 tests (they must still pass against the synthetic fixtures, or update fixtures to mirror real structure).

- [ ] **Step 2: Add navigation functions**

Add to `spike/carriers/liberty_mutual.py` (fill the `SEL_*` constants from Step 1):
```python
from playwright.sync_api import Page

# Exact selectors confirmed via Live View (Task B2 Step 1):
SEL_USERNAME = "input[name='username']"
SEL_PASSWORD = "input[name='password']"
SEL_SUBMIT = "button[type='submit']"
SEL_MFA_CODE = "input[name='otp']"
SEL_MFA_SUBMIT = "button[type='submit']"


def goto_login(page: Page, login_url: str) -> None:
    page.goto(login_url, wait_until="domcontentloaded")


def submit_credentials(page: Page, username: str, password: str) -> None:
    page.fill(SEL_USERNAME, username)
    page.fill(SEL_PASSWORD, password)
    page.click(SEL_SUBMIT)


def submit_mfa(page: Page, code: str) -> None:
    page.fill(SEL_MFA_CODE, code)
    page.click(SEL_MFA_SUBMIT)
```

- [ ] **Step 3: Run the reliability check ×3 (NO credential submission)**

Create `spike/check_render.py`:
```python
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

from spike.browserbase import create_session
from spike.carriers.liberty_mutual import LMPageState, classify_lm_page
from spike.config import load_config


def main() -> None:
    cfg = load_config(os.environ)
    for i in range(3):  # 3 FRESH sessions; no Context, no credentials
        session_id, connect_url = create_session(cfg)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(connect_url)
            page = browser.contexts[0].pages[0]
            page.goto(cfg.lm_login_url, wait_until="domcontentloaded")
            state = classify_lm_page(page.content(), page.url)
            page.screenshot(path=f"spike/out/render_{i}.png")
            print(f"render {i}: state={state} url={page.url}")
            browser.close()


if __name__ == "__main__":
    main()
```
Run:
```bash
set -a && source .env && set +a
uv run python -m spike.check_render
```
Expected evidence: 3 runs each printing `state=LOGIN_FORM` with a screenshot. That satisfies **criterion 1** (bot-gate reliability) without spending a login attempt. Any `Access Denied`/CAPTCHA → classify with `spike.challenge` and record; decide on §2 escalation.

- [ ] **Step 4: Commit (code only)**

```bash
git add spike/carriers/liberty_mutual.py spike/check_render.py
git commit -m "feat(spike): LM nav functions + bot-gate reliability check (criterion 1)"
```

---

## Task B3: Full happy-path run — login → MFA → fetch PDF (criterion 2; uses 1 attempt)

**Files:**
- Modify: `spike/docfetch.py` (add `fetch_pdf_in_page`)
- Create: `spike/run_liberty.py`

- [ ] **Step 1: Add the proxied in-page fetch (spec §5.3 path 1)**

Add to `spike/docfetch.py`:
```python
from playwright.sync_api import Page


def fetch_pdf_in_page(page: Page, url: str) -> bytes:
    """Fetch a PDF FROM INSIDE the remote browser so it rides the proxy + fingerprint.
    Returns decoded bytes. (Never use context.request — that egresses from our IP.)"""
    b64 = page.evaluate(
        """async (u) => {
            const r = await fetch(u, {credentials: 'include'});
            const buf = await r.arrayBuffer();
            let binary = '';
            const bytes = new Uint8Array(buf);
            for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
            return btoa(binary);
        }""",
        url,
    )
    return decode_base64_pdf(b64)
```

- [ ] **Step 2: Write the orchestrator**

Create `spike/run_liberty.py`:
```python
from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from spike.browserbase import create_session
from spike.carriers.liberty_mutual import (
    LMPageState,
    classify_lm_page,
    discover_document_urls,
    goto_login,
    submit_credentials,
    submit_mfa,
)
from spike.config import load_config
from spike.docfetch import fetch_pdf_in_page, is_valid_pdf
from spike.gate import AttemptGuard, LockoutError
from spike.timing import Timer

OUT = Path("spike/out")


def main() -> None:
    cfg = load_config(os.environ)
    OUT.mkdir(parents=True, exist_ok=True)
    timer = Timer(clock=time.monotonic)
    guard = AttemptGuard(max_attempts=1)

    session_id, connect_url = create_session(cfg, context_id=cfg.browserbase_context_id)
    print("session:", session_id)
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(connect_url)
        page = browser.contexts[0].pages[0]

        goto_login(page, cfg.lm_login_url)
        page.screenshot(path=str(OUT / "01_login.png"))

        guard.use()  # spec §3 rail: at most ONE submission
        submit_credentials(page, cfg.lm_username, cfg.lm_password)
        page.wait_for_load_state("networkidle")
        state = classify_lm_page(page.content(), page.url)
        page.screenshot(path=str(OUT / "02_after_login.png"))
        if state != LMPageState.MFA_PROMPT:
            print(f"ABORT: expected MFA, got {state} — not retrying (lockout rail)")
            browser.close()
            return

        code = input("Enter MFA code: ").strip()
        timer.start("mfa_to_pdf")
        submit_mfa(page, code)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "03_documents.png"))

        refs = discover_document_urls(page.content(), base_url=page.url)
        if not refs:
            print("ABORT: no policy documents discovered")
            browser.close()
            return
        pdf = fetch_pdf_in_page(page, refs[0].url)
        elapsed = timer.stop("mfa_to_pdf")
        assert is_valid_pdf(pdf), "fetched bytes are not a valid PDF"
        (OUT / "policy.pdf").write_bytes(pdf)
        print(f"OK: saved {refs[0].name} ({len(pdf)} bytes), mfa->pdf={elapsed:.2f}s")
        print("context id (set BROWSERBASE_CONTEXT_ID to reuse):", session_id)
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except LockoutError as exc:
        print("LOCKOUT RAIL:", exc)
```

- [ ] **Step 3: Run the full happy path (uses one real login attempt)**

Run:
```bash
set -a && source .env && set +a
uv run python -m spike.run_liberty
```
Expected evidence: prompts for MFA, then prints `OK: saved ... mfa->pdf=N.NNs`; `spike/out/policy.pdf` is a valid, openable PDF; screenshots `01/02/03`. This is **criterion 2** + the **criterion 4** latency sample. On any login failure it aborts (no retry).

- [ ] **Step 4: Commit (code only)**

```bash
git add spike/docfetch.py spike/run_liberty.py
git commit -m "feat(spike): orchestrator — login->MFA->proxied PDF fetch (criteria 2,4)"
```

---

## Task B4: Session-reuse runs (criterion 3 + warm latency)

- [ ] **Step 1: Capture the Context id for reuse**

Browserbase persists cookies via a **Context**. To reuse, the first run must create a Context and you set `BROWSERBASE_CONTEXT_ID` in `.env` to it. If `create_session` returned a session rather than a reusable context id, create a Context up front:
```bash
# one-time: create a persistent context and copy its id into .env
uv run python -c "import os; from browserbase import Browserbase; \
print(Browserbase(api_key=os.environ['BROWSERBASE_API_KEY']).contexts.create(project_id=os.environ['BROWSERBASE_PROJECT_ID']).id)"
```
Set the printed id as `BROWSERBASE_CONTEXT_ID` in `.env`, then run `spike.run_liberty` once (Task B3) so the context stores authenticated cookies.

- [ ] **Step 2: Re-run ×2 and record carrier re-challenge behavior**

Run (twice), with `BROWSERBASE_CONTEXT_ID` set:
```bash
set -a && source .env && set +a
uv run python -m spike.run_liberty   # run #1 (reuse)
uv run python -m spike.run_liberty   # run #2 (reuse)
```
Expected evidence: record for each whether the run reached documents **without** a fresh MFA prompt (criterion 3 = pass) or was re-challenged (documented limitation, not a kill), plus the reattach→PDF latency. The orchestrator already classifies the post-load page state; note whether `MFA_PROMPT` reappeared.

- [ ] **Step 3: No code change expected** — if reuse needs a code tweak (e.g., skip credential submission when already authenticated), add a branch in `run_liberty.py` that checks `classify_lm_page` *before* `guard.use()` and skips login when the documents area is already reachable. Commit only if changed.

---

## Task B5: Results writeup + go/no-go

**Files:**
- Create: `spike/out/RESULTS.md` (git-ignored; this is the deliverable artifact)

- [ ] **Step 1: Write `spike/out/RESULTS.md`** with these named fields (spec §8):
  - Pass/fail per criterion 1–5.
  - MFA channel observed (SMS/email/app).
  - Which §5.3 fetch path worked.
  - Latency: cold vs warm; MFA→PDF and reattach→PDF (with sample sizes).
  - Reuse: did the carrier re-challenge?
  - Structured failure classification (if any): `challenge.to_fields(...)` output — Akamai `_abck` state, Auth0 challenge type, HTTP status, CAPTCHA presence, screenshot path.
  - Browserbase tier used; whether §2 escalation was triggered.
  - **Verdict computed via `evaluate_gate(form_renders_ok=..., completions=..., bot_blocked=...)`** (A8) — paste the `GateResult.outcome` + `reason`, so the go/no-go is the pre-committed rule applied to the observed counts, not a judgment call.
  - **Go/no-go recommendation for Phase 0b (Geico).**

- [ ] **Step 2: Final verify**

Run:
```bash
uv run ruff check . && uv run mypy spike && uv run pytest -q
```
Expected: all clean (Phase B added live code; offline tests still pass).

- [ ] **Step 3: Commit the spike code state**

```bash
git add -A && git commit -m "chore(spike): finalize Phase 0a; results captured in spike/out (git-ignored)"
```

---

## Spec Coverage Self-Check

- Criterion 1 (≥3 clean renders, no submit) → Task B2 Step 3. ✓
- Criterion 2 (full proxied completion + PDF) → Task B3. ✓
- Criterion 3 (reuse re-challenge finding) → Task B4. ✓
- Criterion 4 (latency, cold/warm, small-n) → Task B3 + B4 + Timer (A6). ✓
- Criterion 5 (structured evidence) → challenge (A3) + B5. ✓
- Gate rule as code → `evaluate_gate` (A8). ✓
- Lockout rail → `AttemptGuard` + orchestrator `guard.use()` (A8, B3). ✓
- Proxied egress (M1 fix) → `fetch_pdf_in_page` in-page fetch (B3). ✓
- Start-cheap stealth posture → `advanced_stealth` default off (A7). ✓
- Secrets/PII handling → `.env`/`.env.example`/`spike/out/` git-ignored (A0). ✓
- Offline tests for machinery → A1–A8. ✓

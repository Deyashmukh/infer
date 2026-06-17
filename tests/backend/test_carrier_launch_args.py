"""Per-carrier Chromium launch args: LM forces HTTP/1.1, Geico runs HTTP/2.

Uses a fake Playwright so the composition in ChromiumDriver._ensure is verified without
launching a real browser.
"""

from __future__ import annotations

from typing import Any

import pytest

import backend.chromium_driver as cd
from backend.carriers import geico, lm
from spike.config import load_config

_AUTOMATION_FLAG = "--disable-blink-features=AutomationControlled"


class _FakePage:
    async def evaluate(self, script: str) -> str:
        return "Mozilla/5.0 (X11) HeadlessChrome/120.0 Safari/537.36"


class _FakeContext:
    async def new_page(self) -> _FakePage:
        return _FakePage()

    async def add_init_script(self, script: str) -> None:
        return None

    async def close(self) -> None:
        return None


class _FakeBrowser:
    async def new_context(self, **kwargs: Any) -> _FakeContext:
        return _FakeContext()

    async def close(self) -> None:
        return None


class _FakeChromium:
    def __init__(self, rec: dict[str, Any]) -> None:
        self._rec = rec

    async def launch(self, *, headless: bool, args: list[str]) -> _FakeBrowser:
        self._rec["args"] = args
        return _FakeBrowser()


class _FakePlaywright:
    def __init__(self, rec: dict[str, Any]) -> None:
        self.chromium = _FakeChromium(rec)

    async def stop(self) -> None:
        return None


class _FakeFactory:
    def __init__(self, rec: dict[str, Any]) -> None:
        self._rec = rec

    async def start(self) -> _FakePlaywright:
        return _FakePlaywright(self._rec)


async def _launch_args(
    monkeypatch: pytest.MonkeyPatch, carrier: str, env: dict[str, str]
) -> list[str]:
    rec: dict[str, Any] = {}
    monkeypatch.setattr(cd, "async_playwright", lambda: _FakeFactory(rec))
    cfg = load_config({"LM_LOGIN_URL": "https://x", **env})
    driver = cd.ChromiumDriver(cfg, carrier)
    await driver._ensure()
    return list(rec["args"])


def test_carrier_launch_args_constants() -> None:
    # LM forces HTTP/1.1 (its Cloudflare login edge rejects h2); Geico runs HTTP/2.
    assert lm.LAUNCH_ARGS == ["--disable-http2"]
    assert geico.LAUNCH_ARGS == []


async def test_geico_runs_http2_no_disable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    args = await _launch_args(monkeypatch, "geico", {})
    assert "--disable-http2" not in args
    assert _AUTOMATION_FLAG in args


async def test_lm_forces_http1(monkeypatch: pytest.MonkeyPatch) -> None:
    args = await _launch_args(monkeypatch, "liberty_mutual", {})
    assert "--disable-http2" in args
    assert _AUTOMATION_FLAG in args


async def test_global_args_compose_with_carrier_args(monkeypatch: pytest.MonkeyPatch) -> None:
    args = await _launch_args(monkeypatch, "geico", {"CHROMIUM_ARGS": "--no-sandbox"})
    assert "--no-sandbox" in args  # global infra arg
    assert "--disable-http2" not in args  # carrier still drives the network fingerprint

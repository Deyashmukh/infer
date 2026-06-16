from __future__ import annotations

from collections.abc import Callable
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, ProxySettings, async_playwright

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
            proxy: ProxySettings | None = None
            if self._cfg.proxy_server:
                proxy = ProxySettings(
                    server=self._cfg.proxy_server,
                    username=self._cfg.proxy_username or "",
                    password=self._cfg.proxy_password or "",
                )
            self._ctx = await self._browser.new_context(accept_downloads=True, proxy=proxy)
            self._page = await self._ctx.new_page()
        return self._page

    async def open_login(self, login_url: str) -> None:
        raise NotImplementedError  # filled in the next task

    async def submit_credentials(self, username: str, password: str) -> AuthStep:
        raise NotImplementedError  # filled in the next task

    async def submit_mfa(self, code: str) -> AuthStep:
        raise NotImplementedError  # filled in the next task

    async def list_documents(self) -> list[DocRef]:
        raise NotImplementedError  # filled in the next task

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        raise NotImplementedError  # filled in the next task

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
        self._page = self._ctx = None

def make_chromium_driver_factory(cfg: Config) -> Callable[[], ChromiumDriver]:
    def factory() -> ChromiumDriver:
        return ChromiumDriver(cfg)
    return factory

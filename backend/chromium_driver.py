from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    ProxySettings,
    StorageState,
    async_playwright,
)

from backend.browser import AuthStep, CarrierModule, DocRef, FetchedDoc
from backend.carriers import registry
from spike.config import Config


class ChromiumDriver:
    def __init__(self, cfg: Config, carrier: str) -> None:
        self._cfg = cfg
        self._carrier: CarrierModule = registry.carrier_module(carrier)
        self._pw: Any = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    async def _ensure(self, storage_state: StorageState | None = None) -> Page:
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
            self._ctx = await self._browser.new_context(
                accept_downloads=True,
                proxy=proxy,
                storage_state=storage_state,
            )
            self._page = await self._ctx.new_page()
        return self._page

    async def open_login(self, login_url: str) -> None:
        page = await self._ensure()
        await self._carrier.open_login(page, login_url)

    async def submit_credentials(self, username: str, password: str) -> AuthStep:
        page = await self._ensure()
        return await self._carrier.submit_credentials(page, username, password)

    async def submit_mfa(self, code: str) -> AuthStep:
        page = await self._ensure()
        return await self._carrier.submit_mfa(page, code)

    async def list_documents(self) -> list[DocRef]:
        page = await self._ensure()
        return await self._carrier.list_documents(page)

    async def fetch_document(self, ref: DocRef) -> FetchedDoc:
        page = await self._ensure()
        assert self._ctx is not None  # guaranteed by _ensure
        return await self._carrier.fetch_document(self._ctx, page, ref)

    async def storage_state(self) -> dict[str, Any]:
        assert self._ctx is not None, "storage_state() called before browser was opened"
        # StorageState is a TypedDict (subtype of dict); cast to satisfy the Protocol.
        raw: StorageState = await self._ctx.storage_state()
        return dict(raw)

    async def try_resume(self, state: dict[str, Any]) -> bool:
        """Load *state* into a fresh context and check if the session is still live.

        Creates (or recreates) the browser context with the cached storage state,
        then delegates to the carrier's is_authenticated check.  Returns True if
        the documents page is reachable without login; False if the session has
        expired.  Never submits credentials.
        """
        # StorageState is a TypedDict; narrow via cast so _ensure sees the right type.
        page = await self._ensure(storage_state=cast(StorageState, state))
        return await self._carrier.is_authenticated(page)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
        self._page = self._ctx = None


def make_chromium_driver_factory(cfg: Config) -> Callable[[str], ChromiumDriver]:
    def factory(carrier: str) -> ChromiumDriver:
        return ChromiumDriver(cfg, carrier)
    return factory

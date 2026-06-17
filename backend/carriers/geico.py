"""Geico carrier stub — real flow pending portal recon.

Each function mirrors the exact signature of carriers/lm.py.
"""

from __future__ import annotations

from playwright.async_api import BrowserContext, Page

from backend.browser import AuthStep, DocRef, FetchedDoc


async def open_login(page: Page, login_url: str) -> None:
    raise NotImplementedError("Geico flow not yet implemented — pending portal recon")


async def submit_credentials(page: Page, username: str, password: str) -> AuthStep:
    raise NotImplementedError("Geico flow not yet implemented — pending portal recon")


async def submit_mfa(page: Page, code: str) -> AuthStep:
    raise NotImplementedError("Geico flow not yet implemented — pending portal recon")


async def list_documents(page: Page) -> list[DocRef]:
    raise NotImplementedError("Geico flow not yet implemented — pending portal recon")


async def fetch_document(ctx: BrowserContext, page: Page, ref: DocRef) -> FetchedDoc:
    raise NotImplementedError("Geico flow not yet implemented — pending portal recon")

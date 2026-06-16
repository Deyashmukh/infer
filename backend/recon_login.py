"""Throwaway recon: click LM's "Log in" CTA and inspect the auth page.

No credentials, free-plan (no proxy) by default. Tells us (a) whether the
Akamai/Auth0 auth page loads from a datacenter IP or gets blocked, and (b) the
form selectors to calibrate backend/carriers/lm.py. Delete after calibration.

    set -a && source .env && set +a && PREFLIGHT_PROXY=0 uv run python -m backend.recon_login
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from spike.browserbase import create_session, release_session
from spike.config import load_config

OUT = Path("spike/out")
_DUMP_JS = """() => {
  const grab = (el) => ({
    tag: el.tagName.toLowerCase(), type: el.getAttribute('type'),
    name: el.getAttribute('name'), id: el.id || null,
    placeholder: el.getAttribute('placeholder'),
    autocomplete: el.getAttribute('autocomplete'),
    aria: el.getAttribute('aria-label'),
    text: (el.innerText || el.value || '').trim().slice(0, 40) || null,
  });
  return {
    inputs: [...document.querySelectorAll('input')].map(grab),
    buttons: [...document.querySelectorAll('button, a[role=button], input[type=submit]')].map(grab),
  };
}"""


async def _click_login(page: Page) -> str:
    for role, name in (("button", "Log in"), ("link", "Log in"), ("button", "Log In")):
        loc = page.get_by_role(role, name=name)  # type: ignore[arg-type]
        if await loc.count() > 0:
            await loc.first.click()
            return f"{role}:{name}"
    # fallback: any clickable with that text
    await page.locator("a:has-text('Log in'), button:has-text('Log in')").first.click()
    return "text-fallback"


async def main() -> None:
    cfg = load_config(os.environ)
    use_proxy = os.environ.get("PREFLIGHT_PROXY", "1") == "1"
    OUT.mkdir(parents=True, exist_ok=True)
    sid, connect_url = create_session(cfg, use_proxy=use_proxy)
    out: dict[str, Any] = {"proxy": use_proxy}
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(connect_url)
        try:
            page = browser.contexts[0].pages[0]
            await page.goto(cfg.lm_login_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            out["landing_ctas"] = await page.evaluate(_DUMP_JS)
            out["clicked"] = await _click_login(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as exc:
                out["wait_warning"] = f"{type(exc).__name__}: {exc}"
            await page.wait_for_timeout(2500)
            out["auth_url"] = page.url
            cookies = {c["name"]: c["value"] for c in await browser.contexts[0].cookies()}
            out["abck_state"] = cookies.get("_abck", "<absent>")[:40]
            body = (await page.inner_text("body")).lower()
            out["access_denied"] = "access denied" in body
            out["auth_form"] = await page.evaluate(_DUMP_JS)
            await page.screenshot(path=str(OUT / "recon_auth.png"))
        finally:
            await browser.close()
            release_session(cfg, sid)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

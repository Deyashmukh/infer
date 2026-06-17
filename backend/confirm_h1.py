"""Final confirmation: does forcing HTTP/1.1 (--disable-http2) let the FULL login
COMPLETE (credentials -> MFA -> authenticated account)? Local Chromium, longer waits,
the whole flow. The matrix proved --disable-http2 removes ERR_HTTP2_PROTOCOL_ERROR
but only checked the 10s post-creds state; this goes all the way to the account.

If this reaches the account, the fix is: a self-hosted browser launched with
--disable-http2 (this script IS the prototype of that driver).

PREREQ: uv run playwright install chromium
Real terminal (interactive creds + MFA):

    set -a && source .env && set +a && uv run python -m backend.confirm_h1
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import json
import os
import time
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Request, Response, async_playwright

from spike.carriers.liberty_mutual import discover_document_urls
from spike.config import load_config

OUT = Path("spike/out")
_OTP = (
    "input[autocomplete=one-time-code]",
    "input[name*=code i]",
    "input[id*=code i]",
    "input[inputmode=numeric]",
    "input[type=tel]",
)


async def _locate_otp(page: Page) -> Any:
    for sel in _OTP:
        loc = page.locator(sel)
        if await loc.count() > 0 and await loc.first.is_visible():
            return loc.first
    inputs = page.locator("input")
    for i in range(await inputs.count()):
        el = inputs.nth(i)
        if not await el.is_visible():
            continue
        itype = (await el.get_attribute("type") or "text").lower()
        iname = (await el.get_attribute("name") or "").lower()
        if itype in ("text", "tel", "number") and iname not in ("username", "password"):
            return el
    return None


async def main() -> None:
    cfg = load_config(os.environ)
    OUT.mkdir(parents=True, exist_ok=True)
    user = input("LM username/email: ").strip()
    pwd = getpass.getpass("LM password (hidden): ")
    failed: list[dict[str, str | None]] = []
    login_resp: dict[str, Any] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-http2"])
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()

            def on_failed(r: Request) -> None:
                failed.append({"u": r.url.split("?")[0][-55:], "f": r.failure})

            def on_resp(r: Response) -> None:
                if "usernamepassword/login" in r.url:
                    login_resp.update({"status": r.status})

            page.on("requestfailed", on_failed)
            page.on("response", on_resp)

            await page.goto(cfg.lm_login_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await page.get_by_role("link", name="Log in").first.click()
            await page.wait_for_selector("input[name=username]", timeout=30000)
            await page.fill("input[name=username]", user)
            await page.fill("input[name=password]", pwd)
            t0 = time.monotonic()
            await page.click("button[type=submit]")

            state = "TIMEOUT"
            for _ in range(30):  # up to 30s (HTTP/1.1 is slower than h2)
                await page.wait_for_timeout(1000)
                if await _locate_otp(page) is not None or "/mfa" in page.url:
                    state = "MFA"
                    break
                if "something went wrong" in (await page.inner_text("body")).lower():
                    state = "BOT_REJECT"
                    break
            await page.screenshot(path=str(OUT / "h1_postcreds.png"))
            lm_failed = [f for f in failed if "libertymutual" in str(f.get("u"))]
            print(f"\npost-creds state={state}  login_resp={login_resp}  lm_failed={lm_failed}")

            if state != "MFA":
                print(">>> Did not reach MFA. HTTP/1.1 did not complete the login this attempt.")
                return

            code = input("Enter the MFA code you received: ").strip()
            otp = await _locate_otp(page)
            if otp is None:
                print(">>> Could not locate the code field.")
                return
            # Type digit-by-digit (not fill): Auth0's client-side validation only
            # enables the "Continue" button on real per-keystroke events. fill()
            # sets the value in one shot and the button stays disabled.
            await otp.click()
            await otp.press_sequentially(code, delay=60)
            await page.wait_for_timeout(400)
            await otp.press("Enter")  # submit via keyboard; robust vs a disabled button

            authed = False
            for _ in range(30):
                await page.wait_for_timeout(1000)
                if "login.libertymutual.com" not in page.url and "/mfa" not in page.url:
                    authed = True  # left the Auth0 auth domain => MFA accepted
                    break
                btn = page.locator("button[type=submit]:not([disabled])")
                if await btn.count() > 0 and await btn.first.is_visible():
                    with contextlib.suppress(Exception):
                        await btn.first.click(timeout=2000)
            if authed:
                # The /account/auth?code=... URL is a transient OAuth-callback
                # handler; wait for it to redirect into the real dashboard before
                # we inspect navigation.
                for _ in range(20):
                    if "/account/auth" not in page.url:
                        break
                    await page.wait_for_timeout(1000)
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=15000)
                await page.wait_for_timeout(1500)
                # Persist the authenticated session (cookies + storage) so the rest
                # of the build can reuse it without re-running MFA. spike/out is
                # git-ignored; this file holds live session tokens — do not commit.
                session_state = await ctx.storage_state()
                (OUT / "lm_state.json").write_text(json.dumps(session_state))
                # Capture the documents-page HTML (in a separate tab so the main
                # page stays on the dashboard) as the Task-3 parser fixture source.
                # PII — sanitize before committing; spike/out is git-ignored.
                with contextlib.suppress(Exception):
                    doc_page = await ctx.new_page()
                    await doc_page.goto(
                        "https://eservice.libertymutual.com/accountmanager/documents",
                        wait_until="domcontentloaded",
                    )
                    await doc_page.wait_for_timeout(2500)
                    (OUT / "documents_real.html").write_text(await doc_page.content())
                    await doc_page.close()
                    print("    (documents-page HTML -> spike/out/documents_real.html)")
            await page.screenshot(path=str(OUT / "h1_postmfa.png"))
            docs = discover_document_urls(await page.content(), base_url=page.url)
            nav = await page.evaluate(
                "() => [...document.querySelectorAll('a[href]')]"
                ".map(a=>({href:a.href,"
                "text:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,60)}))"
                ".filter(x=>x.href && !x.href.startsWith('javascript')).slice(0,120)"
            )
            account = json.dumps({"url": page.url, "nav": nav}, default=str)
            (OUT / "h1_account.json").write_text(account)
            print(
                f"\n>>> AUTHENTICATED={authed}  url={page.url}  "
                f"creds->authed={time.monotonic() - t0:.0f}s  pdf_links={len(docs)}"
            )
            print("    (account nav -> spike/out/h1_account.json)")
            if authed:
                print("    (session saved -> spike/out/lm_state.json; reusable, no re-MFA)")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

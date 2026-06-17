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
import hashlib
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
    src_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
    print(f"[build check] confirm_h1 SRC={src_hash}  (compare to the value I gave you)")
    cfg = load_config(os.environ)
    OUT.mkdir(parents=True, exist_ok=True)
    user = input("LM username/email: ").strip()
    pwd = getpass.getpass("LM password (hidden): ")
    failed: list[dict[str, str | None]] = []
    login_resp: dict[str, Any] = {}
    login_sent = {"sent": False}  # did the /usernamepassword/login POST actually fire?

    async with async_playwright() as pw:
        launch_args = ["--disable-http2"]
        # PROXY_SERVER (e.g. socks5://127.0.0.1:1080) routes egress via the SSH-tunnel test.
        proxy_server = os.environ.get("PROXY_SERVER")
        if proxy_server:
            launch_args.append(f"--proxy-server={proxy_server}")
        browser = await pw.chromium.launch(headless=True, args=launch_args)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()

            def on_failed(r: Request) -> None:
                failed.append({"u": r.url.split("?")[0][-55:], "f": r.failure})

            def on_resp(r: Response) -> None:
                if "usernamepassword/login" in r.url:
                    login_resp.update({"status": r.status})

            def on_request(r: Request) -> None:
                if "usernamepassword/login" in r.url:
                    login_sent["sent"] = True

            page.on("requestfailed", on_failed)
            page.on("response", on_resp)
            page.on("request", on_request)

            egress = "?"
            with contextlib.suppress(Exception):
                await page.goto(
                    "https://api.ipify.org?format=text",
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                egress = (await page.inner_text("body")).strip()[:40]
            print(f"[egress] outbound IP this run = {egress}  (datacenter EC2 IP vs your home IP)")

            await page.goto(cfg.lm_login_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            # Robustly reach the Auth0 login form. The "Log in" click can silently
            # no-op if the landing page hasn't finished hydrating (slower in the EC2
            # container), so retry the click until the username field appears.
            for _ in range(5):
                with contextlib.suppress(Exception):
                    await page.get_by_role("link", name="Log in").first.click()
                with contextlib.suppress(Exception):
                    await page.wait_for_selector("input[name=username]", timeout=6000)
                if await page.locator("input[name=username]").count() > 0:
                    break
                await page.wait_for_timeout(1500)
            if await page.locator("input[name=username]").count() == 0:
                login_els = await page.evaluate(
                    "() => [...document.querySelectorAll('a,button')]"
                    ".filter(e => /log\\s*in/i.test(e.innerText || ''))"
                    ".map(e => ({tag: e.tagName, href: e.getAttribute('href') || '',"
                    " text: (e.innerText || '').trim().slice(0, 30), vis: !!e.offsetParent}))"
                )
                await page.screenshot(path=str(OUT / "h1_noform.png"))
                print(f"\n>>> login form never loaded.  url={page.url}")
                print(f"    login-ish elements: {login_els}")
                print("    (screenshot -> spike/out/h1_noform.png)")
                return
            await page.fill("input[name=username]", user)
            await page.fill("input[name=password]", pwd)
            await page.wait_for_timeout(400)  # let the form's JS attach its submit handler
            t0 = time.monotonic()
            await page.click("button[type=submit]")
            # A click landing before the login SPA wires up its submit handler
            # silently no-ops (observed on the datacenter run: login_resp stayed
            # empty and the page never left www.libertymutual.com -> 30s TIMEOUT).
            # Confirm the credential POST actually fired; re-click once if not.
            for _ in range(6):
                await page.wait_for_timeout(1000)
                if login_sent["sent"] or login_resp or "login.libertymutual.com" in page.url:
                    break
            else:
                with contextlib.suppress(Exception):
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
            print(
                f"\npost-creds state={state}  login_POST_sent={login_sent['sent']}  "
                f"login_resp={login_resp}  lm_failed={lm_failed}"
            )

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

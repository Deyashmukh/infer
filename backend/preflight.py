"""Egress + login-render pre-flight: the cheap first gate signal.

Does a hosted Browserbase browser (residential US proxy) reach Liberty Mutual's
login page without a hard block? Runs N fresh sessions, submits NO credentials
(zero lockout risk), and records egress IP, HTTP status, bot-challenge
classification, and a screenshot per run. Run with:

    set -a && source .env && set +a && uv run python -m backend.preflight
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from spike.browserbase import create_session
from spike.carriers.liberty_mutual import classify_lm_page
from spike.challenge import ChallengeSignals, classify_challenge
from spike.config import load_config

OUT = Path("spike/out")
RUNS = 3
_CAPTCHA_MARKERS = ("recaptcha", "hcaptcha", "/cdn-cgi/challenge", "px-captcha", "captcha")


async def _check(cfg: Any, i: int, use_proxy: bool) -> dict[str, Any]:
    # connect_url is a live bearer credential — never printed/logged.
    session_id, connect_url = create_session(cfg, use_proxy=use_proxy)
    result: dict[str, Any] = {"run": i, "session_id": session_id, "proxy": use_proxy}
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(connect_url)
        try:
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            ip_resp = await page.goto(
                "https://api.ipify.org?format=json", wait_until="domcontentloaded"
            )
            result["egress_ip"] = (await page.inner_text("body")) if ip_resp else "<no response>"

            resp = await page.goto(cfg.lm_login_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            body_text = await page.inner_text("body")
            cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
            signals = ChallengeSignals(
                url=page.url,
                status=resp.status if resp else 0,
                body_text=body_text,
                cookies=cookies,
                has_captcha=any(m in html.lower() for m in _CAPTCHA_MARKERS),
            )
            kind = classify_challenge(signals)
            result["final_url"] = page.url
            result["http_status"] = signals.status
            result["challenge"] = kind.value
            result["challenge_fields"] = kind.to_fields(signals)
            result["lm_page_state"] = classify_lm_page(html, page.url).value
            result["abck_present"] = "_abck" in cookies
            await page.screenshot(path=str(OUT / f"preflight_{i}.png"))
        finally:
            await browser.close()
    return result


async def main() -> None:
    cfg = load_config(os.environ)
    use_proxy = os.environ.get("PREFLIGHT_PROXY", "1") == "1"
    OUT.mkdir(parents=True, exist_ok=True)
    mode = "residential-US proxy" if use_proxy else "NO proxy (free-plan datacenter IP)"
    print(f"pre-flight mode: {mode}\n")
    runs: list[dict[str, Any]] = []
    for i in range(RUNS):
        try:
            r = await _check(cfg, i, use_proxy)
        except Exception as exc:
            r = {"run": i, "error": f"{type(exc).__name__}: {exc}"}
        runs.append(r)
        print(json.dumps(r, indent=2, default=str))
    (OUT / "preflight_results.json").write_text(json.dumps(runs, indent=2, default=str))
    clean = sum(1 for r in runs if r.get("challenge") == "NONE" and r.get("http_status") == 200)
    print(f"\n=== {clean}/{RUNS} runs reached LM login cleanly (HTTP 200, no challenge) ===")


if __name__ == "__main__":
    asyncio.run(main())

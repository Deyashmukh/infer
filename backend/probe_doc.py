"""Probe HOW a Liberty Mutual policy document is actually retrieved. Using the
saved session, click the documents-page actions ("Policy documents", then
"View / print") and capture the mechanism: a download event, a popup/new tab
holding a PDF URL, or an application/pdf response. This settles the doc-fetch
design — return URLs to the client vs. proxy the bytes through the backend.
Non-interactive; reuses spike/out/lm_state.json (no credentials, no MFA).

    uv run python -m backend.probe_doc
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

from playwright.async_api import Download, Page, Response, async_playwright

OUT = Path("spike/out")
STATE = OUT / "lm_state.json"
DOCS_URL = "https://eservice.libertymutual.com/accountmanager/documents"


async def main() -> None:
    if not STATE.exists():
        print(f">>> {STATE} not found — run backend.confirm_h1 first.")
        return
    events: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-http2"])
        try:
            ctx = await browser.new_context(storage_state=str(STATE), accept_downloads=True)
            page = await ctx.new_page()

            def on_pdf(r: Response) -> None:
                ct = (r.headers.get("content-type") or "").lower()
                cd = (r.headers.get("content-disposition") or "").lower()
                bare = r.url.lower().split("?")[0]
                if "application/pdf" in ct or "attachment" in cd or bare.endswith(".pdf"):
                    events.append(
                        {"kind": "response", "url": r.url[:160], "ct": ct[:40], "cd": cd[:70]}
                    )

            def on_download(d: Download) -> None:
                events.append(
                    {"kind": "download", "url": d.url[:160], "suggested": d.suggested_filename}
                )

            def on_popup(p: Page) -> None:
                events.append({"kind": "popup", "url": p.url[:160]})

            ctx.on("response", on_pdf)
            ctx.on("page", on_popup)
            page.on("download", on_download)

            await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=45000)
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(1500)

            # Click the first visible "View / print" action and watch what it
            # triggers. (Don't touch the "Policy documents" accordion header — it
            # collapses the section and hides these buttons.)
            loc = page.locator(":is(button,a)", has_text="View / print")
            clicked = None
            for i in range(await loc.count()):
                item = loc.nth(i)
                if await item.is_visible():
                    clicked = "View / print"
                    with contextlib.suppress(Exception):
                        await item.click(timeout=5000)
                    break

            await page.wait_for_timeout(6000)  # let a download/popup/response settle
            open_pages = [p.url[:160] for p in ctx.pages]
            await page.screenshot(path=str(OUT / "docs_probe.png"), full_page=True)
            (OUT / "docs_probe.json").write_text(
                json.dumps(
                    {"clicked": clicked, "open_pages": open_pages, "events": events}, indent=2
                )
            )
            print(f">>> clicked={clicked}  events={len(events)}  open_tabs={len(open_pages)}")
            for e in events:
                print("   ", e)
            print(f"    open tabs: {open_pages}")
            print("    detail -> spike/out/docs_probe.json  (+ docs_probe.png)")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

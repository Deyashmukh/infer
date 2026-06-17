"""Map the Liberty Mutual documents page by REUSING the saved authenticated
session (spike/out/lm_state.json) — no credentials, no MFA. Fully non-interactive:
loads the stored cookies, opens /accountmanager/documents, and reports how policy
PDFs are exposed (static .pdf links vs. authenticated download endpoints) so the
real doc-fetch driver can target them precisely.

    uv run python -m backend.map_docs
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

from playwright.async_api import Response, async_playwright

from spike.carriers.liberty_mutual import classify_lm_page, discover_document_urls

OUT = Path("spike/out")
STATE = OUT / "lm_state.json"
DOCS_URL = "https://eservice.libertymutual.com/accountmanager/documents"


async def main() -> None:
    if not STATE.exists():
        print(f">>> {STATE} not found — run backend.confirm_h1 first to save a session.")
        return
    pdf_responses: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-http2"])
        try:
            ctx = await browser.new_context(storage_state=str(STATE))
            page = await ctx.new_page()

            def on_resp(r: Response) -> None:
                ct = (r.headers.get("content-type") or "").lower()
                cd = (r.headers.get("content-disposition") or "").lower()
                if "application/pdf" in ct or "attachment" in cd or ".pdf" in r.url.lower():
                    pdf_responses.append(
                        {
                            "url": r.url.split("?")[0][:120],
                            "status": r.status,
                            "ct": ct[:40],
                            "cd": cd[:70],
                        }
                    )

            page.on("response", on_resp)

            await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=45000)
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(2000)

            final_url = page.url
            authed = "login.libertymutual.com" not in final_url and "/account/auth" not in final_url
            html = await page.content()
            (OUT / "documents_real.html").write_text(html)  # raw fixture for the doc-list parser
            state = classify_lm_page(html, final_url)
            pdf_anchors = discover_document_urls(html, base_url=final_url)

            # Broad scan of clickable things on the docs page (links + buttons), to
            # reveal how documents are triggered when they aren't plain .pdf links.
            clickables = await page.evaluate(
                "() => [...document.querySelectorAll('a[href],button,[role=button],[download]')]"
                ".map(e=>({tag:e.tagName.toLowerCase(),"
                "href:e.getAttribute('href')||'',"
                "download:e.getAttribute('download')||'',"
                "text:(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,70)}))"
                ".filter(x=>x.text||x.href||x.download).slice(0,150)"
            )

            await page.screenshot(path=str(OUT / "docs_page.png"), full_page=True)
            (OUT / "docs_page.json").write_text(
                json.dumps(
                    {
                        "final_url": final_url,
                        "authed": authed,
                        "page_state": str(state),
                        "pdf_anchors": [{"name": d.name, "url": d.url} for d in pdf_anchors],
                        "pdf_responses": pdf_responses,
                        "clickables": clickables,
                    },
                    indent=2,
                    default=str,
                )
            )

            print(f">>> docs page: authed={authed}  state={state}  url={final_url}")
            print(
                f"    pdf_anchors={len(pdf_anchors)}  pdf_responses={len(pdf_responses)}  "
                f"clickables={len(clickables)}"
            )
            print("    detail -> spike/out/docs_page.json  (+ docs_page.png)")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Geico carrier step functions (mirrors carriers/lm.py signatures).

Geico's login is plain HTML, but the post-login portal is a Flutter canvas app — there is no
DOM to click reliably. Instead this carrier authenticates, then drives Geico's JSON ``/ws/``
APIs directly: the post-MFA dashboard URL carries a session ``token``; the Proof-of-Insurance
endpoint (``/ws/proof-of-insurance``) yields each vehicle's id; and the ID-card endpoint
(``/ws/view-document/id-card``) returns a real PDF per vehicle. Those PDFs drop straight into
the react-pdf viewer. Pure parsing/URL logic lives in ``backend.geico_idcard_api``.

Anti-bot: ChromiumDriver masks navigator.webdriver + uses a clean Chrome UA, which Geico's
login JS (client) and edge (server) require before they will process the credential POST.
Geico runs over HTTP/2 (see ``LAUNCH_ARGS``); only LM needs HTTP/1.1.
"""

from __future__ import annotations

import contextlib
import logging
import time as _time
from typing import Any

from playwright.async_api import BrowserContext, Page, Response

from backend.browser import AuthStep, DocRef, FetchedDoc
from backend.geico_idcard_api import id_card_url, parse_id_card_docs
from backend.models import CarrierAuthError, DocFetchError, MfaError

logger = logging.getLogger(__name__)

DASHBOARD = "https://portfolio.geico.com/dashboard"
_EDGE = "https://edgecustomer.geico.com"

# Geico runs fine over HTTP/2 (unlike LM's Cloudflare edge), so no --disable-http2 here.
LAUNCH_ARGS: list[str] = []

# Session token query string ("token=..."), lifted from the post-MFA dashboard URL and keyed
# by id(page). The carrier API is stateless (functions take a Page), so this stashes the token
# that the edgecustomer ``/ws/`` endpoints authenticate against.
_token_query: dict[int, str] = {}


def _token_for(page: Page) -> str:
    """The session token query for *page* — captured at MFA, or read off the dashboard URL."""
    q = _token_query.get(id(page))
    if q is not None:
        return q
    url = page.url
    if "portfolio.geico.com" in url and "?" in url:
        return url.split("?", 1)[1]
    return ""


def _is_poi_response(r: Response) -> bool:
    """True for the ``/ws/proof-of-insurance`` JSON call (not the look-alike feedback call)."""
    return r.url.split("?", 1)[0].rstrip("/").endswith("/ws/proof-of-insurance")


async def _enabled_button_boxes(page: Page) -> dict[int, tuple[int, int, int, int]]:
    """Index -> bbox for each enabled role=button (Flutter buttons have no labels; 'Next'
    is found as the button that transitions disabled->enabled when a method is selected)."""
    out: dict[int, tuple[int, int, int, int]] = {}
    btns = page.get_by_role("button")
    for i in range(await btns.count()):
        if not await btns.nth(i).is_disabled():
            bb = await btns.nth(i).bounding_box()
            if bb:
                out[i] = (round(bb["x"]), round(bb["y"]), round(bb["width"]), round(bb["height"]))
    return out


async def open_login(page: Page, login_url: str) -> None:
    """Navigate to the eCAMS login page and wait for the (slow SPA) credential form."""
    await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    for _ in range(40):
        await page.wait_for_timeout(1500)
        if await page.locator("input[type=password]").count() > 0:
            return
    raise CarrierAuthError("Geico login form never rendered")


async def submit_credentials(page: Page, username: str, password: str) -> AuthStep:
    """Submit credentials, then select the Text MFA method (which sends the code).

    The username field is input[autocomplete=email]; submit via Enter, retrying until the
    /ws/login/authenticate POST fires. On reaching /mfa/options, pick 'Get a Text' and click
    the button that enables (Next) — that triggers the SMS. Returns NEEDS_MFA.
    """
    sent = {"v": False}

    def _on(r: Any) -> None:
        if "/ws/login/authenticate" in r.url:
            sent["v"] = True

    page.on("request", _on)
    try:
        u = page.locator("input[autocomplete=email]").first
        p = page.locator("input[type=password]").first
        for _ in range(4):
            with contextlib.suppress(Exception):
                await u.click()
                await u.fill("")
                await u.fill(username)
                await p.click()
                await p.fill("")
                await p.fill(password)
                await page.wait_for_timeout(400)
                await p.press("Enter")
            for _ in range(6):
                await page.wait_for_timeout(1000)
                if sent["v"] or "/mfa/" in page.url.lower():
                    break
            if sent["v"] or "/mfa/" in page.url.lower():
                break
    finally:
        page.remove_listener("request", _on)

    # Poll for the MFA method screen (or a credential error).
    for _ in range(40):
        await page.wait_for_timeout(1000)
        url = page.url.lower()
        if "/mfa/options" in url:
            await _choose_text_mfa(page)
            return AuthStep.NEEDS_MFA
        if "/mfa/" in url:  # already past options (e.g. straight to code entry)
            return AuthStep.NEEDS_MFA
        body = (await page.inner_text("body")).lower()
        if "do not match" in body or "credentials you entered" in body:
            raise CarrierAuthError("Geico credentials rejected")

    raise CarrierAuthError(f"timed out waiting for Geico MFA (url={page.url})")


async def _choose_text_mfa(page: Page) -> None:
    """On /mfa/options (Flutter canvas): select the 2nd radio ('Get a Text') and click the
    button that becomes enabled as a result ('Next'), which sends the SMS."""
    before = set((await _enabled_button_boxes(page)).values())
    with contextlib.suppress(Exception):
        await page.get_by_role("radio").nth(1).click()
        await page.wait_for_timeout(1200)
        after = await _enabled_button_boxes(page)
        nxt = next((i for i, b in after.items() if b not in before), None)
        if nxt is not None:
            await page.get_by_role("button").nth(nxt).click()
            await page.wait_for_timeout(4000)


async def submit_mfa(page: Page, code: str) -> AuthStep:
    """Enter the texted code on /mfa/pin and capture the session token from the dashboard URL.

    The page is Flutter canvas: a single 'Verification code' field (~234,218) and a
    'Submit Code' button (~1063,421) in the 1280-wide viewport. Verifying the code redirects to
    portfolio.geico.com/dashboard?token=..., whose token the edgecustomer endpoints accept.
    """
    t0 = _time.monotonic()
    with contextlib.suppress(Exception):
        field = page.locator(
            "input[autocomplete=one-time-code],input[inputmode=numeric],input[type=tel]"
        )
        if await field.count() > 0:
            await field.first.click()
        else:
            await page.mouse.click(234, 218)
        await page.keyboard.type(code, delay=80)
        await page.wait_for_timeout(500)
        await page.mouse.click(1063, 421)  # 'Submit Code'

    # Wait for the post-MFA redirect to the token-bearing dashboard URL.
    with contextlib.suppress(Exception):
        await page.wait_for_url("**portfolio.geico.com**", timeout=45000)
    for _ in range(20):
        if "portfolio.geico.com" in page.url.lower():
            break
        await page.wait_for_timeout(1000)

    if "portfolio.geico.com" not in page.url.lower():
        raise MfaError("Geico MFA did not complete (still on the verification page)")

    _token_query[id(page)] = page.url.split("?", 1)[1] if "?" in page.url else ""
    logger.info(
        "[geico] MFA->dashboard in %.2fs (token=%s)",
        _time.monotonic() - t0,
        bool(_token_query[id(page)]),
    )
    return AuthStep.AUTHENTICATED


async def is_authenticated(page: Page) -> bool:
    """Reach the dashboard without logging in (used for cached-session resume)."""
    with contextlib.suppress(Exception):
        await page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=30000)
    return "portfolio.geico.com" in page.url and "login" not in page.url.lower()


async def _load_proof_of_insurance(page: Page, query: str) -> str:
    """Load Proof-of-Insurance and return its ``/ws/proof-of-insurance`` JSON body.

    Navigating to the POI page boots the SPA, which fires ``/ws/proof-of-insurance`` itself; we
    capture that response. A direct API GET would be faster (~0.6s vs ~4s) but the edge requires
    an ASP.NET ``x-xsrf-token`` antiforgery header whose ``XSRF-TOKEN`` cookie isn't set until an
    edgecustomer page has loaded — so priming it costs about as much as the page-nav itself.
    """
    body = ""
    with contextlib.suppress(Exception):
        async with page.expect_response(_is_poi_response, timeout=30000) as resp_info:
            await page.goto(
                f"{_EDGE}/documents/proof-of-insurance-home?{query}",
                wait_until="commit",
                timeout=45000,
            )
        body = await (await resp_info.value).text()
    return body


async def list_documents(page: Page) -> list[DocRef]:
    """Return one ID-card document per insured vehicle, from ``/ws/proof-of-insurance``.

    The payload carries each vehicle's id (and year/make/model for the label); fetch_document
    turns each id into a PDF.
    """
    t0 = _time.monotonic()
    body = await _load_proof_of_insurance(page, _token_for(page))
    docs = parse_id_card_docs(body)
    logger.info(
        "[geico] proof-of-insurance -> %d vehicle(s) in %.2fs", len(docs), _time.monotonic() - t0
    )
    if not docs:
        raise DocFetchError("Geico proof-of-insurance returned no vehicles")
    return docs


async def _get_pdf(ctx: BrowserContext, url: str) -> bytes | None:
    """GET *url* with the context's cookies; return the body iff it is a PDF, else None."""
    with contextlib.suppress(Exception):
        resp = await ctx.request.get(url, timeout=30000)
        body = await resp.body()
        if body[:5] == b"%PDF-":
            return body
    return None


async def fetch_document(ctx: BrowserContext, page: Page, ref: DocRef) -> FetchedDoc:
    """Fetch one vehicle's ID-card PDF from the edgecustomer endpoint (token-authenticated)."""
    t0 = _time.monotonic()
    query = _token_for(page)
    url = id_card_url(ref.doc_id, query)

    pdf = await _get_pdf(ctx, url)
    via = "direct"
    if pdf is None:
        # Fallback: load the cards page to prime any session state, then retry the API GET.
        with contextlib.suppress(Exception):
            await page.goto(
                f"{_EDGE}/documents/poi-id-cards-send?{query}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(1500)
        pdf = await _get_pdf(ctx, url)
        via = "after-cards-page"

    if pdf is None:
        raise DocFetchError(f"Geico ID-card PDF not returned for vehicle {ref.doc_id[:8]}")
    logger.info(
        "[geico] id-card %s (%s) %d bytes in %.2fs",
        ref.doc_id[:8],
        via,
        len(pdf),
        _time.monotonic() - t0,
    )
    return FetchedDoc(name=ref.name, content=pdf)

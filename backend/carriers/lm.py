"""Liberty Mutual carrier-specific browser step functions.

Each function operates on a Playwright Page (or BrowserContext) and encodes the selectors,
timings, and robustness logic for LM's Auth0 login + document portal. ChromiumDriver delegates
all LM-specific work here; adding a carrier (e.g. Geico) means a parallel module with the same
function signatures (see carriers/geico.py).
"""

from __future__ import annotations

import contextlib
import logging
import time as _time
from typing import Any

from playwright.async_api import BrowserContext, Page

from backend.browser import AuthStep, DocRef, FetchedDoc
from backend.models import BotChallengeError, CarrierAuthError, DocFetchError, MfaError
from spike.docfetch import is_valid_pdf

logger = logging.getLogger(__name__)

DOCS_URL = "https://eservice.libertymutual.com/accountmanager/documents"

# LM's Cloudflare login edge rejects HTTP/2 (the credential POST fires but the edge returns a
# "something went wrong" page — confirmed live 2026-06-17). Force HTTP/1.1. The flag is
# browser-global, so this also pins the document fetch to HTTP/1.1.
LAUNCH_ARGS = ["--disable-http2"]

# Auth0 OTP-field selectors, in preference order.
_OTP_SELECTORS = (
    "input[autocomplete=one-time-code]",
    "input[name*=code i]",
    "input[id*=code i]",
    "input[inputmode=numeric]",
    "input[type=tel]",
)


async def _locate_otp(page: Page) -> Any:
    """Return the first visible OTP input, or None if the field isn't present yet."""
    for sel in _OTP_SELECTORS:
        loc = page.locator(sel)
        if await loc.count() > 0 and await loc.first.is_visible():
            return loc.first
    # Fallback: any visible non-credential input.
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


async def open_login(page: Page, login_url: str) -> None:
    """Navigate to the LM landing page and reach the Auth0 credential form.

    Robustly clicks "Log in" with retry until ``input[name=username]`` appears
    (a hydration-race guard). Raises BotChallengeError if the page shows a hard
    block instead of the form.
    """
    await page.goto(login_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    # Retry the "Log in" click until the username field appears (up to 5 attempts).
    # The click can silently no-op if the React landing page hasn't hydrated yet.
    for _ in range(5):
        with contextlib.suppress(Exception):
            await page.get_by_role("link", name="Log in").first.click()
        with contextlib.suppress(Exception):
            await page.wait_for_selector("input[name=username]", timeout=6000)
        if await page.locator("input[name=username]").count() > 0:
            break
        await page.wait_for_timeout(1500)

    if await page.locator("input[name=username]").count() == 0:
        body = (await page.inner_text("body")).lower()
        if "something went wrong" in body or "access denied" in body:
            raise BotChallengeError(
                "bot challenge on login page",
                fields={"kind": "LANDING_BLOCK", "url": page.url},
            )
        raise BotChallengeError(
            "login form never loaded",
            fields={"kind": "FORM_NOT_FOUND", "url": page.url},
        )


async def submit_credentials(page: Page, username: str, password: str) -> AuthStep:
    """Fill and submit the Auth0 username+password form, reliably.

    Re-fills + re-clicks until the credential POST (usernamepassword/login) is
    actually observed, guarding against a dropped submit click. Then polls up to
    60 s for the MFA state; raises CarrierAuthError on "something went wrong".
    """
    login_sent: dict[str, bool] = {"sent": False}

    def _on_request(r: Any) -> None:
        if "usernamepassword/login" in r.url:
            login_sent["sent"] = True

    page.on("request", _on_request)

    # Fill + click button[type=submit] fires the usernamepassword/login POST (confirmed by
    # live recon). The earlier flakiness was a broken re-click guard that treated "still on
    # login.libertymutual.com" — where the form itself lives — as success, so it never
    # retried a dropped click. Here we re-fill + re-click until the POST is actually
    # observed. login_sent flips true only once the POST fires, so at most ONE real
    # credential attempt is made regardless of how many clicks were dropped -> no lockout.
    try:
        for _ in range(5):
            with contextlib.suppress(Exception):
                await page.fill("input[name=username]", username)
                await page.fill("input[name=password]", password)
                await page.wait_for_timeout(400)
                await page.click("button[type=submit]")
            for _ in range(5):
                await page.wait_for_timeout(1000)
                if login_sent["sent"]:
                    break
            if login_sent["sent"]:
                break
    finally:
        page.remove_listener("request", _on_request)

    logger.info("[lm] credential POST fired=%s url=%s", login_sent["sent"], page.url[:70])

    # Poll up to 60 s for MFA state or an error (HTTP/1.1 is slower than h2).
    for _ in range(60):
        await page.wait_for_timeout(1000)
        if await _locate_otp(page) is not None or "/mfa" in page.url:
            return AuthStep.NEEDS_MFA
        body = (await page.inner_text("body")).lower()
        if "something went wrong" in body:
            raise CarrierAuthError("credentials rejected by Liberty Mutual")

    # Diagnostic: capture what LM is actually showing so we can see why MFA wasn't reached.
    with contextlib.suppress(Exception):
        await page.screenshot(path="spike/out/lm_mfa_timeout.png", full_page=True)
    body_txt = ""
    with contextlib.suppress(Exception):
        body_txt = (await page.inner_text("body"))[:300]
    logger.warning(
        "[lm] MFA-wait TIMEOUT post_fired=%s url=%s body=%r",
        login_sent["sent"],
        page.url[:70],
        body_txt,
    )
    raise CarrierAuthError(
        f"timed out waiting for MFA prompt after credential submission (url={page.url})"
    )


async def submit_mfa(page: Page, code: str) -> AuthStep:
    """Type the MFA code digit-by-digit and wait for the session to authenticate.

    Uses press_sequentially (not fill) because Auth0's client-side validation
    only enables the Continue button on real per-keystroke events. Submits via
    Enter to avoid a disabled-button race.
    """
    t0 = _time.monotonic()
    otp = await _locate_otp(page)
    if otp is None:
        raise MfaError("OTP input field not found on page")

    await otp.click()
    await otp.press_sequentially(code, delay=60)
    await page.wait_for_timeout(400)
    await otp.press("Enter")

    # Poll up to 30 s for leaving the Auth0 login domain. 250 ms granularity so we detect the
    # post-auth redirect promptly (1 s rounding was up to ~1 s of pure latency).
    for _ in range(120):
        await page.wait_for_timeout(250)
        if "login.libertymutual.com" not in page.url and "/mfa" not in page.url:
            # Wait out any transient OAuth-callback redirect (/account/auth?code=...).
            for _ in range(40):
                if "/account/auth" not in page.url:
                    break
                await page.wait_for_timeout(250)
            # Minimal settle — list_documents navigates fresh and waits on its own controls,
            # so anything more here is pure latency.
            await page.wait_for_timeout(300)
            logger.info("[lm] MFA->authed in %.2fs", _time.monotonic() - t0)
            return AuthStep.AUTHENTICATED

        # If the Continue button becomes enabled, click it (belt-and-suspenders).
        btn = page.locator("button[type=submit]:not([disabled])")
        if await btn.count() > 0 and await btn.first.is_visible():
            with contextlib.suppress(Exception):
                await btn.first.click(timeout=2000)

    raise MfaError("timed out waiting for authentication after MFA submission")


async def is_authenticated(page: Page) -> bool:
    """Navigate to the documents URL and return True if the session is still live.

    Returns False if the carrier bounces us to a login domain, indicating the
    cached session has expired.  Must NOT submit credentials.
    """
    try:
        await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        return False
    return "login.libertymutual.com" not in page.url


async def list_documents(page: Page) -> list[DocRef]:
    """Navigate to the documents page and enumerate visible "View / print" controls.

    Returns a list of DocRef where doc_id is the 0-based index (str) of the
    control among all visible "View / print" elements, and name is derived from
    the enclosing policy card's heading text.
    """
    t0 = _time.monotonic()
    await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=45000)

    # Wait for the "View / print" controls to render — targeted, and far faster than a
    # networkidle wait on this heavy SPA (which can sit at the full 15s).
    loc = page.locator(":is(button,a)", has_text="View / print")
    with contextlib.suppress(Exception):
        await loc.first.wait_for(state="attached", timeout=20000)
    total = await loc.count()

    refs: list[DocRef] = []
    visible_i = 0
    for i in range(total):
        item = loc.nth(i)
        if not await item.is_visible():
            continue

        # Derive a human name from the nearest ancestor card/section heading.
        name = await _extract_doc_name(page, item, visible_i)
        refs.append(DocRef(doc_id=str(visible_i), name=name))
        visible_i += 1

    if not refs:
        raise DocFetchError("no 'View / print' controls found on documents page")

    logger.info("[lm] list-documents -> %d doc(s) in %.2fs", len(refs), _time.monotonic() - t0)
    return refs


async def _extract_doc_name(page: Page, item: Any, index: int) -> str:
    """Best-effort: walk up the DOM from the "View / print" element to find a
    policy-card heading. Falls back to a generic label on failure."""
    try:
        _HEADING_SEL = (
            "h1,h2,h3,h4,h5,h6,"
            "[class*=title],[class*=heading],[class*=name]"
        )
        name: str = await item.evaluate(
            f"""el => {{
                const sel = '{_HEADING_SEL}';
                let node = el.parentElement;
                for (let d = 0; d < 8 && node; d++, node = node.parentElement) {{
                    const h = node.querySelector(sel);
                    if (h) {{
                        const t = (h.innerText || h.textContent || '').trim();
                        if (t) return t;
                    }}
                }}
                return '';
            }}"""
        )
        return name.strip() or f"Document {index + 1}"
    except Exception:
        return f"Document {index + 1}"


async def fetch_document(ctx: BrowserContext, page: Page, ref: DocRef) -> FetchedDoc:
    """Click the ref-th "View / print" control and capture the PDF response.

    The click opens a popup containing an ``application/pdf`` response from a
    ``/document/download/...`` URL. Captures the response body directly.
    Falls back to a context-level GET request (same cookie jar) if popup capture
    fails. Raises DocFetchError if no valid PDF is obtained.
    """
    t0 = _time.monotonic()
    # Reuse the page list_documents just loaded — re-navigating to the docs page here is a
    # redundant slow round-trip. Only navigate if we've actually left the documents page.
    if DOCS_URL not in page.url:
        await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=45000)

    loc = page.locator(":is(button,a)", has_text="View / print")
    with contextlib.suppress(Exception):
        await loc.first.wait_for(state="attached", timeout=20000)
    idx = int(ref.doc_id)

    # Collect only visible controls to re-index by visible position.
    visible_items: list[Any] = []
    total = await loc.count()
    for i in range(total):
        item = loc.nth(i)
        if await item.is_visible():
            visible_items.append(item)

    if idx >= len(visible_items):
        raise DocFetchError(
            f"doc_id {ref.doc_id} out of range (only {len(visible_items)} visible controls)"
        )

    target_item = visible_items[idx]

    # Expect a popup: "View / print" opens the PDF in a new tab/window.
    pdf_url: str | None = None
    content: bytes | None = None

    popup_url = ""
    try:
        async with ctx.expect_page(timeout=15000) as popup_info:
            await target_item.click(timeout=5000)
        popup = await popup_info.value

        # Capture the application/pdf response. Generous timeout (HTTP/1.1 PDF loads are
        # slow) and a broad predicate (content-type OR a download/.pdf URL).
        with contextlib.suppress(Exception):
            resp = await popup.wait_for_event(
                "response",
                predicate=lambda r: "application/pdf"
                in (r.headers.get("content-type") or "").lower()
                or "/document/download/" in r.url
                or r.url.lower().endswith(".pdf"),
                timeout=25000,
            )
            pdf_url = resp.url
            with contextlib.suppress(Exception):
                content = await resp.body()

        # Fallback: re-fetch the popup's settled PDF URL through the authed context.
        if content is None:
            with contextlib.suppress(Exception):
                await popup.wait_for_timeout(2000)
            if "/document/download/" in popup.url or popup.url.lower().endswith(".pdf"):
                pdf_url = popup.url
        if content is None and pdf_url:
            with contextlib.suppress(Exception):
                resp = await ctx.request.get(pdf_url)
                content = await resp.body()

        popup_url = popup.url
        if content is None:  # diagnostic: capture what the popup is actually showing
            with contextlib.suppress(Exception):
                await popup.screenshot(path="spike/out/lm_doc_popup.png")
        with contextlib.suppress(Exception):
            await popup.close()

    except Exception as exc:
        if content is None:
            raise DocFetchError(f"failed to capture PDF popup for {ref.name!r}: {exc}") from exc

    if content is None:
        raise DocFetchError(f"no PDF content captured for {ref.name!r} (popup={popup_url})")

    if not is_valid_pdf(content):
        raise DocFetchError(
            f"fetched bytes for {ref.name!r} are not a valid PDF "
            f"(got {len(content)} bytes, header={content[:8]!r})"
        )

    logger.info(
        "[lm] fetch %r (%d bytes) in %.2fs", ref.name, len(content), _time.monotonic() - t0
    )
    return FetchedDoc(name=ref.name, content=content)

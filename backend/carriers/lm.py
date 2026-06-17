"""Liberty Mutual carrier-specific browser step functions.

Each function operates on a Playwright Page (or BrowserContext) and encodes
the selectors, timings, and robustness logic proven by the spike scripts
(backend/confirm_h1.py, backend/probe_doc.py). ChromiumDriver delegates all
LM-specific work here; adding a second carrier (e.g. Geico) means a parallel
module with the same function signatures.
"""

from __future__ import annotations

import contextlib
from typing import Any

from playwright.async_api import BrowserContext, Page

from backend.browser import AuthStep, DocRef, FetchedDoc
from backend.models import BotChallengeError, CarrierAuthError, DocFetchError, MfaError
from spike.docfetch import is_valid_pdf

DOCS_URL = "https://eservice.libertymutual.com/accountmanager/documents"

# Auth0 OTP-field selectors, in preference order (from confirm_h1._locate_otp).
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
    # Fallback: any visible non-credential input (mirrors confirm_h1._locate_otp).
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
    (the hydration-race guard from confirm_h1). Raises BotChallengeError if the
    page shows a hard block instead of the form.
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
    """Fill and submit the Auth0 username+password form.

    Exactly one submission: if the credential POST doesn't fire within 6 s,
    re-clicks once (the submit-handler race observed on slower hosts). Polls up
    to 30 s for the MFA state; raises CarrierAuthError on "something went wrong".
    """
    login_sent: dict[str, bool] = {"sent": False}

    def _on_request(r: Any) -> None:
        if "usernamepassword/login" in r.url:
            login_sent["sent"] = True

    page.on("request", _on_request)

    await page.fill("input[name=username]", username)
    await page.fill("input[name=password]", password)
    await page.wait_for_timeout(400)  # let the form's JS attach its submit handler
    await page.click("button[type=submit]")

    # Confirm the credential POST actually fired; re-click once if not (mirrors
    # the guard in confirm_h1 for the silent-no-op case on slow hosts).
    for _ in range(6):
        await page.wait_for_timeout(1000)
        if login_sent["sent"] or "login.libertymutual.com" in page.url:
            break
    else:
        with contextlib.suppress(Exception):
            await page.click("button[type=submit]")

    page.remove_listener("request", _on_request)

    # Poll up to 30 s for MFA state or an error (HTTP/1.1 is slower than h2).
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if await _locate_otp(page) is not None or "/mfa" in page.url:
            return AuthStep.NEEDS_MFA
        body = (await page.inner_text("body")).lower()
        if "something went wrong" in body:
            raise CarrierAuthError("credentials rejected by Liberty Mutual")

    raise CarrierAuthError("timed out waiting for MFA prompt after credential submission")


async def submit_mfa(page: Page, code: str) -> AuthStep:
    """Type the MFA code digit-by-digit and wait for the session to authenticate.

    Uses press_sequentially (not fill) because Auth0's client-side validation
    only enables the Continue button on real per-keystroke events. Submits via
    Enter to avoid a disabled-button race.
    """
    otp = await _locate_otp(page)
    if otp is None:
        raise MfaError("OTP input field not found on page")

    await otp.click()
    await otp.press_sequentially(code, delay=60)
    await page.wait_for_timeout(400)
    await otp.press("Enter")

    # Poll up to 30 s for leaving the Auth0 login domain.
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if "login.libertymutual.com" not in page.url and "/mfa" not in page.url:
            # Wait out any transient OAuth-callback redirect (/account/auth?code=...).
            for _ in range(20):
                if "/account/auth" not in page.url:
                    break
                await page.wait_for_timeout(1000)
            with contextlib.suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=15000)
            return AuthStep.AUTHENTICATED

        # If the Continue button becomes enabled, click it (belt-and-suspenders).
        btn = page.locator("button[type=submit]:not([disabled])")
        if await btn.count() > 0 and await btn.first.is_visible():
            with contextlib.suppress(Exception):
                await btn.first.click(timeout=2000)

    raise MfaError("timed out waiting for authentication after MFA submission")


async def list_documents(page: Page) -> list[DocRef]:
    """Navigate to the documents page and enumerate visible "View / print" controls.

    Returns a list of DocRef where doc_id is the 0-based index (str) of the
    control among all visible "View / print" elements, and name is derived from
    the enclosing policy card's heading text.
    """
    await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=45000)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=15000)
    await page.wait_for_timeout(1500)

    # Enumerate all visible "View / print" controls (buttons or links).
    loc = page.locator(":is(button,a)", has_text="View / print")
    total = await loc.count()

    refs: list[DocRef] = []
    for i in range(total):
        item = loc.nth(i)
        if not await item.is_visible():
            continue

        # Derive a human name from the nearest ancestor card/section heading.
        name = await _extract_doc_name(page, item, i)
        refs.append(DocRef(doc_id=str(i), name=name))

    if not refs:
        raise DocFetchError("no 'View / print' controls found on documents page")

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
    # Re-navigate to the documents page so the live locator is fresh.
    await page.goto(DOCS_URL, wait_until="domcontentloaded", timeout=45000)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=15000)
    await page.wait_for_timeout(1500)

    loc = page.locator(":is(button,a)", has_text="View / print")
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

    try:
        async with ctx.expect_page(timeout=10000) as popup_info:
            await target_item.click(timeout=5000)
        popup = await popup_info.value

        # Wait for the popup to navigate to the PDF download URL.
        for _ in range(15):
            await popup.wait_for_timeout(500)
            url = popup.url
            if "/document/download/" in url:
                pdf_url = url
                break
            ct = ""
            with contextlib.suppress(Exception):
                resp = await popup.wait_for_event(
                    "response",
                    predicate=lambda r: "application/pdf"
                    in (r.headers.get("content-type") or "").lower(),
                    timeout=1000,
                )
                ct = (resp.headers.get("content-type") or "").lower()
                if "application/pdf" in ct:
                    content = await resp.body()
                    pdf_url = resp.url
                    break

        if content is None and pdf_url:
            # Re-fetch via the context's request (authenticated cookies).
            resp = await ctx.request.get(pdf_url)
            content = await resp.body()

        with contextlib.suppress(Exception):
            await popup.close()

    except Exception as exc:
        # If popup capture failed entirely, try a download-event fallback.
        if content is None:
            raise DocFetchError(f"failed to capture PDF popup for {ref.name!r}: {exc}") from exc

    if content is None:
        raise DocFetchError(f"no PDF content captured for {ref.name!r}")

    if not is_valid_pdf(content):
        raise DocFetchError(
            f"fetched bytes for {ref.name!r} are not a valid PDF "
            f"(got {len(content)} bytes, header={content[:8]!r})"
        )

    return FetchedDoc(name=ref.name, content=content)

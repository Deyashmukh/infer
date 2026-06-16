from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from urllib.parse import urljoin

# --- DOM markers: recalibrated against real DOM in Task B2 (spec §5.1) ---
_LOGIN_MARKERS = (r'name=["\']username["\']', r'type=["\']password["\']')
_MFA_MARKERS = (r"verify your identity", r"enter the code", r'name=["\']otp["\']')
_DOCS_MARKERS = (r"policy documents", r"declarations")


def _matches_any(html: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, html, re.IGNORECASE) for p in patterns)


def _matches_all(html: str, patterns: tuple[str, ...]) -> bool:
    return all(re.search(p, html, re.IGNORECASE) for p in patterns)


class LMPageState(StrEnum):
    LOGIN_FORM = "LOGIN_FORM"
    MFA_PROMPT = "MFA_PROMPT"
    DOCUMENTS = "DOCUMENTS"
    OTHER = "OTHER"


def classify_lm_page(html: str, url: str) -> LMPageState:
    if _matches_any(html, _MFA_MARKERS):
        return LMPageState.MFA_PROMPT
    if _matches_any(html, _DOCS_MARKERS):
        return LMPageState.DOCUMENTS
    if _matches_all(html, _LOGIN_MARKERS):
        return LMPageState.LOGIN_FORM
    return LMPageState.OTHER


@dataclass(frozen=True)
class DocumentRef:
    name: str
    url: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None


def discover_document_urls(html: str, base_url: str) -> list[DocumentRef]:
    parser = _AnchorParser()
    parser.feed(html)
    # Ensure base_url ends with "/" so urljoin treats it as a directory, not a file.
    base = base_url.rstrip("/") + "/"
    refs: list[DocumentRef] = []
    for href, text in parser.links:
        absolute = urljoin(base, href)
        if absolute.lower().endswith(".pdf"):
            refs.append(DocumentRef(name=text or absolute, url=absolute))
    return refs

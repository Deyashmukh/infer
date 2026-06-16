from __future__ import annotations

import re
from enum import StrEnum

# --- DOM markers: recalibrated against real DOM in Task B2 (spec §5.1) ---
_LOGIN_MARKERS = (r'name=["\']username["\']', r'type=["\']password["\']')
_MFA_MARKERS = (r"verify your identity", r"enter the code", r'name=["\']otp["\']')
_DOCS_MARKERS = (r"policy documents", r"declarations")


def _matches_any(html: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, html, re.IGNORECASE) for p in patterns)


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
    if all(re.search(p, html, re.IGNORECASE) for p in _LOGIN_MARKERS):
        return LMPageState.LOGIN_FORM
    return LMPageState.OTHER

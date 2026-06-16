from __future__ import annotations

import base64
import binascii

_PDF_MAGIC = b"%PDF-"


def is_valid_pdf(data: bytes, min_bytes: int = 1024) -> bool:
    """A byte blob looks like a real, non-trivial PDF."""
    return len(data) >= min_bytes and data.startswith(_PDF_MAGIC)


def decode_base64_pdf(encoded: str) -> bytes:
    """Decode base64 produced by an in-page fetch. Raises ValueError on bad input."""
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64 PDF payload: {exc}") from exc

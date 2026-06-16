import base64

import pytest

from spike.docfetch import decode_base64_pdf, is_valid_pdf

PDF_BYTES = b"%PDF-1.7\n" + b"0" * 2000 + b"\n%%EOF"


def test_is_valid_pdf_accepts_real_pdf():
    assert is_valid_pdf(PDF_BYTES) is True


def test_is_valid_pdf_rejects_non_pdf():
    assert is_valid_pdf(b"<html>not a pdf</html>") is False


def test_is_valid_pdf_rejects_too_small():
    assert is_valid_pdf(b"%PDF-1.7") is False  # header but trivially small


def test_decode_base64_pdf_roundtrips():
    encoded = base64.b64encode(PDF_BYTES).decode("ascii")
    assert decode_base64_pdf(encoded) == PDF_BYTES


def test_decode_base64_pdf_rejects_garbage():
    with pytest.raises(ValueError):
        decode_base64_pdf("not!!base64!!")

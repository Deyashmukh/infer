from pathlib import Path

from spike.carriers.liberty_mutual import DocumentRef, discover_document_urls

FIX = Path(__file__).parent / "fixtures" / "lm"


def test_discovers_pdf_links_and_resolves_relative():
    html = (FIX / "documents_list.html").read_text()
    refs = discover_document_urls(html, base_url="https://account.libertymutual.com/account")
    urls = {r.url for r in refs}
    assert "https://account.libertymutual.com/account/docs/dec-page.pdf" in urls
    assert "https://account.libertymutual.com/docs/idcard.pdf" in urls
    assert all(isinstance(r, DocumentRef) for r in refs)


def test_ignores_non_pdf_links():
    html = (FIX / "documents_list.html").read_text()
    refs = discover_document_urls(html, base_url="https://account.libertymutual.com/account")
    assert all(r.url.endswith(".pdf") for r in refs)
    assert len(refs) == 2


def test_names_come_from_link_text():
    html = (FIX / "documents_list.html").read_text()
    refs = discover_document_urls(html, base_url="https://account.libertymutual.com/account")
    names = {r.name for r in refs}
    assert "2026 Declarations Page" in names

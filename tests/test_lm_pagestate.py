from pathlib import Path

import pytest

from spike.carriers.liberty_mutual import LMPageState, classify_lm_page

FIX = Path(__file__).parent / "fixtures" / "lm"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("login_form.html", LMPageState.LOGIN_FORM),
        ("mfa_prompt.html", LMPageState.MFA_PROMPT),
        ("documents.html", LMPageState.DOCUMENTS),
    ],
)
def test_classify_lm_page(name, expected):
    html = (FIX / name).read_text()
    assert classify_lm_page(html, url="https://account.libertymutual.com/x") == expected


def test_unrecognized_page_is_other():
    assert classify_lm_page("<html><body>hello</body></html>", url="x") == LMPageState.OTHER

import json

from spike.challenge import ChallengeKind, ChallengeSignals, classify_challenge


def sig(**kw) -> ChallengeSignals:
    base = dict(
        url="https://login.libertymutual.com",
        status=200,
        body_text="Sign in to your account",
        cookies={},
        has_captcha=False,
    )
    base.update(kw)
    return ChallengeSignals(**base)


def test_clean_page_is_none():
    assert classify_challenge(sig()) is ChallengeKind.NONE


def test_akamai_access_denied():
    s = sig(status=403, body_text="Access Denied\nReference #18.abc")
    assert classify_challenge(s) is ChallengeKind.AKAMAI_ACCESS_DENIED


def test_captcha_detected():
    assert classify_challenge(sig(has_captcha=True)) is ChallengeKind.CAPTCHA


def test_rate_limited():
    assert classify_challenge(sig(status=429)) is ChallengeKind.RATE_LIMIT


def test_unknown_block_on_other_4xx():
    assert classify_challenge(sig(status=401, body_text="blocked")) is ChallengeKind.UNKNOWN_BLOCK


def test_to_result_fields_is_json_safe():
    s = sig(status=403, body_text="Access Denied Reference #1", cookies={"_abck": "~-1~"})
    fields = classify_challenge(s).to_fields(s)
    assert fields["kind"] == "AKAMAI_ACCESS_DENIED"
    assert fields["status"] == 403
    assert "_abck" in fields["abck_state"]
    json.dumps(fields)  # must not raise — the record goes into RESULTS.md

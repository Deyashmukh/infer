import pytest

from backend.models import (
    BotChallengeError,
    CarrierAuthError,
    CarrierError,
    CreateSessionRequest,
    DocFetchError,
    ErrorInfo,
    MfaError,
    MfaRequest,
    SessionExpiredError,
    SessionStatus,
)


def test_error_hierarchy():
    for exc in (BotChallengeError, CarrierAuthError, MfaError, DocFetchError, SessionExpiredError):
        assert issubclass(exc, CarrierError)


def test_bot_challenge_carries_fields():
    err = BotChallengeError("blocked", fields={"kind": "AKAMAI_ACCESS_DENIED"})
    assert err.fields["kind"] == "AKAMAI_ACCESS_DENIED"


def test_error_info_from_exception_uses_class_name():
    info = ErrorInfo.from_exception(CarrierAuthError("bad creds"))
    assert info.type == "CarrierAuthError"
    assert info.message == "bad creds"


def test_error_info_includes_fields_for_bot_challenge():
    info = ErrorInfo.from_exception(BotChallengeError("blocked", fields={"kind": "CAPTCHA"}))
    assert info.fields == {"kind": "CAPTCHA"}


def test_create_session_request_requires_known_carrier():
    req = CreateSessionRequest(carrier="liberty_mutual", username="u", password="p")
    assert req.carrier == "liberty_mutual"
    with pytest.raises(ValueError):
        CreateSessionRequest(carrier="acme_insurance", username="u", password="p")


def test_mfa_request_requires_nonempty_code():
    assert MfaRequest(code="123456").code == "123456"
    with pytest.raises(ValueError):
        MfaRequest(code="")


def test_session_status_values():
    assert {s.value for s in SessionStatus} == {
        "STARTING",
        "AWAITING_MFA",
        "VERIFYING_MFA",
        "FETCHING",
        "READY",
        "FAILED",
    }

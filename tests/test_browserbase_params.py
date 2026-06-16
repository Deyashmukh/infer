from spike.browserbase import build_session_params
from spike.config import Config

CFG = Config(
    browserbase_api_key="bb_x",
    browserbase_project_id="proj_1",
    lm_login_url="https://www.libertymutual.com/log-in",
    browserbase_context_id=None,
)


def test_params_request_residential_us_proxy():
    params = build_session_params(CFG)
    assert params["projectId"] == "proj_1"
    proxies = params["proxies"]
    assert isinstance(proxies, list) and proxies[0]["geolocation"]["country"] == "US"


def test_params_omit_context_when_absent():
    params = build_session_params(CFG)
    assert "context" not in params["browserSettings"]


def test_params_include_persistent_context_when_id_given():
    params = build_session_params(CFG, context_id="ctx_9")
    ctx = params["browserSettings"]["context"]
    assert ctx == {"id": "ctx_9", "persist": True}


def test_advanced_stealth_off_by_default_on_by_request():
    assert "advancedStealth" not in build_session_params(CFG)["browserSettings"]
    stealth_params = build_session_params(CFG, advanced_stealth=True)
    assert stealth_params["browserSettings"]["advancedStealth"] is True

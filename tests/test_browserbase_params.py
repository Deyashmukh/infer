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
    assert params["project_id"] == "proj_1"
    assert params["keep_alive"] is True
    proxies = params["proxies"]
    assert isinstance(proxies, list) and proxies[0]["geolocation"]["country"] == "US"


def test_params_omit_browser_settings_when_no_context_or_stealth():
    assert "browser_settings" not in build_session_params(CFG)


def test_use_proxy_toggle():
    assert "proxies" in build_session_params(CFG)  # default on (the real gate)
    assert "proxies" not in build_session_params(CFG, use_proxy=False)  # free-plan probe


def test_params_include_persistent_context_when_id_given():
    params = build_session_params(CFG, context_id="ctx_9")
    assert params["browser_settings"]["context"] == {"id": "ctx_9", "persist": True}


def test_advanced_stealth_off_by_default_on_by_request():
    assert "browser_settings" not in build_session_params(CFG)
    bs = build_session_params(CFG, advanced_stealth=True)["browser_settings"]
    assert bs["advanced_stealth"] is True

import pytest

from spike.config import ConfigError, load_config


def test_load_config_defaults():
    cfg = load_config({"LM_LOGIN_URL": "https://www.libertymutual.com/log-in"})
    assert cfg.lm_login_url.endswith("/log-in")
    assert cfg.geico_login_url is None
    assert cfg.headless is True
    # Default has no global Chromium args; carrier network args (e.g. --disable-http2) live on
    # each CarrierModule.LAUNCH_ARGS, not in the global config.
    assert cfg.chromium_args == []
    assert cfg.proxy_server is None


def test_load_config_geico_login_url():
    cfg = load_config({"LM_LOGIN_URL": "https://x", "GEICO_LOGIN_URL": "https://geico/login"})
    assert cfg.geico_login_url == "https://geico/login"

def test_load_config_proxy_and_overrides():
    cfg = load_config({
        "LM_LOGIN_URL": "https://x", "HEADLESS": "false",
        "CHROMIUM_ARGS": "--disable-http2 --no-sandbox",
        "PROXY_SERVER": "http://p:8080", "PROXY_USERNAME": "u", "PROXY_PASSWORD": "pw",
    })
    assert cfg.headless is False
    assert cfg.chromium_args == ["--disable-http2", "--no-sandbox"]
    assert cfg.proxy_server == "http://p:8080"
    assert cfg.proxy_username == "u"
    assert cfg.proxy_password == "pw"

def test_missing_login_url_raises():
    with pytest.raises(ConfigError):
        load_config({})

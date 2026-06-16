import pytest

from spike.config import ConfigError, load_config


def test_load_config_defaults():
    cfg = load_config({"LM_LOGIN_URL": "https://www.libertymutual.com/log-in"})
    assert cfg.lm_login_url.endswith("/log-in")
    assert cfg.headless is True
    assert cfg.chromium_args == ["--disable-http2"]
    assert cfg.proxy_server is None

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

import pytest

from spike.config import Config, ConfigError, load_config

BASE = {
    "BROWSERBASE_API_KEY": "bb_live_x",
    "BROWSERBASE_PROJECT_ID": "proj_1",
    "LM_USERNAME": "user@example.com",
    "LM_PASSWORD": "pw",
    "LM_LOGIN_URL": "https://www.libertymutual.com/log-in",
}


def test_load_config_returns_typed_config():
    cfg = load_config(BASE)
    assert isinstance(cfg, Config)
    assert cfg.browserbase_project_id == "proj_1"
    assert cfg.browserbase_context_id is None  # optional, absent


def test_load_config_reads_optional_context_id():
    cfg = load_config({**BASE, "BROWSERBASE_CONTEXT_ID": "ctx_9"})
    assert cfg.browserbase_context_id == "ctx_9"


def test_missing_required_key_raises_with_key_name():
    broken = {k: v for k, v in BASE.items() if k != "LM_PASSWORD"}
    with pytest.raises(ConfigError) as exc:
        load_config(broken)
    assert "LM_PASSWORD" in str(exc.value)

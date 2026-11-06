import pytest

from shared.config import Settings, get_settings

AI_VARS = ("AI_PROVIDER", "AI_MODEL", "AI_API_KEY", "APP_ENV", "LOG_LEVEL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in AI_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_without_env_file():
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    assert settings.log_level == "INFO"


def test_no_ai_model_or_provider_is_hardcoded():
    settings = Settings(_env_file=None)
    assert settings.ai_provider is None
    assert settings.ai_model is None
    assert settings.ai_api_key is None


def test_values_come_from_environment(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "example-provider")
    monkeypatch.setenv("AI_MODEL", "example-model")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings(_env_file=None)
    assert settings.ai_provider == "example-provider"
    assert settings.ai_model == "example-model"
    assert settings.log_level == "DEBUG"


def test_api_key_is_masked_when_printed(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "fake-test-key-123")
    settings = Settings(_env_file=None)
    assert "fake-test-key-123" not in repr(settings)
    assert "fake-test-key-123" not in str(settings.ai_api_key)
    assert settings.ai_api_key.get_secret_value() == "fake-test-key-123"


def test_invalid_log_level_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    with pytest.raises(ValueError):
        Settings(_env_file=None)

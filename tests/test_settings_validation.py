import pytest
from pydantic import ValidationError

from shared.config import Settings


def _production_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "env": "production",
        "api_secret_key": "prod-api-secret",
        "openai_api_key": "sk-live-openai",
        "gateway_service_url": "http://gateway:8000",
        "rag_service_url": "http://rag_service:8007",
        "tool_service_url": "http://tool_service:8008",
        "guardrail_service_url": "http://guardrail_service:8010",
        "monitoring_service_url": "http://monitoring:8005",
        "approval_service_url": "http://approval_service:8011",
    }
    values.update(overrides)
    return Settings(**values)


def test_development_defaults_remain_backward_compatible():
    settings = Settings(_env_file=None)

    assert settings.env in ("development", "testing")
    assert settings.api_secret_key in (
        "change-me-in-production",
        "test-integration-key",
    )


def test_staging_keeps_backward_compatible_defaults():
    settings = Settings(_env_file=None, env="staging")

    assert settings.env == "staging"


def test_production_rejects_default_api_secret_key():
    with pytest.raises(ValidationError, match="API_SECRET_KEY"):
        _production_settings(api_secret_key="change-me-in-production")


def test_production_requires_a_usable_llm_provider():
    with pytest.raises(ValidationError, match="usable LLM provider"):
        _production_settings(openai_api_key="", anthropic_api_key="")


def test_production_accepts_enabled_ollama_without_cloud_api_keys():
    settings = _production_settings(
        openai_api_key="",
        anthropic_api_key="",
        ollama_enabled=True,
    )

    assert settings.ollama_enabled is True


@pytest.mark.parametrize("signing_secret", ["", "your-slack-signing-secret"])
def test_production_rejects_missing_or_placeholder_slack_signing_secret(signing_secret):
    with pytest.raises(ValidationError, match="SLACK_SIGNING_SECRET"):
        _production_settings(
            slack_bot_token="xoxb-live-token",
            slack_signing_secret=signing_secret,
        )


def test_production_accepts_non_placeholder_slack_signing_secret():
    settings = _production_settings(
        slack_bot_token="xoxb-live-token",
        slack_signing_secret="live-slack-signing-secret",
    )

    assert settings.slack_signing_secret == "live-slack-signing-secret"

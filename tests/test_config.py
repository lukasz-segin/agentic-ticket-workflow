"""LLM settings are checked at worker startup; the API's settings ignore them (FR-009)."""

import pytest

from agentic_ticket_workflow.config import LlmSettings, Settings
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.openai_llm import OpenAIChatModel
from agentic_ticket_workflow.worker import build_model

LLM_VARS = ("LLM_MODE", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    for name in LLM_VARS:
        monkeypatch.delenv(name, raising=False)


def test_fake_is_the_default_and_ignores_the_other_values(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "whatever")

    llm = LlmSettings.from_env()

    assert llm.mode == "fake"
    assert isinstance(build_model(llm), FakeChatModel)


def test_openai_mode_builds_the_real_model_and_allows_an_empty_key(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.setenv("LLM_BASE_URL", " http://localhost:11434/v1 ")
    monkeypatch.setenv("LLM_MODEL", "llama3.1")

    llm = LlmSettings.from_env()

    assert (llm.base_url, llm.model, llm.api_key) == ("http://localhost:11434/v1", "llama3.1", "")
    assert isinstance(build_model(llm), OpenAIChatModel)


@pytest.mark.parametrize("missing", ["LLM_BASE_URL", "LLM_MODEL"])
def test_openai_mode_needs_endpoint_and_model(monkeypatch, missing):
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-value")
    for name in ("LLM_BASE_URL", "LLM_MODEL"):
        if name != missing:
            monkeypatch.setenv(name, "set")

    with pytest.raises(ValueError, match=missing) as raised:
        LlmSettings.from_env()

    assert "sk-secret-value" not in str(raised.value)


def test_unknown_mode_is_refused(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "bogus")

    with pytest.raises(ValueError, match="LLM_MODE"):
        LlmSettings.from_env()


@pytest.mark.parametrize("mode", ["openai", "bogus"])
def test_api_settings_ignore_the_llm_settings(monkeypatch, mode):
    monkeypatch.setenv("LLM_MODE", mode)

    assert Settings.from_env().task_queue  # the API starts whatever the LLM settings are

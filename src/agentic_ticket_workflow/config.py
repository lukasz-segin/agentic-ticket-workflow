"""Settings read from environment variables (defaults match .env.example)."""

import os
from dataclasses import dataclass

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LLM_MODES = ("fake", "openai")


@dataclass(frozen=True)
class Settings:
    """Settings both processes read. The LLM settings are the worker's alone (`LlmSettings`)."""

    temporal_address: str
    temporal_namespace: str
    task_queue: str
    helpdesk_failure_rate: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        failure_rate = float(os.environ.get("HELPDESK_FAILURE_RATE", "0.3"))
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError(f"HELPDESK_FAILURE_RATE must be within [0, 1], got {failure_rate}")
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {log_level}")
        return cls(
            temporal_address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
            temporal_namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
            task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "tickets"),
            helpdesk_failure_rate=failure_rate,
            log_level=log_level,
        )


@dataclass(frozen=True)
class LlmSettings:
    """Which model the worker uses (FR-009). Checked at worker startup, so bad config touches no ticket."""

    mode: str
    base_url: str
    model: str
    api_key: str

    @classmethod
    def from_env(cls) -> LlmSettings:
        mode = os.environ.get("LLM_MODE", "fake").strip()
        if mode not in LLM_MODES:
            raise ValueError(f"LLM_MODE must be one of {', '.join(LLM_MODES)}, got {mode}")
        settings = cls(
            mode=mode,
            base_url=os.environ.get("LLM_BASE_URL", "").strip(),
            model=os.environ.get("LLM_MODEL", "").strip(),
            # May be empty: keyless local servers (e.g. Ollama) need none. Never put it in an error message.
            api_key=os.environ.get("LLM_API_KEY", "").strip(),
        )
        if mode == "openai":
            for name, value in (("LLM_BASE_URL", settings.base_url), ("LLM_MODEL", settings.model)):
                if not value:
                    raise ValueError(f"{name} must be set when LLM_MODE=openai")
        return settings

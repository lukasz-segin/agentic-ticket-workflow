"""Settings read from environment variables (defaults match .env.example)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    temporal_address: str
    temporal_namespace: str
    task_queue: str
    llm_mode: str
    helpdesk_failure_rate: float

    @classmethod
    def from_env(cls) -> Settings:
        llm_mode = os.environ.get("LLM_MODE", "fake")
        if llm_mode != "fake":
            raise ValueError(f"LLM_MODE={llm_mode} is not supported yet; use fake")
        failure_rate = float(os.environ.get("HELPDESK_FAILURE_RATE", "0.3"))
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError(f"HELPDESK_FAILURE_RATE must be within [0, 1], got {failure_rate}")
        return cls(
            temporal_address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
            temporal_namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
            task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "tickets"),
            llm_mode=llm_mode,
            helpdesk_failure_rate=failure_rate,
        )

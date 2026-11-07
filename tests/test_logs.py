import io
import json
import logging

import pytest

from agentic_ticket_workflow.config import Settings
from agentic_ticket_workflow.logs import configure_logging

LOGGERS = ("", "agentic_ticket_workflow", "temporalio", "uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture(autouse=True)
def restore_logging():
    saved = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).level, logging.getLogger(name).propagate)
        for name in LOGGERS
    }
    yield
    for name, (handlers, level, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.fixture
def emit():
    """Configure JSON logging into a buffer; return a function that logs one record and parses its line."""
    buffer = io.StringIO()
    configure_logging("DEBUG", stream=buffer)
    log = logging.getLogger("agentic_ticket_workflow.test")

    def _emit(*args, **kwargs) -> tuple[dict, str]:
        start = buffer.tell()
        log.info(*args, **kwargs)
        lines = buffer.getvalue()[start:].splitlines()
        assert len(lines) == 1
        return json.loads(lines[0]), lines[0]

    return _emit


def test_one_json_object_per_line_with_fixed_keys(emit):
    line, _ = emit("ticket %s", "seen", extra={"ticket_id": "T-1", "step": "received"})

    assert {"ts", "level", "logger", "message"} <= line.keys()
    assert line["level"] == "INFO"
    assert line["logger"] == "agentic_ticket_workflow.test"
    assert line["message"] == "ticket seen"
    assert line["ticket_id"] == "T-1"
    assert line["workflow_id"] == "ticket-T-1"
    assert line["step"] == "received"


def test_ids_derived_from_temporal_activity_extra(emit):
    details = {
        "activity_id": "1",
        "activity_type": "act",
        "attempt": 2,
        "workflow_id": "ticket-T-1",
        "workflow_run_id": "run-1",
    }
    line, _ = emit("Completing activity as failed", extra={"temporal_activity": details})

    assert line["ticket_id"] == "T-1"
    assert line["workflow_id"] == "ticket-T-1"
    assert line["attempt"] == 2
    assert line["activity_type"] == "act"
    assert line["run_id"] == "run-1"
    assert "temporal_activity" not in line


def test_non_allow_listed_extra_is_dropped(emit):
    line, raw = emit("decided", extra={"ticket_id": "T-1", "body": "my card was charged twice"})

    assert "body" not in line
    assert "charged twice" not in raw


@pytest.mark.parametrize("chained", [False, True])
def test_exception_logs_type_and_frames_without_message(emit, chained):
    def fail():
        if chained:
            try:
                raise ValueError("secret ticket text")
            except ValueError as cause:
                raise RuntimeError("wrapper also secret ticket text") from cause
        raise ValueError("secret ticket text")

    try:
        fail()
    except Exception:
        line, raw = emit("failed", exc_info=True)

    assert line["error_type"] == ("RuntimeError" if chained else "ValueError")
    assert line["stack"] and all(" in " in frame for frame in line["stack"])
    assert "secret ticket text" not in raw


def test_debug_applies_to_our_logger_only():
    configure_logging("DEBUG", stream=io.StringIO())

    assert logging.getLogger("agentic_ticket_workflow.workflow").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("temporalio").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("temporalio.worker._activity").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("uvicorn.access").getEffectiveLevel() == logging.INFO


def test_warning_applies_to_all_loggers():
    configure_logging("WARNING", stream=io.StringIO())

    for name in ("agentic_ticket_workflow", "temporalio", "uvicorn.access"):
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING


def test_configure_logging_is_idempotent():
    buffer = io.StringIO()
    configure_logging("INFO", stream=buffer)
    configure_logging("INFO", stream=buffer)

    logging.getLogger("agentic_ticket_workflow").info("once")

    assert len(buffer.getvalue().splitlines()) == 1


def test_log_level_setting(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "verbose")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings.from_env()

    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings.from_env().log_level == "DEBUG"

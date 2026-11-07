import io
import json
import logging
import uuid

import httpx
import pytest
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities
from agentic_ticket_workflow.api import app
from agentic_ticket_workflow.config import Settings
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.logs import ALLOWED_EXTRAS, configure_logging
from agentic_ticket_workflow.workflow import TicketWorkflow
from tests.test_helpdesk import ScriptedRandom

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


def test_allow_list_does_not_clash_with_log_record_attributes(emit):
    line, _ = emit("plain")

    assert not set(ALLOWED_EXTRAS) & logging.makeLogRecord({}).__dict__.keys()
    assert set(line) == {"ts", "level", "logger", "message"}


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


async def test_t1_is_traceable_end_to_end_without_ticket_text(env, tickets, monkeypatch):
    """FR-010 as the operator sees it: T-1 through the API at DEBUG, with one helpdesk retry."""
    buffer = io.StringIO()
    configure_logging("DEBUG", stream=buffer)
    task_queue = str(uuid.uuid4())
    monkeypatch.setattr(app.state, "temporal_client", env.client, raising=False)
    monkeypatch.setattr(app.state, "task_queue", task_queue, raising=False)
    # First helpdesk call fails before recording; the retry succeeds.
    acts = TicketActivities(FakeChatModel(), FakeHelpdesk(0.5, rng=ScriptedRandom([0.0, 0.1, 0.9])))
    t1 = tickets["T-1"]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        async with Worker(env.client, task_queue=task_queue, workflows=[TicketWorkflow],
                          activities=[acts.decide, acts.act]):
            assert (await http.post("/tickets", json=t1.model_dump())).status_code == 202
            await env.client.get_workflow_handle("ticket-T-1").result()
            view = (await http.get("/tickets/T-1")).json()

    raw = buffer.getvalue().splitlines()
    lines = [json.loads(line) for line in raw]  # every line is JSON

    ticket_lines = [line for line in lines if "ticket_id" in line or "workflow_id" in line]
    assert ticket_lines
    for line in ticket_lines:
        assert (line.get("ticket_id"), line.get("workflow_id")) == ("T-1", "ticket-T-1"), line

    assert any(line["message"] == "ticket submitted" for line in lines)
    assert {line["step"] for line in lines if line["message"] == "step entered"} == {
        "received", "deciding", "acting", "done",
    }
    decision = next(line for line in lines if line["message"] == "decision made")
    assert (decision["category"], decision["priority"], decision["action"]) == ("account", "normal", "reply")
    assert any(
        line["level"] == "WARNING" and line.get("error_type") == "HelpdeskTemporaryError" and "ticket_id" in line
        for line in lines
    )
    assert any(line["message"] == "ticket status read" for line in lines)

    secrets = (t1.body, t1.subject, view["decision"]["action"]["message"])
    for line in raw:
        for secret in secrets:
            # Lines are JSON: match the text as json.dumps would write it, too.
            assert secret not in line and json.dumps(secret)[1:-1] not in line, line

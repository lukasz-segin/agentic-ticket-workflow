import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from temporalio.client import (
    WorkflowExecutionStatus,
    WorkflowUpdateFailedError,
    WorkflowUpdateRPCTimeoutOrCancelledError,
)
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities, check
from agentic_ticket_workflow.api import app
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.models import CloseAction
from agentic_ticket_workflow.workflow import NOT_AWAITING_APPROVAL, TicketWorkflow


async def test_submit_and_read_t1_through_the_real_activities(env, tickets, monkeypatch):
    task_queue = str(uuid.uuid4())
    monkeypatch.setattr(app.state, "temporal_client", env.client, raising=False)
    monkeypatch.setattr(app.state, "task_queue", task_queue, raising=False)
    acts = TicketActivities(FakeChatModel(), FakeHelpdesk(0.0))
    t1 = tickets["T-1"].model_dump()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        async with Worker(
            env.client, task_queue=task_queue, workflows=[TicketWorkflow], activities=[acts.decide, check, acts.act]
        ):
            first = await http.post("/tickets", json=t1)
            assert first.status_code == 202
            assert first.json() == {"ticket_id": "T-1", "workflow_id": "ticket-T-1", "created": True}

            again = await http.post("/tickets", json=t1)
            assert again.status_code == 200
            assert again.json()["created"] is False

            await env.client.get_workflow_handle("ticket-T-1").result()

            view = await http.get("/tickets/T-1")
            assert view.status_code == 200
            body = view.json()
            assert body["status"] == "completed"
            assert body["step"] == "done"
            assert body["decision"]["action"]["type"] == "reply"
            assert body["decision"]["action"]["article_ids"] == ["KB-1"]
            assert body["tool_calls"]
            assert body["result"]["helpdesk_ref"]

            after = await http.post("/tickets", json=t1)
            assert after.status_code == 200
            assert after.json()["created"] is False

        # The worker is gone; a completed ticket is still readable from history.
        view = await http.get("/tickets/T-1")
        assert view.status_code == 200
        assert view.json()["status"] == "completed"

        assert (await http.get("/tickets/NOPE")).status_code == 404
        # Malformed IDs are rejected before any lookup, so arbitrary path text never reaches a log line.
        assert (await http.get("/tickets/has%20space")).status_code == 422

        missing_body = {k: v for k, v in t1.items() if k != "body"}
        assert (await http.post("/tickets", json=missing_body)).status_code == 422

    assert len(acts.helpdesk.performed) == 1


@asynccontextmanager
async def api_and_worker(env, monkeypatch):
    """The API wired to the test server, and a worker with the real activities and a helpdesk that never fails."""
    task_queue = str(uuid.uuid4())
    monkeypatch.setattr(app.state, "temporal_client", env.client, raising=False)
    monkeypatch.setattr(app.state, "task_queue", task_queue, raising=False)
    acts = TicketActivities(FakeChatModel(), FakeHelpdesk(0.0))
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http,
        Worker(
            env.client, task_queue=task_queue, workflows=[TicketWorkflow], activities=[acts.decide, check, acts.act]
        ),
    ):
        yield http, acts


async def wait_for_step(http: httpx.AsyncClient, ticket_id: str, step: str) -> dict:
    for _ in range(200):
        view = await http.get(f"/tickets/{ticket_id}")
        if view.status_code == 200 and view.json()["step"] == step:
            return view.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"ticket {ticket_id} never reached step {step!r}")


async def test_approve_t2_through_the_api(env, tickets, monkeypatch):
    approval = {"approved": True, "approver": "Ann", "comment": "duplicate confirmed"}
    async with api_and_worker(env, monkeypatch) as (http, acts):
        assert (await http.post("/tickets", json=tickets["T-2"].model_dump())).status_code == 202
        waiting = await wait_for_step(http, "T-2", "awaiting_approval")
        assert waiting["status"] == "running"
        assert waiting["decision"]["action"] == {"type": "refund", "invoice_id": "INV-1002", "amount_eur": 49.0}
        assert waiting["result"] is None

        approved = await http.post("/tickets/T-2/approval", json=approval)
        assert approved.status_code == 200
        assert approved.json() == {"ticket_id": "T-2", "workflow_id": "ticket-T-2", "approved": True}
        again = await http.post("/tickets/T-2/approval", json={"approved": False})
        assert again.status_code == 409

        await env.client.get_workflow_handle("ticket-T-2").result()
        done = (await http.get("/tickets/T-2")).json()

    assert done["status"] == "completed"
    assert done["step"] == "done"
    assert done["result"]["action"] == waiting["decision"]["action"]
    assert done["approval"] == approval
    assert list(acts.helpdesk.performed) == ["ticket-T-2:refund"]


async def test_approval_refusals_through_the_api(env, tickets, monkeypatch):
    async with api_and_worker(env, monkeypatch) as (http, acts):
        # A finished ticket: refused at the describe() stage.
        assert (await http.post("/tickets", json=tickets["T-1"].model_dump())).status_code == 202
        await env.client.get_workflow_handle("ticket-T-1").result()
        assert (await http.post("/tickets/T-1/approval", json={"approved": True})).status_code == 409

        assert (await http.post("/tickets/NOPE/approval", json={"approved": True})).status_code == 404
        assert (await http.post("/tickets/has%20space/approval", json={"approved": True})).status_code == 422

        # A second waiting refund: a bad body is refused, a minimal one (no approver, no comment) is accepted.
        t2b = tickets["T-2"].model_copy(update={"ticket_id": "T-2b"}).model_dump()
        assert (await http.post("/tickets", json=t2b)).status_code == 202
        await wait_for_step(http, "T-2b", "awaiting_approval")
        assert (await http.post("/tickets/T-2b/approval", json={"approver": "Ann"})).status_code == 422
        assert (await http.post("/tickets/T-2b/approval", json={"approved": True, "approver": ""})).status_code == 422
        rejected = await http.post("/tickets/T-2b/approval", json={"approved": False})
        assert rejected.status_code == 200
        assert rejected.json()["approved"] is False
        status = await env.client.get_workflow_handle_for(TicketWorkflow.run, "ticket-T-2b").result()

    assert status.result.action == CloseAction(reason="refund_rejected")
    assert "ticket-T-2b:refund" not in acts.helpdesk.performed


class _RunningClient:
    """A Temporal client stub: the ticket is running, but its Update fails with the given error."""

    def __init__(self, error: Exception):
        self.error = error

    def get_workflow_handle_for(self, *args, **kwargs):
        return self

    async def describe(self, *args, **kwargs):
        return SimpleNamespace(status=WorkflowExecutionStatus.RUNNING)

    async def execute_update(self, *args, **kwargs):
        raise self.error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        # The workflow closed between describe() and the Update.
        (RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b""), 409),
        (RPCError("workflow closed", RPCStatusCode.FAILED_PRECONDITION, b""), 409),
        (WorkflowUpdateFailedError(ApplicationError("refused", type=NOT_AWAITING_APPROVAL)), 409),
        # No worker picked up the Update in time, or Temporal is down.
        (WorkflowUpdateRPCTimeoutOrCancelledError(), 503),
        (RPCError("connection refused", RPCStatusCode.UNAVAILABLE, b""), 503),
    ],
)
async def test_update_stage_errors_map_to_http_codes(monkeypatch, error, code):
    monkeypatch.setattr(app.state, "temporal_client", _RunningClient(error), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.post("/tickets/T-2/approval", json={"approved": True})).status_code == code


class _UnavailableClient:
    """A Temporal client stub whose every call fails as if the server were down."""

    def _fail(self, *args, **kwargs):
        raise RPCError("connection refused", RPCStatusCode.UNAVAILABLE, b"")

    async def start_workflow(self, *args, **kwargs):
        self._fail()

    def get_workflow_handle_for(self, *args, **kwargs):
        return self

    async def describe(self, *args, **kwargs):
        self._fail()


async def test_temporal_unavailable_returns_503(tickets, monkeypatch):
    monkeypatch.setattr(app.state, "temporal_client", _UnavailableClient(), raising=False)
    monkeypatch.setattr(app.state, "task_queue", "unused", raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.post("/tickets", json=tickets["T-1"].model_dump())).status_code == 503
        assert (await http.get("/tickets/T-1")).status_code == 503
        assert (await http.post("/tickets/T-2/approval", json={"approved": True})).status_code == 503

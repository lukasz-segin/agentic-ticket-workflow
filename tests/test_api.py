import uuid

import httpx
import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentic_ticket_workflow.activities import TicketActivities
from agentic_ticket_workflow.api import app
from agentic_ticket_workflow.fake_llm import FakeChatModel
from agentic_ticket_workflow.helpdesk import FakeHelpdesk
from agentic_ticket_workflow.workflow import TicketWorkflow


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        yield env


async def test_submit_and_read_t1_through_the_real_activities(env, tickets):
    task_queue = str(uuid.uuid4())
    app.state.temporal_client = env.client
    app.state.task_queue = task_queue
    acts = TicketActivities(FakeChatModel(), FakeHelpdesk(0.0))
    t1 = tickets["T-1"].model_dump()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        async with Worker(env.client, task_queue=task_queue, workflows=[TicketWorkflow],
                          activities=[acts.decide, acts.act]):
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

        missing_body = {k: v for k, v in t1.items() if k != "body"}
        assert (await http.post("/tickets", json=missing_body)).status_code == 422

    assert len(acts.helpdesk.performed) == 1

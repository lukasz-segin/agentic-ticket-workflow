"""HTTP layer (FR-001…FR-003): start or find a ticket's workflow and read its status."""

from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from agentic_ticket_workflow.config import Settings
from agentic_ticket_workflow.models import Ticket, TicketStatus
from agentic_ticket_workflow.workflow import TicketWorkflow, workflow_id_for


class SubmitResponse(BaseModel):
    ticket_id: str
    workflow_id: str
    created: bool


class TicketView(TicketStatus):
    # Temporal's execution status (running, completed, failed, …); the workflow can't know its own.
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.temporal_client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )
    app.state.task_queue = settings.task_queue
    yield


app = FastAPI(title="agentic-ticket-workflow", lifespan=lifespan)


@app.post("/tickets", response_model=SubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_ticket(ticket: Ticket, request: Request, response: Response) -> SubmitResponse:
    client: Client = request.app.state.temporal_client
    workflow_id = workflow_id_for(ticket.ticket_id)
    try:
        await client.start_workflow(
            TicketWorkflow.run,
            ticket,
            id=workflow_id,
            task_queue=request.app.state.task_queue,
            # Rejects running *and* closed executions with this ID, so a ticket is never processed twice.
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        response.status_code = status.HTTP_200_OK
        return SubmitResponse(ticket_id=ticket.ticket_id, workflow_id=workflow_id, created=False)
    return SubmitResponse(ticket_id=ticket.ticket_id, workflow_id=workflow_id, created=True)


@app.get("/tickets/{ticket_id}", response_model=TicketView)
async def get_ticket(ticket_id: str, request: Request) -> TicketView:
    client: Client = request.app.state.temporal_client
    handle = client.get_workflow_handle_for(TicketWorkflow.run, workflow_id_for(ticket_id))
    try:
        description = await handle.describe()
    except RPCError as err:
        if err.status == RPCStatusCode.NOT_FOUND:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"ticket {ticket_id} not found") from err
        raise

    if description.status == WorkflowExecutionStatus.COMPLETED:
        # Read from history: needs no worker.
        ticket_status = await handle.result()
    else:
        try:
            ticket_status = await handle.query(TicketWorkflow.status, rpc_timeout=timedelta(seconds=2))
        except Exception as err:  # no worker, query timeout or a query failure
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ticket status unavailable") from err

    return TicketView(**ticket_status.model_dump(), status=description.status.name.lower())

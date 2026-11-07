"""HTTP layer (FR-001…FR-003, FR-006): start or find a ticket's workflow, read its status, answer a refund."""

import logging
from contextlib import asynccontextmanager
from datetime import timedelta

import uvicorn
from fastapi import FastAPI, HTTPException, Path, Request, Response, status
from pydantic import BaseModel
from temporalio.client import (
    Client,
    WorkflowExecutionDescription,
    WorkflowExecutionStatus,
    WorkflowHandle,
    WorkflowQueryFailedError,
    WorkflowUpdateFailedError,
    WorkflowUpdateRPCTimeoutOrCancelledError,
)
from temporalio.common import WorkflowIDReusePolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from agentic_ticket_workflow.config import Settings
from agentic_ticket_workflow.logs import configure_logging
from agentic_ticket_workflow.models import IDENTIFIER_PATTERN, Approval, Ticket, TicketStatus
from agentic_ticket_workflow.workflow import NOT_AWAITING_APPROVAL, TicketWorkflow, workflow_id_for

log = logging.getLogger("agentic_ticket_workflow.api")

# Temporal errors a later call may get past: the client answers 503 instead of 500.
_UNAVAILABLE = {RPCStatusCode.UNAVAILABLE, RPCStatusCode.DEADLINE_EXCEEDED}
# What an Update gets when the workflow closed after `describe()` said it was running.
_CLOSED_MEANWHILE = {RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION}


def _ids(ticket_id: str, workflow_id: str) -> dict[str, str]:
    return {"ticket_id": ticket_id, "workflow_id": workflow_id}


def _temporal_unavailable(ticket_id: str, workflow_id: str, err: Exception) -> HTTPException:
    log.warning("temporal unavailable", extra={**_ids(ticket_id, workflow_id), "error_type": type(err).__name__})
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ticket service temporarily unavailable")


class SubmitResponse(BaseModel):
    ticket_id: str
    workflow_id: str
    created: bool


class TicketView(TicketStatus):
    # Temporal's execution status (running, completed, failed, …); the workflow can't know its own.
    status: str


class ApprovalResponse(BaseModel):
    ticket_id: str
    workflow_id: str
    approved: bool


async def _describe(handle: WorkflowHandle, ticket_id: str, workflow_id: str) -> WorkflowExecutionDescription:
    """The ticket's execution, or 404 if there is none and 503 if Temporal can't be reached."""
    try:
        return await handle.describe(rpc_timeout=timedelta(seconds=5))
    except RPCError as err:
        if err.status == RPCStatusCode.NOT_FOUND:
            log.info("ticket not found", extra=_ids(ticket_id, workflow_id))
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"ticket {ticket_id} not found") from err
        if err.status in _UNAVAILABLE:
            raise _temporal_unavailable(ticket_id, workflow_id, err) from err
        raise


def _approval_refused(ticket_id: str, workflow_id: str) -> HTTPException:
    log.info("approval refused", extra={**_ids(ticket_id, workflow_id), "reason_code": NOT_AWAITING_APPROVAL})
    return HTTPException(status.HTTP_409_CONFLICT, f"ticket {ticket_id} is not awaiting approval")


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
        log.info("ticket already submitted", extra=_ids(ticket.ticket_id, workflow_id))
        response.status_code = status.HTTP_200_OK
        return SubmitResponse(ticket_id=ticket.ticket_id, workflow_id=workflow_id, created=False)
    except RPCError as err:
        if err.status in _UNAVAILABLE:
            raise _temporal_unavailable(ticket.ticket_id, workflow_id, err) from err
        raise
    log.info("ticket submitted", extra=_ids(ticket.ticket_id, workflow_id))
    return SubmitResponse(ticket_id=ticket.ticket_id, workflow_id=workflow_id, created=True)


@app.get("/tickets/{ticket_id}", response_model=TicketView)
async def get_ticket(
    request: Request,
    # Same rule as Ticket.ticket_id: arbitrary path text never reaches a log line.
    ticket_id: str = Path(pattern=IDENTIFIER_PATTERN),
) -> TicketView:
    client: Client = request.app.state.temporal_client
    workflow_id = workflow_id_for(ticket_id)
    handle = client.get_workflow_handle_for(TicketWorkflow.run, workflow_id)
    description = await _describe(handle, ticket_id, workflow_id)

    if description.status == WorkflowExecutionStatus.COMPLETED:
        # Read from history: needs no worker.
        try:
            ticket_status = await handle.result(rpc_timeout=timedelta(seconds=5))
        except RPCError as err:
            if err.status in _UNAVAILABLE:
                raise _temporal_unavailable(ticket_id, workflow_id, err) from err
            raise
    else:
        try:
            ticket_status = await handle.query(TicketWorkflow.status, rpc_timeout=timedelta(seconds=2))
        except (WorkflowQueryFailedError, RPCError) as err:  # no worker, query timeout or a query failure
            raise _temporal_unavailable(ticket_id, workflow_id, err) from err

    view = TicketView(**ticket_status.model_dump(), status=description.status.name.lower())
    log.debug("ticket status read", extra={**_ids(ticket_id, workflow_id), "status": view.status, "step": view.step})
    return view


@app.post("/tickets/{ticket_id}/approval", response_model=ApprovalResponse)
async def approve_ticket(
    approval: Approval,
    request: Request,
    ticket_id: str = Path(pattern=IDENTIFIER_PATTERN),
) -> ApprovalResponse:
    """Approve or reject a waiting refund. Returns once the answer is recorded, not once it is acted on.

    404: no such ticket. 409: the ticket isn't waiting for an approval (any more), which the workflow's
    Update validator decides, so a late or second answer never reaches the workflow."""
    client: Client = request.app.state.temporal_client
    workflow_id = workflow_id_for(ticket_id)
    handle = client.get_workflow_handle_for(TicketWorkflow.run, workflow_id)
    # An Update to a closed workflow fails at the RPC level, so check first that it is running.
    description = await _describe(handle, ticket_id, workflow_id)
    if description.status != WorkflowExecutionStatus.RUNNING:
        raise _approval_refused(ticket_id, workflow_id)

    try:
        await handle.execute_update(TicketWorkflow.approve, approval, rpc_timeout=timedelta(seconds=5))
    except WorkflowUpdateFailedError as err:
        if isinstance(err.cause, ApplicationError) and err.cause.type == NOT_AWAITING_APPROVAL:
            raise _approval_refused(ticket_id, workflow_id) from err
        raise
    except RPCError as err:
        if err.status in _CLOSED_MEANWHILE:
            raise _approval_refused(ticket_id, workflow_id) from err
        if err.status in _UNAVAILABLE:
            raise _temporal_unavailable(ticket_id, workflow_id, err) from err
        raise
    except WorkflowUpdateRPCTimeoutOrCancelledError as err:  # e.g. no worker to run the Update
        raise _temporal_unavailable(ticket_id, workflow_id, err) from err

    # The approver name is an audit field; the comment is free text and is never logged.
    log.info(
        "approval recorded",
        extra={**_ids(ticket_id, workflow_id), "approved": approval.approved, "approver": approval.approver},
    )
    return ApprovalResponse(ticket_id=ticket_id, workflow_id=workflow_id, approved=approval.approved)


def serve() -> None:
    """API entrypoint: configure JSON logging before uvicorn starts, so its own lines are JSON too."""
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    # log_config=None: uvicorn leaves logging to us. No access log: the ticket lines above replace it.
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)


if __name__ == "__main__":
    serve()

"""JSON log lines that can be traced by ticket and never carry ticket text (FR-010).

Every record becomes one JSON object. Only fixed keys, the two IDs, a few Temporal
fields and the allow-listed extras reach the output: an extra that is not in
`ALLOWED_EXTRAS` is dropped, so a stray `extra={"body": ...}` can't leak.
"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any, TextIO

from agentic_ticket_workflow.workflow import ticket_id_from, workflow_id_for

# Values that are either Literal-typed or produced by our own code, never model or ticket text.
# `reason` takes only code-produced reason codes (e.g. "refund_needs_approval"), never a model-written reason.
ALLOWED_EXTRAS = (
    "step",
    "status",
    "created",
    "category",
    "priority",
    "action",
    "tools",
    "reason",
    "helpdesk_ref",
)

# Loggers that would otherwise bring their own handlers or levels; they follow the root instead.
_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "temporalio")
APP_LOGGER = "agentic_ticket_workflow"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = record.__dict__
        wf: dict[str, Any] = fields.get("temporal_workflow") or {}
        act: dict[str, Any] = fields.get("temporal_activity") or {}

        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        workflow_id = fields.get("workflow_id") or wf.get("workflow_id") or act.get("workflow_id")
        ticket_id = fields.get("ticket_id") or (ticket_id_from(workflow_id) if workflow_id else None)
        if ticket_id and not workflow_id:
            workflow_id = workflow_id_for(ticket_id)
        if ticket_id:
            line["ticket_id"] = ticket_id
        if workflow_id:
            line["workflow_id"] = workflow_id

        temporal = {
            "run_id": wf.get("run_id") or act.get("workflow_run_id"),
            "attempt": act.get("attempt") or wf.get("attempt"),
            "activity_type": act.get("activity_type"),
        }
        line.update({k: v for k, v in temporal.items() if v is not None})
        line.update({k: fields[k] for k in ALLOWED_EXTRAS if k in fields})

        if isinstance(record.exc_info, tuple) and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            # Type and frames only: the message and any chained cause may hold ticket or model text.
            line["error_type"] = exc_type.__name__
            line["stack"] = [f"{f.filename}:{f.lineno} in {f.name}" for f in traceback.extract_tb(tb)]

        return json.dumps(line, default=str)


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    """One JSON handler on the root. `level` applies to our loggers; all others stay at INFO or above,
    because the Temporal SDK's DEBUG lines dump activity payloads, which hold ticket text."""
    app_level = logging.getLevelNamesMapping()[level.upper()]

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for old in root.handlers[:]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(max(logging.INFO, app_level))

    logging.getLogger(APP_LOGGER).setLevel(app_level)
    for name in _THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True

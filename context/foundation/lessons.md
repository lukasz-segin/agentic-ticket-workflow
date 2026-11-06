# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Ticket text hides in derived payloads, not only in `body`

- **Context**: src/agentic_ticket_workflow/fake_llm.py:71, models.py:82 (TicketStatus.tool_calls); agent.py exception causes (review F4/F5, first-ticket-answered)
- **Problem**: The search_kb tool argument is subject + body, so `tool_calls` (and the decision, and any exception chained from a Pydantic ValidationError over model output) carry ticket text. Logging or raising these verbatim breaks FR-010's "never the ticket body" without ever touching `ticket.body`.
- **Rule**: Treat tool-call arguments, model output, decisions and their exception causes as ticket text. Logs carry only `ticket_id`, `workflow_id`, step, action type, tool names and error type names. Errors raised from model output use `from None` and a message without model text.
- **Applies to**: logging (S-02 onward), activity/agent error messages, any new field derived from ticket or model text

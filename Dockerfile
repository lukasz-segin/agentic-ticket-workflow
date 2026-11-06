# One image for both processes: CMD runs the API; compose overrides it for the
# worker with `python -m agentic_ticket_workflow.worker`.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# README.md is needed because pyproject.toml declares it and uv_build reads it.
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

RUN useradd --uid 10001 --no-create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "agentic_ticket_workflow.api:app", "--host", "0.0.0.0", "--port", "8000"]

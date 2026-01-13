FROM python:3.13-slim

# Copy uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Environment variables for optimization
# UV_COMPILE_BYTECODE=1: Compiles Python to .pyc for faster startup
# UV_LINK_MODE=copy: Ensures cache works smoothly across filesystems
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- LAYER 1: Dependencies ---
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# --- LAYER 2: Application Code ---
COPY . /app

# Install the project itself (creates .venv)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Place the virtual environment in the PATH
# This allows us to run "uvicorn" directly without "uv run"
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
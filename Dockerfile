# Self-hosted headless Chromium + FastAPI backend, deployable unchanged to a VM.
# The base image bundles Chromium + system libs; its tag MUST match the pinned
# `playwright` package (==1.60.0) so `uv run` finds the preinstalled browser.
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Factory returns a FastAPI app wired to the real Chromium driver. Chromium in a container
# needs --shm-size=1g and CHROMIUM_ARGS=--no-sandbox (see README).
CMD ["uv", "run", "uvicorn", "--factory", "backend.main:build_production_app", "--host", "0.0.0.0", "--port", "8000"]

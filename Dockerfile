# Self-hosted headless Chromium + backend. Used by milestone 0 (login gate) and
# the product (Task 5 switches CMD to the API). The base image bundles Chromium +
# system libs; the tag MUST match the pinned `playwright` package (Task 1: ==1.60.0)
# so `uv run` finds the preinstalled browser via PLAYWRIGHT_BROWSERS_PATH.
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Milestone 0 default: the proven interactive login gate (creds + MFA on stdin).
# Task 5 replaces this with: uvicorn --factory backend.main:build_production_app
CMD ["uv", "run", "python", "-m", "backend.confirm_h1"]

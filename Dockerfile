# ---- Stage 1: build the React frontend ----
# Built here so the backend can serve it at / (single-origin app = one URL to share).
# Empty VITE_API_URL => the SPA calls the API at its own origin (relative paths).
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_URL= npm run build

# ---- Stage 2: self-hosted headless Chromium + FastAPI backend ----
# The base image bundles Chromium + system libs; its tag MUST match the pinned
# `playwright` package (==1.60.0) so `uv run` finds the preinstalled browser.
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
# Built SPA from stage 1 — backend.main mounts it at / when present (no-op if absent).
COPY --from=frontend /fe/dist ./frontend/dist

# Factory returns a FastAPI app wired to the real Chromium driver + the built SPA. Chromium in
# a container needs --shm-size=1g and CHROMIUM_ARGS=--no-sandbox (see README).
CMD ["uv", "run", "uvicorn", "--factory", "backend.main:build_production_app", "--host", "0.0.0.0", "--port", "8000"]

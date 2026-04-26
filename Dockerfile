# syntax=docker/dockerfile:1.6
# Multi-stage build: stage 1 cài deps, stage 2 chỉ giữ runtime files (image nhỏ hơn)

# ─── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps cho sentence-transformers / torch
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user -r requirements.txt

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/app/.local/bin:$PATH \
    HF_HOME=/home/app/.cache/huggingface

# Chạy dưới user non-root cho an toàn
RUN useradd --create-home --shell /bin/bash app
USER app
WORKDIR /home/app

# Copy site-packages từ stage builder
COPY --from=builder --chown=app:app /root/.local /home/app/.local

# Copy source
COPY --chown=app:app . .

# Tạo data dirs (ChromaDB + SQLite + crawl cache)
RUN mkdir -p data/raw data/clean db/chroma_store

EXPOSE 8000 8501

# Toàn bộ config (port, host) đến từ .env qua docker-compose.
# uvicorn tự đọc UVICORN_HOST/UVICORN_PORT, không cần truyền flag.
CMD ["uvicorn", "api.main:app"]

# ==============================================================================
# Multi-Stage Production Dockerfile for Anti-Proxy FastAPI Backend
# Non-root execution, minimal runtime attack surface, pinned base image.
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build & Dependencies
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 2: Minimal Non-Root Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Security: Create unprivileged system group and user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -M -d /nonexistent appuser

WORKDIR /app

# Install pre-built wheels from builder stage
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels requirements.txt

# Copy application source code
COPY app ./app

# Uploaded student photos live outside the source tree, on a named volume
# mounted here (see docker-compose.yml). Created and owned by the service user
# so a fresh volume is initialised with the right ownership.
RUN mkdir -p /data/uploads/student_profiles && \
    chown -R appuser:appgroup /data/uploads && \
    chmod -R 0750 /data/uploads

ENV UPLOADS_DIR=/data/uploads

# Set least-privilege permissions
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ==============================================================================
# Multi-Stage Production Dockerfile for Anti-Proxy Vision Service
# Non-root execution (UID 10002), InsightFace/ONNX model caching, secure context.
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependency Builder
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# ------------------------------------------------------------------------------
# Stage 1b: Liveness models
# MiniFASNet (Apache-2.0) converted to ONNX and published as a release asset of
# this repository (docs/adr/ADR-011-passive-liveness-gate.md). The checksum is
# enforced by the builder: a file that does not match fails the build.
# ------------------------------------------------------------------------------
FROM scratch AS liveness-models

ADD --checksum=sha256:c058068e54189e467aff1991442b8cf5c75220ab0356f49c9508aaff9e3e91e6 \
    https://github.com/krishtewatia/anti_proxy_attendance/releases/download/liveness-models-v1/minifasnet_v2_scale2.7_80x80.onnx \
    /liveness/minifasnet_v2_scale2.7_80x80.onnx
ADD --checksum=sha256:2be5c295aefee7bf6356edbf6303b1827aab5d793e4a1898de4e11fb0fa2db35 \
    https://github.com/krishtewatia/anti_proxy_attendance/releases/download/liveness-models-v1/minifasnet_v1se_scale4.0_80x80.onnx \
    /liveness/minifasnet_v1se_scale4.0_80x80.onnx

# ------------------------------------------------------------------------------
# Stage 2: Minimal Non-Root CV Runtime
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Install essential native libraries for OpenCV and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Security: Dedicated system group and user
RUN groupadd -g 10002 visiongroup && \
    useradd -u 10002 -g visiongroup -m -d /home/visionuser -s /sbin/nologin visionuser

WORKDIR /app

# Install dependencies from builder wheels.
# setuptools is upgraded first: the copy bundled with the base image vendors
# vulnerable jaraco.context and wheel versions (flagged HIGH by Trivy).
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade setuptools && \
    pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels requirements.txt

# Prepare directories for model caching and offline event outbox
RUN mkdir -p /home/visionuser/.insightface/models /app/data && \
    chown -R visionuser:visiongroup /home/visionuser /app

# Copy application source code
COPY --chown=visionuser:visiongroup . /app

# Liveness models, read-only for the service user. The directory is created
# first with normal permissions: copying a directory with --chmod=0444 would
# also strip its execute bit, and the service could then not open the files.
RUN mkdir -p /app/models/liveness && chmod 0755 /app/models /app/models/liveness
COPY --from=liveness-models --chown=root:root --chmod=0444     /liveness/minifasnet_v2_scale2.7_80x80.onnx     /liveness/minifasnet_v1se_scale4.0_80x80.onnx     /app/models/liveness/
# Fail the build if the service user cannot read them.
RUN su -s /bin/sh visionuser -c 'test -r /app/models/liveness/minifasnet_v2_scale2.7_80x80.onnx && test -r /app/models/liveness/minifasnet_v1se_scale4.0_80x80.onnx'

USER visionuser

ENV PYTHONUNBUFFERED=1 \
    INSIGHTFACE_HOME=/home/visionuser/.insightface \
    OUTBOX_DIR=/app/data \
    LIVENESS_MODEL_DIR=/app/models/liveness

EXPOSE 8088

# Healthcheck: verifies Python process and listening signaling port
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import socket; s = socket.socket(); s.connect(('127.0.0.1', 8088)); s.close()" || exit 1

CMD ["python", "run_vision_service.py", "--host", "0.0.0.0", "--port", "8088", "--backend-url", "http://backend:8000"]

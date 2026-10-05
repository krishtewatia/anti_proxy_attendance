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

# Install dependencies from builder wheels
COPY --from=builder /build/wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels requirements.txt

# Prepare directories for model caching and offline event outbox
RUN mkdir -p /home/visionuser/.insightface/models /app/data && \
    chown -R visionuser:visiongroup /home/visionuser /app

# Copy application source code
COPY --chown=visionuser:visiongroup . /app

USER visionuser

ENV PYTHONUNBUFFERED=1 \
    INSIGHTFACE_HOME=/home/visionuser/.insightface \
    OUTBOX_DIR=/app/data

EXPOSE 8088

# Healthcheck: verifies Python process and listening signaling port
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import socket; s = socket.socket(); s.connect(('127.0.0.1', 8088)); s.close()" || exit 1

CMD ["python", "run_webrtc_camera.py", "--host", "0.0.0.0", "--port", "8088", "--backend-url", "http://backend:8000", "--camera-id", "CAM_ROOM_101_DOOR", "--cv", "--dispatch"]

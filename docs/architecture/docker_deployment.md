# Docker Compose Full Local Stack Guide (Step 2E.11)

> [!NOTE]
> **Historical context.** This document was written when a phone could stream to the vision service over WebRTC on port 8088. That path has been removed (see [ADR-010](../adr/ADR-010-drop-webrtc-phone-ingest.md)). Frames now go from the browser to the backend, the vision service is internal only, and doorway mode is offline-tested with no live ingest. Passages below that describe WebRTC, the phone camera page or port 8088 as a public endpoint no longer apply.

This document provides a comprehensive operational guide for running the Anti-Proxy Attendance System locally in Docker Compose with reproducible, multi-stage, non-root containers.

---

## 1. Stack Architecture & Topology

The Docker Compose setup defines 5 services across an isolated bridge network (`anti-proxy-net`):

```
                                      [ Mobile Phone (LAN) ]
                                                │
                                    WebRTC / HTTPS (Port 8088)
                                                ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│ React Frontend          │         │ Vision Service          │
│ (Unprivileged Nginx)    │         │ (InsightFace + ByteTrack│
│ Port 3000 -> 8080       │         │ Profile: demo           │
└────────────┬────────────┘         └───────────┬─────────────┘
             │ Reverse Proxy                    │ x-api-key Ingestion
             ▼ (/api/v1/)                       ▼ (POST /api/v1/events)
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Backend (Port 8000)                                 │
│ Multi-stage python:3.12-slim runtime (non-root appuser)     │
└─────────────────────────────┬───────────────────────────────┘
                              │ Authenticated Driver
                              ▼ (Port 27017, localhost only)
┌─────────────────────────────────────────────────────────────┐
│ MongoDB 8.0 with Authentication & Persistent Volume         │
└─────────────────────────────────────────────────────────────┘
```

### Services Summary

| Service | Image / Base | Non-Root User | Host Port | Purpose | Profile |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`mongodb`** | `mongo:8.0` | `mongodb` (UID 999) | `127.0.0.1:27017` | Event persistence, users, cameras | Default |
| **`backend`** | `python:3.12-slim` | `appuser` (UID 10001) | `8000` | FastAPI REST API, RBAC, Presence | Default |
| **`frontend`** | `nginxinc/nginx-unprivileged:1.27-alpine` | `nginx` (UID 101) | `3000` (mapped to 8080) | Teacher dashboard & Admin UI | Default |
| **`vision-service`** | `python:3.11-slim` | `visionuser` (UID 10002) | `8088` | WebRTC signaling, Face inference | `demo`, `vision` |
| **`rtsp-sim`** | `bluenviron/mediamtx:1.9.3` | `mediamtx` | `8554` | Simulated CCTV RTSP broadcast | `rtsp-sim` |

> **MongoDB 8.0.** Local, CI and the smoke test run MongoDB 8.0, the version MongoDB Atlas free clusters run. An existing 7.0 data volume starts under 8.0 without any migration step (its compatibility version stays 7.0, which is fine).

---

## 2. Security Boundaries & Hardening

1. **Non-Root Execution**: Every custom container executes under dedicated unprivileged system users (`appuser:10001`, `visionuser:10002`, `nginx:101`).
2. **MongoDB Authentication**: Root user initialized via environment variables; application user `antiproxy_user` granted only `readWrite` access to `anti_proxy_attendance` via `/docker-entrypoint-initdb.d/init-mongo.js`.
3. **Restricted Port Exposure**: MongoDB is bound strictly to `127.0.0.1:27017`, preventing exposure on external LAN interfaces.
4. **No Baked-in Secrets**: Passwords, JWT keys, and API tokens are dynamically injected via `.env` or Docker secrets; `.dockerignore` prevents accidental secret leakage during build.
5. **Persistent Volumes**:
   - `anti_proxy_mongo_data`: Database files.
   - `anti_proxy_model_cache`: InsightFace (`buffalo_l`, `buffalo_sc`) weights cached across restarts.
   - `anti_proxy_vision_outbox`: Resilient offline SQLite/JSON event spooling.

---

## 3. Quickstart: One-Command Reproduction

### Step 1: Initialize Environment

Copy the configuration template:
```bash
cp .env.example .env
```
Populate `.env` with secure keys:
```env
MONGO_ROOT_PASSWORD=MySecureMongoRootPassword123!
MONGO_APP_PASSWORD=MySecureAppPassword123!
JWT_SECRET_KEY=at_least_32_chars_random_secret_string_here!
VISION_SERVICE_API_KEY=my_secure_random_vision_api_key_456!
```

### Step 2: Start the System

**Option A: Default Development Stack (Backend, Frontend, MongoDB)**
```bash
docker compose up -d
```

**Option B: Full Demo Stack (includes Vision Service)**
```bash
docker compose --profile demo up -d
```

**Option C: Full Stack with RTSP CCTV Simulator**
```bash
docker compose --profile demo --profile rtsp-sim up -d
```

Verify all containers are healthy:
```bash
docker compose ps
```

---

## 4. Database Seeding & Admin Bootstrap

To initialize the database with an Admin, Demo Teacher, Demo Students, Registered Camera, and an Active Attendance Session:

```bash
python scripts/seed_demo.py --non-interactive
```

*(Interactive mode will prompt securely for passwords without echoing to terminal).*

Created resources:
- **Admin**: `admin@system.local`
- **Teacher**: `teacher@demo.edu`
- **Classroom**: `ROOM_101`
- **Camera**: `CAM_ROOM_101_DOOR`
- **Active Session**: `CS-101` in `ROOM_101`

---

## 5. WebRTC Phone Access & Secure Context (LAN / HTTPS)

Modern mobile browsers (iOS Safari, Android Chrome) enforce a strict **Secure Context** policy:
`navigator.mediaDevices.getUserMedia()` is **BLOCKED** on unencrypted HTTP connections unless accessing `localhost`.

When streaming from a smartphone on the local network (`http://192.168.x.x:8088`), mobile browsers will deny camera access.

### Recommended Solutions for Local Testing

#### Solution 1: Reverse Proxy with `mkcert` (Recommended)
1. Install `mkcert` (https://github.com/FiloSottile/mkcert).
2. Generate local CA and install on your phone's certificate store.
3. Issue a certificate for your machine's LAN IP:
   ```bash
   mkcert 192.168.1.50
   ```
4. Configure an HTTPS reverse proxy (e.g. Caddy or Nginx) to forward port `8443 -> 8088`.

#### Solution 2: Android USB Reverse Port Forwarding (Zero Setup)
Connect your Android phone via USB with developer mode enabled:
```bash
adb reverse tcp:8088 tcp:8088
```
Now, on the phone's Chrome browser, navigate to:
```
http://localhost:8088
```
Because the phone connects to `localhost`, Chrome considers it a **Secure Context** and allows full camera access without SSL!

#### Solution 3: Chrome Flag Override (Android Only)
In Android Chrome:
1. Open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`.
2. Add your server's LAN address (e.g. `http://192.168.1.50:8088`).
3. Enable the flag and restart Chrome.

---

## 6. Operational Commands

### Viewing Logs
```bash
# View all logs
docker compose logs -f

# View backend logs only
docker compose logs -f backend

# View vision service inference logs
docker compose logs -f vision-service
```

### Running the End-to-End Smoke Test
Verify the full system lifecycle automatically:
```bash
python scripts/docker_smoke_test.py
```

### Clean Teardown
```bash
# Stop containers
docker compose down

# Stop containers and destroy volumes (clean state)
docker compose down -v
```

---

## 7. Known Limitations & CPU Considerations in Containers

1. **CPU Inference in Containers**:
   InsightFace (`SCRFD` face detection and `ArcFace` embeddings) is CPU-intensive. Under Docker on macOS or Windows (WSL2), ensure at least 4 virtual CPUs and 4 GB RAM are allocated in Docker settings.
2. **ONNX Threading**:
   By default, `run_webrtc_camera.py` uses `--intra-threads 4 --inter-threads 2`. On constrained hosts, adjust these parameters to prevent thread contention.
3. **Apple Silicon / ARM64 Translation**:
   When running on ARM64 hosts, images build natively using multi-stage Alpine/Slim bases; ONNX Runtime provides native ARM64 wheels.

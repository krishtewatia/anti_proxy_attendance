# Operational Troubleshooting Guide

> [!NOTE]
> **Historical context.** This document was written when a phone could stream to the vision service over WebRTC on port 8088. That path has been removed (see [ADR-010](../adr/ADR-010-drop-webrtc-phone-ingest.md)). Frames now go from the browser to the backend, the vision service is internal only, and doorway mode is offline-tested with no live ingest. Passages below that describe WebRTC, the phone camera page or port 8088 as a public endpoint no longer apply.

## 1. Quick Diagnostic Flowchart

```mermaid
flowchart TD
    START["Encountered an Issue?"] --> CHK{"Which Component?"}
    CHK -->|"Camera Stream / WebRTC"| CAM["1. Mobile Camera Permissions & LAN HTTPS"]
    CHK -->|"Computer Vision"| MOD["2. Missing InsightFace Model Weights"]
    CHK -->|"Backend API / Database"| DB["3. MongoDB Authentication & Connectivity"]
    CHK -->|"Startup / Compose"| PORT["4. Port Conflicts & Docker Daemons"]
```

---

## 2. WebRTC Mobile Phone Camera Access over LAN

### The Issue
Modern mobile browsers (Chrome on Android, Safari on iOS) enforce strict W3C security standards: `navigator.mediaDevices.getUserMedia` is **only accessible in a Secure Context** (i.e., `https://` or `http://localhost`).

When opening the camera streaming page over a Local Area Network (e.g., `http://192.168.1.100:8088`), the browser may fail silently or throw:
```text
TypeError: Cannot read properties of undefined (reading 'getUserMedia')
NotAllowedError: Permission denied / Insecure origin
```

### Verified Solutions

#### Solution A: Enable Chrome Insecure Origin Flag (Fastest for Testing)
1. On the mobile phone, open Chrome and navigate to:
   ```text
   chrome://flags/#unsafely-treat-insecure-origin-as-secure
   ```
2. Enable the flag.
3. In the text area below the flag, add your workstation's LAN IP and port:
   ```text
   http://192.168.1.100:8088
   ```
4. Click **Relaunch** at the bottom of the screen.
5. Re-open `http://192.168.1.100:8088`—the browser will now prompt for camera access.

#### Solution B: Localhost Testing from PC Webcam
If demonstrating locally without a phone, open [http://localhost:8088](http://localhost:8088) directly in your desktop browser. Since `localhost` is inherently trusted, camera access is granted immediately.

#### Solution C: Local TLS Tunnel via Caddy or Ngrok
```bash
# Using ngrok:
ngrok http 8088
# Open the secure https://xxxx.ngrok-free.app link on any mobile device.
```

---

## 3. Missing InsightFace Model Weights

### The Issue
At startup, `LiveCVPipeline` attempts to load the `buffalo_l` model bundle (`scrfd_10g_kps.onnx` and `w600k_r50.onnx`). If running offline or behind a strict campus firewall, the automatic download may hang or raise:
```text
insightface.model_zoo.model_zoo.ModelNotFoundError
URLError: <urlopen error timed out>
```

### Verified Solutions
The models are stored in the user's home directory:
- **Windows**: `C:\Users\<username>\.insightface\models\buffalo_l\`
- **Linux / Docker**: `/root/.insightface/models/buffalo_l/`

If downloading fails automatically:
1. Download `buffalo_l.zip` manually from the [InsightFace Release Repository](https://github.com/deepinsight/insightface/releases).
2. Extract the files into `~/.insightface/models/buffalo_l/`:
   ```text
   ~/.insightface/models/buffalo_l/
   ├── 1k3d68.onnx
   ├── 2d106det.onnx
   ├── genderage.onnx
   ├── scrfd_10g_kps.onnx
   └── w600k_r50.onnx
   ```
3. When using Docker Compose, the pre-configured named volume `model_cache` persists downloaded weights across container rebuilds.

---

## 4. MongoDB Authentication & Connection Errors

### The Issue
FastAPI raises connection errors or authentication failures during startup:
```text
pymongo.errors.OperationFailure: Authentication failed.
pymongo.errors.ServerSelectionTimeoutError: No replica set members found
```

### Root Causes & Verified Resolutions

#### Scenario 1: Docker Compose Auth Mismatch
- MongoDB initialization (`docker/init-mongo.js`) creates an unprivileged user (`MONGO_APP_USERNAME`) inside the database specified by `DATABASE_NAME`.
- Ensure your `MONGODB_URL` includes the `authSource` parameter:
  ```text
  mongodb://antiproxy_user:your_password@mongodb:27017/anti_proxy_attendance?authSource=anti_proxy_attendance
  ```

#### Scenario 2: Running Without Docker (Bare-Metal Local Development)
- If running a bare-metal local MongoDB instance without credentials, configure `.env`:
  ```text
  MONGODB_URL=mongodb://localhost:27017
  ```
- If no MongoDB instance is running at all, the FastAPI backend will log a warning and **automatically fall back to an in-memory mock client** (`mongomock-motor`), allowing unit tests and API exploration to continue seamlessly.

---

## 5. Port Conflicts

The system requires four default network ports:
- `3000`: React Frontend (Vite)
- `8000`: FastAPI Backend
- `8088`: WebRTC Phone Camera Streamer
- `27017`: MongoDB Database

### Identifying and Freeing Busy Ports

#### On Windows (PowerShell):
```powershell
# Identify process listening on port 8000:
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess, State

# Stop the conflicting process by PID:
Stop-Process -Id <PID> -Force
```

#### On Linux / macOS:
```bash
# Identify and kill process on port 8000:
lsof -i :8000
kill -9 <PID>
```

---

## 6. Outbox Queue Inspection & Recovery

The Vision Service records all transit events in a local SQLite database (`outbox.db`) to ensure zero event loss during network interruptions:

```bash
# Inspect outbox status using sqlite3:
sqlite3 outbox.db "SELECT event_id, identity, direction, state, retry_count FROM outbox_events;"

# Check pending un-transmitted events:
sqlite3 outbox.db "SELECT count(*) FROM outbox_events WHERE state = 'PENDING';"
```

If the backend was temporarily offline, the background dispatcher thread automatically resumes transmissions with randomized exponential backoff as soon as `http://localhost:8000/api/v1/health` returns healthy.

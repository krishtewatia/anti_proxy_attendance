# Environment Variables Reference Guide

> [!NOTE]
> **Historical context.** This document was written when a phone could stream to the vision service over WebRTC on port 8088. That path has been removed (see [ADR-010](../adr/ADR-010-drop-webrtc-phone-ingest.md)). Frames now go from the browser to the backend, the vision service is internal only, and doorway mode is offline-tested with no live ingest. Passages below that describe WebRTC, the phone camera page or port 8088 as a public endpoint no longer apply.

## 1. Overview & Setup

The Anti-Proxy Attendance System relies on environment variables for database connections, cryptographic keys, perception thresholds, and service discovery.

A starter template is provided in [`.env.example`](file:///.env.example). To configure the local stack:
```bash
cp .env.example .env
```

To generate cryptographically secure random secrets for `.env`:
```bash
# Generate high-entropy 32-byte secret (for JWT_SECRET_KEY or VISION_SERVICE_API_KEY):
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 2. Master Configuration Reference Table

### 2.1 Core Application & Database Settings
| Variable | Default Value | Required | Target | Description & Security Notes |
| :--- | :---: | :---: | :---: | :--- |
| `APP_NAME` | `Anti-Proxy Attendance System` | No | All | Human-readable system name. |
| `APP_ENV` | `development` | No | All | Environment mode (`development`, `staging`, `production`). |
| `DEBUG` | `true` | No | Backend | Enables verbose FastAPI debugging and stack traces. Must be `false` in production. |
| `MONGO_ROOT_USERNAME` | `admin` | Yes (Docker) | Docker | Root administrative username for container initialization. |
| `MONGO_ROOT_PASSWORD` | *(None)* | Yes (Docker) | Docker | Strong password for MongoDB root admin. |
| `MONGO_APP_USERNAME` | `antiproxy_user` | Yes (Docker) | Docker | Unprivileged application database user created by `init-mongo.js`. |
| `MONGO_APP_PASSWORD` | *(None)* | Yes (Docker) | Docker | Strong password for unprivileged application database user. |
| `DATABASE_NAME` | `anti_proxy_attendance` | No | Backend | Target MongoDB database name. |
| `EVENTS_COLLECTION` | `attendance_events` | No | Backend | MongoDB collection for storing raw transit events. |
| `MONGODB_URL` | `mongodb://localhost:27017` | Yes | Backend | Full MongoDB URI. For Docker: `mongodb://${MONGO_APP_USERNAME}:${MONGO_APP_PASSWORD}@mongodb:27017/${DATABASE_NAME}?authSource=${DATABASE_NAME}`. |

### 2.2 JWT Authentication & Access Control
| Variable | Default Value | Required | Target | Description & Security Notes |
| :--- | :---: | :---: | :---: | :--- |
| `JWT_SECRET_KEY` | *(None)* | **YES** | Backend | Secret key used to sign HS256 JWT tokens. **Must be $\ge 32$ characters long**. Application startup fails if using weak passwords (`secret`, `password`, `changeme`). |
| `JWT_ALGORITHM` | `HS256` | No | Backend | Cryptographic signing algorithm. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | No | Backend | Access token lifetime in minutes. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,...` | No | Backend | Comma-separated list of allowed browser origins. Wildcard `*` with credentials is explicitly rejected. |

### 2.3 Service-to-Service Ingestion & Security
| Variable | Default Value | Required | Target | Description & Security Notes |
| :--- | :---: | :---: | :---: | :--- |
| `VISION_SERVICE_API_KEY` | *(None)* | **YES** | Backend & Vision | Shared secret token passed by Vision Service in `X-Camera-Token` or `Bearer` header. |
| `VISION_SERVICE_API_KEY_HASH`| *(None)* | No | Backend | Optional precomputed SHA-256 hex digest of the vision service key for zero-plaintext verification. |
| `VISION_CAMERA_KEYS` | `{}` | No | Backend | Optional JSON map of per-camera tokens: `{"CAM_01": "secret1", "CAM_02": "secret2"}`. |
| `REQUIRE_CAMERA_AUTH` | `true` | No | Backend | Enforces authentication on `POST /api/v1/events`. Must always be `true` outside test harnesses. |
| `EVENTS_MAX_PAYLOAD_BYTES` | `65536` (64 KB) | No | Backend | Maximum allowed body size for transit event requests to prevent memory exhaustion DoS. |
| `EVENTS_RATE_LIMIT_PER_MINUTE` | `600` | No | Backend | Maximum allowed event posts per minute per camera IP. |
| `EVENT_TIMESTAMP_VALIDATION_ENABLED`| `true` | No | Backend | Validates event timestamps are within acceptable past/future skew windows. |
| `EVENT_MAX_FUTURE_SKEW_SECONDS` | `2592000` (30 d) | No | Backend | Maximum allowed future timestamp skew. |
| `EVENT_MAX_PAST_AGE_SECONDS` | `5184000` (60 d) | No | Backend | Maximum allowed past age for ingested historical events. |
| `CAP_MISSING_EXIT_AT_SESSION_END` | `false` | No | Backend | If `true`, unclosed `ENTRY` events without an `EXIT` are credited up to `session_end` upon finalization. |

### 2.4 Vision Service & Perception Parameters
| Variable | Default Value | Required | Target | Description & Security Notes |
| :--- | :---: | :---: | :---: | :--- |
| `API_BASE_URL` | `http://localhost:8000` | Yes | Vision | Base URL of the backend FastAPI service. |
| `CAMERA_ID` | `CAM_ROOM_101_DOOR` | Yes | Vision | Unique identifier of the camera reporting events. |
| `CLASSROOM_ID` | `LH-101` | No | Vision | Classroom identifier bound to the camera. |
| `CAMERA_ROLE` | `BOTH` | No | Vision | Operational transit role (`ENTRY`, `EXIT`, or `BOTH`). |
| `SOURCE_TYPE` | `webrtc` | No | Vision | Video input source (`webrtc`, `rtsp`, or `file`). |
| `RTSP_URL` | *(None)* | If RTSP | Vision | RTSP stream endpoint (e.g. `rtsp://user:pass@192.168.1.50:554/live`). Never logged. |
| `WEBRTC_PORT` | `8088` | No | Vision | Port for embedded WebRTC phone streaming server. |
| `WEBRTC_ACCESS_TOKEN` | *(None)* | No | Vision | Optional authentication token required to initiate WebRTC stream from browser. |
| `RECOGNITION_SIMILARITY_THRESHOLD`| `0.50` | No | Vision | Minimum ArcFace cosine score to consider identity match. |
| `RECOGNITION_MIN_MARGIN` | `0.15` | No | Vision | Minimum relative margin between top candidate and second-best candidate. |
| `RECOGNITION_MIN_VOTES` | `3` | No | Vision | Number of consistent frames required for track identity confirmation. |
| `DEADBAND_PIXELS` | `14.0` | No | Vision | Width of boundary hysteresis zone around line in pixels. |
| `OUTBOX_DB_PATH` | `outbox.db` | No | Vision | File path for local SQLite durable outbox store. |

### 2.5 Frontend Web Application
| Variable | Default Value | Required | Target | Description & Security Notes |
| :--- | :---: | :---: | :---: | :--- |
| `VITE_API_URL` | `http://localhost:8000` | Yes | Frontend | Backend API endpoint URL used by browser AJAX requests. |

---

## 3. Configuration Security Checklist

1. **Never commit `.env` files**: Confirm that `.env` is listed in [`.gitignore`](file:///.gitignore).
2. **Rotate secrets across environments**: Use distinct keys for local development, testing, and production.
3. **Audit token lengths**: Ensure `JWT_SECRET_KEY` and `VISION_SERVICE_API_KEY` are at least 32 characters long.
4. **Disable debugging in production**: Set `DEBUG=false` to prevent internal trace exposure.
5. **No CORS wildcards**: Restrict `CORS_ALLOWED_ORIGINS` to trusted institution web domains.

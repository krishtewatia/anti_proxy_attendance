# API Reference & Service Integration Guide

## 1. Interactive API Documentation

The FastAPI backend automatically generates interactive OpenAPI documentation and schema specifications accessible when the backend is running:

| Documentation Surface | Local URL | Description |
| :--- | :--- | :--- |
| **Swagger UI (Interactive)** | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive testing console with JWT authorization modal. |
| **ReDoc (Static Specifications)** | [http://localhost:8000/redoc](http://localhost:8000/redoc) | Clean, readable documentation of all endpoints, parameters, and schemas. |
| **OpenAPI Specification (JSON)**| [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json) | Raw OpenAPI 3.1.0 JSON schema for code generation and automated testing. |

---

## 2. Authentication & Authorization Schemes

The system enforces two distinct authentication layers:

### 2.1 User Authentication (OAuth2 Bearer JWT)
Used by human operators (Teachers, Administrators, Students) accessing web dashboard endpoints:
- **Header**: `Authorization: Bearer <JWT_ACCESS_TOKEN>`
- **Token Format**: HS256 signed JSON Web Token containing `sub` (User ID), `role`, and `exp`.
- **RBAC Roles**:
  - `ADMIN`: Full system access, camera registry management, student biometric enrollment, and audit log inspection.
  - `TEACHER`: Session creation, live attendance monitoring, manual attendance overrides, and session finalization.
  - `STUDENT`: Read-only access to personal attendance records and profile status.

### 2.2 Machine-to-Machine Camera Service Auth
Used by edge cameras and vision workers dispatching events to `POST /api/v1/events`:
- **Supported Headers**:
  - `X-Camera-Token: <SECRET_KEY>`
  - `Authorization: Bearer <SECRET_KEY>`
- **Security Validation**: Validated via timing-safe cryptographic comparison (`secrets.compare_digest`). Optionally verifies that the token corresponds to the specific `camera_id` declared in the payload.

---

## 3. Core API Route Groups

### 3.1 Authentication (`/api/v1/auth`)
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v1/auth/login` | Public | Authenticate with email/password; returns access token. |
| `POST` | `/api/v1/auth/register` | Admin | Register a new user account with specified role. |
| `GET` | `/api/v1/auth/me` | Authenticated | Retrieve authenticated user profile and permissions. |

### 3.2 Vision Event Ingestion (`/api/v1/events`)
> Detailed specification available in [Event Contract Specification](file:///docs/api/event-contract.md).

| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v1/events` | Camera Service | Ingest directional transit event (`ENTRY` / `EXIT`). Enforces 64 KB payload cap and 600 req/min rate limit. |
| `GET` | `/api/v1/events` | Teacher / Admin | Query ingested events with pagination and filtering. |

### 3.3 Session Management (`/sessions`)
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `POST` | `/sessions` | Teacher / Admin | Schedule or start a new attendance session. |
| `GET` | `/sessions` | Teacher / Admin | List all sessions created by or assigned to the user. |
| `GET` | `/sessions/{id}` | Teacher / Admin | Retrieve session metadata and scheduled time boundaries. |
| `GET` | `/sessions/{id}/live` | Teacher / Admin | Retrieve real-time attendance snapshot (student states, accumulated presence, recent event feed). |
| `POST` | `/sessions/{id}/roster` | Teacher / Admin | Assign enrolled student list to the session. |

### 3.4 Attendance & Finalization (`/attendance`)
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `GET` | `/attendance/session/{id}` | Teacher / Admin | Fetch calculated attendance records for a session. |
| `POST` | `/attendance/session/{id}/finalize` | Teacher / Admin | Lock session, evaluate 75% presence ratio, and assign `PRESENT` / `ABSENT` statuses. |
| `POST` | `/attendance/corrections` | Teacher / Admin | Submit a manual attendance override with mandatory audit justification. |

### 3.5 Camera Registry (`/cameras`)
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `POST` | `/cameras` | Admin | Register a new camera with classroom binding and role (`ENTRY`, `EXIT`, `BOTH`). |
| `GET` | `/cameras` | Teacher / Admin | List all registered cameras and operational health. |
| `GET` | `/cameras/{id}/health` | Teacher / Admin | Check camera heartbeat and last-seen timestamp. |
| `DELETE` | `/cameras/{id}` | Admin | De-register camera from system. |

### 3.6 Student Biometric Enrollment (`/enrollment`)
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `POST` | `/enrollment/student` | Admin | Upload multi-photo enrollment bundle, extract 512-d ArcFace mean embedding, and store profile. |
| `GET` | `/enrollment/gallery` | Camera Service | Fetch current gallery vector matrix for in-memory camera matching. |

### 3.7 Audit & Compliance (`/audit`)
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `GET` | `/audit/events` | Admin | Query immutable audit log with actor and timestamp filters. |
| `GET` | `/audit/resource/{type}/{id}` | Admin | Retrieve complete modification history for a specific resource. |

### 3.8 Health & Telemetry
| Method | Path | Access | Summary |
| :--- | :--- | :---: | :--- |
| `GET` | `/health` or `/api/v1/health` | Public | Liveness probe returning service status. |
| `GET` | `/ready` | Public | Readiness probe verifying database connectivity. |

---

## 4. Standard Error Codes & Envelopes

All error responses return structured JSON:

```json
{
  "detail": "Descriptive human-readable error explanation",
  "error_code": "RESOURCE_NOT_FOUND",
  "timestamp": "2026-10-03T11:30:00Z"
}
```

| HTTP Status | Meaning | Typical Trigger |
| :---: | :--- | :--- |
| **`400 Bad Request`** | Malformed parameters | Invalid timestamp format, end time prior to start time. |
| **`401 Unauthorized`** | Missing or invalid auth | Expired JWT token, invalid `X-Camera-Token`. |
| **`403 Forbidden`** | Insufficient permissions | Student attempting to access teacher finalization endpoint. |
| **`404 Not Found`** | Resource missing | Requested `session_id` or `camera_id` does not exist. |
| **`413 Payload Too Large`**| Body exceeds size limit | Event batch or image upload exceeds `EVENTS_MAX_PAYLOAD_BYTES` (64 KB). |
| **`422 Unprocessable`** | Schema validation failure | Missing required field according to Pydantic model. |
| **`429 Too Many Requests`**| Rate limit exceeded | Camera worker sending > 600 requests/minute. |

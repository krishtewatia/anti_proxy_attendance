from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import events_router
from app.api.routes.attendance import router as attendance_router
from app.api.routes.attendance_corrections import (
    router as attendance_corrections_router,
)
from app.api.routes.session_roster import router as session_roster_router
from app.api.routes.session_finalization import (
    router as session_finalization_router,
)
from app.api.routes.audit import router as audit_router
from app.api.routes.auth import router as auth_router
from app.api.routes.enrollment import router as enrollment_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.students import router as students_router
from app.api.routes.cameras import router as cameras_router
from app.api.routes.admin import router as admin_router
from app.api.routes.academic import router as academic_router
from app.api.routes.teachers import router as teachers_router
from app.database import close_client, get_database, init_indexes
from app.database.academic import seed_academic_data_if_empty


from app.core.config import settings
from app.core.logging_security import setup_security_logging
from app.security.config import (
    JWT_SECRET_KEY,
    is_insecure_recognition_key_allowed,
    validate_jwt_secret_strength,
    validate_liveness_mode,
    validate_recognition_signing_key,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Security Validations
    validate_jwt_secret_strength(JWT_SECRET_KEY)
    validate_recognition_signing_key(
        settings.RECOGNITION_SIGNING_KEY,
        allow_insecure=is_insecure_recognition_key_allowed(),
    )
    validate_liveness_mode(settings.LIVENESS_MODE)
    setup_security_logging()

    # Startup: ensure database indexes are initialized
    db = get_database()
    try:
        await init_indexes(db)
    except Exception:
        # Fallback to in-memory mock client if local MongoDB daemon is not running
        from app.database import mongodb
        from mongomock_motor import AsyncMongoMockClient

        mongodb._client = AsyncMongoMockClient()
        db = mongodb.get_database()
        await init_indexes(db)
    try:
        await seed_academic_data_if_empty()
    except Exception:
        pass
    yield
    # Shutdown: close active client connection
    close_client()


from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Anti-Proxy Attendance System Backend",
    version="0.1.0",
    description="Backend API for Anti-Proxy Attendance System",
    lifespan=lifespan,
)

cors_origins = settings.CORS_ALLOWED_ORIGINS
allow_creds = True
if "*" in cors_origins:
    allow_creds = False  # W3C CORS forbids credentials when wildcard '*' is used

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_payload_size_limit(request: Request, call_next):
    if request.method == "POST" and request.url.path.rstrip("/").endswith("/events"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.EVENTS_MAX_PAYLOAD_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "detail": f"Payload size exceeds maximum allowed limit of {settings.EVENTS_MAX_PAYLOAD_BYTES} bytes"
                },
            )
    return await call_next(request)


# Register API v1 routes
app.include_router(events_router, prefix="/api/v1")
app.include_router(attendance_router)
app.include_router(attendance_corrections_router)
app.include_router(session_roster_router)
app.include_router(session_finalization_router)
app.include_router(sessions_router)
app.include_router(students_router)
app.include_router(audit_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(enrollment_router)
if not settings.DEMO_MODE:
    app.include_router(cameras_router)
app.include_router(admin_router)
app.include_router(academic_router)
app.include_router(teachers_router)

# Mount uploads directory for static file serving
from pathlib import Path
from fastapi.staticfiles import StaticFiles

uploads_dir = Path("/app/uploads") if Path("/app/uploads").exists() else Path("uploads")
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Anti-Proxy Attendance API"}


@app.get("/health")
@app.get("/api/v1/health")
def health_check():
    return {
        "status": "healthy",
        "service": "anti-proxy-backend",
        "version": "0.1.0",
    }


@app.get("/ready")
def readiness_check():
    return {
        "status": "ready",
        "service": "anti-proxy-backend",
        "version": "0.1.0",
    }

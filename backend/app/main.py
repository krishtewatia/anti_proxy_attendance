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
from app.api.routes.sessions import router as sessions_router
from app.api.routes.students import router as students_router
from app.database import close_client, get_database, init_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    yield
    # Shutdown: close active client connection
    close_client()



from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Anti-Proxy Attendance System Backend",
    version="0.1.0",
    description="Backend API for Anti-Proxy Attendance System",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/")
def read_root():
    return {"message": "Welcome to the Anti-Proxy Attendance API"}


@app.get("/health")
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

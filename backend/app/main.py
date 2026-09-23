from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.routes import events_router
from app.database import close_client, get_database, init_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure database indexes are initialized
    try:
        db = get_database()
        await init_indexes(db)
    except Exception:
        # Allows startup in environments where MongoDB is lazy-loaded or mocked
        pass
    yield
    # Shutdown: close active client connection
    close_client()


app = FastAPI(
    title="Anti-Proxy Attendance System Backend",
    version="0.1.0",
    description="Backend API for Anti-Proxy Attendance System",
    lifespan=lifespan,
)

# Register API v1 routes
app.include_router(events_router, prefix="/api/v1")


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

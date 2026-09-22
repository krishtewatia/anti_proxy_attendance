from fastapi import FastAPI

app = FastAPI(
    title="Anti-Proxy Attendance System Backend",
    version="0.1.0",
    description="Backend API for Anti-Proxy Attendance System",
)


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

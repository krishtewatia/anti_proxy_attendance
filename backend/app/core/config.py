import os
from pathlib import Path
from dotenv import load_dotenv

# Load backend/.env if present
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BACKEND_DIR / ".env"
load_dotenv(dotenv_path=env_path)

UPLOADS_DIR = (
    Path("/app/uploads/student_profiles")
    if Path("/app/uploads").exists()
    else (BACKEND_DIR / "uploads" / "student_profiles")
)


class Settings:
    PROJECT_NAME: str = os.getenv("APP_NAME", "Anti-Proxy Attendance System")
    ENVIRONMENT: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in {"true", "1", "yes"}

    # MongoDB connection settings
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "anti_proxy_attendance")
    EVENTS_COLLECTION: str = os.getenv("EVENTS_COLLECTION", "attendance_events")

    # Service-to-service / Camera credentials
    VISION_SERVICE_API_KEY: str = os.getenv("VISION_SERVICE_API_KEY", "")
    VISION_SERVICE_API_KEY_HASH: str = os.getenv("VISION_SERVICE_API_KEY_HASH", "")
    VISION_CAMERA_KEYS: str = os.getenv("VISION_CAMERA_KEYS", "")
    REQUIRE_CAMERA_AUTH: bool = os.getenv("REQUIRE_CAMERA_AUTH", "true").lower() in {
        "true",
        "1",
        "yes",
    }

    # CORS configuration
    CORS_ALLOWED_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]

    # Ingestion protection
    EVENTS_MAX_PAYLOAD_BYTES: int = int(os.getenv("EVENTS_MAX_PAYLOAD_BYTES", "65536"))  # 64 KB
    EVENTS_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("EVENTS_RATE_LIMIT_PER_MINUTE", "600"))

    # Event timestamp validation
    EVENT_MAX_FUTURE_SKEW_SECONDS: int = int(
        os.getenv("EVENT_MAX_FUTURE_SKEW_SECONDS", str(86400 * 30))
    )
    EVENT_MAX_PAST_AGE_SECONDS: int = int(os.getenv("EVENT_MAX_PAST_AGE_SECONDS", str(86400 * 60)))
    EVENT_TIMESTAMP_VALIDATION_ENABLED: bool = os.getenv(
        "EVENT_TIMESTAMP_VALIDATION_ENABLED", "true"
    ).lower() in {"true", "1", "yes"}

    # Missing EXIT finalization behavior
    CAP_MISSING_EXIT_AT_SESSION_END: bool = os.getenv(
        "CAP_MISSING_EXIT_AT_SESSION_END", "false"
    ).lower() in {"true", "1", "yes"}

    # Simplified Demo Mode flag (restricts cameras to CAM_ROOM_101_DOOR and hides CCTV config)
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() in {"true", "1", "yes"}
    DEMO_CAMERA_ID: str = os.getenv("DEMO_CAMERA_ID", "CAM_ROOM_101_DOOR")


settings = Settings()

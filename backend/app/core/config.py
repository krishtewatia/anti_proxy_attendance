"""Application configuration settings."""

import os
from pathlib import Path


class Settings:
    PROJECT_NAME: str = os.getenv("APP_NAME", "Anti-Proxy Attendance System")
    ENVIRONMENT: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in {"true", "1", "yes"}

    # MongoDB connection settings
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "anti_proxy_attendance")
    EVENTS_COLLECTION: str = os.getenv("EVENTS_COLLECTION", "attendance_events")


settings = Settings()

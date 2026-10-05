import os
from pathlib import Path
from dotenv import load_dotenv

# Load backend/.env if present
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

WEAK_JWT_SECRETS = {
    "secret",
    "password",
    "changeme",
    "admin",
    "12345678",
    "12345678901234567890123456789012",
    "development",
    "test",
    "default",
}


def validate_jwt_secret_strength(key: str | None) -> None:
    """Validate JWT secret key length and prevent common insecure defaults."""
    if not key or not key.strip():
        raise RuntimeError("JWT_SECRET_KEY environment variable is not set")
    if key.lower().strip() in WEAK_JWT_SECRETS:
        raise RuntimeError("JWT_SECRET_KEY is using an insecure, commonly guessed default value")
    if len(key) < 32:
        raise RuntimeError(
            f"JWT_SECRET_KEY must be at least 32 characters long for cryptographic security (found {len(key)})"
        )


validate_jwt_secret_strength(JWT_SECRET_KEY)

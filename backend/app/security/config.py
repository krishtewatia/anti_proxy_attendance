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

RECOGNITION_KEY_MIN_LENGTH = 32
PLACEHOLDER_KEY_PREFIX = "replace_with"


def is_insecure_recognition_key_allowed() -> bool:
    """Explicit opt-out for local development and tests only."""
    return os.getenv("ALLOW_INSECURE_RECOGNITION_KEY", "false").lower() in {"true", "1", "yes"}


def validate_recognition_signing_key(key: str | None, *, allow_insecure: bool = False) -> None:
    """Refuse to start without a real recognition signing key.

    The key authenticates every recognition result that can mark attendance,
    so a missing, placeholder or short key must never reach a running service.
    ``allow_insecure`` is the explicit development/test override.
    """
    if allow_insecure:
        return
    if not key or not key.strip():
        raise RuntimeError(
            "RECOGNITION_SIGNING_KEY is not set. Generate one with "
            '`python -c "import secrets; print(secrets.token_hex(32))"` and set it for both '
            "the backend and the vision service."
        )
    cleaned = key.strip()
    if cleaned.lower().startswith(PLACEHOLDER_KEY_PREFIX):
        raise RuntimeError(
            "RECOGNITION_SIGNING_KEY is still the placeholder from .env.example. "
            "Replace it with a generated secret."
        )
    if len(cleaned) < RECOGNITION_KEY_MIN_LENGTH:
        raise RuntimeError(
            f"RECOGNITION_SIGNING_KEY must be at least {RECOGNITION_KEY_MIN_LENGTH} characters "
            f"long (found {len(cleaned)})."
        )

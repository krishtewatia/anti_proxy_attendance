"""Security logging filter to scrub sensitive data from application logs."""

from __future__ import annotations

import logging
import re
from typing import Any

# Regular expressions for identifying sensitive data
BEARER_PATTERN = re.compile(r"Bearer\s+([A-Za-z0-9\-_\.=]+)", re.IGNORECASE)
API_KEY_PATTERN = re.compile(
    r"((?:['\"]?(?:x[-_]api[-_]key|api[-_]key|access[-_]token)['\"]?)\s*[:=]\s*['\"]?)([A-Za-z0-9\-_\.=]+)(['\"]?)",
    re.IGNORECASE,
)
PASSWORD_PATTERN = re.compile(
    r"((?:['\"]?(?:password|secret)['\"]?)\s*[:=]\s*['\"]?)([^'\",\s]+)(['\"]?)",
    re.IGNORECASE,
)
BASE64_IMAGE_PATTERN = re.compile(
    r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=]+",
    re.IGNORECASE,
)
LONG_EMBEDDING_PATTERN = re.compile(r"\[\s*(-?\d+\.\d+,\s*){8,}-?\d+\.\d+\s*\]")


class SensitiveDataFilter(logging.Filter):
    """Logging filter that scrubs tokens, passwords, API keys, embeddings, and raw base64 images."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.scrub_sensitive_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self.scrub_sensitive_value(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.scrub_sensitive_value(arg) for arg in record.args)

        return True

    @classmethod
    def scrub_sensitive_text(cls, text: str) -> str:
        """Scrub sensitive credential and biometric patterns from string messages."""
        if not isinstance(text, str):
            return text
        text = BEARER_PATTERN.sub(r"Bearer [REDACTED]", text)
        text = API_KEY_PATTERN.sub(r"\1[REDACTED]\3", text)
        text = PASSWORD_PATTERN.sub(r"\1[REDACTED]\3", text)
        text = BASE64_IMAGE_PATTERN.sub(r"[BASE64_IMAGE_REDACTED]", text)
        text = LONG_EMBEDDING_PATTERN.sub(r"[EMBEDDING_VECTOR_REDACTED]", text)
        return text

    @classmethod
    def scrub_sensitive_value(cls, val: Any) -> Any:
        if isinstance(val, str):
            return cls.scrub_sensitive_text(val)
        return val


def setup_security_logging() -> None:
    """Attach SensitiveDataFilter to root and application loggers."""
    sec_filter = SensitiveDataFilter()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(sec_filter)
    root_logger.addFilter(sec_filter)

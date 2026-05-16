"""Secret redaction helpers for traces and audit records."""

from __future__ import annotations

import os
from typing import Any


SENSITIVE_KEY_PARTS = (
    "PASS",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "PRIVATE_KEY",
    "WALLET_PASS",
)

REDACTION = "[REDACTED]"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTION if _is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _redact_known_secret_values(value)
    return value


def _is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    return any(part in upper for part in SENSITIVE_KEY_PARTS)


def _redact_known_secret_values(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        if not value or len(value) < 4 or not _is_sensitive_key(key):
            continue
        redacted = redacted.replace(value, REDACTION)
    return redacted

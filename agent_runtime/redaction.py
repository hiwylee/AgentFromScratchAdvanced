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
)

# These terms are sensitive wherever they appear in a key (for example
# oracleDsn, tns_admin, wallet_location). Non-secret status booleans using these
# words are preserved by redact() so diagnostics such as wallet_path_exists stay
# useful while actual string values are hidden.
SENSITIVE_KEY_SUBSTRINGS = (
    "DSN",
    "TNS",
    "WALLET",
    "CONNECTION_STRING",
)

REDACTION = "[REDACTED]"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_sensitive_key_value(item) if _is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _redact_known_secret_values(value)
    return value


def _redact_sensitive_key_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    return REDACTION


def _is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    if any(part in upper for part in SENSITIVE_KEY_SUBSTRINGS):
        return True
    return any(
        upper == part
        or upper.startswith(f"{part}_")
        or upper.endswith(f"_{part}")
        or f"_{part}_" in upper
        for part in SENSITIVE_KEY_PARTS
    )


def _redact_known_secret_values(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        if not value or len(value) < 4 or not _is_sensitive_key(key):
            continue
        redacted = redacted.replace(value, REDACTION)
    return redacted

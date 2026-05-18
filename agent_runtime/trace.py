"""Structured trace records for local agent runs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .loop import AgentResult
from .redaction import REDACTION, SENSITIVE_KEY_PARTS, redact
from .types import utc_now


TRACE_SCHEMA_VERSION = "agent-runtime.trace.v1"
TRACE_EVENT_SCHEMA_VERSION = "agent-runtime.trace-event.v1"


class SecretLeakError(AssertionError):
    """Raised when a known secret value appears in serialized output."""


@dataclass(frozen=True)
class ArtifactVersions:
    prompt_versions: dict[str, dict[str, str]] = field(default_factory=lambda: {
        "intent_classifier": {
            "path": "artifacts/prompts/intent-classifier.md",
            "version": "1",
        },
    })
    policy_versions: dict[str, dict[str, str]] = field(default_factory=lambda: {
        "redaction_policy": {
            "path": "artifacts/policies/redaction-policy.json",
            "version": "1",
        },
    })
    memory_versions: dict[str, dict[str, str]] = field(default_factory=lambda: {
        "runtime_memory": {
            "path": "none",
            "version": "none",
        },
    })
    eval_versions: dict[str, dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceRecord:
    run_id: str
    created_at: str
    schema_version: str
    artifact_versions: dict[str, Any]
    intent: dict[str, Any]
    action: dict[str, Any]
    final_answer: dict[str, Any]
    monitor: dict[str, Any]
    events: list[dict[str, Any]]

    @classmethod
    def from_agent_result(
        cls,
        result: AgentResult,
        *,
        artifact_versions: ArtifactVersions | None = None,
    ) -> "TraceRecord":
        versions = artifact_versions or ArtifactVersions()
        return cls(
            run_id=result.run_id,
            created_at=utc_now(),
            schema_version=TRACE_SCHEMA_VERSION,
            artifact_versions=versions.to_dict(),
            intent=result.intent,
            action=result.action,
            final_answer=result.final_answer,
            monitor={
                "status_path": result.status_path,
                "events_path": result.events_path,
                "audit_path": result.audit_path,
            },
            events=load_monitor_events(Path(result.events_path)),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


def load_monitor_events(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []
    return [
        normalize_monitor_event(json.loads(line))
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize_monitor_event(event: dict[str, Any]) -> dict[str, Any]:
    """Convert monitor JSONL events into the generic trace event shape."""
    event_type = str(event.get("event", "unknown"))
    payload = redact(event.get("data", {}))
    return {
        "schema_version": TRACE_EVENT_SCHEMA_VERSION,
        "run_id": event.get("run_id"),
        "sequence": event.get("sequence"),
        "created_at": event.get("created_at"),
        "event_type": event_type,
        "category": _event_category(event_type),
        "payload": payload,
        "event": event_type,
        "data": payload,
    }


def _event_category(event_type: str) -> str:
    if event_type.startswith("workflow_"):
        return "workflow"
    if event_type in {
        "human_gate_opened",
        "human_decision_recorded",
        "resume_validation_failed",
        "resume_validation_passed",
    }:
        return "workflow"
    if event_type.startswith("target_load") or event_type.startswith("trusted_checkpoint"):
        return "workflow"
    if event_type.startswith("run_"):
        return "run"
    if event_type.startswith("tool_"):
        return "tool"
    return "agent"


def write_trace(record: TraceRecord, trace_dir: Path) -> Path:
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{record.run_id}.trace.json"
    data = record.to_dict()
    assert_no_known_secret_values(data, context="trace")
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def assert_no_known_secret_values(data: Any, *, context: str) -> None:
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    leaked_keys = [
        key
        for key, value in _known_secret_values().items()
        if value in serialized and value != REDACTION
    ]
    if leaked_keys:
        names = ", ".join(sorted(leaked_keys))
        raise SecretLeakError(f"{context} contains unredacted known secret value(s): {names}")


def _known_secret_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in os.environ.items():
        if not value or len(value) < 4:
            continue
        if _is_low_signal_secret_value(value):
            continue
        if any(part in key.upper() for part in SENSITIVE_KEY_PARTS):
            values[key] = value
    return values


def _is_low_signal_secret_value(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "false", "none", "null", "test", "token", "secret", "password"}:
        return True
    if len(set(normalized)) <= 2:
        return True
    return False

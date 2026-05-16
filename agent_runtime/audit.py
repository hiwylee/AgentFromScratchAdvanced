"""Append-only trace and audit persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from .redaction import redact


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    created_at: str
    event: str
    data: Dict[str, Any]

    @classmethod
    def create(cls, event: str, data: Dict[str, Any]) -> "RunRecord":
        return cls(
            run_id=str(uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            event=event,
            data=redact(data),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "event": self.event,
            "data": self.data,
        }


def write_trace(record: RunRecord, trace_dir: Path) -> Path:
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{record.run_id}.json"
    path.write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def append_audit(record: RunRecord, audit_path: Path) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

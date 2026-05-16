"""Run monitoring files for local agent execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .redaction import redact
from .types import RunState, utc_now


@dataclass
class RunMonitor:
    run_id: str
    root_dir: Path
    state: RunState = "running"
    started_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    event_count: int = 0

    @property
    def run_dir(self) -> Path:
        return self.root_dir / self.run_id

    @property
    def status_path(self) -> Path:
        return self.run_dir / "status.json"

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"

    def start(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.write_status()

    def event(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        self.event_count += 1
        event = {
            "run_id": self.run_id,
            "sequence": self.event_count,
            "created_at": utc_now(),
            "event": name,
            "data": redact(data),
        }
        with self.events_path.open("a", encoding="utf-8") as events_file:
            events_file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.updated_at = event["created_at"]
        self.write_status()
        return event

    def finish(self, state: RunState, summary: dict[str, Any]) -> None:
        self.state = state
        self.event("run_finished", summary)
        self.write_status(extra={"summary": redact(summary)})

    def pause(self, state: RunState, summary: dict[str, Any]) -> None:
        self.state = state
        self.event("run_paused", summary)
        self.write_status(extra={"summary": redact(summary)})

    def write_status(self, extra: dict[str, Any] | None = None) -> None:
        status = {
            "run_id": self.run_id,
            "state": self.state,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "event_count": self.event_count,
            "events_path": str(self.events_path),
        }
        if extra:
            status.update(extra)
        self.status_path.write_text(
            json.dumps(redact(status), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def latest_status(root_dir: Path) -> dict[str, Any] | None:
    if not root_dir.exists():
        return None
    status_files = sorted(root_dir.glob("*/status.json"), key=lambda path: path.stat().st_mtime)
    if not status_files:
        return None
    return json.loads(status_files[-1].read_text(encoding="utf-8"))

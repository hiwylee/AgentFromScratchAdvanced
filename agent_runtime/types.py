"""Core runtime types for the intent-first agent loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


Role = Literal["user", "assistant", "tool", "system"]
ActionKind = Literal["final_answer", "ask_clarification", "inspect_schema", "refuse"]
RunState = Literal["running", "completed", "failed", "cancelled", "timed_out"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    source: str
    content: dict[str, Any]
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FinalAnswer:
    content: str
    assumptions: list[str] = field(default_factory=list)
    next_action: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Budget:
    max_steps: int = 4
    timeout_seconds: int = 30
    token_budget: int = 4000
    cost_budget_usd: float = 0.0
    row_budget: int = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

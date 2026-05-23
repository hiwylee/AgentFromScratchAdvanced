"""Core runtime types for the intent-first agent loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Event
from typing import Any, Literal


Role = Literal["user", "assistant", "tool", "system"]
FailureReason = Literal[
    "missing_context",
    "ambiguous_request",
    "tool_error",
    "policy_denied",
    "data_mismatch",
    "timeout",
    "external_unavailable",
    "budget_exceeded",
    "unsafe_side_effect",
    "schema_or_contract_mismatch",
]
SuggestedAction = Literal["retry", "use_alternative", "clarify", "proceed", "abort", "skip"]
ActionKind = Literal[
    "final_answer",
    "ask_clarification",
    "inspect_schema",
    "select_workflow",
    "refuse",
    "model_error",
]
IntentRoute = Literal[
    "database_analysis",
    "business_workflow",
    "general_answer",
    "unknown",
]
RunState = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "stopped",
    "paused",
    "checkpoint_required",
    "closed",
    "blocked",
]


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


@dataclass
class ConversationSlot:
    """Short-term session slot — intentionally NOT a MemoryRecord.

    Lives only for the duration of one session (in-memory + session.json).
    Never passes through the self-evolution gate or review workflow.
    """

    key: str
    value: Any
    source_step_id: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntentResult:
    """Result of intent classification — capabilities/slots are drift-signature targets."""

    # deterministic fields — included in drift signature
    capabilities: list[str]
    slots: dict[str, Any]
    primary_route: IntentRoute

    # non-deterministic fields — excluded from drift signature
    confidence: float
    rationale: str
    alternatives: list[tuple[list[str], float]]
    needs_clarification: bool
    clarification_prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def signature_dict(self) -> dict[str, Any]:
        """Deterministic subset for drift signature hashing."""
        return {
            "capabilities": sorted(self.capabilities),
            "slots": self.slots,
            "primary_route": self.primary_route,
        }


@dataclass(frozen=True)
class Budget:
    max_steps: int = 4
    timeout_seconds: float = 30
    token_budget: int = 4000
    cost_budget_usd: float = 0.0
    row_budget: int = 100

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CancellationToken:
    """Small thread-safe cancellation primitive for local runtime controls."""

    def __init__(self) -> None:
        self._event = Event()
        self._reason = "cancelled"

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> None:
        clean_reason = reason.strip()
        self._reason = clean_reason or "cancelled"
        self._event.set()

    def to_dict(self) -> dict[str, Any]:
        return {"is_cancelled": self.is_cancelled, "reason": self.reason}

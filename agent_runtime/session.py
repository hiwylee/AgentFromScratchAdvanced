"""Session context management for the agent runtime.

SessionContext holds short-term state for one conversation session.
It is intentionally NOT backed by MemoryRecord — session slots are
transient and do not pass through the self-evolution gate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import Budget, ConversationSlot, Message
from .redaction import redact

# Cost estimates in USD per tool call tier (rough upper bounds)
_COST_ESTIMATE_USD: dict[str, float] = {
    "fast": 0.001,
    "medium": 0.01,
    "slow": 0.10,
}


@dataclass
class BudgetTracker:
    """Mutable budget tracker — Budget itself stays frozen.

    Budget.cost_budget_usd = 0.0 means no cost limit.
    """

    initial: Budget
    tokens_used: int = 0
    cost_used_usd: float = 0.0
    tool_retries: int = 0

    def would_exceed(self, cost_estimate: str) -> bool:
        """Check if running a tool with this cost_estimate would exceed budget.

        cost_estimate: "fast" | "medium" | "slow"
        Returns True only if cost_budget_usd > 0 and limit would be exceeded.
        """
        if self.initial.cost_budget_usd == 0.0:
            return False
        increment = _COST_ESTIMATE_USD.get(cost_estimate, _COST_ESTIMATE_USD["medium"])
        return (self.cost_used_usd + increment) > self.initial.cost_budget_usd

    def charge_tokens(self, tokens: int) -> None:
        self.tokens_used += tokens

    def charge_retry(self) -> bool:
        """Increment retry counter. Returns True if still within budget."""
        self.tool_retries += 1
        return self.tool_retries <= self.initial.max_steps

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "cost_used_usd": self.cost_used_usd,
            "tool_retries": self.tool_retries,
            "initial": self.initial.to_dict(),
        }


@dataclass
class SessionContext:
    """Short-term context for one agent session.

    Persisted to {run_dir}/{session_id}/ as split files:
      messages.jsonl  — append-only, redacted
      state.json      — slots, budget, active_plan summary
      summary.md      — generated on session close (optional)
    """

    session_id: str
    conversation_history: list[Message] = field(default_factory=list)
    slots: dict[str, ConversationSlot] = field(default_factory=dict)
    tool_results_cache: dict[str, Any] = field(default_factory=dict)
    budget_tracker: BudgetTracker | None = None
    instruction_sources: list[str] = field(default_factory=list)
    redaction_status: str = "clean"  # "clean" | "sanitized"
    approved_memories: list[Any] = field(default_factory=list)

    def add_message(self, message: Message) -> None:
        self.conversation_history.append(message)

    def recent_history(self, n: int = 20) -> list[Message]:
        """Return the last *n* messages from conversation_history.

        Used for LLM context injection to prevent context explosion.
        If n <= 0, returns all messages (same as conversation_history).

        P11 note: AgentLoop is currently single-turn and does not maintain a
        SessionContext across calls. This method is a foundation for multi-turn
        context management — wire into model.choose_action(context=) when
        AgentLoop gains persistent session support.
        """
        if n <= 0:
            return list(self.conversation_history)
        return list(self.conversation_history[-n:])

    def set_slot(self, key: str, value: Any, source_step_id: str = "") -> None:
        self.slots[key] = ConversationSlot(
            key=key,
            value=value,
            source_step_id=source_step_id,
        )

    def get_slot(self, key: str) -> Any | None:
        slot = self.slots.get(key)
        if slot is None:
            return None
        return slot.value

    def cache_tool_result(self, tool_name: str, input_hash: str, result: Any) -> None:
        cache_key = f"{tool_name}:{input_hash}"
        self.tool_results_cache[cache_key] = result

    def get_cached_result(self, tool_name: str, input_hash: str) -> Any | None:
        cache_key = f"{tool_name}:{input_hash}"
        return self.tool_results_cache.get(cache_key)

    def save(self, session_dir: Path) -> None:
        """Persist session to disk. Creates directory if needed.
        File permissions: 0o700 for dir, 0o600 for files.
        All content passes through redact() before write.
        """
        session_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(session_dir, 0o700)

        # Write messages.jsonl — append-only (truncate on save for full consistency)
        messages_path = session_dir / "messages.jsonl"
        with messages_path.open("w", encoding="utf-8") as fh:
            for msg in self.conversation_history:
                redacted = redact(msg.to_dict())
                fh.write(json.dumps(redacted, ensure_ascii=False) + "\n")
        os.chmod(messages_path, 0o600)

        # Build state dict
        slots_serialized = {
            k: redact(v.to_dict()) for k, v in self.slots.items()
        }
        state: dict[str, Any] = {
            "session_id": self.session_id,
            "redaction_status": self.redaction_status,
            "instruction_sources": self.instruction_sources,
            "slots": slots_serialized,
            "budget": self.budget_tracker.to_dict() if self.budget_tracker else None,
        }
        redacted_state = redact(state)
        state_path = session_dir / "state.json"
        state_path.write_text(
            json.dumps(redacted_state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(state_path, 0o600)

    @classmethod
    def load(cls, session_dir: Path) -> "SessionContext":
        """Load a SessionContext from a previously saved session directory."""
        state_path = session_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))

        session_id = state["session_id"]
        redaction_status = state.get("redaction_status", "clean")
        instruction_sources = state.get("instruction_sources", [])

        # Reconstruct slots
        slots: dict[str, ConversationSlot] = {}
        for k, slot_dict in state.get("slots", {}).items():
            slots[k] = ConversationSlot(
                key=slot_dict["key"],
                value=slot_dict["value"],
                source_step_id=slot_dict.get("source_step_id", ""),
                created_at=slot_dict.get("created_at", ""),
            )

        # Reconstruct budget tracker
        budget_tracker: BudgetTracker | None = None
        budget_data = state.get("budget")
        if budget_data is not None:
            initial_data = budget_data.get("initial", {})
            budget_tracker = BudgetTracker(
                initial=Budget(
                    max_steps=initial_data.get("max_steps", 4),
                    timeout_seconds=initial_data.get("timeout_seconds", 30),
                    token_budget=initial_data.get("token_budget", 4000),
                    cost_budget_usd=initial_data.get("cost_budget_usd", 0.0),
                    row_budget=initial_data.get("row_budget", 100),
                ),
                tokens_used=budget_data.get("tokens_used", 0),
                cost_used_usd=budget_data.get("cost_used_usd", 0.0),
                tool_retries=budget_data.get("tool_retries", 0),
            )

        # Reconstruct conversation history from messages.jsonl
        conversation_history: list[Message] = []
        messages_path = session_dir / "messages.jsonl"
        if messages_path.exists():
            for line in messages_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                msg_dict = json.loads(line)
                conversation_history.append(
                    Message(
                        role=msg_dict["role"],
                        content=msg_dict["content"],
                        created_at=msg_dict.get("created_at", ""),
                    )
                )

        return cls(
            session_id=session_id,
            conversation_history=conversation_history,
            slots=slots,
            tool_results_cache={},
            budget_tracker=budget_tracker,
            instruction_sources=instruction_sources,
            redaction_status=redaction_status,
        )

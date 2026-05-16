"""Mock model adapter for the first agent loop."""

from __future__ import annotations

from .intent import UserIntent
from .types import Action


class MockModel:
    """Deterministic model boundary used before API-backed models exist."""

    name = "mock-intent-planner"
    version = "1"

    def choose_action(self, intent: UserIntent) -> Action:
        if intent.safety_level == "blocked_write_request":
            return Action(
                kind="refuse",
                reason="The request appears to require write or destructive database access.",
                payload={"next_action": intent.next_action},
            )
        if intent.requires_oracle_adw_context and intent.ambiguities:
            return Action(
                kind="ask_clarification",
                reason="The request needs Oracle ADW schema or business glossary context.",
                payload={
                    "ambiguities": intent.ambiguities,
                    "required_context": intent.required_context,
                },
            )
        if intent.requires_oracle_adw_context:
            return Action(
                kind="inspect_schema",
                reason="The request can proceed by inspecting Oracle ADW schema context.",
                payload={"required_context": intent.required_context},
            )
        return Action(
            kind="final_answer",
            reason="The request does not require Oracle ADW context.",
            payload={"next_action": intent.next_action},
        )

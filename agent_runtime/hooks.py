"""Event-driven hook system for the agent runtime.

All handler invocations pass data through redact() to prevent secret leakage.
Handler failures are isolated — one failing hook never blocks others or the
main execution flow.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from .redaction import redact

HookHandler = Callable[[str, dict[str, Any]], None]
# Signature: handler(event_name: str, data: dict) -> None
#
# Tacit knowledge events fired by tacit_knowledge.py and workflow.py:
#   "verification_episode_created" — a VerificationEpisode was stored
#   "tacit_signal_extracted"       — TacitSignalExtractor produced heuristics
#   "reflection_complete"          — ReflectionAgent finished a reflection


class HookRegistry:
    """Register and fire event-driven hooks.

    Usage:
        registry = HookRegistry()
        registry.register("tool_completed", my_handler)
        registry.fire("tool_completed", {"result": ...})
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = defaultdict(list)

    def register(self, event: str, handler: HookHandler) -> None:
        """Register handler for event. Multiple handlers per event are allowed."""
        if not event or not callable(handler):
            raise ValueError("event must be non-empty string and handler must be callable")
        self._handlers[event].append(handler)

    def fire(self, event: str, data: dict[str, Any]) -> None:
        """Fire event: data passes through redact(), each handler is isolated.

        Handler failures are caught and silently discarded — a failing hook
        never blocks the execution flow or other handlers.
        """
        safe_data = redact(data)
        for handler in self._handlers.get(event, []):
            try:
                handler(event, safe_data)
            except Exception:  # noqa: BLE001
                pass  # handler failure must not propagate

    def handlers_for(self, event: str) -> list[HookHandler]:
        """Return registered handlers for event (copy — safe for inspection)."""
        return list(self._handlers.get(event, []))

    def registered_events(self) -> list[str]:
        """Return list of events that have at least one handler."""
        return [e for e, hs in self._handlers.items() if hs]

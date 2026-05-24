"""Tests for AgentLoop hook firing behaviour.

Covers:
- intent_analyzed hook fires on every run()
- intent_analyzed hook data contains "intent" key
- plan_shadow_recorded hook fires after successful plan shadow
- hook_registry=None runs without error
- memory_injected hook fires when approved memory is present
- memory_injected hook does NOT fire when memory_dir is empty
- a hook that raises an exception does not crash the loop
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent_runtime.hooks import HookRegistry
from agent_runtime.loop import AgentLoop
from agent_runtime.self_evolution import MEMORY_RECORD_SCHEMA_VERSION
from agent_runtime.types import Budget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_memory_file(directory: Path, memory_id: str, key: str, value: str) -> Path:
    """Write a minimal approved MemoryRecord JSON file to *directory*."""
    record = {
        "schema_version": MEMORY_RECORD_SCHEMA_VERSION,
        "memory_id": memory_id,
        "key": key,
        "value": value,
        "status": "active",
        "tags": [],
        "provenance": {
            "source_type": "test",
            "source_id": "test-src",
            "author": "tester",
            "recorded_at": "2026-01-01T00:00:00Z",
            "confidence": 1.0,
            "evidence": [],
            "scope": "project",
            "expires_at": None,
            "review_status": "approved",
        },
    }
    path = Path(directory) / f"{memory_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _run_with_hooks(
    user_text: str,
    memory_dir: Path | None = None,
) -> tuple[list[tuple[str, dict]], Any]:
    """Run the agent loop with hooks capturing intent_analyzed, memory_injected,
    and plan_shadow_recorded events.  Returns (fired_list, result)."""
    fired: list[tuple[str, dict]] = []
    registry = HookRegistry()
    registry.register("intent_analyzed", lambda e, d: fired.append((e, d)))
    registry.register("memory_injected", lambda e, d: fired.append((e, d)))
    registry.register("plan_shadow_recorded", lambda e, d: fired.append((e, d)))

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        loop = AgentLoop(
            run_root=td_path / "runs",
            audit_path=td_path / "audit.jsonl",
            hook_registry=registry,
            memory_dir=memory_dir,
            budget=Budget(max_steps=4, timeout_seconds=30),
        )
        result = loop.run(user_text)

    return fired, result


def _fired_event_names(fired: list[tuple[str, dict]]) -> list[str]:
    return [e for e, _ in fired]


def _fired_data_for(fired: list[tuple[str, dict]], event: str) -> list[dict]:
    return [d for e, d in fired if e == event]


# ---------------------------------------------------------------------------
# intent_analyzed hook tests
# ---------------------------------------------------------------------------

class IntentAnalyzedHookTests(unittest.TestCase):

    def test_intent_analyzed_hook_fires(self):
        fired, _ = _run_with_hooks("지난달 상품별 매출 추이를 보여줘")
        self.assertIn("intent_analyzed", _fired_event_names(fired))

    def test_intent_analyzed_hook_has_intent_key(self):
        fired, _ = _run_with_hooks("지난달 상품별 매출 추이를 보여줘")
        payloads = _fired_data_for(fired, "intent_analyzed")
        self.assertTrue(len(payloads) >= 1, "No intent_analyzed payload captured")
        self.assertIn("intent", payloads[0])


# ---------------------------------------------------------------------------
# plan_shadow_recorded hook tests
# ---------------------------------------------------------------------------

class PlanShadowHookTests(unittest.TestCase):

    def test_plan_shadow_hook_fires(self):
        fired, _ = _run_with_hooks("지난달 상품별 매출 추이를 보여줘")
        self.assertIn("plan_shadow_recorded", _fired_event_names(fired))


# ---------------------------------------------------------------------------
# hook_registry=None safety test
# ---------------------------------------------------------------------------

class HookRegistryNoneTests(unittest.TestCase):

    def test_hook_registry_none_no_error(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            loop = AgentLoop(
                run_root=td_path / "runs",
                audit_path=td_path / "audit.jsonl",
                hook_registry=None,
                budget=Budget(max_steps=4, timeout_seconds=30),
            )
            try:
                result = loop.run("hello world")
            except Exception as exc:
                self.fail(f"loop.run() raised unexpectedly with hook_registry=None: {exc}")
            self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# memory_injected hook tests
# ---------------------------------------------------------------------------

class MemoryInjectedHookTests(unittest.TestCase):

    def test_memory_injected_hook_fires_with_valid_memory(self):
        with tempfile.TemporaryDirectory() as mem_td:
            mem_dir = Path(mem_td)
            _write_memory_file(mem_dir, "hook-mem-1", "preferred_language", "Korean")
            fired, _ = _run_with_hooks("summarize this repository", memory_dir=mem_dir)
            self.assertIn("memory_injected", _fired_event_names(fired))

    def test_memory_injected_not_fired_when_no_memory(self):
        with tempfile.TemporaryDirectory() as mem_td:
            mem_dir = Path(mem_td)
            # empty directory — no memory files
            fired, _ = _run_with_hooks("summarize this repository", memory_dir=mem_dir)
            self.assertNotIn("memory_injected", _fired_event_names(fired))


# ---------------------------------------------------------------------------
# hook failure isolation test
# ---------------------------------------------------------------------------

class HookFailureIsolationTests(unittest.TestCase):

    def test_hook_failure_does_not_crash_loop(self):
        """A hook that raises must not prevent loop.run() from returning a result."""
        fired: list[str] = []
        registry = HookRegistry()

        def exploding_handler(event: str, data: dict) -> None:
            raise RuntimeError("simulated hook failure")

        def recording_handler(event: str, data: dict) -> None:
            fired.append(event)

        registry.register("intent_analyzed", exploding_handler)
        registry.register("intent_analyzed", recording_handler)

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            loop = AgentLoop(
                run_root=td_path / "runs",
                audit_path=td_path / "audit.jsonl",
                hook_registry=registry,
                budget=Budget(max_steps=4, timeout_seconds=30),
            )
            try:
                result = loop.run("hello world")
            except Exception as exc:
                self.fail(f"loop.run() raised unexpectedly after hook failure: {exc}")

        self.assertIsNotNone(result)
        # The recording handler should still have been called despite the earlier failure.
        self.assertIn("intent_analyzed", fired)


if __name__ == "__main__":
    unittest.main()

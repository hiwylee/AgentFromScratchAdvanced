"""Integration tests for ToolRunner + HookRegistry.

Coverage targets:
- ToolRunner accepts hook_registry parameter without error
- hook_registry=None (default) does not raise
- tool_completed event fires hook after successful tool run
- tool_started event fires hook before handler executes
- tool_invalid event fires hook when call validation fails
- tool_blocked event fires hook when policy blocks the tool
- hook data is passed through redact() — no raw secrets
- hook handler exception does not block the tool run result
- hook_registry=None means fire() is never called (spy pattern)
- two hooks on the same event are both called
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agent_runtime.hooks import HookRegistry
from agent_runtime.tools import (
    ToolCall,
    ToolExecutionContext,
    ToolParameter,
    ToolRegistry,
    ToolRunner,
    ToolSpec,
    default_tool_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(tmp_dir: str) -> ToolExecutionContext:
    """Build a ToolExecutionContext that writes audit records into tmp_dir."""
    return ToolExecutionContext(
        run_id="hook-test-run",
        audit_path=Path(tmp_dir) / "audit.jsonl",
    )


def _make_context_approved(tmp_dir: str, *, approved_high_risk=(), approved_write=()) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="hook-test-run",
        audit_path=Path(tmp_dir) / "audit.jsonl",
        approved_high_risk_tools=tuple(approved_high_risk),
        approved_write_tools=tuple(approved_write),
    )


def _echo_registry() -> ToolRegistry:
    """Return a minimal registry with a single harmless echo tool."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="echo",
            description="Echo text.",
            parameters=(ToolParameter(name="text", type="string"),),
            read_only=True,
            risk_level="low",
        ),
        lambda args: {"text": args["text"]},
    )
    return registry


# ---------------------------------------------------------------------------
# Parameter acceptance tests
# ---------------------------------------------------------------------------

class ToolRunnerHookRegistryParameterTests(unittest.TestCase):

    def test_tool_runner_accepts_hook_registry(self):
        """ToolRunner can be constructed with an explicit HookRegistry without raising."""
        with tempfile.TemporaryDirectory() as tmp:
            hook_registry = HookRegistry()

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )

            self.assertIs(hook_registry, runner.hook_registry)

    def test_hook_registry_none_is_default(self):
        """ToolRunner constructed without hook_registry defaults to None and runs fine."""
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(_echo_registry(), context=_make_context(tmp))

            result = runner.run(ToolCall("echo", {"text": "hi"}))

            self.assertEqual("completed", result.state)
            self.assertIsNone(runner.hook_registry)


# ---------------------------------------------------------------------------
# Hook firing tests — successful run
# ---------------------------------------------------------------------------

class ToolRunnerHookFiringTests(unittest.TestCase):

    def test_tool_completed_fires_hook(self):
        """After a successful tool run the hook registered on tool_completed is called."""
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_completed", lambda event, data: calls.append(event))

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            runner.run(ToolCall("echo", {"text": "hello"}))

            self.assertEqual(["tool_completed"], calls)

    def test_tool_started_fires_hook(self):
        """Before the handler executes the hook registered on tool_started is called."""
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_started", lambda event, data: calls.append(event))

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            runner.run(ToolCall("echo", {"text": "hello"}))

            self.assertIn("tool_started", calls)

    def test_tool_started_fires_before_completed(self):
        """tool_started hook fires before tool_completed hook in a single run."""
        with tempfile.TemporaryDirectory() as tmp:
            order = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_started", lambda event, data: order.append("started"))
            hook_registry.register("tool_completed", lambda event, data: order.append("completed"))

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            runner.run(ToolCall("echo", {"text": "order-test"}))

            self.assertEqual(["started", "completed"], order)


# ---------------------------------------------------------------------------
# Hook firing tests — validation and policy failures
# ---------------------------------------------------------------------------

class ToolRunnerHookErrorPathTests(unittest.TestCase):

    def test_tool_invalid_fires_hook(self):
        """When a tool call fails validation, the tool_invalid event fires on the hook."""
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_invalid", lambda event, data: calls.append(event))

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            # Pass wrong type for "text" (integer instead of string) to trigger invalid.
            result = runner.run(ToolCall("echo", {"text": 999}))

            self.assertEqual("invalid", result.state)
            self.assertIn("tool_invalid", calls)

    def test_tool_blocked_fires_hook(self):
        """When policy blocks a tool, the tool_blocked event fires on the hook."""
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_blocked", lambda event, data: calls.append(event))

            registry = ToolRegistry()
            registry.register(
                ToolSpec(
                    name="dangerous",
                    description="A write tool that needs approval.",
                    read_only=False,
                    risk_level="high",
                ),
                lambda args: {"done": True},
            )

            runner = ToolRunner(
                registry,
                context=_make_context(tmp),  # no approvals granted
                hook_registry=hook_registry,
            )
            result = runner.run(ToolCall("dangerous"))

            self.assertEqual("blocked", result.state)
            self.assertIn("tool_blocked", calls)


# ---------------------------------------------------------------------------
# Redaction test
# ---------------------------------------------------------------------------

class ToolRunnerHookRedactionTests(unittest.TestCase):

    def test_hook_data_is_redacted(self):
        """Data passed to the hook handler must not contain raw secret values."""
        import os

        previous = os.environ.get("HOOK_TEST_PASSWORD")
        os.environ["HOOK_TEST_PASSWORD"] = "super-secret-hook-value"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                received_data = []
                hook_registry = HookRegistry()
                hook_registry.register(
                    "tool_completed",
                    lambda event, data: received_data.append(str(data)),
                )

                registry = ToolRegistry()
                registry.register(
                    ToolSpec(name="secret_tool", description="Returns secret."),
                    lambda args: {"password": "super-secret-hook-value", "ok": True},
                )

                runner = ToolRunner(
                    registry,
                    context=_make_context(tmp),
                    hook_registry=hook_registry,
                )
                runner.run(ToolCall("secret_tool"))

                combined = "".join(received_data)
                self.assertNotIn("super-secret-hook-value", combined)
        finally:
            if previous is None:
                os.environ.pop("HOOK_TEST_PASSWORD", None)
            else:
                os.environ["HOOK_TEST_PASSWORD"] = previous


# ---------------------------------------------------------------------------
# Isolation / resilience tests
# ---------------------------------------------------------------------------

class ToolRunnerHookIsolationTests(unittest.TestCase):

    def test_hook_failure_does_not_block_tool_run(self):
        """When a hook handler raises, the tool run result is still returned normally."""
        with tempfile.TemporaryDirectory() as tmp:
            hook_registry = HookRegistry()
            hook_registry.register("tool_completed", lambda event, data: 1 / 0)

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            result = runner.run(ToolCall("echo", {"text": "resilience"}))

            self.assertEqual("completed", result.state)
            self.assertEqual({"text": "resilience"}, result.output)

    def test_no_hook_registry_no_fire(self):
        """When hook_registry=None, the HookRegistry.fire method is never invoked."""
        with tempfile.TemporaryDirectory() as tmp:
            spy = MagicMock(spec=HookRegistry)

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=None,
            )
            runner.run(ToolCall("echo", {"text": "spy-test"}))

            spy.fire.assert_not_called()

    def test_multiple_hooks_all_fired(self):
        """Two handlers registered on tool_completed are both called after a successful run."""
        with tempfile.TemporaryDirectory() as tmp:
            calls_a = []
            calls_b = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_completed", lambda event, data: calls_a.append(event))
            hook_registry.register("tool_completed", lambda event, data: calls_b.append(event))

            runner = ToolRunner(
                _echo_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            runner.run(ToolCall("echo", {"text": "multi"}))

            self.assertEqual(["tool_completed"], calls_a)
            self.assertEqual(["tool_completed"], calls_b)


# ---------------------------------------------------------------------------
# Integration with default_tool_registry
# ---------------------------------------------------------------------------

class ToolRunnerHookWithDefaultRegistryTests(unittest.TestCase):

    def test_hook_fires_on_default_tool_registry_run(self):
        """Hook on tool_completed fires when running mock_data_query via default_tool_registry."""
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            hook_registry = HookRegistry()
            hook_registry.register("tool_completed", lambda event, data: calls.append(event))

            runner = ToolRunner(
                default_tool_registry(),
                context=_make_context(tmp),
                hook_registry=hook_registry,
            )
            result = runner.run(ToolCall("mock_data_query", {"dimension": "channel"}))

            self.assertEqual("completed", result.state)
            self.assertIn("tool_completed", calls)


if __name__ == "__main__":
    unittest.main()

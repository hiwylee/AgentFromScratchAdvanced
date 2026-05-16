import os
import tempfile
import unittest
from pathlib import Path

from agent_runtime.tools import (
    ToolCall,
    ToolExecutionContext,
    ToolParameter,
    ToolRegistry,
    ToolRunner,
    ToolSpec,
)


class ToolRegistryTests(unittest.TestCase):
    def test_registers_and_lists_tool_specs(self):
        registry = ToolRegistry()

        registry.register(
            ToolSpec(
                name="echo",
                description="Echo a value.",
                parameters=(ToolParameter(name="text", type="string"),),
            ),
            lambda args: {"text": args["text"]},
        )

        specs = registry.specs()
        self.assertEqual("echo", specs[0]["name"])
        self.assertTrue(specs[0]["read_only"])
        self.assertEqual("text", specs[0]["parameters"][0]["name"])

    def test_rejects_duplicate_tool_names(self):
        registry = ToolRegistry()
        spec = ToolSpec(name="echo", description="Echo a value.")

        registry.register(spec, lambda args: {})

        with self.assertRaises(ValueError):
            registry.register(spec, lambda args: {})

    def test_validates_required_unknown_and_typed_arguments(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="lookup",
                description="Lookup a record.",
                parameters=(
                    ToolParameter(name="id", type="string"),
                    ToolParameter(name="limit", type="integer", required=False),
                ),
            ),
            lambda args: {"ok": True},
        )

        self.assertEqual([], registry.validate_call(ToolCall("lookup", {"id": "A-1", "limit": 1})))

        errors = registry.validate_call(ToolCall("lookup", {"limit": "1", "extra": True}))
        self.assertIn("missing required argument: id", errors)
        self.assertIn("argument limit must be integer", errors)
        self.assertIn("unknown argument: extra", errors)


class ToolRunnerTests(unittest.TestCase):
    def test_runs_tool_and_emits_progress_and_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            registry = ToolRegistry()
            registry.register(
                ToolSpec(
                    name="echo",
                    description="Echo a value.",
                    parameters=(ToolParameter(name="text", type="string"),),
                ),
                lambda args: {"text": args["text"]},
            )
            runner = ToolRunner(
                registry,
                context=_tool_context(tmp),
                event_sink=lambda event, data: events.append((event, data)),
            )

            result = runner.run(ToolCall("echo", {"text": "hello"}))

            self.assertEqual("completed", result.state)
            self.assertEqual({"text": "hello"}, result.output)
            self.assertEqual(["tool_started", "tool_completed"], [event for event, _ in events])
            audit_text = (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("tool_started", audit_text)
            self.assertIn("tool_completed", audit_text)

    def test_invalid_call_does_not_run_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            registry = ToolRegistry()
            registry.register(
                ToolSpec(
                    name="echo",
                    description="Echo a value.",
                    parameters=(ToolParameter(name="text", type="string"),),
                ),
                lambda args: calls.append(args),
            )

            result = ToolRunner(registry, context=_tool_context(tmp)).run(ToolCall("echo", {"text": 1}))

            self.assertEqual("invalid", result.state)
            self.assertEqual(0, result.attempts)
            self.assertEqual([], calls)

    def test_retries_failed_tool_until_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempts = []
            registry = ToolRegistry()

            def flaky(args):
                attempts.append(args)
                if len(attempts) == 1:
                    raise RuntimeError("temporary")
                return {"ok": True}

            registry.register(ToolSpec(name="flaky", description="Flaky tool."), flaky)

            result = ToolRunner(registry, context=_tool_context(tmp)).run(ToolCall("flaky"), max_attempts=2)

            self.assertEqual("completed", result.state)
            self.assertEqual(2, result.attempts)
            self.assertEqual({"ok": True}, result.output)

    def test_blocks_write_or_high_risk_tools_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            registry = ToolRegistry()
            registry.register(
                ToolSpec(name="load_target", description="Load target.", risk_level="high", read_only=False),
                lambda args: calls.append(args) or {"loaded": True},
            )

            blocked = ToolRunner(registry, context=_tool_context(tmp)).run(ToolCall("load_target"))
            approved = ToolRunner(
                registry,
                context=_tool_context(
                    tmp,
                    approved_high_risk_tools=("load_target",),
                    approved_write_tools=("load_target",),
                ),
            ).run(ToolCall("load_target"))

            self.assertEqual("blocked", blocked.state)
            self.assertEqual("completed", approved.state)
            self.assertEqual([{}], calls)

    def test_tool_result_events_and_audit_are_redacted(self):
        previous = os.environ.get("TOOL_TEST_PASSWORD")
        os.environ["TOOL_TEST_PASSWORD"] = "tool-secret-value"
        events = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                registry = ToolRegistry()
                registry.register(
                    ToolSpec(
                        name="secret_echo",
                        description="Echo a value.",
                        parameters=(ToolParameter(name="text", type="string"),),
                    ),
                    lambda args: {"message": args["text"], "password": "tool-secret-value"},
                )
                runner = ToolRunner(
                    registry,
                    context=_tool_context(tmp),
                    event_sink=lambda event, data: events.append((event, data)),
                )

                result = runner.run(ToolCall("secret_echo", {"text": "tool-secret-value"}))

                serialized = (
                    str(result.to_dict())
                    + str(events)
                    + (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
                )
                self.assertNotIn("tool-secret-value", serialized)
                self.assertIn("[REDACTED]", serialized)
        finally:
            if previous is None:
                os.environ.pop("TOOL_TEST_PASSWORD", None)
            else:
                os.environ["TOOL_TEST_PASSWORD"] = previous


def _tool_context(
    tmp: str,
    *,
    approved_high_risk_tools=(),
    approved_write_tools=(),
) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="tool-test-run",
        audit_path=Path(tmp) / "audit.jsonl",
        approved_high_risk_tools=approved_high_risk_tools,
        approved_write_tools=approved_write_tools,
    )


if __name__ == "__main__":
    unittest.main()

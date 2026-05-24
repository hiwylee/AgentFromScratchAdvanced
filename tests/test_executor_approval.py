"""Tests for human-gate approval callback behaviour in StepExecutor."""
import sys
import unittest
from io import StringIO
from unittest.mock import patch

from agent_runtime.executor import StepExecutor, make_cli_approval_callback
from agent_runtime.planner import ExecutionPlan, PlanStep


def _make_plan(requires_approval: bool = True) -> ExecutionPlan:
    step = PlanStep(
        step_id="s1",
        description="Delete all rows",
        required_capabilities=["oracle_sh.data.write"],
        primary_capability="oracle_sh.data.write",
        depends_on=[],
        success_criteria=["rows_deleted > 0"],
        expected_output="deletion count",
        retry_policy={"max_attempts": 1},
        risk_level="high",
        requires_approval=requires_approval,
        fallback_strategy="abort",
    )
    return ExecutionPlan(request_id="req-1", goal="delete rows", primary_route="database_analysis", steps=[step])


class ApprovalSkipTests(unittest.TestCase):
    """StepExecutor skips/proceeds based on approval_callback."""

    def test_skip_when_no_callback(self):
        plan = _make_plan(requires_approval=True)
        # minimal mock registry and runner
        from agent_runtime.tools import ToolRegistry, ToolRunner, ToolExecutionContext
        from pathlib import Path
        registry = ToolRegistry()
        runner = ToolRunner(registry, context=ToolExecutionContext(run_id="r1", audit_path=Path("/tmp/t.jsonl")))
        results = StepExecutor().run_plan(plan, runner, approval_callback=None)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].skipped)
        self.assertIn("approval_required_no_callback", results[0].error)

    def test_proceeds_when_callback_approves(self):
        plan = _make_plan(requires_approval=True)
        from agent_runtime.tools import ToolRegistry, ToolRunner, ToolExecutionContext, ToolSpec, ToolParameter
        from pathlib import Path
        registry = ToolRegistry()
        # register a tool matching the capability
        spec = ToolSpec(
            name="write_tool",
            description="write tool",
            parameters=[ToolParameter(name="step_id", type="string", description="", required=True),
                        ToolParameter(name="capability", type="string", description="", required=True)],
            capabilities=["oracle_sh.data.write"],
            risk_level="high",
            read_only=False,
            cost_estimate="fast",
        )
        registry.register(spec, lambda args: {"ok": True})
        runner = ToolRunner(registry, context=ToolExecutionContext(run_id="r2", audit_path=Path("/tmp/t.jsonl")))
        results = StepExecutor().run_plan(plan, runner, approval_callback=lambda step: True)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].skipped)

    def test_skips_when_callback_denies(self):
        plan = _make_plan(requires_approval=True)
        from agent_runtime.tools import ToolRegistry, ToolRunner, ToolExecutionContext
        from pathlib import Path
        registry = ToolRegistry()
        runner = ToolRunner(registry, context=ToolExecutionContext(run_id="r3", audit_path=Path("/tmp/t.jsonl")))
        results = StepExecutor().run_plan(plan, runner, approval_callback=lambda step: False)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].skipped)
        self.assertIn("approval_denied", results[0].error)


class CliApprovalCallbackTests(unittest.TestCase):
    """make_cli_approval_callback factory tests (no real stdin)."""

    def _step(self):
        return PlanStep(
            step_id="s1",
            description="Risky operation",
            required_capabilities=["oracle_sh.data.write"],
            primary_capability="oracle_sh.data.write",
            depends_on=[],
            success_criteria=[],
            expected_output="done",
            retry_policy={"max_attempts": 1},
            risk_level="high",
            requires_approval=True,
            fallback_strategy="abort",
        )

    def test_returns_true_on_y_input(self):
        output = StringIO()
        cb = make_cli_approval_callback(timeout_seconds=5.0, output_sink=output.write)
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            mock_stdin.readline.return_value = "y\n"
            # patch input() to return "y"
            with patch("builtins.input", return_value="y"):
                result = cb(self._step())
        self.assertTrue(result)

    def test_returns_false_on_n_input(self):
        output = StringIO()
        cb = make_cli_approval_callback(timeout_seconds=5.0, output_sink=output.write)
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            with patch("builtins.input", return_value="n"):
                result = cb(self._step())
        self.assertFalse(result)

    def test_returns_false_on_non_interactive(self):
        output = StringIO()
        cb = make_cli_approval_callback(timeout_seconds=5.0, output_sink=output.write)
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            result = cb(self._step())
        self.assertFalse(result)

    def test_output_contains_step_info(self):
        captured = []
        cb = make_cli_approval_callback(timeout_seconds=5.0, output_sink=captured.append)
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            cb(self._step())
        full_output = " ".join(captured)
        self.assertIn("s1", full_output)
        self.assertIn("Risky operation", full_output)
        self.assertIn("high", full_output)


if __name__ == "__main__":
    unittest.main()

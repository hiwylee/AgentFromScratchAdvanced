"""Unit tests for agent_runtime.executor."""
from __future__ import annotations
import unittest
from agent_runtime.executor import StepExecutor, StepResult
from agent_runtime.planner import ExecutionPlan, KeywordPlanner
from agent_runtime.types import IntentResult
from agent_runtime.tools import ToolResult
from agent_runtime.verifier import VerificationResult


def _intent(route: str) -> IntentResult:
    return IntentResult(
        capabilities=[],
        slots={},
        primary_route=route,  # type: ignore[arg-type]
        confidence=1.0,
        rationale="test",
        alternatives=[],
        needs_clarification=False,
    )


def _two_step_plan() -> ExecutionPlan:
    return KeywordPlanner().build(_intent("database_analysis"), request_id="r1")


def _cyclic_plan() -> ExecutionPlan:
    from agent_runtime.planner import PlanStep
    s1 = PlanStep(step_id="a", description="a", required_capabilities=["x"],
                  primary_capability="x", depends_on=["b"],
                  success_criteria=[], expected_output="", retry_policy={"max_attempts": 1})
    s2 = PlanStep(step_id="b", description="b", required_capabilities=["x"],
                  primary_capability="x", depends_on=["a"],
                  success_criteria=[], expected_output="", retry_policy={"max_attempts": 1})
    return ExecutionPlan(request_id="r2", goal="cycle", primary_route="general_answer", steps=[s1, s2])


class StepExecutorShadowTests(unittest.TestCase):
    def test_valid_plan_all_skipped(self) -> None:
        plan = _two_step_plan()
        results = StepExecutor().run_plan_shadow(plan)
        self.assertEqual(2, len(results))
        self.assertTrue(all(r.skipped for r in results))
        self.assertTrue(all(r.tool_result is None for r in results))

    def test_valid_plan_no_error(self) -> None:
        plan = _two_step_plan()
        results = StepExecutor().run_plan_shadow(plan)
        self.assertTrue(all(r.error == "" for r in results))

    def test_cyclic_plan_error_message(self) -> None:
        plan = _cyclic_plan()
        results = StepExecutor().run_plan_shadow(plan)
        self.assertEqual(2, len(results))
        self.assertTrue(all("cycle" in r.error for r in results))

    def test_empty_plan_returns_empty(self) -> None:
        plan = ExecutionPlan(request_id="r3", goal="empty", primary_route="general_answer", steps=[])
        results = StepExecutor().run_plan_shadow(plan)
        self.assertEqual([], results)

    def test_step_result_to_dict_keys(self) -> None:
        r = StepResult(step_id="s1", tool_name=None, tool_result=None,
                       verification=None, skipped=True, error="")
        d = r.to_dict()
        self.assertIn("step_id", d)
        self.assertIn("skipped", d)
        self.assertIn("error", d)
        self.assertTrue(d["skipped"])


def _make_tool_result(state: str = "completed") -> ToolResult:
    return ToolResult(
        tool_name="mock_tool",
        state=state,  # type: ignore[arg-type]
        attempts=1,
        latency_ms=10,
        output={"row_count": 5},
    )


def _make_verification(
    success: bool = True,
    alternative_tool: str | None = None,
) -> VerificationResult:
    return VerificationResult(
        success=success,
        issues=[] if success else ["criterion failed: output.row_count > 10"],
        failure_reason=None if success else "data_mismatch",
        suggested_action="proceed" if success else "retry",
        alternative_tool=alternative_tool,
    )


class StepResultToDictTests(unittest.TestCase):
    def test_step_result_to_dict_with_tool_result(self) -> None:
        """tool_result이 None이 아닐 때 to_dict()에 tool_result 포함."""
        r = StepResult(
            step_id="s1",
            tool_name="mock_tool",
            tool_result=_make_tool_result(),
            verification=None,
            skipped=False,
            error="",
        )
        d = r.to_dict()
        self.assertIsNotNone(d["tool_result"])
        self.assertIsInstance(d["tool_result"], dict)

    def test_step_result_to_dict_with_verification(self) -> None:
        """verification이 None이 아닐 때 to_dict()에 success/issues/failure_reason/suggested_action/alternative_tool 포함."""
        r = StepResult(
            step_id="s2",
            tool_name="mock_tool",
            tool_result=None,
            verification=_make_verification(success=False),
            skipped=False,
            error="",
        )
        d = r.to_dict()
        self.assertIsNotNone(d["verification"])
        v = d["verification"]
        self.assertIn("success", v)
        self.assertIn("issues", v)
        self.assertIn("failure_reason", v)
        self.assertIn("suggested_action", v)
        self.assertIn("alternative_tool", v)

    def test_step_result_to_dict_verification_all_fields(self) -> None:
        """VerificationResult의 모든 필드가 직렬화됨."""
        vr = _make_verification(success=False)
        r = StepResult(
            step_id="s3",
            tool_name="mock_tool",
            tool_result=None,
            verification=vr,
            skipped=False,
            error="",
        )
        d = r.to_dict()
        v = d["verification"]
        self.assertFalse(v["success"])
        self.assertEqual(v["issues"], ["criterion failed: output.row_count > 10"])
        self.assertEqual(v["failure_reason"], "data_mismatch")
        self.assertEqual(v["suggested_action"], "retry")
        self.assertIsNone(v["alternative_tool"])

    def test_step_result_to_dict_with_alternative_tool(self) -> None:
        """alternative_tool이 None이 아닐 때 직렬화됨."""
        vr = _make_verification(success=False, alternative_tool="fallback_tool")
        r = StepResult(
            step_id="s4",
            tool_name="mock_tool",
            tool_result=None,
            verification=vr,
            skipped=False,
            error="",
        )
        d = r.to_dict()
        self.assertEqual(d["verification"]["alternative_tool"], "fallback_tool")


if __name__ == "__main__":
    unittest.main()

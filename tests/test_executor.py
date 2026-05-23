"""Unit tests for agent_runtime.executor."""
from __future__ import annotations
import unittest
from agent_runtime.executor import StepExecutor, StepResult
from agent_runtime.planner import ExecutionPlan, KeywordPlanner
from agent_runtime.types import IntentResult


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


if __name__ == "__main__":
    unittest.main()

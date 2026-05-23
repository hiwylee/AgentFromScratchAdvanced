"""Unit tests for agent_runtime.planner."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_runtime.planner import ExecutionPlan, KeywordPlanner, PlanStep
from agent_runtime.types import IntentResult


_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "artifacts" / "schemas" / "plan.schema.v1.json"
)

_DEFAULT_RETRY = {"max_attempts": 3}


def _make_step(
    step_id: str,
    depends_on: list[str] | None = None,
    risk_level: str = "low",
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        description=f"Step {step_id}",
        required_capabilities=["cap"],
        primary_capability="cap",
        depends_on=depends_on or [],
        success_criteria=["output is not None"],
        expected_output="some output",
        retry_policy=dict(_DEFAULT_RETRY),
        risk_level=risk_level,  # type: ignore[arg-type]
    )


def _make_plan(steps: list[PlanStep]) -> ExecutionPlan:
    return ExecutionPlan(
        request_id="test-req-1",
        goal="test goal",
        primary_route="general_answer",
        steps=steps,
    )


class TopologicalGroupsTests(unittest.TestCase):
    def test_independent_steps_are_in_same_group(self) -> None:
        steps = [_make_step("a"), _make_step("b"), _make_step("c")]
        plan = _make_plan(steps)
        groups = plan.topological_groups()
        self.assertEqual(1, len(groups))
        ids = {s.step_id for s in groups[0]}
        self.assertEqual({"a", "b", "c"}, ids)

    def test_sequential_dependencies_produce_one_step_per_group(self) -> None:
        steps = [
            _make_step("a"),
            _make_step("b", depends_on=["a"]),
            _make_step("c", depends_on=["b"]),
        ]
        plan = _make_plan(steps)
        groups = plan.topological_groups()
        self.assertEqual(3, len(groups))
        self.assertEqual(["a"], [s.step_id for s in groups[0]])
        self.assertEqual(["b"], [s.step_id for s in groups[1]])
        self.assertEqual(["c"], [s.step_id for s in groups[2]])

    def test_diamond_pattern_groups_correctly(self) -> None:
        # A -> B, A -> C, B -> D, C -> D
        steps = [
            _make_step("A"),
            _make_step("B", depends_on=["A"]),
            _make_step("C", depends_on=["A"]),
            _make_step("D", depends_on=["B", "C"]),
        ]
        plan = _make_plan(steps)
        groups = plan.topological_groups()
        self.assertEqual(3, len(groups))
        self.assertEqual(["A"], [s.step_id for s in groups[0]])
        self.assertEqual({"B", "C"}, {s.step_id for s in groups[1]})
        self.assertEqual(["D"], [s.step_id for s in groups[2]])


class ValidateTests(unittest.TestCase):
    def test_valid_graph_returns_empty_list(self) -> None:
        steps = [_make_step("a"), _make_step("b", depends_on=["a"])]
        plan = _make_plan(steps)
        self.assertEqual([], plan.validate())

    def test_unknown_depends_on_is_reported(self) -> None:
        steps = [_make_step("a", depends_on=["nonexistent"])]
        plan = _make_plan(steps)
        errors = plan.validate()
        self.assertEqual(1, len(errors))
        self.assertIn("nonexistent", errors[0])

    def test_cycle_is_detected(self) -> None:
        steps = [
            _make_step("a", depends_on=["b"]),
            _make_step("b", depends_on=["a"]),
        ]
        plan = _make_plan(steps)
        errors = plan.validate()
        self.assertTrue(any("cycle" in e for e in errors))


class PlanStepTests(unittest.TestCase):
    def test_high_risk_auto_sets_requires_approval(self) -> None:
        step = _make_step("dangerous", risk_level="high")
        self.assertTrue(step.requires_approval)

    def test_low_risk_does_not_require_approval(self) -> None:
        step = _make_step("safe", risk_level="low")
        self.assertFalse(step.requires_approval)


class KeywordPlannerTests(unittest.TestCase):
    def _planner(self) -> KeywordPlanner:
        return KeywordPlanner()

    def _intent(self, route: str) -> IntentResult:
        return IntentResult(
            capabilities=[],
            slots={},
            primary_route=route,  # type: ignore[arg-type]
            confidence=1.0,
            rationale="test",
            alternatives=[],
            needs_clarification=False,
        )

    def test_database_analysis_produces_two_steps(self) -> None:
        planner = self._planner()
        plan = planner.build(self._intent("database_analysis"), request_id="req-1")
        self.assertEqual(2, len(plan.steps))
        self.assertEqual("inspect_schema", plan.steps[0].step_id)
        self.assertEqual("execute_query", plan.steps[1].step_id)

    def test_business_workflow_produces_two_steps(self) -> None:
        planner = self._planner()
        plan = planner.build(self._intent("business_workflow"), request_id="req-2")
        self.assertEqual(2, len(plan.steps))
        self.assertEqual("select_workflow", plan.steps[0].step_id)
        self.assertEqual("execute_workflow", plan.steps[1].step_id)

    def test_general_answer_produces_one_step(self) -> None:
        planner = self._planner()
        plan = planner.build(self._intent("general_answer"), request_id="req-3")
        self.assertEqual(1, len(plan.steps))
        self.assertEqual("answer", plan.steps[0].step_id)

    def test_high_risk_step_requires_approval(self) -> None:
        planner = self._planner()
        plan = planner.build(self._intent("business_workflow"), request_id="req-4")
        for step in plan.steps:
            self.assertEqual("high", step.risk_level)
            self.assertTrue(step.requires_approval)

    def test_database_analysis_plan_validates_clean(self) -> None:
        planner = self._planner()
        plan = planner.build(self._intent("database_analysis"), request_id="req-5")
        self.assertEqual([], plan.validate())

    def test_primary_route_propagated_to_plan(self) -> None:
        planner = self._planner()
        plan = planner.build(self._intent("database_analysis"), request_id="req-6")
        self.assertEqual("database_analysis", plan.primary_route)


class ToDictSchemaTests(unittest.TestCase):
    def _load_schema(self) -> dict | None:
        if not _SCHEMA_PATH.exists():
            return None
        return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _sample_plan(self) -> ExecutionPlan:
        planner = KeywordPlanner()
        return planner.build(
            IntentResult(
                capabilities=["schema_inspection"],
                slots={},
                primary_route="database_analysis",  # type: ignore[arg-type]
                confidence=1.0,
                rationale="test",
                alternatives=[],
                needs_clarification=False,
            ),
            request_id="schema-test-1",
        )

    def test_to_dict_has_required_top_level_keys(self) -> None:
        plan = self._sample_plan()
        d = plan.to_dict()
        for key in ("request_id", "goal", "primary_route", "steps"):
            self.assertIn(key, d)

    def test_to_dict_steps_have_required_fields(self) -> None:
        plan = self._sample_plan()
        required_step_fields = {
            "step_id",
            "description",
            "required_capabilities",
            "primary_capability",
            "depends_on",
            "success_criteria",
            "expected_output",
            "retry_policy",
            "risk_level",
            "requires_approval",
            "fallback_strategy",
        }
        for step_dict in plan.to_dict()["steps"]:
            for field in required_step_fields:
                self.assertIn(field, step_dict, f"missing field: {field}")

    def test_to_dict_validates_against_json_schema(self) -> None:
        schema = self._load_schema()
        plan = self._sample_plan()
        d = plan.to_dict()

        try:
            import jsonschema  # type: ignore[import-untyped]
            jsonschema.validate(instance=d, schema=schema)
        except ImportError:
            # jsonschema not available — fall back to structural checks
            self.assertIsInstance(d["request_id"], str)
            self.assertIsInstance(d["goal"], str)
            self.assertIsInstance(d["primary_route"], str)
            self.assertIsInstance(d["steps"], list)
            self.assertGreater(len(d["steps"]), 0)


if __name__ == "__main__":
    unittest.main()

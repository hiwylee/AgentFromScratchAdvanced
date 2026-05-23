"""Tests for _trace_signature() determinism with IntentResult and UserIntent."""

import unittest
from collections.abc import Mapping

from agent_runtime.self_evolution import _intent_signature, _trace_signature
from agent_runtime.types import IntentResult


class IntentSignatureDeterminismTests(unittest.TestCase):
    """Verify that only deterministic fields affect the drift signature."""

    def _make_intent_result_dict(
        self,
        *,
        capabilities=None,
        slots=None,
        primary_route="database_analysis",
        confidence=0.9,
        rationale="some rationale",
        alternatives=None,
        clarification_prompt=None,
    ):
        return {
            "capabilities": capabilities or ["revenue_query"],
            "slots": slots or {"metric": "revenue"},
            "primary_route": primary_route,
            "confidence": confidence,
            "rationale": rationale,
            "alternatives": alternatives or [],
            "needs_clarification": False,
            "clarification_prompt": clarification_prompt,
        }

    # ------------------------------------------------------------------
    # IntentResult instance path
    # ------------------------------------------------------------------

    def test_intent_result_instance_uses_signature_dict(self):
        ir = IntentResult(
            capabilities=["revenue_query"],
            slots={"metric": "revenue"},
            primary_route="database_analysis",
            confidence=0.95,
            rationale="LLM said so",
            alternatives=[],
            needs_clarification=False,
        )
        sig = _intent_signature(ir)
        self.assertEqual({"revenue_query"}, set(sig["capabilities"]))
        self.assertEqual({"metric": "revenue"}, sig["slots"])
        self.assertEqual("database_analysis", sig["primary_route"])
        self.assertNotIn("confidence", sig)
        self.assertNotIn("rationale", sig)
        self.assertNotIn("alternatives", sig)
        self.assertNotIn("clarification_prompt", sig)

    def test_intent_result_instance_same_caps_same_signature(self):
        base = IntentResult(
            capabilities=["revenue_query"],
            slots={"metric": "revenue"},
            primary_route="database_analysis",
            confidence=0.9,
            rationale="first rationale",
            alternatives=[],
            needs_clarification=False,
        )
        other = IntentResult(
            capabilities=["revenue_query"],
            slots={"metric": "revenue"},
            primary_route="database_analysis",
            confidence=0.5,
            rationale="completely different rationale",
            alternatives=[[["revenue_query"], 0.3]],
            needs_clarification=True,
            clarification_prompt="Can you clarify?",
        )
        self.assertEqual(_intent_signature(base), _intent_signature(other))

    # ------------------------------------------------------------------
    # Serialized IntentResult dict path (capabilities key present)
    # ------------------------------------------------------------------

    def test_serialized_intent_result_same_caps_same_signature(self):
        d1 = self._make_intent_result_dict(rationale="rationale A", confidence=0.9)
        d2 = self._make_intent_result_dict(rationale="rationale B", confidence=0.1)
        self.assertEqual(_intent_signature(d1), _intent_signature(d2))

    def test_serialized_intent_result_different_rationale_same_signature(self):
        d1 = self._make_intent_result_dict(rationale="explanation one")
        d2 = self._make_intent_result_dict(rationale="entirely different explanation")
        self.assertEqual(_intent_signature(d1), _intent_signature(d2))

    def test_serialized_intent_result_different_alternatives_same_signature(self):
        d1 = self._make_intent_result_dict(alternatives=[])
        d2 = self._make_intent_result_dict(
            alternatives=[[["other_cap"], 0.4], [["yet_another"], 0.2]]
        )
        self.assertEqual(_intent_signature(d1), _intent_signature(d2))

    def test_serialized_intent_result_different_clarification_prompt_same_signature(self):
        d1 = self._make_intent_result_dict(clarification_prompt=None)
        d2 = self._make_intent_result_dict(clarification_prompt="Please clarify your intent.")
        self.assertEqual(_intent_signature(d1), _intent_signature(d2))

    def test_serialized_intent_result_different_capabilities_different_signature(self):
        d1 = self._make_intent_result_dict(capabilities=["revenue_query"])
        d2 = self._make_intent_result_dict(capabilities=["count_query"])
        self.assertNotEqual(_intent_signature(d1), _intent_signature(d2))

    def test_serialized_intent_result_different_route_different_signature(self):
        d1 = self._make_intent_result_dict(primary_route="database_analysis")
        d2 = self._make_intent_result_dict(primary_route="business_workflow")
        self.assertNotEqual(_intent_signature(d1), _intent_signature(d2))

    def test_serialized_intent_result_excludes_nondeterministic_keys(self):
        d = self._make_intent_result_dict(
            confidence=0.77,
            rationale="verbose rationale text",
            alternatives=[[["cap_x"], 0.5]],
            clarification_prompt="Clarify please.",
        )
        sig = _intent_signature(d)
        self.assertNotIn("confidence", sig)
        self.assertNotIn("rationale", sig)
        self.assertNotIn("alternatives", sig)
        self.assertNotIn("clarification_prompt", sig)

    def test_capabilities_sorted_for_determinism(self):
        d1 = self._make_intent_result_dict(capabilities=["b_cap", "a_cap"])
        d2 = self._make_intent_result_dict(capabilities=["a_cap", "b_cap"])
        self.assertEqual(_intent_signature(d1), _intent_signature(d2))

    # ------------------------------------------------------------------
    # Legacy UserIntent dict path (no capabilities key)
    # ------------------------------------------------------------------

    def test_user_intent_dict_preserves_legacy_fields(self):
        d = {
            "intent_type": "data_analysis",
            "task_type": "revenue",
            "safety_level": "safe",
            "next_action": "inspect_schema",
        }
        sig = _intent_signature(d)
        self.assertEqual("data_analysis", sig["intent_type"])
        self.assertEqual("revenue", sig["task_type"])
        self.assertEqual("safe", sig["safety_level"])
        self.assertEqual("inspect_schema", sig["next_action"])

    def test_user_intent_dict_same_fields_same_signature(self):
        d1 = {
            "intent_type": "data_analysis",
            "task_type": "revenue",
            "safety_level": "safe",
            "next_action": "inspect_schema",
        }
        d2 = dict(d1)
        self.assertEqual(_intent_signature(d1), _intent_signature(d2))

    def test_user_intent_dict_different_field_different_signature(self):
        d1 = {
            "intent_type": "data_analysis",
            "task_type": "revenue",
            "safety_level": "safe",
            "next_action": "inspect_schema",
        }
        d2 = dict(d1)
        d2["intent_type"] = "workflow"
        self.assertNotEqual(_intent_signature(d1), _intent_signature(d2))

    # ------------------------------------------------------------------
    # Full _trace_signature integration checks
    # ------------------------------------------------------------------

    def test_trace_signature_with_intent_result_dict_excludes_nondeterministic(self):
        trace_data = {
            "intent": self._make_intent_result_dict(
                rationale="this should not affect the hash",
                confidence=0.42,
            ),
            "action": {"kind": "final_answer"},
            "final_answer": {"next_action": "none"},
            "events": [],
        }
        sig = _trace_signature(trace_data)
        intent_sig = sig["intent"]
        self.assertNotIn("confidence", intent_sig)
        self.assertNotIn("rationale", intent_sig)
        self.assertNotIn("alternatives", intent_sig)
        self.assertIn("capabilities", intent_sig)
        self.assertIn("slots", intent_sig)
        self.assertIn("primary_route", intent_sig)

    def test_trace_signature_with_user_intent_dict_preserves_legacy(self):
        trace_data = {
            "intent": {
                "intent_type": "data_analysis",
                "task_type": "revenue",
                "safety_level": "safe",
                "next_action": "inspect_schema",
            },
            "action": {"kind": "final_answer"},
            "final_answer": {"next_action": "none"},
            "events": [],
        }
        sig = _trace_signature(trace_data)
        intent_sig = sig["intent"]
        self.assertEqual("data_analysis", intent_sig["intent_type"])
        self.assertEqual("revenue", intent_sig["task_type"])

    def test_trace_signature_stable_across_runs_intent_result(self):
        """Same deterministic fields must produce identical signatures on repeated calls."""
        trace_data = {
            "intent": self._make_intent_result_dict(
                capabilities=["revenue_query"],
                slots={"metric": "revenue", "period": "last_month"},
                primary_route="database_analysis",
                rationale="run 1 rationale",
                confidence=0.8,
            ),
            "action": {"kind": "final_answer"},
            "final_answer": {"next_action": "none"},
            "events": [],
        }
        sig1 = _trace_signature(trace_data)
        # Mutate non-deterministic fields — signature must not change.
        trace_data["intent"]["rationale"] = "run 2 completely different rationale"
        trace_data["intent"]["confidence"] = 0.1
        sig2 = _trace_signature(trace_data)
        self.assertEqual(sig1, sig2)


if __name__ == "__main__":
    unittest.main()

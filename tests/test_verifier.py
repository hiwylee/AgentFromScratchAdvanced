"""Unit tests for agent_runtime.verifier."""

import unittest

from agent_runtime.tools import ToolResult
from agent_runtime.verifier import ToolResultVerifier, VerificationResult


def _make_result(state: str, output: dict | None = None, error: str = "") -> ToolResult:
    return ToolResult(
        tool_name="test_tool",
        state=state,  # type: ignore[arg-type]
        attempts=1,
        latency_ms=10,
        output=output or {},
        error=error,
    )


class TestToolResultVerifierStateGates(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = ToolResultVerifier()

    def test_blocked_yields_policy_denied_and_abort(self) -> None:
        result = _make_result("blocked", error="write_tool_requires_explicit_approval")
        vr = self.verifier.verify(result, [])
        self.assertFalse(vr.success)
        self.assertEqual(vr.failure_reason, "policy_denied")
        self.assertEqual(vr.suggested_action, "abort")
        self.assertTrue(any("blocked" in issue for issue in vr.issues))

    def test_failed_yields_tool_error_and_retry(self) -> None:
        result = _make_result("failed", error="RuntimeError: connection refused")
        vr = self.verifier.verify(result, [])
        self.assertFalse(vr.success)
        self.assertEqual(vr.failure_reason, "tool_error")
        self.assertEqual(vr.suggested_action, "retry")

    def test_invalid_yields_schema_or_contract_mismatch_and_abort(self) -> None:
        result = _make_result("invalid", error="missing required argument: id")
        vr = self.verifier.verify(result, [])
        self.assertFalse(vr.success)
        self.assertEqual(vr.failure_reason, "schema_or_contract_mismatch")
        self.assertEqual(vr.suggested_action, "abort")

    def test_timed_out_yields_timeout_and_retry(self) -> None:
        result = _make_result("timed_out")
        vr = self.verifier.verify(result, [])
        self.assertFalse(vr.success)
        self.assertEqual(vr.failure_reason, "timeout")
        self.assertEqual(vr.suggested_action, "retry")


class TestToolResultVerifierCriteria(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = ToolResultVerifier()

    def test_completed_no_criteria_is_success(self) -> None:
        result = _make_result("completed", output={"ok": True})
        vr = self.verifier.verify(result, [])
        self.assertTrue(vr.success)
        self.assertIsNone(vr.failure_reason)
        self.assertEqual(vr.suggested_action, "proceed")

    def test_completed_all_criteria_pass(self) -> None:
        result = _make_result("completed", output={"row_count": 5, "tables": ["SALES"]})
        vr = self.verifier.verify(
            result,
            ["tool.state == 'completed'", "output.row_count > 0", "output.tables is not empty"],
        )
        self.assertTrue(vr.success)
        self.assertEqual(vr.issues, [])

    def test_completed_row_count_gt_zero_fails_when_zero(self) -> None:
        result = _make_result("completed", output={"row_count": 0})
        vr = self.verifier.verify(result, ["output.row_count > 0"])
        self.assertFalse(vr.success)
        self.assertEqual(vr.failure_reason, "data_mismatch")
        self.assertTrue(any("output.row_count > 0" in issue for issue in vr.issues))

    def test_completed_row_count_gt_zero_passes_when_positive(self) -> None:
        result = _make_result("completed", output={"row_count": 3})
        vr = self.verifier.verify(result, ["output.row_count > 0"])
        self.assertTrue(vr.success)

    def test_completed_tables_not_empty_passes(self) -> None:
        result = _make_result("completed", output={"tables": ["SALES", "COSTS"]})
        vr = self.verifier.verify(result, ["output.tables is not empty"])
        self.assertTrue(vr.success)

    def test_completed_tables_not_empty_fails_on_empty_list(self) -> None:
        result = _make_result("completed", output={"tables": []})
        vr = self.verifier.verify(result, ["output.tables is not empty"])
        self.assertFalse(vr.success)
        self.assertEqual(vr.failure_reason, "data_mismatch")

    def test_completed_tables_not_empty_fails_when_key_missing(self) -> None:
        result = _make_result("completed", output={})
        vr = self.verifier.verify(result, ["output.tables is not empty"])
        self.assertFalse(vr.success)

    def test_tool_state_eq_completed_criterion(self) -> None:
        result = _make_result("completed")
        vr = self.verifier.verify(result, ["tool.state == 'completed'"])
        self.assertTrue(vr.success)

    def test_unparseable_criterion_is_skipped(self) -> None:
        result = _make_result("completed", output={"ok": True})
        # Unknown criterion should be skipped, not cause failure.
        vr = self.verifier.verify(result, ["this is not a real criterion !!!"])
        self.assertTrue(vr.success)


class TestToolResultVerifierFallbackStrategy(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = ToolResultVerifier()

    def test_fallback_strategy_skip_propagates_on_criteria_failure(self) -> None:
        result = _make_result("completed", output={"row_count": 0})
        vr = self.verifier.verify(result, ["output.row_count > 0"], fallback_strategy="skip")
        self.assertFalse(vr.success)
        self.assertEqual(vr.suggested_action, "skip")

    def test_fallback_strategy_clarify_propagates_on_criteria_failure(self) -> None:
        result = _make_result("completed", output={"tables": []})
        vr = self.verifier.verify(result, ["output.tables is not empty"], fallback_strategy="clarify")
        self.assertFalse(vr.success)
        self.assertEqual(vr.suggested_action, "clarify")

    def test_fallback_strategy_use_alternative_propagates(self) -> None:
        result = _make_result("completed", output={"row_count": 0})
        vr = self.verifier.verify(result, ["output.row_count > 0"], fallback_strategy="use_alternative")
        self.assertFalse(vr.success)
        self.assertEqual(vr.suggested_action, "use_alternative")

    def test_invalid_fallback_strategy_defaults_to_retry(self) -> None:
        result = _make_result("completed", output={"row_count": 0})
        vr = self.verifier.verify(result, ["output.row_count > 0"], fallback_strategy="nonsense")
        self.assertFalse(vr.success)
        self.assertEqual(vr.suggested_action, "retry")

    def test_state_gate_abort_ignores_fallback_strategy(self) -> None:
        # blocked always aborts regardless of fallback_strategy
        result = _make_result("blocked", error="policy")
        vr = self.verifier.verify(result, [], fallback_strategy="retry")
        self.assertEqual(vr.suggested_action, "abort")


class TestVerificationResultDataclass(unittest.TestCase):
    def test_fields_accessible(self) -> None:
        vr = VerificationResult(
            success=True,
            issues=[],
            failure_reason=None,
            suggested_action="proceed",
            alternative_tool=None,
        )
        self.assertTrue(vr.success)
        self.assertIsNone(vr.alternative_tool)


if __name__ == "__main__":
    unittest.main()

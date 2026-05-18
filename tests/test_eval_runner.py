import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_runtime.eval_runner import EVAL_FIXTURE_SCHEMA_VERSION, run_golden_evals
from agent_runtime.redaction import REDACTION
from agent_runtime.trace import (
    SecretLeakError,
    TRACE_EVENT_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    assert_no_known_secret_values,
)


class EvalRunnerTests(unittest.TestCase):
    def test_golden_evals_pass_locally_and_write_versioned_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "eval-output"

            result = run_golden_evals(output_dir=output_dir)

            self.assertTrue(result.passed, result.to_dict())
            self.assertEqual(9, len(result.case_results))
            self.assertTrue((output_dir / "eval-summary.json").exists())
            sh_case_result = next(
                case_result
                for case_result in result.case_results
                if case_result.case_id == "sh_revenue_product_month_schema_context"
            )
            self.assertEqual("ask_clarification", sh_case_result.actual["action"]["kind"])
            self.assertNotIn("trace_events", sh_case_result.actual)

            for case_result in result.case_results:
                trace_path = Path(case_result.trace_path)
                self.assertTrue(trace_path.exists())
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                self.assertEqual(TRACE_SCHEMA_VERSION, trace["schema_version"])
                self.assertEqual("1", trace["artifact_versions"]["prompt_versions"]["intent_classifier"]["version"])
                self.assertEqual("1", trace["artifact_versions"]["policy_versions"]["redaction_policy"]["version"])
                self.assertEqual("none", trace["artifact_versions"]["memory_versions"]["runtime_memory"]["version"])
                self.assertGreaterEqual(len(trace["events"]), 1)
                self.assertEqual(TRACE_EVENT_SCHEMA_VERSION, trace["events"][0]["schema_version"])
                self.assertIn("event_type", trace["events"][0])
                self.assertIn("payload", trace["events"][0])

            sh_trace = json.loads(Path(sh_case_result.trace_path).read_text(encoding="utf-8"))
            tool_completed = next(
                event
                for event in sh_trace["events"]
                if event["event_type"] == "tool_completed"
            )
            output = tool_completed["payload"]["result"]["output"]
            self.assertEqual("oracle_adw_sh.v1", output["profile_id"])
            self.assertFalse(output["external_access"])
            self.assertFalse(output["sql_execution_enabled"])
            query_plan = output["query_plan"]
            self.assertEqual("agent-runtime.query-plan.v1", query_plan["schema_version"])
            self.assertEqual("planned", query_plan["status"])
            self.assertTrue(query_plan["policy_validation"]["allowed"])
            self.assertEqual("allowed", query_plan["policy_validation"]["code"])
            self.assertFalse(query_plan["execution"]["enabled"])
            self.assertEqual("not_executed", query_plan["execution"]["status"])
            self.assertIn("SH.SALES", query_plan["selected_table_ids"])
            self.assertIn("SH.PRODUCTS", query_plan["selected_table_ids"])
            self.assertIn("SH.TIMES", query_plan["selected_table_ids"])
            self.assertNotIn("rows", query_plan["execution"])
            self.assertNotIn("result_rows", query_plan)
            result_explanation = output["result_explanation"]
            self.assertEqual("agent-runtime.result-explanation.v1", result_explanation["schema_version"])
            self.assertEqual("succeeded", result_explanation["status"])
            self.assertEqual("fake/deterministic", result_explanation["source"])
            self.assertFalse(result_explanation["real_database_execution"])
            self.assertEqual("fake", result_explanation["sql_execution_backend"])
            self.assertEqual(2, result_explanation["row_count"])
            self.assertEqual(
                "schema-context-product-month-fake-results",
                result_explanation["adapter_response_metadata"]["fixture_id"],
            )
            self.assertEqual(
                "sh-revenue-product-month-demo",
                result_explanation["adapter_response_metadata"]["scenario_id"],
            )
            self.assertEqual(
                "fake-sql-execution-adapter.v1",
                result_explanation["adapter_response_metadata"]["adapter_version"],
            )
            self.assertFalse(result_explanation["adapter_response_metadata"]["oracle_adw_execution"])
            self.assertFalse(result_explanation["adapter_response_metadata"]["sqlcl_execution"])
            self.assertNotIn("real_database_rows", result_explanation)
            self.assertNotIn("oracle_adw_rows", result_explanation)
            self.assertNotIn("sqlcl_rows", result_explanation)

            explanation_cases = {
                "sh_revenue_channel_month_schema_context": (
                    ["month", "channel", "revenue"],
                    "schema-context-channel-month-fake-results",
                    "sh-revenue-channel-month-demo",
                ),
                "sh_revenue_promotion_month_schema_context": (
                    ["month", "promotion_category", "revenue"],
                    "schema-context-promotion-category-month-fake-results",
                    "sh-revenue-promotion-category-month-demo",
                ),
            }
            for case_id, (columns, fixture_id, scenario_id) in explanation_cases.items():
                with self.subTest(case_id=case_id):
                    case_result = next(
                        item
                        for item in result.case_results
                        if item.case_id == case_id
                    )
                    trace = json.loads(Path(case_result.trace_path).read_text(encoding="utf-8"))
                    tool_completed = next(
                        event
                        for event in trace["events"]
                        if event["event_type"] == "tool_completed"
                    )
                    output = tool_completed["payload"]["result"]["output"]
                    self.assertFalse(output["sql_execution_enabled"])
                    self.assertEqual("planned", output["query_plan"]["status"])
                    self.assertFalse(output["query_plan"]["execution"]["enabled"])
                    self.assertEqual("not_executed", output["query_plan"]["execution"]["status"])
                    result_explanation = output["result_explanation"]
                    self.assertEqual("agent-runtime.result-explanation.v1", result_explanation["schema_version"])
                    self.assertEqual("succeeded", result_explanation["status"])
                    self.assertEqual("fake/deterministic", result_explanation["source"])
                    self.assertFalse(result_explanation["real_database_execution"])
                    self.assertEqual("fake", result_explanation["sql_execution_backend"])
                    self.assertEqual(columns, result_explanation["columns"])
                    self.assertEqual(fixture_id, result_explanation["adapter_response_metadata"]["fixture_id"])
                    self.assertEqual(scenario_id, result_explanation["adapter_response_metadata"]["scenario_id"])
                    self.assertEqual(
                        "fake-sql-execution-adapter.v1",
                        result_explanation["adapter_response_metadata"]["adapter_version"],
                    )
                    self.assertFalse(result_explanation["adapter_response_metadata"]["oracle_adw_execution"])
                    self.assertFalse(result_explanation["adapter_response_metadata"]["sqlcl_execution"])
                    self.assertNotIn("real_database_rows", result_explanation)
                    self.assertNotIn("oracle_adw_rows", result_explanation)
                    self.assertNotIn("sqlcl_rows", result_explanation)

            refusal_cases = {
                "sh_revenue_region_month_ambiguous_schema_context": "ask_clarification",
                "sh_revenue_month_unsupported_schema_context": "ask_clarification",
                "blocked_database_write": "refuse",
            }
            for case_id, action_kind in refusal_cases.items():
                with self.subTest(case_id=case_id):
                    case_result = next(
                        item
                        for item in result.case_results
                        if item.case_id == case_id
                    )
                    self.assertEqual(action_kind, case_result.actual["action"]["kind"])
                    trace = json.loads(Path(case_result.trace_path).read_text(encoding="utf-8"))
                    _assert_absent_anywhere(
                        self,
                        trace["events"],
                        {
                            "result_explanation",
                            "rows",
                            "result_rows",
                            "real_database_rows",
                            "oracle_adw_rows",
                            "sqlcl_rows",
                            "real_database_execution",
                            "sql_execution_backend",
                        },
                    )

    def test_eval_runner_fails_on_mismatched_query_plan_trace_expectation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "fixtures"
            output_dir = root / "output"
            fixture_dir.mkdir()
            _write_fixture_with_bad_query_plan_expectation(fixture_dir / "bad-query-plan.json")

            result = run_golden_evals(fixture_dir=fixture_dir, output_dir=output_dir)

            self.assertFalse(result.passed, result.to_dict())
            self.assertEqual(1, len(result.case_results))
            self.assertFalse(result.case_results[0].passed)
            self.assertIn("query_plan", "\n".join(result.case_results[0].mismatches))

    def test_eval_runner_redacts_known_secret_values_from_trace_and_summary(self):
        previous = os.environ.get("EVAL_TEST_PASSWORD")
        os.environ["EVAL_TEST_PASSWORD"] = "eval-secret-value-1234"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture_dir = root / "fixtures"
                output_dir = root / "output"
                fixture_dir.mkdir()
                _write_fixture_with_secret_input(fixture_dir / "secret-input.json")

                result = run_golden_evals(fixture_dir=fixture_dir, output_dir=output_dir)

                self.assertTrue(result.passed, result.to_dict())
                summary_text = (output_dir / "eval-summary.json").read_text(encoding="utf-8")
                self.assertNotIn("eval-secret-value-1234", summary_text)
                self.assertIn(REDACTION, summary_text)

                trace_texts = [
                    path.read_text(encoding="utf-8")
                    for path in output_dir.glob("**/*.trace.json")
                ]
                self.assertEqual(1, len(trace_texts))
                self.assertNotIn("eval-secret-value-1234", trace_texts[0])
                self.assertIn(REDACTION, trace_texts[0])
        finally:
            if previous is None:
                os.environ.pop("EVAL_TEST_PASSWORD", None)
            else:
                os.environ["EVAL_TEST_PASSWORD"] = previous

    def test_secret_check_fails_on_known_secret_value(self):
        previous = os.environ.get("TRACE_TEST_TOKEN")
        os.environ["TRACE_TEST_TOKEN"] = "trace-secret-value-5678"
        try:
            with self.assertRaises(SecretLeakError):
                assert_no_known_secret_values(
                    {"unsafe": "trace-secret-value-5678"},
                    context="unit test",
                )
        finally:
            if previous is None:
                os.environ.pop("TRACE_TEST_TOKEN", None)
            else:
                os.environ["TRACE_TEST_TOKEN"] = previous

    def test_secret_check_ignores_common_low_signal_values(self):
        previous = os.environ.get("TRACE_TEST_TOKEN")
        os.environ["TRACE_TEST_TOKEN"] = "true"
        try:
            assert_no_known_secret_values(
                {"passed": True, "text": "true"},
                context="unit test",
            )
        finally:
            if previous is None:
                os.environ.pop("TRACE_TEST_TOKEN", None)
            else:
                os.environ["TRACE_TEST_TOKEN"] = previous


def _assert_absent_anywhere(
    test_case: unittest.TestCase,
    value: object,
    forbidden_keys: set[str],
    path: str = "trace",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            test_case.assertNotIn(key, forbidden_keys, f"{path}.{key} should be absent")
            _assert_absent_anywhere(test_case, item, forbidden_keys, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_absent_anywhere(test_case, item, forbidden_keys, f"{path}[{index}]")


def _write_fixture_with_secret_input(path: Path) -> None:
    fixture = {
        "schema_version": EVAL_FIXTURE_SCHEMA_VERSION,
        "fixture_id": "secret-redaction-v1",
        "cases": [
            {
                "case_id": "secret_input",
                "input": "summarize eval-secret-value-1234",
                "expected": {
                    "intent": {
                        "intent_type": "general",
                        "next_action": "answer_directly",
                    },
                    "action": {
                        "kind": "final_answer",
                    },
                },
            }
        ],
    }
    path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_fixture_with_bad_query_plan_expectation(path: Path) -> None:
    fixture = {
        "schema_version": EVAL_FIXTURE_SCHEMA_VERSION,
        "fixture_id": "bad-query-plan-v1",
        "cases": [
            {
                "case_id": "bad_query_plan_status",
                "input": "Show monthly revenue by product from the Oracle ADW SH schema.",
                "expected": {
                    "trace_events": [
                        {
                            "event_type": "tool_completed",
                            "payload": {
                                "result": {
                                    "output": {
                                        "query_plan": {
                                            "schema_version": "agent-runtime.query-plan.v1",
                                            "status": "blocked",
                                        }
                                    }
                                }
                            },
                        }
                    ]
                },
            }
        ],
    }
    path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()

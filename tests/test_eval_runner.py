import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_runtime.eval_runner import EVAL_FIXTURE_SCHEMA_VERSION, run_golden_evals
from agent_runtime.redaction import REDACTION
from agent_runtime.trace import (
    SecretLeakError,
    TRACE_SCHEMA_VERSION,
    assert_no_known_secret_values,
)


class EvalRunnerTests(unittest.TestCase):
    def test_golden_evals_pass_locally_and_write_versioned_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "eval-output"

            result = run_golden_evals(output_dir=output_dir)

            self.assertTrue(result.passed, result.to_dict())
            self.assertEqual(4, len(result.case_results))
            self.assertTrue((output_dir / "eval-summary.json").exists())

            for case_result in result.case_results:
                trace_path = Path(case_result.trace_path)
                self.assertTrue(trace_path.exists())
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
                self.assertEqual(TRACE_SCHEMA_VERSION, trace["schema_version"])
                self.assertEqual("1", trace["artifact_versions"]["prompt_versions"]["intent_classifier"]["version"])
                self.assertEqual("1", trace["artifact_versions"]["policy_versions"]["redaction_policy"]["version"])
                self.assertEqual("none", trace["artifact_versions"]["memory_versions"]["runtime_memory"]["version"])
                self.assertGreaterEqual(len(trace["events"]), 1)

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


if __name__ == "__main__":
    unittest.main()

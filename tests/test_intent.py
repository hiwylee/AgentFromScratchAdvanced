import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_runtime.audit import RunRecord, append_audit, write_trace
from agent_runtime.intent import analyze_user_intent
from agent_runtime.loop import AgentLoop
from agent_runtime.monitor import latest_status
from agent_runtime.types import Budget


class IntentTests(unittest.TestCase):
    def test_korean_database_analysis_intent(self):
        intent = analyze_user_intent("지난달 상품별 매출 추이를 보여줘")

        self.assertEqual("database_analysis", intent.intent_type)
        self.assertEqual("trend_analysis", intent.task_type)
        self.assertEqual("read_only", intent.safety_level)
        self.assertTrue(intent.requires_oracle_adw_context)
        self.assertEqual(["revenue"], intent.entities["metrics"])
        self.assertEqual(["product"], intent.entities["dimensions"])
        self.assertIn("business_glossary", intent.required_context)
        self.assertIn("metric_definition", intent.ambiguities)

    def test_general_request_does_not_require_adw(self):
        intent = analyze_user_intent("summarize this repository")

        self.assertEqual("general", intent.intent_type)
        self.assertFalse(intent.requires_oracle_adw_context)
        self.assertEqual("answer_directly", intent.next_action)

    def test_write_request_is_blocked(self):
        intent = analyze_user_intent("고객 테이블에서 오래된 데이터를 삭제해줘")

        self.assertEqual("database_analysis", intent.intent_type)
        self.assertEqual("blocked_write_request", intent.safety_level)
        self.assertEqual("refuse_or_request_explicit_safe_alternative", intent.next_action)


class AuditTests(unittest.TestCase):
    def test_trace_and_audit_redact_sensitive_environment_values(self):
        previous = os.environ.get("DB_USER_PASS")
        os.environ["DB_USER_PASS"] = "super-secret-test-password"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                record = RunRecord.create(
                    event="intent_analyzed",
                    data={
                        "DB_USER_PASS": "super-secret-test-password",
                        "message": "value is super-secret-test-password",
                    },
                )

                trace_path = write_trace(record, tmp_path / "traces")
                audit_path = tmp_path / "audit.jsonl"
                append_audit(record, audit_path)

                trace_text = trace_path.read_text(encoding="utf-8")
                audit_text = audit_path.read_text(encoding="utf-8")
                self.assertNotIn("super-secret-test-password", trace_text)
                self.assertNotIn("super-secret-test-password", audit_text)
                self.assertIn("[REDACTED]", trace_text)
                self.assertIn("[REDACTED]", audit_text)

                parsed = json.loads(trace_text)
                self.assertEqual("intent_analyzed", parsed["event"])
        finally:
            if previous is None:
                os.environ.pop("DB_USER_PASS", None)
            else:
                os.environ["DB_USER_PASS"] = previous


class AgentLoopTests(unittest.TestCase):
    def test_agent_loop_writes_monitorable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=4, timeout_seconds=30),
            )

            result = loop.run("지난달 상품별 매출 추이를 보여줘")

            self.assertEqual("database_analysis", result.intent["intent_type"])
            self.assertEqual("ask_clarification", result.action["kind"])
            self.assertTrue(Path(result.status_path).exists())
            self.assertTrue(Path(result.events_path).exists())
            self.assertTrue(Path(result.audit_path).exists())

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("completed", status["state"])
            self.assertGreaterEqual(status["event_count"], 5)

    def test_agent_loop_blocks_write_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(run_root=tmp_path / "runs", audit_path=tmp_path / "audit.jsonl")

            result = loop.run("고객 테이블에서 오래된 데이터를 삭제해줘")

            self.assertEqual("blocked_write_request", result.intent["safety_level"])
            self.assertEqual("refuse", result.action["kind"])
            self.assertIn("read-only", result.final_answer["content"])


if __name__ == "__main__":
    unittest.main()

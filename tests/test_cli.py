import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_runtime import cli
from agent_runtime.cli import main
from agent_runtime.sql_execution import SqlExecutionResponse


class CliTests(unittest.TestCase):
    def test_operator_live_audit_payload_omits_response_rows(self):
        payload: dict[str, object] = {"response": {"rows": [{"secret": "value"}], "row_count": 1}}

        audit_payload = cli._operator_query_audit_payload(payload)
        response = audit_payload["response"]
        original_response = payload["response"]

        assert isinstance(response, dict)
        assert isinstance(original_response, dict)
        self.assertNotIn("rows", response)
        self.assertTrue(response["rows_omitted_from_audit"])
        self.assertIn("rows", original_response)

    def test_operator_adw_smoke_audit_omits_response_rows(self):
        class FakeAdapter:
            def __init__(self, *args, **kwargs):
                pass

            def execute(self, request):
                return SqlExecutionResponse(
                    ok=True,
                    status="succeeded",
                    backend="sqlcl",
                    columns=("SMOKE_CHECK",),
                    rows=({"SMOKE_CHECK": 1},),
                    row_count=1,
                    backend_metadata={
                        "execution_state": "executed",
                        "sql_sha256": "abc123",
                    },
                )

        config = SimpleNamespace(redacted_status=lambda: {"db_user_configured": True})

        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"
            with patch("agent_runtime.cli.OracleAdwConfig.from_env", return_value=config), patch(
                "agent_runtime.cli._validate_operator_adw_limits", return_value=None
            ), patch("agent_runtime.cli._validate_operator_adw_config", return_value=None), patch(
                "agent_runtime.cli.verify_sqlcl", return_value=SimpleNamespace(ok=True)
            ), patch("agent_runtime.cli.SqlclReadOnlyAdapter", FakeAdapter), redirect_stdout(output):
                exit_code = main(
                    [
                        "operator",
                        "adw-smoke",
                        "--confirm-live-adw-smoke",
                        "--audit-log",
                        str(audit_path),
                    ]
                )

            stdout_payload = json.loads(output.getvalue())
            audit_record = json.loads(audit_path.read_text(encoding="utf-8").strip())

        self.assertEqual(0, exit_code)
        self.assertIn("rows", stdout_payload["response"])
        audit_response = audit_record["data"]["response"]
        self.assertNotIn("rows", audit_response)
        self.assertEqual(1, audit_response["row_count"])
        self.assertTrue(audit_response["rows_omitted_from_audit"])

    def test_operator_adw_provision_completed_runner_failed_incomplete_is_not_success(self):
        output = io.StringIO()
        config = SimpleNamespace(db_user="WORKER")
        completed = {
            "status": "completed",
            "returncode": 0,
            "stdout_bytes": 2,
            "stderr_bytes": 0,
            "stdout": "{}",
            "stderr": "",
            "actions_applied": ["grant_role:DWROLE"],
        }
        classification = {
            "classification": "failed_incomplete",
            "state": {
                "active_prefix": "post",
                "post": {"compliant": False},
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agent_runtime.cli._load_local_env", lambda path: None), patch(
                "agent_runtime.cli.OracleAdwConfig.from_env", return_value=config
            ), patch(
                "agent_runtime.cli._validate_operator_admin_provision_config", return_value=None
            ), patch(
                "agent_runtime.cli.verify_sqlcl",
                return_value=SimpleNamespace(ok=True),
            ), patch(
                "agent_runtime.cli._run_admin_provision_sqlcl", return_value=completed
            ), patch(
                "agent_runtime.cli._classify_admin_provisioning_result", return_value=classification
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "operator",
                        "adw-provision-working-user",
                        "--grant-profile",
                        "prototype-any-table-read",
                        "--confirm-live-adw-admin-provision",
                        "--audit-log",
                        str(Path(tmp) / "audit.jsonl"),
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code)
        self.assertEqual("failed", payload["state"])
        self.assertTrue(payload["runner_succeeded"])
        self.assertFalse(payload["provisioning_succeeded"])
        self.assertFalse(payload["admin_execution_succeeded"])

    def test_operator_adw_provision_completed_runner_compliant_classification_succeeds(self):
        output = io.StringIO()
        config = SimpleNamespace(db_user="WORKER")
        completed = {
            "status": "completed",
            "returncode": 0,
            "stdout_bytes": 2,
            "stderr_bytes": 0,
            "stdout": "{}",
            "stderr": "",
            "actions_applied": [],
        }
        classification = {
            "classification": "already_compliant",
            "state": {
                "active_prefix": "pre",
                "pre": {"compliant": True},
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch("agent_runtime.cli._load_local_env", lambda path: None), patch(
                "agent_runtime.cli.OracleAdwConfig.from_env", return_value=config
            ), patch(
                "agent_runtime.cli._validate_operator_admin_provision_config", return_value=None
            ), patch(
                "agent_runtime.cli.verify_sqlcl",
                return_value=SimpleNamespace(ok=True),
            ), patch(
                "agent_runtime.cli._run_admin_provision_sqlcl", return_value=completed
            ), patch(
                "agent_runtime.cli._classify_admin_provisioning_result", return_value=classification
            ), redirect_stdout(output):
                exit_code = main(
                    [
                        "operator",
                        "adw-provision-working-user",
                        "--grant-profile",
                        "prototype-any-table-read",
                        "--confirm-live-adw-admin-provision",
                        "--audit-log",
                        str(Path(tmp) / "audit.jsonl"),
                    ]
                )

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual("succeeded", payload["state"])
        self.assertTrue(payload["runner_succeeded"])
        self.assertTrue(payload["provisioning_succeeded"])
        self.assertTrue(payload["admin_execution_succeeded"])

    def test_operator_sql_file_is_read_with_byte_bound(self):
        class BoundedBytesFile:
            def __init__(self):
                self.read_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self, size=-1):
                self.read_sizes.append(size)
                return b"select 1 from dual"

        fake_file = BoundedBytesFile()

        with patch("pathlib.Path.open", return_value=fake_file):
            sql_text, source, error = cli._load_operator_sql(
                sql=None,
                sql_file="query.sql",
                sql_stdin=False,
            )

        self.assertEqual("select 1 from dual", sql_text)
        self.assertEqual("file", source)
        self.assertIsNone(error)
        self.assertEqual([cli.MAX_OPERATOR_SQL_BYTES + 1], fake_file.read_sizes)

    def test_operator_sql_file_invalid_utf8_returns_explicit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "bad.sql"
            sql_path.write_bytes(b"select \xff from dual")

            sql_text, source, error = cli._load_operator_sql(
                sql=None,
                sql_file=str(sql_path),
                sql_stdin=False,
            )

        self.assertIsNone(sql_text)
        self.assertEqual("file", source)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual("invalid_sql_encoding", error["code"])

    def test_operator_sql_stdin_is_read_with_byte_bound(self):
        class BoundedStdinBuffer:
            def __init__(self):
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return b"select 1 from dual"

        fake_buffer = BoundedStdinBuffer()
        fake_stdin = SimpleNamespace(buffer=fake_buffer)

        with patch("sys.stdin", fake_stdin):
            sql_text, source, error = cli._load_operator_sql(
                sql=None,
                sql_file=None,
                sql_stdin=True,
            )

        self.assertEqual("select 1 from dual", sql_text)
        self.assertEqual("stdin", source)
        self.assertIsNone(error)
        self.assertEqual([cli.MAX_OPERATOR_SQL_BYTES + 1], fake_buffer.read_sizes)

    def test_ask_openai_provider_requires_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with patch("agent_runtime.cli._load_local_env", lambda path: None):
                with patch.dict(os.environ, {}, clear=True):
                    with redirect_stdout(output):
                        exit_code = main(
                            [
                                "ask",
                                "hello",
                                "--model-provider",
                                "openai",
                                "--run-dir",
                                str(Path(tmp) / "runs"),
                                "--audit-log",
                                str(Path(tmp) / "audit.jsonl"),
                            ]
                        )

            payload = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual("configuration_required", payload["state"])
            self.assertEqual("openai", payload["provider"])
            self.assertIn("OPENAI_API_KEY", payload["required_environment"])

    def test_ask_oci_provider_can_be_selected_by_llm_env_and_requires_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with patch("agent_runtime.cli._load_local_env", lambda path: None):
                with patch.dict(
                    os.environ,
                    {
                        "LLM": "oci",
                        "OCI_BASE_URL": "https://example.oci.oraclecloud.com/openai/v1",
                        "OCI_MODEL": "xai.grok-4-1-fast-non-reasoning",
                    },
                    clear=True,
                ):
                    with redirect_stdout(output):
                        exit_code = main(
                            [
                                "ask",
                                "hello",
                                "--run-dir",
                                str(Path(tmp) / "runs"),
                                "--audit-log",
                                str(Path(tmp) / "audit.jsonl"),
                            ]
                        )

            payload = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual("configuration_required", payload["state"])
            self.assertEqual("oci", payload["provider"])
            self.assertIn("OCI_BASE_URL", payload["required_environment"])
            self.assertIn("OCI_API_KEY or OCI_API_KEY_2", payload["required_environment"])

    def test_ask_oci_provider_redacts_configured_key_from_error_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with patch("agent_runtime.cli._load_local_env", lambda path: None):
                with patch.dict(
                    os.environ,
                    {
                        "OCI_BASE_URL": "not-a-url",
                        "OCI_API_KEY": "test-oci-secret",
                    },
                    clear=True,
                ):
                    with redirect_stdout(output):
                        exit_code = main(
                            [
                                "ask",
                                "hello",
                                "--model-provider",
                                "oci",
                                "--run-dir",
                                str(Path(tmp) / "runs"),
                                "--audit-log",
                                str(Path(tmp) / "audit.jsonl"),
                            ]
                        )

            self.assertEqual(2, exit_code)
            self.assertNotIn("test-oci-secret", output.getvalue())
            payload = json.loads(output.getvalue())
            self.assertEqual("oci", payload["provider"])

    def test_ask_mock_provider_ignores_project_env_when_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with patch.dict(os.environ, {}, clear=True):
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "ask",
                            "hello",
                            "--model-provider",
                            "mock",
                            "--run-dir",
                            str(Path(tmp) / "runs"),
                            "--audit-log",
                            str(Path(tmp) / "audit.jsonl"),
                        ]
                    )

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("final_answer", payload["action"]["kind"])

    def test_workflow_command_rejects_unsupported_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "workflow",
                        "지난달 매출 분석해줘",
                        "--run-dir",
                        str(Path(tmp) / "runs"),
                        "--audit-log",
                        str(Path(tmp) / "audit.jsonl"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual("unsupported_workflow", payload["state"])

    def test_workflow_command_redacts_unsupported_request_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            old_value = os.environ.get("WORKFLOW_TEST_PASSWORD")
            os.environ["WORKFLOW_TEST_PASSWORD"] = "super-secret-value"
            try:
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "workflow",
                            "지원하지 않는 요청 super-secret-value",
                            "--run-dir",
                            str(Path(tmp) / "runs"),
                            "--audit-log",
                            str(Path(tmp) / "audit.jsonl"),
                        ]
                    )
            finally:
                if old_value is None:
                    os.environ.pop("WORKFLOW_TEST_PASSWORD", None)
                else:
                    os.environ["WORKFLOW_TEST_PASSWORD"] = old_value

            payload = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertNotIn("super-secret-value", output.getvalue())
            self.assertEqual("지원하지 않는 요청 [REDACTED]", payload["request_text"])

    def test_workflow_command_runs_supported_patent_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "workflow",
                        "이번달 특허자산 대체 등록 진행해줘",
                        "--run-dir",
                        str(Path(tmp) / "runs"),
                        "--audit-log",
                        str(Path(tmp) / "audit.jsonl"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("checkpoint_required", payload["state"])
            self.assertEqual("blocked", payload["target_load"]["state"])
            self.assertTrue(Path(payload["status_path"]).exists())

    def test_operator_propose_improvement_records_candidate_without_applying(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            output_dir = Path(tmp) / "candidates"
            audit_path = Path(tmp) / "audit.jsonl"

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "operator",
                        "propose-improvement",
                        "--candidate-id",
                        "candidate-docs-001",
                        "--candidate-type",
                        "docs",
                        "--trigger-type",
                        "operator_note",
                        "--summary",
                        "Clarify operator runbook.",
                        "--proposed-change",
                        "Add one troubleshooting note.",
                        "--affected-artifact",
                        "docs/runbooks/operator-adw.md",
                        "docs",
                        "1",
                        "2",
                        "--source-type",
                        "operator_note",
                        "--source-id",
                        "manual-session",
                        "--author",
                        "unit-test",
                        "--confidence",
                        "0.7",
                        "--evidence",
                        "tests/test_cli.py",
                        "--output-dir",
                        str(output_dir),
                        "--audit-log",
                        str(audit_path),
                    ]
                )

            payload = json.loads(output.getvalue())
            candidate_path = Path(payload["candidate_path"])
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            audit_lines = audit_path.read_text(encoding="utf-8").splitlines()

            self.assertEqual(0, exit_code)
            self.assertEqual("recorded", payload["state"])
            self.assertFalse(payload["applied"])
            self.assertEqual("not_run", payload["acceptance_gate_state"])
            self.assertEqual("proposed", candidate["status"])
            self.assertEqual("pending", candidate["review"]["decision"])
            self.assertEqual("pending", candidate["provenance"]["review_status"])
            self.assertEqual(1, len(audit_lines))

    def test_operator_propose_improvement_rejects_unsafe_candidate_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "operator",
                        "propose-improvement",
                        "--candidate-id",
                        "../bad",
                        "--candidate-type",
                        "docs",
                        "--trigger-type",
                        "operator_note",
                        "--summary",
                        "Clarify operator runbook.",
                        "--proposed-change",
                        "Add one troubleshooting note.",
                        "--affected-artifact",
                        "docs/runbooks/operator-adw.md",
                        "docs",
                        "1",
                        "2",
                        "--source-type",
                        "operator_note",
                        "--source-id",
                        "manual-session",
                        "--output-dir",
                        str(Path(tmp) / "candidates"),
                        "--audit-log",
                        str(Path(tmp) / "audit.jsonl"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("rejected", payload["state"])
            self.assertEqual("invalid_improvement_candidate", payload["error"]["code"])

    def test_operator_propose_improvement_rejects_non_finite_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "operator",
                        "propose-improvement",
                        "--candidate-id",
                        "candidate-docs-001",
                        "--candidate-type",
                        "docs",
                        "--trigger-type",
                        "operator_note",
                        "--summary",
                        "Clarify operator runbook.",
                        "--proposed-change",
                        "Add one troubleshooting note.",
                        "--affected-artifact",
                        "docs/runbooks/operator-adw.md",
                        "docs",
                        "1",
                        "2",
                        "--source-type",
                        "operator_note",
                        "--source-id",
                        "manual-session",
                        "--confidence",
                        "nan",
                        "--output-dir",
                        str(Path(tmp) / "candidates"),
                        "--audit-log",
                        str(Path(tmp) / "audit.jsonl"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("rejected", payload["state"])
            self.assertEqual("invalid_improvement_candidate", payload["error"]["code"])
            self.assertIn("finite number", payload["error"]["message"])

    def test_operator_propose_improvement_reports_write_failure_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"

            with patch("agent_runtime.cli.write_improvement_candidate", side_effect=OSError("disk full")):
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "operator",
                            "propose-improvement",
                            "--candidate-id",
                            "candidate-docs-001",
                            "--candidate-type",
                            "docs",
                            "--trigger-type",
                            "operator_note",
                            "--summary",
                            "Clarify operator runbook.",
                            "--proposed-change",
                            "Add one troubleshooting note.",
                            "--affected-artifact",
                            "docs/runbooks/operator-adw.md",
                            "docs",
                            "1",
                            "2",
                            "--source-type",
                            "operator_note",
                            "--source-id",
                            "manual-session",
                            "--output-dir",
                            str(Path(tmp) / "candidates"),
                            "--audit-log",
                            str(audit_path),
                        ]
                    )

            payload = json.loads(output.getvalue())
            audit_payload = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(1, exit_code)
            self.assertEqual("failed", payload["state"])
            self.assertEqual("candidate_write_failed", payload["error"]["code"])
            self.assertEqual("failed", audit_payload["data"]["state"])


if __name__ == "__main__":
    unittest.main()

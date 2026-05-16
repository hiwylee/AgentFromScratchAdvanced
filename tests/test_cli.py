import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent_runtime.cli import main


class CliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

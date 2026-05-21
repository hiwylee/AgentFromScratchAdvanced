import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_runtime.oracle_adw import SqlclReadOnlyExecutionPlan, SqlclRunResult
from agent_runtime.redaction import REDACTION
from agent_runtime.sqlcl_runner import (
    SqlclRunnerResult,
    SqlclSubprocessRequest,
    build_redacted_sqlcl_runner_metadata,
    run_sqlcl_plan,
    run_sqlcl_subprocess,
)


class SqlclSubprocessRunnerTests(unittest.TestCase):
    def test_runner_passes_plan_command_env_stdin_and_timeout(self):
        calls = []
        plan = _plan(
            env={"TNS_ADMIN": "/wallet/path", "UNAPPROVED_KEY": "plan-value"},
            stdin="connect AGENT_RO/db-secret@adw-secret-service\nselect 1\n",
            timeout_seconds=9,
        )

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"items":[]}',
                stderr="",
            )

        result = run_sqlcl_plan(
            plan,
            base_env={"PATH": "/bin", "UNAPPROVED_KEY": "base-value"},
            runner=fake_run,
        )

        self.assertIsInstance(result, SqlclRunnerResult)
        self.assertEqual("completed", result.status)
        self.assertEqual('{"items":[]}', result.stdout)
        self.assertEqual((("/opt/sqlcl/bin/sql", "-S", "-L", "-nolog")), calls[0][0])
        self.assertEqual(
            "connect AGENT_RO/db-secret@adw-secret-service\nselect 1\n",
            calls[0][1]["input"],
        )
        self.assertEqual(9, calls[0][1]["timeout"])
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertTrue(calls[0][1]["text"])
        self.assertEqual("/bin", calls[0][1]["env"]["PATH"])
        self.assertEqual("base-value", calls[0][1]["env"]["UNAPPROVED_KEY"])
        self.assertEqual("/wallet/path", calls[0][1]["env"]["TNS_ADMIN"])

    def test_timeout_returns_structured_result_without_stdin_or_secrets(self):
        plan = _plan(
            stdin="connect AGENT_RO/db-secret@adw-secret-service\nselect 1\n",
            timeout_seconds=3,
        )

        def fake_run(args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=args,
                timeout=kwargs["timeout"],
                output="partial db-secret stdout extra-secret",
                stderr=b"partial adw-secret-service stderr extra-secret",
            )

        result = run_sqlcl_plan(
            plan,
            base_env={"DB_USER_PASS": "db-secret", "EXTRA_SECRET": "extra-secret"},
            runner=fake_run,
        )
        rendered = (
            f"{result!r} {result.to_redacted_dict()} "
            f"{result.stdout} {result.stderr}"
        )

        self.assertEqual("timeout", result.status)
        self.assertEqual(-1, result.returncode)
        self.assertTrue(result.timed_out)
        self.assertIn("timed out after 3 seconds", result.stderr)
        self.assertNotIn("connect AGENT_RO", rendered)
        self.assertNotIn("db-secret", rendered)
        self.assertNotIn("adw-secret-service", rendered)
        self.assertNotIn("extra-secret", rendered)
        self.assertEqual(REDACTION, result.to_redacted_dict()["stdin"])

    def test_oversized_stdout_and_stderr_are_bounded_and_classified(self):
        plan = _plan(max_output_bytes=5, max_error_bytes=4)

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="abcdef",
                stderr="wxyz!",
            )

        result = run_sqlcl_plan(plan, runner=fake_run)

        self.assertEqual("output_too_large", result.status)
        self.assertTrue(result.stdout_too_large)
        self.assertTrue(result.stderr_too_large)
        self.assertEqual(6, result.stdout_bytes)
        self.assertEqual(5, result.stderr_bytes)
        self.assertEqual("abcde", result.stdout)
        self.assertEqual("wxyz", result.stderr)

    def test_default_runner_stops_process_when_stdout_limit_is_exceeded(self):
        plan = _plan(
            command=(
                sys.executable,
                "-c",
                (
                    "import sys, time; "
                    "sys.stdout.write('x' * 2048); "
                    "sys.stdout.flush(); "
                    "time.sleep(5)"
                ),
            ),
            timeout_seconds=30,
            max_output_bytes=1024,
        )

        started = time.monotonic()
        result = run_sqlcl_plan(plan)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 3)
        self.assertEqual("output_too_large", result.status)
        self.assertTrue(result.stdout_too_large)
        self.assertEqual(1025, result.stdout_bytes)
        self.assertEqual(1024, len(result.stdout.encode("utf-8")))

    def test_default_runner_stops_process_when_stderr_limit_is_exceeded(self):
        plan = _plan(
            command=(
                sys.executable,
                "-c",
                (
                    "import sys, time; "
                    "sys.stderr.write('e' * 2048); "
                    "sys.stderr.flush(); "
                    "time.sleep(5)"
                ),
            ),
            timeout_seconds=30,
            max_error_bytes=1024,
        )

        started = time.monotonic()
        result = run_sqlcl_plan(plan)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 3)
        self.assertEqual("error_output_too_large", result.status)
        self.assertTrue(result.stderr_too_large)
        self.assertEqual(1025, result.stderr_bytes)
        self.assertEqual(1024, len(result.stderr.encode("utf-8")))

    def test_default_runner_drains_output_from_child_after_wrapper_exits(self):
        plan = _plan(
            command=(
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "subprocess.Popen([sys.executable, '-c', "
                    "\"import time; time.sleep(1.5); print('late child output')\"]);"
                ),
            ),
            timeout_seconds=10,
        )

        result = run_sqlcl_plan(plan)

        self.assertEqual("completed", result.status)
        self.assertEqual(0, result.returncode)
        self.assertIn("late child output", result.stdout)

    def test_default_runner_timeout_kills_child_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "child-survived.txt"
            plan = _plan(
                command=(
                    sys.executable,
                    "-c",
                    (
                        "import subprocess, sys, time; "
                        "subprocess.Popen([sys.executable, '-c', "
                        f"\"import pathlib, time; time.sleep(1.2); pathlib.Path({str(marker)!r}).write_text('survived')\"]); "
                        "time.sleep(10)"
                    ),
                ),
                timeout_seconds=1,
            )

            result = run_sqlcl_plan(plan)
            time.sleep(1.6)

            self.assertEqual("timeout", result.status)
            self.assertFalse(marker.exists())

    def test_default_runner_output_limit_kills_child_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "child-survived.txt"
            plan = _plan(
                command=(
                    sys.executable,
                    "-c",
                    (
                        "import subprocess, sys, time; "
                        "subprocess.Popen([sys.executable, '-c', "
                        f"\"import pathlib, time; time.sleep(1.2); pathlib.Path({str(marker)!r}).write_text('survived')\"]); "
                        "sys.stdout.write('x' * 2048); sys.stdout.flush(); time.sleep(10)"
                    ),
                ),
                timeout_seconds=30,
                max_output_bytes=1024,
            )

            result = run_sqlcl_plan(plan)
            time.sleep(1.6)

            self.assertEqual("output_too_large", result.status)
            self.assertFalse(marker.exists())

    def test_default_runner_timeout_kills_child_when_group_leader_exited(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "child-survived.txt"
            plan = _plan(
                command=(
                    sys.executable,
                    "-c",
                    (
                        "import subprocess, sys; "
                        "subprocess.Popen([sys.executable, '-c', "
                        f"\"import pathlib, time; time.sleep(1.2); pathlib.Path({str(marker)!r}).write_text('survived')\"]); "
                        "sys.exit(0)"
                    ),
                ),
                timeout_seconds=1,
            )

            result = run_sqlcl_plan(plan)
            time.sleep(1.6)

            self.assertEqual("timeout", result.status)
            self.assertFalse(marker.exists())

    def test_generic_sqlcl_subprocess_runner_bounds_admin_style_output(self):
        request = SqlclSubprocessRequest(
            command=(
                sys.executable,
                "-c",
                (
                    "import sys, time; "
                    "sys.stdout.write('secret-' + 'value' + 'x' * 2048); "
                    "sys.stdout.flush(); "
                    "time.sleep(5)"
                ),
            ),
            stdin="admin-secret-stdin",
            env={"DB_WALLET_PATH": "/wallet-secret"},
            timeout_seconds=30,
            max_output_bytes=1024,
            max_error_bytes=1024,
            sensitive_values=("secret-value", "admin-secret-stdin"),
        )

        started = time.monotonic()
        result = run_sqlcl_subprocess(request)
        elapsed = time.monotonic() - started
        rendered = f"{result!r} {result.to_redacted_dict()} {result.stdout}"

        self.assertLess(elapsed, 3)
        self.assertEqual("output_too_large", result.status)
        self.assertTrue(result.stdout_too_large)
        self.assertEqual(1025, result.stdout_bytes)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("admin-secret-stdin", rendered)
        self.assertNotIn("/wallet-secret", rendered)

    def test_to_sqlcl_run_result_keeps_compatibility_shape(self):
        plan = _plan()

        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=7,
                stdout="safe stdout",
                stderr="safe stderr",
            )

        result = run_sqlcl_plan(plan, runner=fake_run).to_sqlcl_run_result()

        self.assertIsInstance(result, SqlclRunResult)
        self.assertEqual(7, result.returncode)
        self.assertEqual("safe stdout", result.stdout)
        self.assertEqual("safe stderr", result.stderr)

    def test_redacted_metadata_has_no_env_values_or_stdin(self):
        plan = _plan(
            env={
                "TNS_ADMIN": "/wallet/secret-path",
                "DB_DSN": "adw-secret-service",
                "DB_USER_PASS": "db-secret",
            },
            stdin="connect AGENT_RO/db-secret@adw-secret-service\nselect 1\n",
        )

        metadata = build_redacted_sqlcl_runner_metadata(
            plan,
            base_env={"PATH": "/bin", "EXTRA_SECRET": "extra-secret"},
        )
        rendered = str(metadata)

        self.assertEqual(REDACTION, metadata["stdin"])
        self.assertNotIn("DB_DSN", metadata["plan_env"])
        self.assertNotIn("DB_USER_PASS", metadata["plan_env"])
        self.assertIn("DB_DSN", metadata["rejected_plan_env_keys"])
        self.assertIn("DB_USER_PASS", metadata["rejected_plan_env_keys"])
        self.assertIn("PATH", metadata["env_keys"])
        self.assertIn("TNS_ADMIN", metadata["env_keys"])
        self.assertNotIn("connect AGENT_RO", rendered)
        self.assertNotIn("db-secret", rendered)
        self.assertNotIn("adw-secret-service", rendered)
        self.assertNotIn("extra-secret", rendered)


def _plan(
    *,
    command=("/opt/sqlcl/bin/sql", "-S", "-L", "-nolog"),
    env=None,
    stdin="select 1\n",
    timeout_seconds=30,
    max_output_bytes=1_048_576,
    max_error_bytes=65_536,
) -> SqlclReadOnlyExecutionPlan:
    return SqlclReadOnlyExecutionPlan(
        command=command,
        env=env or {},
        stdin=stdin,
        timeout_seconds=timeout_seconds,
        row_limit=100,
        max_output_bytes=max_output_bytes,
        max_error_bytes=max_error_bytes,
        sql_sha256="abc123",
        working_user="AGENT_RO",
        _sensitive_values=("db-secret", "adw-secret-service", "wallet-secret"),
    )


if __name__ == "__main__":
    unittest.main()

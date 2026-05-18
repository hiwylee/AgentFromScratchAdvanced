import subprocess
import unittest
from unittest.mock import patch

from agent_runtime.oracle_adw import (
    OracleAdwConfig,
    SqlclReadOnlyExecutionSettings,
    SqlclRunResult,
)
from agent_runtime.redaction import REDACTION
from agent_runtime.sql_execution import (
    FakeSqlExecutionAdapter,
    SqlExecutionRequest,
    SqlclReadOnlyAdapter,
)
from agent_runtime.sqlcl_runner import SqlclRunnerResult


class FakeSqlExecutionAdapterTests(unittest.TestCase):
    def test_fake_adapter_returns_deterministic_success(self):
        adapter = FakeSqlExecutionAdapter(
            rows=({"CUSTOMER_ID": 1, "AMOUNT": 25},),
            metadata={"profile": "unit-test"},
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))

        self.assertTrue(response.ok)
        self.assertEqual("succeeded", response.status)
        self.assertEqual("fake", response.backend)
        self.assertEqual(("CUSTOMER_ID", "AMOUNT"), response.columns)
        self.assertEqual(1, response.row_count)
        self.assertEqual("unit-test", response.backend_metadata["profile"])


class SqlclReadOnlyAdapterTests(unittest.TestCase):
    def test_sqlcl_adapter_returns_closed_response_by_default(self):
        adapter = SqlclReadOnlyAdapter(_config())

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))
        response_dict = response.to_redacted_dict()

        self.assertFalse(response.ok)
        self.assertEqual("closed", response.status)
        self.assertEqual("sqlcl", response.backend)
        self.assertEqual("real_execution_closed", response.error.code)
        self.assertFalse(response.backend_metadata["allow_real_execution"])
        self.assertEqual("closed", response.backend_metadata["execution_state"])
        self.assertNotIn("db-secret", str(response_dict))
        self.assertNotIn("adw-secret-service", str(response_dict))
        self.assertNotIn("wallet-secret", str(response_dict))

    def test_unsafe_sql_is_rejected_before_execution(self):
        called = False

        def runner(_plan):
            nonlocal called
            called = True
            return SqlclRunResult(returncode=0, stdout="[]")

        adapter = SqlclReadOnlyAdapter(_config(), runner=runner)

        response = adapter.execute(SqlExecutionRequest(sql="delete from customers"))

        self.assertFalse(response.ok)
        self.assertEqual("rejected", response.status)
        self.assertEqual("write_or_admin_sql", response.error.code)
        self.assertFalse(called)

    def test_redacted_dry_run_metadata_contains_no_credential_values(self):
        adapter = SqlclReadOnlyAdapter(
            _config(),
            settings=SqlclReadOnlyExecutionSettings(timeout_seconds=7, row_limit=42),
        )

        response = adapter.execute(SqlExecutionRequest(sql="select customer_id from customers"))
        redacted = response.to_redacted_dict()
        rendered = str(redacted)

        self.assertEqual(REDACTION, redacted["audit_metadata"]["execution"]["stdin"])
        self.assertEqual(42, redacted["backend_metadata"]["limits"]["row_limit"])
        self.assertEqual(7, redacted["backend_metadata"]["limits"]["timeout_seconds"])
        self.assertNotIn("db-secret", rendered)
        self.assertNotIn("adw-secret-service", rendered)
        self.assertNotIn("admin-secret", rendered)
        self.assertNotIn("wallet-secret", rendered)

    def test_backend_metadata_is_generic_not_sqlcl_process_shape(self):
        adapter = SqlclReadOnlyAdapter(_config())

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))
        metadata = response.backend_metadata

        self.assertEqual("sqlcl", metadata["backend"])
        self.assertIn("sql_sha256", metadata)
        self.assertIn("limits", metadata)
        self.assertNotIn("command", metadata)
        self.assertNotIn("argv", metadata)
        self.assertNotIn("stdin", metadata)
        self.assertIn("command", response.audit_metadata["execution"])
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])

    def test_runner_is_not_called_while_execution_is_closed(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            return SqlclRunResult(returncode=0, stdout="[]")

        adapter = SqlclReadOnlyAdapter(_config(), runner=runner)

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))

        self.assertEqual("closed", response.status)
        self.assertEqual([], calls)

    def test_runner_is_called_only_when_real_execution_is_explicitly_enabled(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            return SqlclRunResult(
                returncode=0,
                stdout='{"items":[{"CUSTOMER_ID":1,"AMOUNT":25}]}',
            )

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select customer_id, amount from sales"))
        response_dict = response.to_redacted_dict()
        rendered = str(response_dict)

        self.assertEqual(1, len(calls))
        self.assertTrue(response.ok)
        self.assertEqual("succeeded", response.status)
        self.assertEqual("sqlcl", response.backend)
        self.assertEqual(("CUSTOMER_ID", "AMOUNT"), response.columns)
        self.assertEqual(({"CUSTOMER_ID": 1, "AMOUNT": 25},), response.rows)
        self.assertEqual(1, response.row_count)
        self.assertEqual("executed", response.backend_metadata["execution_state"])
        self.assertTrue(response.backend_metadata["allow_real_execution"])
        self.assertNotIn("command", response.backend_metadata)
        self.assertNotIn("stdin", response.backend_metadata)
        self.assertIn("outcome", response.audit_metadata)
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assertNotIn("connect AGENT_RO", rendered)
        self.assertNotIn("select customer_id, amount from sales", rendered)
        self.assertNotIn("db-secret", rendered)
        self.assertNotIn("adw-secret-service", rendered)
        self.assertNotIn("wallet-secret", rendered)

    def test_enabled_runner_failure_returns_structured_redacted_error(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            return SqlclRunResult(
                returncode=9,
                stdout="",
                stderr="ORA-01017: invalid credentials for db-secret@adw-secret-service",
            )

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))
        response_dict = response.to_redacted_dict()
        rendered = str(response_dict)

        self.assertEqual(1, len(calls))
        self.assertFalse(response.ok)
        self.assertEqual("failed", response.status)
        self.assertEqual("sqlcl_error", response.error.code)
        self.assertEqual(9, response.error.detail["returncode"])
        self.assertIn("outcome", response.audit_metadata)
        self.assertEqual("sqlcl_error", response.audit_metadata["outcome"]["error"]["code"])
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assertNotIn("connect AGENT_RO", rendered)
        self.assertNotIn("db-secret", rendered)
        self.assertNotIn("adw-secret-service", rendered)
        self.assertNotIn("wallet-secret", rendered)

    def test_enabled_runner_timeout_result_returns_structured_redacted_error(self):
        def runner(plan):
            return SqlclRunnerResult(
                returncode=-1,
                stderr="timed out while using db-secret@adw-secret-service",
                timed_out=True,
            )

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))
        redacted = response.to_redacted_dict()
        rendered = str(redacted)

        self.assertFalse(response.ok)
        self.assertEqual("timeout", response.status)
        self.assertEqual("timeout", response.error.code)
        self.assertEqual(-1, response.error.detail["returncode"])
        self.assertEqual("timeout", response.backend_metadata["runner_status"])
        self.assertEqual("timeout", response.audit_metadata["outcome"]["error"]["code"])
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assertNotIn("connect AGENT_RO", rendered)
        self.assertNotIn("db-secret", rendered)
        self.assertNotIn("adw-secret-service", rendered)
        self.assertNotIn("wallet-secret", rendered)

    def test_enabled_runner_timeout_exception_returns_structured_redacted_error(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            raise subprocess.TimeoutExpired(
                cmd=plan.command,
                timeout=plan.timeout_seconds,
                stderr=(
                    "timed out after connect agent_ro/db-secret@adw-secret-service "
                    "using wallet-secret admin-secret"
                ),
            )

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))

        self.assertEqual(1, len(calls))
        self.assertFalse(response.ok)
        self.assertEqual("timeout", response.status)
        self.assertEqual("timeout", response.error.code)
        self.assertEqual("timeout", response.backend_metadata["runner_status"])
        self.assertEqual("timeout", response.audit_metadata["outcome"]["error"]["code"])
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assertIn("stderr", response.error.detail)
        self.assertNotIn("db-secret", response.error.detail["stderr"])
        self.assertNotIn("adw-secret-service", response.error.detail["stderr"])
        self.assertNotIn("wallet-secret", response.error.detail["stderr"])
        self.assertNotIn("admin-secret", response.error.detail["stderr"])
        self.assert_no_sqlcl_secret_leaks(response, calls[0])

    def test_enabled_runner_stdout_stream_limit_returns_redacted_failed_error(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            return SqlclRunnerResult(
                returncode=0,
                stdout="db-secret adw-secret-service wallet-secret",
                stdout_too_large=True,
                stdout_bytes=10_000,
                command=plan.command,
                env_keys=tuple(plan.env),
                timeout_seconds=plan.timeout_seconds,
            )

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))

        self.assertEqual(1, len(calls))
        self.assertFalse(response.ok)
        self.assertEqual("failed", response.status)
        self.assertEqual("output_too_large", response.error.code)
        self.assertEqual(0, response.error.detail["returncode"])
        self.assertEqual("output_too_large", response.backend_metadata["runner_status"])
        self.assertEqual(
            "output_too_large",
            response.audit_metadata["outcome"]["error"]["code"],
        )
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assert_no_sqlcl_secret_leaks(response, calls[0])

    def test_enabled_runner_stderr_stream_limit_returns_redacted_failed_error(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            return SqlclRunnerResult(
                returncode=0,
                stderr="db-secret adw-secret-service wallet-secret",
                stderr_too_large=True,
                stderr_bytes=10_000,
                command=plan.command,
                env_keys=tuple(plan.env),
                timeout_seconds=plan.timeout_seconds,
            )

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))

        self.assertEqual(1, len(calls))
        self.assertFalse(response.ok)
        self.assertEqual("failed", response.status)
        self.assertEqual("error_output_too_large", response.error.code)
        self.assertEqual(0, response.error.detail["returncode"])
        self.assertEqual(
            "error_output_too_large",
            response.backend_metadata["runner_status"],
        )
        self.assertEqual(
            "error_output_too_large",
            response.audit_metadata["outcome"]["error"]["code"],
        )
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assert_no_sqlcl_secret_leaks(response, calls[0])

    def test_enabled_runner_pre_output_oserror_returns_redacted_failed_error(self):
        calls = []

        def runner(plan):
            calls.append(plan)
            raise OSError("db-secret adw-secret-service wallet-secret")

        adapter = SqlclReadOnlyAdapter(
            _config(),
            allow_real_execution=True,
            runner=runner,
        )

        response = adapter.execute(SqlExecutionRequest(sql="select * from customers"))

        self.assertEqual(1, len(calls))
        self.assertFalse(response.ok)
        self.assertEqual("failed", response.status)
        self.assertEqual("runner_error", response.error.code)
        self.assertEqual("runner_error", response.backend_metadata["runner_status"])
        self.assertEqual("runner_error", response.audit_metadata["outcome"]["error"]["code"])
        self.assertEqual(REDACTION, response.audit_metadata["execution"]["stdin"])
        self.assert_no_sqlcl_secret_leaks(response, calls[0])

    def test_default_runner_gets_minimal_runtime_env_without_credentials(self):
        calls = []

        def fake_run_sqlcl_plan(plan, *, base_env):
            calls.append((plan, base_env))
            return SqlclRunResult(
                returncode=0,
                stdout='{"items":[{"CUSTOMER_ID":1}]}',
            )

        with patch.dict(
            "os.environ",
            {
                "PATH": "/bin:/java/bin",
                "JAVA_HOME": "/java",
                "HOME": "/home/operator",
                "DB_USER_PASS": "db-secret",
                "DB_DSN": "adw-secret-service",
                "ADMIN_USER_PASS": "admin-secret",
            },
            clear=True,
        ):
            with patch("agent_runtime.sql_execution.run_sqlcl_plan", fake_run_sqlcl_plan):
                adapter = SqlclReadOnlyAdapter(
                    _config(),
                    allow_real_execution=True,
                )
                response = adapter.execute(
                    SqlExecutionRequest(sql="select customer_id from customers")
                )

        self.assertTrue(response.ok)
        self.assertEqual(1, len(calls))
        base_env = calls[0][1]
        self.assertEqual("/bin:/java/bin", base_env["PATH"])
        self.assertEqual("/java", base_env["JAVA_HOME"])
        self.assertEqual("/home/operator", base_env["HOME"])
        self.assertNotIn("DB_USER_PASS", base_env)
        self.assertNotIn("DB_DSN", base_env)
        self.assertNotIn("ADMIN_USER_PASS", base_env)

    def assert_no_sqlcl_secret_leaks(self, response, plan):
        for rendered in (str(response.to_redacted_dict()), str(response.audit_metadata)):
            self.assertNotIn(plan.stdin, rendered)
            self.assertNotIn("connect AGENT_RO", rendered)
            self.assertNotIn("connect agent_ro", rendered)
            self.assertNotIn("admin-secret", rendered)
            self.assertNotIn("db-secret", rendered)
            self.assertNotIn("adw-secret-service", rendered)
            self.assertNotIn("wallet-secret", rendered)


def _config() -> OracleAdwConfig:
    return OracleAdwConfig(
        sqlcl_path="/opt/sqlcl/bin/sql",
        admin_user_pass="admin-secret",
        db_user="agent_ro",
        db_user_pass="db-secret",
        db_dsn="adw-secret-service",
        db_wallet_path="/wallet",
        db_wallet_pass="wallet-secret",
    )


if __name__ == "__main__":
    unittest.main()

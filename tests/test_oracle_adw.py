import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_runtime.oracle_adw import (
    OracleAdwConfig,
    OracleAdwReadOnlyConnector,
    SCHEMA_INTROSPECTION_QUERIES,
    SqlclRunResult,
    validate_read_only_sql,
    verify_sqlcl,
    verify_wallet_paths,
)
from agent_runtime.redaction import REDACTION


class OracleAdwConfigTests(unittest.TestCase):
    def test_config_loads_from_env_and_redacts_secrets(self):
        config = OracleAdwConfig.from_env(
            {
                "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                "ADMIN_USER": "admin",
                "ADMIN_USER_PASS": "admin-secret",
                "DB_USER": "readonly",
                "DB_USER_PASS": "db-secret",
                "DB_DSN": "adw_service_high",
                "DB_WALLET_PATH": "/wallet",
                "DB_WALLET_FILE": "/wallet.zip",
                "DB_WALLET_PASS": "wallet-secret",
            }
        )

        self.assertEqual("/opt/sqlcl/bin/sql", config.sqlcl_path)
        status = config.redacted_status()
        self.assertTrue(status["db_user_pass_configured"])
        self.assertNotIn("db-secret", str(status))

        redacted = config.to_redacted_dict()
        self.assertEqual(REDACTION, redacted["admin_user_pass"])
        self.assertEqual(REDACTION, redacted["db_user_pass"])
        self.assertEqual(REDACTION, redacted["db_wallet_pass"])
        self.assertEqual(REDACTION, redacted["db_dsn"])


class OracleAdwSqlclTests(unittest.TestCase):
    def test_sqlcl_verification_uses_injected_runner_and_redacts_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            sqlcl = Path(tmp) / "sql"
            sqlcl.write_text("#!/bin/sh\n", encoding="utf-8")
            sqlcl.chmod(sqlcl.stat().st_mode | stat.S_IXUSR)
            previous_secret = os.environ.get("DB_USER_PASS")
            os.environ["DB_USER_PASS"] = "leaked-secret"

            seen_commands: list[list[str]] = []

            def runner(command: list[str]) -> SqlclRunResult:
                seen_commands.append(command)
                return SqlclRunResult(
                    returncode=0,
                    stdout="SQLcl 24.1 leaked-secret\n",
                )

            try:
                status = verify_sqlcl(
                    OracleAdwConfig(sqlcl_path=str(sqlcl)),
                    runner=runner,
                )
            finally:
                if previous_secret is None:
                    os.environ.pop("DB_USER_PASS", None)
                else:
                    os.environ["DB_USER_PASS"] = previous_secret

            self.assertTrue(status.ok)
            self.assertEqual([[str(sqlcl), "-version"]], seen_commands)
            redacted = status.to_redacted_dict()
            self.assertEqual("SQLcl 24.1 [REDACTED]", redacted["version"])
            self.assertNotIn("leaked-secret", str(redacted))

    def test_sqlcl_verification_reports_missing_without_running(self):
        called = False

        def runner(command: list[str]) -> SqlclRunResult:
            nonlocal called
            called = True
            return SqlclRunResult(returncode=0)

        status = verify_sqlcl(
            OracleAdwConfig(sqlcl_path="/does/not/exist/sql"),
            runner=runner,
        )

        self.assertFalse(status.ok)
        self.assertFalse(status.exists)
        self.assertFalse(status.version_checked)
        self.assertFalse(called)

    def test_sqlcl_verification_reports_timeout_as_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            sqlcl = Path(tmp) / "sql"
            sqlcl.write_text("#!/bin/sh\n", encoding="utf-8")
            sqlcl.chmod(sqlcl.stat().st_mode | stat.S_IXUSR)

            def runner(command: list[str]) -> SqlclRunResult:
                raise subprocess.TimeoutExpired(command, timeout=10)

            status = verify_sqlcl(OracleAdwConfig(sqlcl_path=str(sqlcl)), runner=runner)

            self.assertFalse(status.ok)
            self.assertTrue(status.version_checked)
            self.assertEqual("sqlcl_version_check_failed:TimeoutExpired", status.error)


class OracleAdwWalletTests(unittest.TestCase):
    def test_wallet_checks_only_report_path_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_dir = tmp_path / "wallet"
            wallet_dir.mkdir()
            wallet_file = tmp_path / "wallet.zip"
            wallet_file.write_text("do-not-read-this-secret", encoding="utf-8")

            status = verify_wallet_paths(
                OracleAdwConfig(
                    db_wallet_path=str(wallet_dir),
                    db_wallet_file=str(wallet_file),
                    db_wallet_pass="wallet-secret",
                )
            )

            self.assertTrue(status.ok)
            self.assertTrue(status.wallet_path_is_dir)
            self.assertTrue(status.wallet_file_is_file)
            redacted = status.to_redacted_dict()
            self.assertNotIn("do-not-read-this-secret", str(redacted))
            self.assertNotIn("wallet-secret", str(redacted))


class OracleAdwReadOnlyPolicyTests(unittest.TestCase):
    def test_allows_select_with_trailing_semicolon_and_schema_queries(self):
        self.assertTrue(validate_read_only_sql("select * from customers;").allowed)
        self.assertTrue(
            validate_read_only_sql(
                "with recent_orders as (select * from orders) "
                "select * from recent_orders"
            ).allowed
        )
        for query in SCHEMA_INTROSPECTION_QUERIES.values():
            with self.subTest(query=query):
                self.assertTrue(validate_read_only_sql(query).allowed)

    def test_blocks_writes_and_ddl_even_inside_with_clause(self):
        blocked = [
            "delete from customers",
            "update customers set status = 'x'",
            "insert into customers(id) values (1)",
            "merge into customers c using updates u on (c.id = u.id)",
            "drop table customers",
            "grant select on customers to someone",
            "with changed as (update customers set status = 'x') select * from changed",
        ]

        for sql in blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("write_or_admin_sql", result.code)

    def test_blocks_select_for_update_plsql_dblink_and_multi_statement(self):
        blocked = {
            "select * from customers for update": "select_for_update",
            "begin null; end;": "unsafe_multi_statement",
            "declare x number; begin null; end;": "unsafe_multi_statement",
            "select * from customers@prod_link": "database_link",
            "select * from a; select * from b": "unsafe_multi_statement",
        }

        for sql, code in blocked.items():
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual(code, result.code)

    def test_blocks_sqlcl_slash_blocks(self):
        result = validate_read_only_sql("begin\nnull;\nend;\n/")

        self.assertFalse(result.allowed)
        self.assertEqual("procedural_block", result.code)

        trailing_comment = validate_read_only_sql(
            "select * from dual\n/ -- trailing comment\nhost echo SQLCL_HOST_RAN"
        )
        self.assertFalse(trailing_comment.allowed)
        self.assertEqual("procedural_block", trailing_comment.code)

        slash_lines = [
            "select 1 from dual\n/ anything",
            "select 1 from dual\n/-- trailing comment",
            "select 1 from dual\n/** block comment */",
            "select 1 from dual\n/anything",
            "select 1 from dual\n/! echo SQLCL_HOST_RAN",
            "select '\n/\nhost echo SQLCL_HOST_RAN",
            "select '\n/! echo SQLCL_HOST_RAN",
            'select "\n/\nhost echo SQLCL_HOST_RAN',
        ]
        for sql in slash_lines:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("procedural_block", result.code)

    def test_blocks_sqlcl_blank_lines_and_command_lines(self):
        blank_line = validate_read_only_sql("select * from dual\n\nhost echo SQLCL_HOST_RAN")
        self.assertFalse(blank_line.allowed)
        self.assertEqual("sqlcl_blank_line", blank_line.code)

        commands = [
            "host echo SQLCL_HOST_RAN",
            "hos echo SQLCL_HOST_RAN",
            "connect readonly/sneaky",
            "conne readonly/sneaky",
            "@script.sql",
            "! echo SQLCL_HOST_RAN",
            "select 1\n.\nhos echo SQLCL_HOST_RAN",
            "select 1\n.\nconne nobody/nope",
        ]
        for sql in commands:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("sqlcl_command", result.code)

    def test_blocks_resource_heavy_hints_but_ignores_strings_and_comments(self):
        blocked = [
            "select /*+ parallel(8) */ * from customers",
            "select /*+ full(customers) */ * from customers",
            "select /*+ parallel_index(customers customers_ix 8) */ * from customers",
            "select --+ parallel(8)\n * from customers",
            "select --+ parallel_index(customers customers_ix 8)\n * from customers",
        ]

        for sql in blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("resource_heavy_hint", result.code)

        allowed = validate_read_only_sql(
            "select 'delete from x; user@example.com' as sample from dual"
        )
        self.assertTrue(allowed.allowed)
        hint_text = validate_read_only_sql(
            "select '/*+ parallel(8) */' as sample from dual"
        )
        self.assertTrue(hint_text.allowed)

    def test_blocks_package_and_unallowlisted_function_calls(self):
        blocked = [
            "select admin_pkg.delete_all() from dual",
            "select admin_pkg.delete_all/*x*/() from dual",
            "select risky_function(customer_id) from customers",
            "select risky_function/*x*/(customer_id) from customers",
            'select "ADMIN_PKG"."DELETE_ALL"() from dual',
            'select "ADMIN_PKG".COUNT() from dual',
            'select ADMIN_PKG."COUNT"() from dual',
            'select "1PKG".COUNT() from dual',
            'select "ADMIN PKG".COUNT() from dual',
            'select ADMIN_PKG."CO UNT"() from dual',
            'select "RISKY_FUNCTION"(customer_id) from customers',
            'select "RISKY FUNCTION"(customer_id) from customers',
            'select "RISKY--FUNCTION"(customer_id) from customers',
            'select "RISKY/*FUNCTION*/"(customer_id) from customers',
            'select "RISKY FUNCTION"/*x*/(customer_id) from customers',
            'select "ADMIN--PKG"."DELETE_ALL"() from dual',
            'select "ADMIN/*PKG*/"."DELETE_ALL"() from dual',
        ]

        for sql in blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("function_call_not_allowed", result.code)

        dotted_blocked = [
            "select admin_pkg.delete_all from dual",
            "select dbms_random.value from dual",
            'select "DBMS--RANDOM".VALUE from dual',
            'select "DBMS/*RANDOM*/".VALUE from dual',
        ]
        for sql in dotted_blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("dotted_reference_not_allowed", result.code)

        nested_scope_blocked = [
            "select admin_pkg.delete_all from dual where exists (select 1 from customers admin_pkg)",
            "select dbms_random.value from dual where exists (select 1 from customers dbms_random)",
            "select c.customer_id from customers c where exists (select 1 from orders o)",
        ]
        for sql in nested_scope_blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("nested_dotted_reference_not_allowed", result.code)

        compound_scope_blocked = [
            "select dbms_random.value from dual union all select 1 from customers dbms_random",
            "select admin_pkg.delete_all from dual union select 1 from customers admin_pkg",
            "select c.customer_id from customers c intersect select o.customer_id from orders o",
        ]
        for sql in compound_scope_blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("compound_dotted_reference_not_allowed", result.code)

        multipart_blocked = [
            "select s.admin_pkg.delete_all from dual s",
            "select s.dbms_random.value from dual s",
            "select schema.customers.customer_id from schema.customers",
            'select "S--"."ADMIN_PKG"."DELETE_ALL" from dual',
            'select "S/*x*/"."ADMIN_PKG"."DELETE_ALL" from dual',
        ]
        for sql in multipart_blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("multi_part_dotted_reference_not_allowed", result.code)

        sequence_blocked = [
            "select audit_seq.nextval from dual audit_seq",
            'select audit_seq."NEXTVAL" from dual audit_seq',
        ]
        for sql in sequence_blocked:
            with self.subTest(sql=sql):
                result = validate_read_only_sql(sql)
                self.assertFalse(result.allowed)
                self.assertEqual("sequence_mutation_not_allowed", result.code)

        self.assertTrue(validate_read_only_sql("select count(*) from customers").allowed)
        self.assertTrue(validate_read_only_sql("select coalesce(region, 'NA') from customers").allowed)
        self.assertTrue(validate_read_only_sql("select c.customer_id from customers c").allowed)
        self.assertTrue(validate_read_only_sql("select customers.customer_id from customers").allowed)

    def test_connector_never_executes_real_db_in_skeleton(self):
        connector = OracleAdwReadOnlyConnector(OracleAdwConfig(db_user="readonly"))

        self.assertTrue(connector.validate_query("select * from dual").allowed)
        with self.assertRaises(NotImplementedError):
            connector.execute_read_only_query("select * from dual")
        with self.assertRaises(ValueError):
            connector.execute_read_only_query("delete from dual")


if __name__ == "__main__":
    unittest.main()

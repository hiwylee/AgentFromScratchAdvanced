import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_runtime.cli import ADW_SMOKE_SQL, main
from agent_runtime.intent import UserIntent
from agent_runtime.loop import AgentLoop
from agent_runtime.monitor import latest_status
from agent_runtime.oracle_adw import SqlclStatus
from agent_runtime.sql_execution import SqlExecutionResponse
from agent_runtime.sqlcl_runner import SqlclRunnerResult
from agent_runtime.tools import ToolParameter, ToolRegistry, ToolSpec, default_tool_registry
from agent_runtime.types import Action, Budget, CancellationToken


class RuntimeControlTests(unittest.TestCase):
    def test_zero_max_steps_stops_after_intent_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=0, timeout_seconds=30),
            )

            result = loop.run("summarize this repository")

            self.assertEqual("general", result.intent["intent_type"])
            self.assertEqual("final_answer", result.action["kind"])
            self.assertEqual("max_steps_exceeded", result.action["reason"])
            self.assertIn("step limit", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("stopped", status["state"])

            event_names = _event_names(Path(result.events_path))
            self.assertIn("intent_analyzed", event_names)
            self.assertNotIn("model_action_selected", event_names)

    def test_one_max_step_allows_the_milestone_one_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=1, timeout_seconds=30),
            )

            result = loop.run("summarize this repository")

            self.assertEqual("final_answer", result.action["kind"])
            self.assertEqual("completed", latest_status(tmp_path / "runs")["state"])
            event_names = _event_names(Path(result.events_path))
            self.assertIn("model_action_selected", event_names)
            self.assertIn("observation_recorded", event_names)

    def test_zero_timeout_times_out_before_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=4, timeout_seconds=0),
            )

            result = loop.run("summarize this repository")

            self.assertEqual({}, result.intent)
            self.assertEqual("timeout_seconds_exceeded", result.action["reason"])
            self.assertIn("timed out", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("timed_out", status["state"])
            self.assertEqual(["run_finished"], _event_names(Path(result.events_path)))

    def test_pre_cancelled_token_cancels_before_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = CancellationToken()
            token.cancel("user_requested")
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                cancellation_token=token,
            )

            result = loop.run("summarize this repository")

            self.assertEqual({}, result.intent)
            self.assertEqual("user_requested", result.action["reason"])
            self.assertIn("cancelled", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("cancelled", status["state"])

    def test_cancellation_during_action_selection_stops_before_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = CancellationToken()
            loop = AgentLoop(
                model=CancelDuringActionSelection(token),
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                cancellation_token=token,
            )

            result = loop.run("summarize this repository")

            self.assertEqual("final_answer", result.action["kind"])
            self.assertEqual("model_requested_cancel", token.reason)
            self.assertIn("cancelled", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("cancelled", status["state"])

            event_names = _event_names(Path(result.events_path))
            self.assertIn("model_action_selected", event_names)
            self.assertNotIn("observation_recorded", event_names)

    def test_inspect_schema_action_runs_read_only_mock_tool_and_records_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=2, timeout_seconds=30),
            )

            result = loop.run("inspect oracle schema")

            self.assertEqual("inspect_schema", result.action["kind"])
            event_names = _event_names(Path(result.events_path))
            self.assertIn("tool_started", event_names)
            self.assertIn("tool_completed", event_names)
            self.assertIn("observation_recorded", event_names)

            observations = [
                event["data"]["observation"]
                for event in _events(Path(result.events_path))
                if event["event"] == "observation_recorded"
            ]
            self.assertEqual("tool:mock_schema_context", observations[-1]["source"])
            self.assertEqual("completed", observations[-1]["content"]["tool_result"]["state"])

    def test_schema_context_observation_selects_sh_tables_without_sql_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=2, timeout_seconds=30),
            )

            result = loop.run("show oracle adw revenue by product by month")

            self.assertEqual("ask_clarification", result.action["kind"])
            observations = [
                event["data"]["observation"]
                for event in _events(Path(result.events_path))
                if event["event"] == "observation_recorded"
            ]
            tool_result = observations[-1]["content"]["tool_result"]
            output = tool_result["output"]
            self.assertEqual("tool:mock_schema_context", observations[-1]["source"])
            self.assertEqual("completed", tool_result["state"])
            self.assertFalse(output["sql_generation_enabled"])
            self.assertFalse(output["sql_execution_enabled"])
            self.assertIn("SQL generation remains closed", output["next_action"])
            self.assertIn("SH.SALES", output["selected_table_ids"])
            self.assertIn("SH.PRODUCTS", output["selected_table_ids"])
            self.assertIn("SH.TIMES", output["selected_table_ids"])
            query_plan = output["query_plan"]
            self.assertEqual("agent-runtime.query-plan.v1", query_plan["schema_version"])
            self.assertEqual("planned", query_plan["status"])
            self.assertTrue(query_plan["policy_validation"]["allowed"])
            self.assertFalse(query_plan["execution"]["enabled"])
            self.assertEqual("not_executed", query_plan["execution"]["status"])
            self.assertNotIn("rows", query_plan["execution"])
            self.assertNotIn("result_rows", query_plan)
            result_explanation = output["result_explanation"]
            self.assertEqual("agent-runtime.result-explanation.v1", result_explanation["schema_version"])
            self.assertEqual("succeeded", result_explanation["status"])
            self.assertEqual("fake/deterministic", result_explanation["source"])
            self.assertFalse(result_explanation["real_database_execution"])
            self.assertEqual("fake", result_explanation["sql_execution_backend"])
            self.assertEqual("fake", result_explanation["execution_response"]["backend"])
            self.assertFalse(result_explanation["adapter_response_metadata"]["oracle_adw_execution"])
            self.assertFalse(result_explanation["adapter_response_metadata"]["sqlcl_execution"])
            output_without_plan = dict(output)
            output_without_plan.pop("query_plan")
            output_without_plan.pop("result_explanation")
            serialized_output = json.dumps(output_without_plan)
            self.assertNotIn("SELECT ", serialized_output.upper())
            self.assertNotIn(" FROM ", serialized_output.upper())

    def test_schema_context_observation_omits_result_explanation_for_ambiguous_region_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=2, timeout_seconds=30),
            )

            result = loop.run("Show monthly revenue by region from the Oracle ADW SH schema.")

            self.assertEqual("ask_clarification", result.action["kind"])
            observations = [
                event["data"]["observation"]
                for event in _events(Path(result.events_path))
                if event["event"] == "observation_recorded"
            ]
            output = observations[-1]["content"]["tool_result"]["output"]
            self.assertEqual("clarification_required", output["query_plan"]["status"])
            self.assertNotIn("result_explanation", output)

    def test_cli_ask_schema_context_records_observation_without_sql_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "ask",
                        "show oracle adw revenue by product by month",
                        "--model-provider",
                        "mock",
                        "--run-dir",
                        str(tmp_path / "runs"),
                        "--audit-log",
                        str(tmp_path / "audit.jsonl"),
                        "--max-steps",
                        "2",
                    ]
                )

            payload = json.loads(output.getvalue())
            observations = [
                event["data"]["observation"]
                for event in _events(Path(payload["events_path"]))
                if event["event"] == "observation_recorded"
            ]
            tool_result = observations[-1]["content"]["tool_result"]
            schema_output = tool_result["output"]
            self.assertEqual(0, exit_code)
            self.assertEqual("tool:mock_schema_context", observations[-1]["source"])
            self.assertFalse(schema_output["sql_generation_enabled"])
            self.assertFalse(schema_output["sql_execution_enabled"])
            self.assertIn("SH.SALES", schema_output["selected_table_ids"])
            self.assertIn("SH.PRODUCTS", schema_output["selected_table_ids"])
            self.assertIn("SH.TIMES", schema_output["selected_table_ids"])
            query_plan = schema_output["query_plan"]
            self.assertEqual("agent-runtime.query-plan.v1", query_plan["schema_version"])
            self.assertEqual("planned", query_plan["status"])
            self.assertTrue(query_plan["policy_validation"]["allowed"])
            self.assertFalse(query_plan["execution"]["enabled"])
            self.assertEqual("not_executed", query_plan["execution"]["status"])
            self.assertNotIn("rows", query_plan["execution"])
            result_explanation = schema_output["result_explanation"]
            self.assertFalse(result_explanation["real_database_execution"])
            self.assertEqual("fake", result_explanation["sql_execution_backend"])
            self.assertFalse(result_explanation["adapter_response_metadata"]["sqlcl_execution"])

    def test_tool_step_respects_max_step_budget_before_running_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=1, timeout_seconds=30),
            )

            result = loop.run("inspect oracle schema")

            self.assertEqual("inspect_schema", result.action["kind"])
            self.assertIn("step limit", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("stopped", status["state"])

            event_names = _event_names(Path(result.events_path))
            self.assertIn("model_action_selected", event_names)
            self.assertNotIn("tool_started", event_names)
            self.assertNotIn("observation_recorded", event_names)

    def test_loop_passes_explicit_retry_limit_to_tool_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            attempts = []
            registry = ToolRegistry()

            def flaky_schema_context(args):
                attempts.append(args)
                if len(attempts) == 1:
                    raise RuntimeError("temporary")
                return {"ok": True}

            registry.register(
                ToolSpec(
                    name="mock_schema_context",
                    description="Flaky schema context.",
                    parameters=(ToolParameter(name="required_context", type="array", required=False),),
                ),
                flaky_schema_context,
            )
            loop = AgentLoop(
                tool_registry=registry,
                tool_max_attempts=2,
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=2, timeout_seconds=30),
            )

            result = loop.run("inspect oracle schema")

            observations = [
                event["data"]["observation"]
                for event in _events(Path(result.events_path))
                if event["event"] == "observation_recorded"
            ]
            self.assertEqual(2, len(attempts))
            self.assertEqual([{"required_context": ["oracle_adw_schema"]}] * 2, attempts)
            self.assertEqual(2, observations[-1]["content"]["tool_result"]["attempts"])
            self.assertEqual("completed", observations[-1]["content"]["tool_result"]["state"])

    def test_loop_tool_monitor_and_audit_events_redact_arguments_and_outputs(self):
        previous = os.environ.get("RUNTIME_TOOL_PASSWORD")
        os.environ["RUNTIME_TOOL_PASSWORD"] = "runtime-tool-secret"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                registry = ToolRegistry()
                registry.register(
                    ToolSpec(
                        name="mock_schema_context",
                        description="Secret echo for redaction coverage.",
                        parameters=(ToolParameter(name="required_context", type="array", required=False),),
                    ),
                    lambda args: {
                        "requested": args["required_context"],
                        "password": "runtime-tool-secret",
                    },
                )
                loop = AgentLoop(
                    model=SecretInspectSchemaModel(),
                    tool_registry=registry,
                    run_root=tmp_path / "runs",
                    audit_path=tmp_path / "audit.jsonl",
                    budget=Budget(max_steps=2, timeout_seconds=30),
                )

                result = loop.run("inspect oracle schema")

                serialized = (
                    Path(result.events_path).read_text(encoding="utf-8")
                    + Path(result.audit_path).read_text(encoding="utf-8")
                )
                self.assertNotIn("runtime-tool-secret", serialized)
                self.assertIn("[REDACTED]", serialized)
        finally:
            if previous is None:
                os.environ.pop("RUNTIME_TOOL_PASSWORD", None)
            else:
                os.environ["RUNTIME_TOOL_PASSWORD"] = previous

    def test_operator_adw_smoke_requires_explicit_live_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()

            with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "operator",
                            "adw-smoke",
                            "--audit-log",
                            str(Path(tmp) / "audit.jsonl"),
                        ]
                    )

            payload = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual("confirmation_required", payload["state"])
            self.assertFalse(payload["live_database_execution"])
            self.assertFalse(payload["live_execution_requested"])
            self.assertFalse(payload["live_execution_attempted"])
            adapter_cls.assert_not_called()
            audit_text = (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("operator.adw_smoke", audit_text)
            self.assertIn("operator_context", audit_text)

    def test_operator_adw_smoke_rejects_missing_config_without_secret_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "relative/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw-secret-service",
                },
                clear=True,
            ):
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "operator",
                            "adw-smoke",
                            "--confirm-live-adw-smoke",
                            "--audit-log",
                            str(audit_path),
                        ]
                    )

            rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("rejected", payload["state"])
            self.assertEqual("sqlcl_path_must_be_absolute", payload["error"]["code"])
            self.assertFalse(payload["live_database_execution"])
            self.assertNotIn("db-secret", rendered)
            self.assertNotIn("adw-secret-service", rendered)

    def test_operator_adw_smoke_runs_fixed_sql_through_live_adapter_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"
            calls = []

            class FakeSmokeAdapter:
                def __init__(self, config, *, settings, allow_real_execution):
                    calls.append(
                        {
                            "config": config,
                            "settings": settings,
                            "allow_real_execution": allow_real_execution,
                        }
                    )

                def execute(self, request):
                    calls.append({"request": request})
                    return SqlExecutionResponse(
                        ok=True,
                        status="succeeded",
                        backend="sqlcl",
                        columns=("SMOKE_CHECK",),
                        rows=({"SMOKE_CHECK": 1},),
                        row_count=1,
                        backend_metadata={
                            "sql_sha256": "smoke-sha",
                            "allow_real_execution": True,
                            "execution_state": "executed",
                            "limits": {"row_limit": 1},
                        },
                        audit_metadata={
                            "event": "sql_execution.read_only.executed",
                            "execution": {"stdin": "[REDACTED]"},
                        },
                    )

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw-secret-service",
                    "DB_WALLET_PATH": str(wallet_path),
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.SqlclReadOnlyAdapter", FakeSmokeAdapter):
                    with patch(
                        "agent_runtime.cli.verify_sqlcl",
                        return_value=SqlclStatus(
                            configured_path="/opt/sqlcl/bin/sql",
                            resolved_path="/opt/sqlcl/bin/sql",
                            exists=True,
                            executable=True,
                            version_checked=True,
                            ok=True,
                            version="SQLcl test",
                        ),
                    ):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-smoke",
                                    "--confirm-live-adw-smoke",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            payload = json.loads(output.getvalue())
            rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
            self.assertEqual(0, exit_code)
            self.assertEqual("succeeded", payload["state"])
            self.assertTrue(payload["live_database_execution"])
            self.assertTrue(calls[0]["allow_real_execution"])
            self.assertEqual(1, calls[0]["settings"].row_limit)
            self.assertEqual(ADW_SMOKE_SQL, calls[1]["request"].sql)
            self.assertEqual("operator_live_adw_smoke", calls[1]["request"].purpose)
            self.assertIn("operator.adw_smoke", audit_path.read_text(encoding="utf-8"))
            self.assertNotIn("db-secret", rendered)
            self.assertNotIn("adw-secret-service", rendered)

    def test_operator_adw_smoke_requires_wallet_tns_alias_and_sqlcl_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()

            cases = [
                (
                    {
                        "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                        "DB_USER": "AGENT_RO",
                        "DB_USER_PASS": "db-secret",
                        "DB_DSN": "(description=(address=secret))",
                        "DB_WALLET_PATH": str(wallet_path),
                    },
                    "db_dsn_must_be_tns_alias",
                    False,
                ),
                (
                    {
                        "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                        "DB_USER": "AGENT_RO",
                        "DB_USER_PASS": "db-secret",
                        "DB_DSN": "adw_secret_service",
                        "DB_WALLET_PATH": str(wallet_path),
                    },
                    "sqlcl_verification_failed",
                    True,
                ),
            ]

            for index, (env, expected_code, expect_verify) in enumerate(cases):
                with self.subTest(expected_code=expected_code):
                    output = io.StringIO()
                    audit_path = tmp_path / f"audit-{index}.jsonl"
                    verify_status = SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True,
                        executable=True,
                        version_checked=True,
                        ok=False,
                        error="sqlcl_version_check_failed",
                    )
                    with patch.dict(os.environ, env, clear=True):
                        with patch(
                            "agent_runtime.cli.verify_sqlcl",
                            return_value=verify_status,
                        ) as verify:
                            with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                                with redirect_stdout(output):
                                    exit_code = main(
                                        [
                                            "operator",
                                            "adw-smoke",
                                            "--confirm-live-adw-smoke",
                                            "--audit-log",
                                            str(audit_path),
                                        ]
                                    )

                    payload = json.loads(output.getvalue())
                    rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
                    self.assertEqual(1, exit_code)
                    self.assertEqual("rejected", payload["state"])
                    self.assertEqual(expected_code, payload["error"]["code"])
                    self.assertTrue(payload["live_execution_requested"])
                    self.assertFalse(payload["live_execution_attempted"])
                    self.assertEqual(expect_verify, verify.called)
                    adapter_cls.assert_not_called()
                    self.assertNotIn("db-secret", rendered)
                    self.assertNotIn("(description=(address=secret))", rendered)

    def test_operator_adw_smoke_rejects_invalid_limits_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                    "DB_WALLET_PATH": str(wallet_path),
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.verify_sqlcl") as verify:
                    with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-smoke",
                                    "--confirm-live-adw-smoke",
                                    "--max-output-bytes",
                                    "10",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            payload = json.loads(output.getvalue())
            rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
            self.assertEqual(1, exit_code)
            self.assertEqual("invalid_max_output_bytes", payload["error"]["code"])
            self.assertTrue(payload["live_execution_requested"])
            self.assertFalse(payload["live_execution_attempted"])
            verify.assert_not_called()
            adapter_cls.assert_not_called()
            self.assertNotIn("db-secret", rendered)

    def test_operator_adw_query_requires_explicit_live_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"

            with patch("agent_runtime.cli.verify_sqlcl") as verify:
                with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                    with redirect_stdout(output):
                        exit_code = main(
                            [
                                "operator",
                                "adw-query",
                                "--sql",
                                "select customer_id from customers",
                                "--audit-log",
                                str(audit_path),
                            ]
                        )

            payload = json.loads(output.getvalue())
            audit_text = audit_path.read_text(encoding="utf-8")
            self.assertEqual(2, exit_code)
            self.assertEqual("confirmation_required", payload["state"])
            self.assertFalse(payload["live_execution_requested"])
            verify.assert_not_called()
            adapter_cls.assert_not_called()
            self.assertIn("operator.adw_query", audit_text)

    def test_operator_adw_query_rejects_unsafe_sql_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                    "DB_WALLET_PATH": str(Path(tmp) / "wallet"),
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.verify_sqlcl") as verify:
                    with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-query",
                                    "--confirm-live-adw-query",
                                    "--sql",
                                    "delete from customers where password = 'db-secret'",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("rejected", payload["state"])
            self.assertEqual("write_or_admin_sql", payload["policy"]["code"])
            self.assertTrue(payload["live_execution_requested"])
            self.assertFalse(payload["live_execution_attempted"])
            verify.assert_not_called()
            adapter_cls.assert_not_called()
            self.assertNotIn("delete from customers", rendered)
            self.assertNotIn("db-secret", rendered)

    def test_operator_adw_query_rejects_sql_policy_cases_before_verification(self):
        unsafe_sql = [
            "select * from customers for update",
            "select * from customers; select * from products",
            "host echo unsafe",
            "@script.sql",
            "select dbms_lock.sleep(1) from dual",
            "select * from dual@prod",
        ]

        for sql in unsafe_sql:
            with self.subTest(sql=sql):
                with tempfile.TemporaryDirectory() as tmp:
                    output = io.StringIO()
                    audit_path = Path(tmp) / "audit.jsonl"
                    with patch("agent_runtime.cli.verify_sqlcl") as verify:
                        with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                            with redirect_stdout(output):
                                exit_code = main(
                                    [
                                        "operator",
                                        "adw-query",
                                        "--confirm-live-adw-query",
                                        "--sql",
                                        sql,
                                        "--audit-log",
                                        str(audit_path),
                                    ]
                                )

                    payload = json.loads(output.getvalue())
                    rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
                    self.assertEqual(1, exit_code)
                    self.assertEqual("rejected", payload["state"])
                    self.assertFalse(payload["policy"]["allowed"])
                    self.assertFalse(payload["live_execution_attempted"])
                    verify.assert_not_called()
                    adapter_cls.assert_not_called()
                    self.assertNotIn(sql, rendered)

    def test_operator_adw_query_runs_read_only_sql_through_live_adapter_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"
            sql_path = tmp_path / "query.sql"
            sql_path.write_text("select customer_id from customers", encoding="utf-8")
            calls = []

            class FakeQueryAdapter:
                def __init__(self, config, *, settings, allow_real_execution):
                    calls.append(
                        {
                            "config": config,
                            "settings": settings,
                            "allow_real_execution": allow_real_execution,
                        }
                    )

                def execute(self, request):
                    calls.append({"request": request})
                    return SqlExecutionResponse(
                        ok=True,
                        status="succeeded",
                        backend="sqlcl",
                        columns=("CUSTOMER_ID",),
                        rows=({"CUSTOMER_ID": 1},),
                        row_count=1,
                        backend_metadata={
                            "sql_sha256": "query-sha",
                            "allow_real_execution": True,
                            "execution_state": "executed",
                            "limits": {"row_limit": 25},
                        },
                        audit_metadata={
                            "event": "sql_execution.read_only.executed",
                            "execution": {"stdin": "[REDACTED]"},
                        },
                    )

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                    "DB_WALLET_PATH": str(wallet_path),
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.SqlclReadOnlyAdapter", FakeQueryAdapter):
                    with patch(
                        "agent_runtime.cli.verify_sqlcl",
                        return_value=SqlclStatus(
                            configured_path="/opt/sqlcl/bin/sql",
                            resolved_path="/opt/sqlcl/bin/sql",
                            exists=True,
                            executable=True,
                            version_checked=True,
                            ok=True,
                            version="SQLcl test",
                        ),
                    ):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-query",
                                    "--confirm-live-adw-query",
                                    "--sql-file",
                                    str(sql_path),
                                    "--row-limit",
                                    "25",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            payload = json.loads(output.getvalue())
            audit_text = audit_path.read_text(encoding="utf-8")
            rendered = output.getvalue() + audit_text
            self.assertEqual(0, exit_code)
            self.assertEqual("succeeded", payload["state"])
            self.assertTrue(payload["live_execution_attempted"])
            self.assertTrue(payload["live_execution_succeeded"])
            self.assertEqual(({"CUSTOMER_ID": 1},), tuple(payload["response"]["rows"]))
            self.assertTrue(calls[0]["allow_real_execution"])
            self.assertEqual(25, calls[0]["settings"].row_limit)
            self.assertEqual("select customer_id from customers", calls[1]["request"].sql)
            self.assertEqual("operator_live_adw_read_only_query", calls[1]["request"].purpose)
            self.assertEqual("file", calls[1]["request"].metadata["sql_source"])
            self.assertIn("operator.adw_query", audit_text)
            self.assertIn("rows_omitted_from_audit", audit_text)
            self.assertNotIn('"rows": [{"CUSTOMER_ID": 1}]', audit_text)
            self.assertNotIn("db-secret", rendered)
            self.assertNotIn("adw_secret_service", rendered)

    def test_operator_adw_query_reads_sql_from_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"
            calls = []

            class FakeQueryAdapter:
                def __init__(self, config, *, settings, allow_real_execution):
                    calls.append({"allow_real_execution": allow_real_execution})

                def execute(self, request):
                    calls.append({"request": request})
                    return SqlExecutionResponse(
                        ok=True,
                        status="succeeded",
                        backend="sqlcl",
                        columns=("CUSTOMER_ID",),
                        rows=(),
                        row_count=0,
                        backend_metadata={
                            "sql_sha256": "stdin-query-sha",
                            "allow_real_execution": True,
                            "execution_state": "executed",
                        },
                    )

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                    "DB_WALLET_PATH": str(wallet_path),
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.SqlclReadOnlyAdapter", FakeQueryAdapter):
                    with patch(
                        "agent_runtime.cli.verify_sqlcl",
                        return_value=SqlclStatus(
                            configured_path="/opt/sqlcl/bin/sql",
                            resolved_path="/opt/sqlcl/bin/sql",
                            exists=True,
                            executable=True,
                            version_checked=True,
                            ok=True,
                            version="SQLcl test",
                        ),
                    ):
                        with patch("sys.stdin", io.StringIO("select customer_id from customers")):
                            with redirect_stdout(output):
                                exit_code = main(
                                    [
                                        "operator",
                                        "adw-query",
                                        "--confirm-live-adw-query",
                                        "--sql-stdin",
                                        "--audit-log",
                                        str(audit_path),
                                    ]
                                )

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("succeeded", payload["state"])
            self.assertEqual("select customer_id from customers", calls[1]["request"].sql)
            self.assertEqual("stdin", calls[1]["request"].metadata["sql_source"])

    def test_operator_adw_query_rejects_invalid_limits_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "DB_USER": "AGENT_RO",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                    "DB_WALLET_PATH": str(wallet_path),
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.verify_sqlcl") as verify:
                    with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-query",
                                    "--confirm-live-adw-query",
                                    "--sql",
                                    "select customer_id from customers",
                                    "--row-limit",
                                    "0",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("invalid_row_limit", payload["error"]["code"])
            self.assertFalse(payload["live_execution_attempted"])
            verify.assert_not_called()
            adapter_cls.assert_not_called()

    def test_operator_adw_query_rejects_empty_oversized_and_unreadable_sql_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            empty_path = tmp_path / "empty.sql"
            empty_path.write_text("", encoding="utf-8")
            oversized_path = tmp_path / "oversized.sql"
            oversized_path.write_text("x" * 16_385, encoding="utf-8")
            missing_path = tmp_path / "missing.sql"

            cases = [
                (empty_path, "empty_sql"),
                (oversized_path, "sql_too_large"),
                (missing_path, "sql_file_unreadable"),
            ]

            for path, expected_code in cases:
                with self.subTest(expected_code=expected_code):
                    output = io.StringIO()
                    audit_path = tmp_path / f"{expected_code}.jsonl"
                    with patch("agent_runtime.cli.verify_sqlcl") as verify:
                        with patch("agent_runtime.cli.SqlclReadOnlyAdapter") as adapter_cls:
                            with redirect_stdout(output):
                                exit_code = main(
                                    [
                                        "operator",
                                        "adw-query",
                                        "--confirm-live-adw-query",
                                        "--sql-file",
                                        str(path),
                                        "--audit-log",
                                        str(audit_path),
                                    ]
                                )

                    payload = json.loads(output.getvalue())
                    self.assertEqual(1, exit_code)
                    self.assertEqual(expected_code, payload["error"]["code"])
                    self.assertFalse(payload["live_execution_attempted"])
                    verify.assert_not_called()
                    adapter_cls.assert_not_called()

    def test_operator_adw_provision_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"

            with patch("agent_runtime.cli.verify_sqlcl") as verify:
                with patch("agent_runtime.cli.run_sqlcl_subprocess") as run:
                    with redirect_stdout(output):
                        exit_code = main(
                            [
                                "operator",
                                "adw-provision-working-user",
                                "--grant-profile",
                                "prototype-any-table-read",
                                "--audit-log",
                                str(audit_path),
                            ]
                        )

            payload = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertEqual("confirmation_required", payload["state"])
            self.assertFalse(payload["admin_execution_requested"])
            verify.assert_not_called()
            run.assert_not_called()
            self.assertIn("operator.adw_provision_working_user", audit_path.read_text(encoding="utf-8"))

    def test_operator_adw_provision_rejects_bad_config_before_sqlcl(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            audit_path = Path(tmp) / "audit.jsonl"

            with patch.dict(
                os.environ,
                {
                    "SQLCL_PATH": "relative/sql",
                    "ADMIN_USER": "ADMIN",
                    "ADMIN_USER_PASS": "admin-secret",
                    "DB_USER": "AIAGENT",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                },
                clear=True,
            ):
                with patch("agent_runtime.cli.verify_sqlcl") as verify:
                    with patch("agent_runtime.cli.run_sqlcl_subprocess") as run:
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "prototype-any-table-read",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("sqlcl_path_must_be_absolute", payload["error"]["code"])
            self.assertFalse(payload["admin_execution_attempted"])
            verify.assert_not_called()
            run.assert_not_called()
            self.assertNotIn("admin-secret", rendered)
            self.assertNotIn("db-secret", rendered)

    def test_operator_adw_provision_runs_admin_sqlcl_with_redacted_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"
            calls = []
            responses = [
                '{"items":[]}',
                "User AIAGENT created.\n",
                _adw_provision_state_json(
                    "post",
                    roles=["DWROLE"],
                    system_privileges=["CREATE SESSION", "SELECT ANY TABLE"],
                    synonyms=["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"],
                ),
            ]

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=responses[len(calls) - 1],
                    stderr="",
                )

            with patch.dict(
                os.environ,
                {
                    "PATH": "/bin:/java/bin",
                    "JAVA_HOME": "/java",
                    "SQLCL_PATH": "/opt/sqlcl/bin/sql",
                    "ADMIN_USER": "ADMIN",
                    "ADMIN_USER_PASS": "admin-secret",
                    "DB_USER": "AIAGENT",
                    "DB_USER_PASS": "db-secret",
                    "DB_DSN": "adw_secret_service",
                    "DB_WALLET_PATH": str(wallet_path),
                    "DB_WALLET_PASS": "wallet-secret",
                },
                clear=True,
            ):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True,
                        executable=True,
                        version_checked=True,
                        ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "prototype-any-table-read",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            payload = json.loads(output.getvalue())
            audit_text = audit_path.read_text(encoding="utf-8")
            rendered = output.getvalue() + audit_text
            self.assertEqual(0, exit_code)
            self.assertEqual("succeeded", payload["state"])
            self.assertEqual("created", payload["provisioning_classification"])
            self.assertTrue(payload["admin_execution_attempted"])
            self.assertEqual("AIAGENT", payload["working_user"])
            self.assertEqual("prototype-any-table-read", payload["grant_profile"])
            self.assertEqual(
                ["CREATE SESSION", "DWROLE", "SELECT ANY TABLE"],
                payload["requested_privileges"],
            )
            self.assertEqual(3, len(calls))
            self.assertEqual(["/opt/sqlcl/bin/sql", "-S", "-L", "-nolog"], list(calls[1].command))
            self.assertNotIn("CREATE USER AIAGENT", calls[0].stdin)
            self.assertIn("CREATE USER AIAGENT", calls[1].stdin)
            self.assertIn("GRANT SELECT ANY TABLE TO AIAGENT", calls[1].stdin)
            self.assertIn(
                "CREATE OR REPLACE SYNONYM AIAGENT.SALES FOR SH.SALES",
                calls[1].stdin,
            )
            self.assertIn(
                "CREATE OR REPLACE SYNONYM AIAGENT.PRODUCTS FOR SH.PRODUCTS",
                calls[1].stdin,
            )
            self.assertNotIn("ALTER USER AIAGENT ACCOUNT UNLOCK", calls[1].stdin)
            self.assertEqual("/bin:/java/bin", calls[1].env["PATH"])
            self.assertEqual("/java", calls[1].env["JAVA_HOME"])
            self.assertNotIn("DB_USER_PASS", calls[1].env)
            self.assertEqual(1_048_576, calls[1].max_output_bytes)
            self.assertEqual(65_536, calls[1].max_error_bytes)
            self.assertIn("operator.adw_provision_working_user", audit_text)
            self.assertIn("[REDACTED_SQLCL_OUTPUT]", audit_text)
            self.assertNotIn("admin-secret", rendered)
            self.assertNotIn("db-secret", rendered)
            self.assertNotIn("wallet-secret", rendered)

    def test_operator_adw_provision_already_compliant_skips_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            calls = []

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=_adw_provision_state_json(
                        "pre",
                        roles=["DWROLE"],
                        system_privileges=["CREATE SESSION", "SELECT ANY TABLE"],
                        synonyms=["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"],
                    ),
                    stderr="",
                )

            with _operator_admin_env(wallet_path):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True,
                        executable=True,
                        version_checked=True,
                        ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "prototype-any-table-read",
                                    "--audit-log",
                                    str(tmp_path / "audit.jsonl"),
                                ]
                            )

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("already_compliant", payload["provisioning_classification"])
            self.assertEqual(1, len(calls))
            self.assertNotIn("CREATE USER AIAGENT", calls[0].stdin)
            self.assertNotIn("GRANT SELECT ANY TABLE TO AIAGENT", calls[0].stdin)

    def test_operator_adw_provision_rejects_drift_before_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            calls = []

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=_adw_provision_state_json(
                        "pre",
                        roles=["DBA", "DWROLE"],
                        system_privileges=["CREATE SESSION", "SELECT ANY TABLE"],
                        synonyms=["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"],
                    ),
                    stderr="",
                )

            with _operator_admin_env(wallet_path):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True,
                        executable=True,
                        version_checked=True,
                        ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "prototype-any-table-read",
                                    "--audit-log",
                                    str(tmp_path / "audit.jsonl"),
                                ]
                            )

            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("rejected", payload["state"])
            self.assertEqual("rejected_drift", payload["provisioning_classification"])
            self.assertEqual(1, len(calls))
            self.assertNotIn("ALTER USER AIAGENT ACCOUNT UNLOCK", calls[0].stdin)
            self.assertIn("unexpected_role:DBA", json.dumps(payload["provisioning_state"]))

    def test_operator_adw_provision_repairs_only_missing_expected_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            calls = []
            responses = [
                _adw_provision_state_json(
                    "pre",
                    roles=[],
                    system_privileges=["CREATE SESSION", "SELECT ANY TABLE"],
                    synonyms=["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES"],
                ),
                "",
                _adw_provision_state_json(
                    "post",
                    roles=["DWROLE"],
                    system_privileges=["CREATE SESSION", "SELECT ANY TABLE"],
                    synonyms=["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"],
                ),
            ]

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=responses[len(calls) - 1],
                    stderr="",
                )

            with _operator_admin_env(wallet_path):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True,
                        executable=True,
                        version_checked=True,
                        ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "prototype-any-table-read",
                                    "--audit-log",
                                    str(tmp_path / "audit.jsonl"),
                                ]
                            )

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("granted_missing_privileges", payload["provisioning_outcome"])
            self.assertEqual(
                ["grant_role:DWROLE", "default_role_all", "create_synonym:TIMES"],
                payload["actions_applied"],
            )
            self.assertEqual(3, len(calls))
            self.assertNotIn("CREATE USER AIAGENT", calls[1].stdin)
            self.assertNotIn("GRANT CREATE SESSION TO AIAGENT", calls[1].stdin)
            self.assertNotIn("GRANT SELECT ANY TABLE TO AIAGENT", calls[1].stdin)
            self.assertIn("GRANT DWROLE TO AIAGENT", calls[1].stdin)
            self.assertIn("CREATE OR REPLACE SYNONYM AIAGENT.TIMES FOR SH.TIMES", calls[1].stdin)
            self.assertNotIn("CREATE OR REPLACE SYNONYM AIAGENT.SALES FOR SH.SALES", calls[1].stdin)

    def test_operator_adw_provision_production_sh_read_creates_object_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            audit_path = tmp_path / "audit.jsonl"
            calls = []
            sh_tables = ["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"]
            object_grants = [("SELECT", "SH", t) for t in sh_tables]
            responses = [
                '{"items":[]}',
                "User AIAGENT created.\n",
                _adw_provision_state_json(
                    "post",
                    roles=[],
                    system_privileges=["CREATE SESSION"],
                    synonyms=sh_tables,
                    object_grants=object_grants,
                ),
            ]

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=responses[len(calls) - 1],
                    stderr="",
                )

            with _operator_admin_env(wallet_path):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True,
                        executable=True,
                        version_checked=True,
                        ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "production-sh-read",
                                    "--audit-log",
                                    str(audit_path),
                                ]
                            )

            payload = json.loads(output.getvalue())
            rendered = output.getvalue() + audit_path.read_text(encoding="utf-8")
            self.assertEqual(0, exit_code)
            self.assertEqual("created", payload["provisioning_classification"])
            self.assertEqual("production-sh-read", payload["grant_profile"])
            expected_privs = ["CREATE SESSION"] + [f"SELECT ON SH.{t}" for t in sh_tables]
            self.assertEqual(sorted(expected_privs), sorted(payload["requested_privileges"]))
            # DDL: CREATE USER + object grants + synonyms
            self.assertIn("CREATE USER AIAGENT", calls[1].stdin)
            self.assertIn("GRANT SELECT ON SH.SALES TO AIAGENT", calls[1].stdin)
            self.assertIn("GRANT SELECT ON SH.PRODUCTS TO AIAGENT", calls[1].stdin)
            self.assertNotIn("GRANT SELECT ANY TABLE TO AIAGENT", calls[1].stdin)
            self.assertNotIn("GRANT DWROLE TO AIAGENT", calls[1].stdin)
            self.assertIn("CREATE OR REPLACE SYNONYM AIAGENT.SALES FOR SH.SALES", calls[1].stdin)
            self.assertNotIn("admin-secret", rendered)
            self.assertNotIn("db-secret", rendered)

    def test_operator_adw_provision_production_sh_read_rejects_select_any_table_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            calls = []

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=_adw_provision_state_json(
                        "pre",
                        roles=["DWROLE"],
                        system_privileges=["CREATE SESSION", "SELECT ANY TABLE"],
                        synonyms=["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"],
                    ),
                    stderr="",
                )

            with _operator_admin_env(wallet_path):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True, executable=True,
                        version_checked=True, ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "production-sh-read",
                                    "--audit-log",
                                    str(tmp_path / "audit.jsonl"),
                                ]
                            )

            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual("rejected_drift", payload["provisioning_classification"])
            # Only precheck ran, no apply
            self.assertEqual(1, len(calls))

    def test_operator_adw_provision_production_sh_read_already_compliant(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wallet_path = tmp_path / "wallet"
            wallet_path.mkdir()
            output = io.StringIO()
            calls = []
            sh_tables = ["CHANNELS", "CUSTOMERS", "PRODUCTS", "SALES", "TIMES"]
            object_grants = [("SELECT", "SH", t) for t in sh_tables]

            def fake_run(request):
                calls.append(request)
                return SqlclRunnerResult(
                    returncode=0,
                    stdout=_adw_provision_state_json(
                        "pre",
                        roles=[],
                        system_privileges=["CREATE SESSION"],
                        synonyms=sh_tables,
                        object_grants=object_grants,
                    ),
                    stderr="",
                )

            with _operator_admin_env(wallet_path):
                with patch(
                    "agent_runtime.cli.verify_sqlcl",
                    return_value=SqlclStatus(
                        configured_path="/opt/sqlcl/bin/sql",
                        resolved_path="/opt/sqlcl/bin/sql",
                        exists=True, executable=True,
                        version_checked=True, ok=True,
                        version="SQLcl test",
                    ),
                ):
                    with patch("agent_runtime.cli.run_sqlcl_subprocess", fake_run):
                        with redirect_stdout(output):
                            exit_code = main(
                                [
                                    "operator",
                                    "adw-provision-working-user",
                                    "--confirm-live-adw-admin-provision",
                                    "--grant-profile",
                                    "production-sh-read",
                                    "--audit-log",
                                    str(tmp_path / "audit.jsonl"),
                                ]
                            )

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("already_compliant", payload["provisioning_classification"])
            self.assertEqual(1, len(calls))

    def test_default_tools_do_not_expose_live_adw_execution(self):
        registry = default_tool_registry()
        specs = [spec["name"] for spec in registry.specs()]

        self.assertNotIn("operator_adw_smoke", specs)
        self.assertNotIn("operator_adw_query", specs)
        self.assertNotIn("operator_adw_provision_working_user", specs)
        self.assertNotIn("sql_execution", specs)
        self.assertEqual(["mock_schema_context", "mock_data_query"], specs)


class CancelDuringActionSelection:
    name = "cancel-test-model"
    version = "1"

    def __init__(self, token: CancellationToken) -> None:
        self.token = token

    def choose_action(self, intent: UserIntent, *, context: dict | None = None) -> Action:
        self.token.cancel("model_requested_cancel")
        return Action(
            kind="final_answer",
            reason="test action selected",
            payload={"next_action": intent.next_action},
        )


class SecretInspectSchemaModel:
    name = "secret-inspect-schema-model"
    version = "1"

    def choose_action(self, intent: UserIntent, *, context: dict | None = None) -> Action:
        return Action(
            kind="inspect_schema",
            reason="test schema inspection",
            payload={"required_context": ["runtime-tool-secret"]},
        )


def _event_names(events_path: Path) -> list[str]:
    return [
        json.loads(line)["event"]
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]


def _events(events_path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]


def _operator_admin_env(wallet_path: Path):
    return patch.dict(
        os.environ,
        {
            "PATH": "/bin:/java/bin",
            "JAVA_HOME": "/java",
            "SQLCL_PATH": "/opt/sqlcl/bin/sql",
            "ADMIN_USER": "ADMIN",
            "ADMIN_USER_PASS": "admin-secret",
            "DB_USER": "AIAGENT",
            "DB_USER_PASS": "db-secret",
            "DB_DSN": "adw_secret_service",
            "DB_WALLET_PATH": str(wallet_path),
            "DB_WALLET_PASS": "wallet-secret",
        },
        clear=True,
    )


def _adw_provision_state_json(
    prefix: str,
    *,
    roles: list[str],
    system_privileges: list[str],
    synonyms: list[str],
    object_grants: list[tuple[str, str, str]] | None = None,
) -> str:
    payloads = [
        {
            "items": [
                {
                    "afs_section": f"{prefix}_user",
                    "username": "AIAGENT",
                    "account_status": "OPEN",
                }
            ]
        },
        {
            "items": [
                {"afs_section": f"{prefix}_role", "granted_role": role}
                for role in roles
            ]
        },
        {
            "items": [
                {"afs_section": f"{prefix}_sys_privilege", "privilege": privilege}
                for privilege in system_privileges
            ]
        },
        {
            "items": [
                {
                    "afs_section": f"{prefix}_synonym",
                    "synonym_name": synonym,
                    "table_owner": "SH",
                    "table_name": synonym,
                }
                for synonym in synonyms
            ]
        },
    ]
    if object_grants:
        payloads.append({
            "items": [
                {
                    "afs_section": f"{prefix}_object_grant",
                    "privilege": priv,
                    "owner": owner,
                    "table_name": tbl,
                }
                for priv, owner, tbl in object_grants
            ]
        })
    return "\n".join(json.dumps(payload) for payload in payloads)


if __name__ == "__main__":
    unittest.main()

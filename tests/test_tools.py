import os
import tempfile
import unittest
from pathlib import Path

from agent_runtime.tools import (
    ToolCall,
    ToolExecutionContext,
    ToolParameter,
    ToolRegistry,
    ToolRunner,
    ToolSpec,
    default_tool_registry,
)


class ToolRegistryTests(unittest.TestCase):
    def test_registers_and_lists_tool_specs(self):
        registry = ToolRegistry()

        registry.register(
            ToolSpec(
                name="echo",
                description="Echo a value.",
                parameters=(ToolParameter(name="text", type="string"),),
            ),
            lambda args: {"text": args["text"]},
        )

        specs = registry.specs()
        self.assertEqual("echo", specs[0]["name"])
        self.assertTrue(specs[0]["read_only"])
        self.assertEqual("text", specs[0]["parameters"][0]["name"])

    def test_rejects_duplicate_tool_names(self):
        registry = ToolRegistry()
        spec = ToolSpec(name="echo", description="Echo a value.")

        registry.register(spec, lambda args: {})

        with self.assertRaises(ValueError):
            registry.register(spec, lambda args: {})

    def test_validates_required_unknown_and_typed_arguments(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="lookup",
                description="Lookup a record.",
                parameters=(
                    ToolParameter(name="id", type="string"),
                    ToolParameter(name="limit", type="integer", required=False),
                ),
            ),
            lambda args: {"ok": True},
        )

        self.assertEqual([], registry.validate_call(ToolCall("lookup", {"id": "A-1", "limit": 1})))

        errors = registry.validate_call(ToolCall("lookup", {"limit": "1", "extra": True}))
        self.assertIn("missing required argument: id", errors)
        self.assertIn("argument limit must be integer", errors)
        self.assertIn("unknown argument: extra", errors)

    def test_default_registry_exposes_only_low_risk_read_only_mock_tools(self):
        registry = default_tool_registry()

        specs = registry.specs()

        self.assertEqual(["mock_schema_context"], [spec["name"] for spec in specs])
        self.assertTrue(all(spec["read_only"] for spec in specs))
        self.assertTrue(all(spec["risk_level"] == "low" for spec in specs))
        self.assertEqual(
            ["required_context", "request_text", "request_terms"],
            [parameter["name"] for parameter in specs[0]["parameters"]],
        )


class ToolRunnerTests(unittest.TestCase):
    def test_runs_tool_and_emits_progress_and_audit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = []
            registry = ToolRegistry()
            registry.register(
                ToolSpec(
                    name="echo",
                    description="Echo a value.",
                    parameters=(ToolParameter(name="text", type="string"),),
                ),
                lambda args: {"text": args["text"]},
            )
            runner = ToolRunner(
                registry,
                context=_tool_context(tmp),
                event_sink=lambda event, data: events.append((event, data)),
            )

            result = runner.run(ToolCall("echo", {"text": "hello"}))

            self.assertEqual("completed", result.state)
            self.assertEqual({"text": "hello"}, result.output)
            self.assertEqual(["tool_started", "tool_completed"], [event for event, _ in events])
            audit_text = (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("tool_started", audit_text)
            self.assertIn("tool_completed", audit_text)

    def test_invalid_call_does_not_run_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            registry = ToolRegistry()
            registry.register(
                ToolSpec(
                    name="echo",
                    description="Echo a value.",
                    parameters=(ToolParameter(name="text", type="string"),),
                ),
                lambda args: calls.append(args),
            )

            result = ToolRunner(registry, context=_tool_context(tmp)).run(ToolCall("echo", {"text": 1}))

            self.assertEqual("invalid", result.state)
            self.assertEqual(0, result.attempts)
            self.assertEqual([], calls)

    def test_retries_failed_tool_until_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempts = []
            registry = ToolRegistry()

            def flaky(args):
                attempts.append(args)
                if len(attempts) == 1:
                    raise RuntimeError("temporary")
                return {"ok": True}

            registry.register(ToolSpec(name="flaky", description="Flaky tool."), flaky)

            result = ToolRunner(registry, context=_tool_context(tmp)).run(ToolCall("flaky"), max_attempts=2)

            self.assertEqual("completed", result.state)
            self.assertEqual(2, result.attempts)
            self.assertEqual({"ok": True}, result.output)

    def test_blocks_write_or_high_risk_tools_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            registry = ToolRegistry()
            registry.register(
                ToolSpec(name="load_target", description="Load target.", risk_level="high", read_only=False),
                lambda args: calls.append(args) or {"loaded": True},
            )

            blocked = ToolRunner(registry, context=_tool_context(tmp)).run(ToolCall("load_target"))
            approved = ToolRunner(
                registry,
                context=_tool_context(
                    tmp,
                    approved_high_risk_tools=("load_target",),
                    approved_write_tools=("load_target",),
                ),
            ).run(ToolCall("load_target"))

            self.assertEqual("blocked", blocked.state)
            self.assertEqual("completed", approved.state)
            self.assertEqual([{}], calls)

    def test_tool_result_events_and_audit_are_redacted(self):
        previous = os.environ.get("TOOL_TEST_PASSWORD")
        os.environ["TOOL_TEST_PASSWORD"] = "tool-secret-value"
        events = []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                registry = ToolRegistry()
                registry.register(
                    ToolSpec(
                        name="secret_echo",
                        description="Echo a value.",
                        parameters=(ToolParameter(name="text", type="string"),),
                    ),
                    lambda args: {"message": args["text"], "password": "tool-secret-value"},
                )
                runner = ToolRunner(
                    registry,
                    context=_tool_context(tmp),
                    event_sink=lambda event, data: events.append((event, data)),
                )

                result = runner.run(ToolCall("secret_echo", {"text": "tool-secret-value"}))

                serialized = (
                    str(result.to_dict())
                    + str(events)
                    + (Path(tmp) / "audit.jsonl").read_text(encoding="utf-8")
                )
                self.assertNotIn("tool-secret-value", serialized)
                self.assertIn("[REDACTED]", serialized)
        finally:
            if previous is None:
                os.environ.pop("TOOL_TEST_PASSWORD", None)
            else:
                os.environ["TOOL_TEST_PASSWORD"] = previous

    def test_default_schema_context_tool_returns_compact_read_only_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema", "business_glossary"],
                        "request_text": "show revenue by product by month from oracle adw",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertFalse(result.output["external_access"])
            self.assertFalse(result.output["sql_generation_enabled"])
            self.assertFalse(result.output["sql_execution_enabled"])
            self.assertIn("SQL generation remains closed", result.output["next_action"])
            self.assertEqual("oracle_adw_sh.v1", result.output["profile_id"])
            self.assertIn("SH.SALES", result.output["selected_table_ids"])
            self.assertIn("SH.PRODUCTS", result.output["selected_table_ids"])
            self.assertIn("SH.TIMES", result.output["selected_table_ids"])
            self.assertIn("considered_tables", result.output)
            self.assertIn("rejected_tables", result.output)
            self.assertIn("glossary_matches", result.output)
            query_plan = result.output["query_plan"]
            self.assertEqual("agent-runtime.query-plan.v1", query_plan["schema_version"])
            self.assertEqual("planned", query_plan["status"])
            self.assertTrue(query_plan["policy_validation"]["allowed"])
            self.assertFalse(query_plan["execution"]["enabled"])
            self.assertEqual("not_executed", query_plan["execution"]["status"])
            self.assertNotIn("rows", query_plan["execution"])
            self.assertNotIn("result_rows", query_plan)
            result_explanation = result.output["result_explanation"]
            self.assertEqual(
                "agent-runtime.result-explanation.v1",
                result_explanation["schema_version"],
            )
            self.assertEqual("succeeded", result_explanation["status"])
            self.assertEqual("fake/deterministic", result_explanation["source"])
            self.assertFalse(result_explanation["real_database_execution"])
            self.assertEqual("fake", result_explanation["sql_execution_backend"])
            self.assertEqual("fake", result_explanation["execution_response"]["backend"])
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
            self.assertEqual(
                (
                    {
                        "month": "demo_month_01",
                        "product_category": "demo_category_alpha",
                        "revenue": 1000,
                    },
                    {
                        "month": "demo_month_02",
                        "product_category": "demo_category_beta",
                        "revenue": 1250,
                    },
                ),
                result_explanation["rows"],
            )
            self.assertEqual(
                "agent-runtime.sample-masking.v1",
                result.output["masking"]["policy_version"],
            )

    def test_default_schema_context_tool_returns_channel_fake_result_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema", "business_glossary"],
                        "request_text": "show revenue by channel by month from oracle adw",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertEqual("planned", result.output["query_plan"]["status"])
            self.assertEqual(
                ("month", "channel", "revenue"),
                result.output["result_explanation"]["columns"],
            )
            self.assertEqual(
                "schema-context-channel-month-fake-results",
                result.output["result_explanation"]["adapter_response_metadata"]["fixture_id"],
            )
            self.assertEqual(
                "sh-revenue-channel-month-demo",
                result.output["result_explanation"]["adapter_response_metadata"]["scenario_id"],
            )
            self.assertFalse(result.output["result_explanation"]["real_database_execution"])
            self.assertFalse(
                result.output["result_explanation"]["adapter_response_metadata"]["oracle_adw_execution"]
            )
            self.assertFalse(
                result.output["result_explanation"]["adapter_response_metadata"]["sqlcl_execution"]
            )

    def test_default_schema_context_tool_returns_promotion_fake_result_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema", "business_glossary"],
                        "request_text": "show revenue by promotion by month from oracle adw",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertEqual("planned", result.output["query_plan"]["status"])
            self.assertEqual(
                ("month", "promotion_category", "revenue"),
                result.output["result_explanation"]["columns"],
            )
            self.assertEqual(
                "schema-context-promotion-category-month-fake-results",
                result.output["result_explanation"]["adapter_response_metadata"]["fixture_id"],
            )
            self.assertEqual(
                "sh-revenue-promotion-category-month-demo",
                result.output["result_explanation"]["adapter_response_metadata"]["scenario_id"],
            )
            self.assertFalse(result.output["result_explanation"]["real_database_execution"])
            self.assertFalse(
                result.output["result_explanation"]["adapter_response_metadata"]["oracle_adw_execution"]
            )
            self.assertFalse(
                result.output["result_explanation"]["adapter_response_metadata"]["sqlcl_execution"]
            )

    def test_default_schema_context_tool_returns_promotion_subcategory_fake_result_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema", "business_glossary"],
                        "request_text": "show revenue by promotion subcategory by month from oracle adw",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertEqual("planned", result.output["query_plan"]["status"])
            self.assertEqual(
                ("month", "promotion_subcategory", "revenue"),
                result.output["result_explanation"]["columns"],
            )
            self.assertEqual(
                "schema-context-promotion-subcategory-month-fake-results",
                result.output["result_explanation"]["adapter_response_metadata"]["fixture_id"],
            )
            self.assertEqual(
                "sh-revenue-promotion-subcategory-month-demo",
                result.output["result_explanation"]["adapter_response_metadata"]["scenario_id"],
            )
            self.assertFalse(result.output["result_explanation"]["real_database_execution"])
            self.assertFalse(
                result.output["result_explanation"]["adapter_response_metadata"]["oracle_adw_execution"]
            )
            self.assertFalse(
                result.output["result_explanation"]["adapter_response_metadata"]["sqlcl_execution"]
            )

    def test_default_schema_context_tool_omits_query_plan_for_unsupported_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema"],
                        "request_text": "inspect oracle schema tables",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertNotIn("query_plan", result.output)
            self.assertNotIn("result_explanation", result.output)

    def test_default_schema_context_tool_omits_result_explanation_for_channel_without_metric_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema", "business_glossary"],
                        "request_text": "Show channels from the Oracle ADW SH schema.",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertNotIn("query_plan", result.output)
            self.assertNotIn("result_explanation", result.output)

    def test_default_schema_context_tool_omits_result_explanation_for_ambiguous_region_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ToolRunner(default_tool_registry(), context=_tool_context(tmp))

            result = runner.run(
                ToolCall(
                    "mock_schema_context",
                    {
                        "required_context": ["oracle_adw_schema", "business_glossary"],
                        "request_text": "Show monthly revenue by region from the Oracle ADW SH schema.",
                    },
                )
            )

            self.assertEqual("completed", result.state)
            self.assertEqual("clarification_required", result.output["query_plan"]["status"])
            self.assertNotIn("result_explanation", result.output)


def _tool_context(
    tmp: str,
    *,
    approved_high_risk_tools=(),
    approved_write_tools=(),
) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="tool-test-run",
        audit_path=Path(tmp) / "audit.jsonl",
        approved_high_risk_tools=approved_high_risk_tools,
        approved_write_tools=approved_write_tools,
    )


if __name__ == "__main__":
    unittest.main()

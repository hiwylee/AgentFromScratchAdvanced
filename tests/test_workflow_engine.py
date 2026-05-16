import json
import tempfile
import unittest
from pathlib import Path

from agent_runtime.workflow import (
    HumanDecision,
    MockPatentAssetConnector,
    WorkflowEngine,
    load_workflow_template,
)


class WorkflowEngineTests(unittest.TestCase):
    def test_run_patent_asset_replacement_requires_checkpoint_before_d_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("checkpoint_required", result["state"])
            self.assertEqual("resolved", result["reconciliation"]["status"])
            self.assertEqual("checkpoint_required", result["human_gate"]["state"])
            self.assertEqual("blocked", result["target_load"]["state"])
            self.assertEqual("explicit_checkpoint_required", result["target_load"]["reason"])
            self.assertTrue(Path(result["status_path"]).exists())
            self.assertTrue(Path(result["events_path"]).exists())
            self.assertTrue(Path(result["audit_path"]).exists())
            self.assertEqual([], connector.loaded_batches)

    def test_resume_with_human_decision_loads_d_after_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )
            result = engine.run_patent_asset_replacement(period="current_month")

            resumed = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="validated checkpoint packet",
                    approved_record_ids=("PA-100", "PA-200"),
                ),
            )

            self.assertEqual("completed", resumed["state"])
            self.assertEqual("completed", resumed["target_load"]["state"])
            self.assertEqual(2, resumed["target_load"]["result"]["record_count"])
            self.assertEqual(["PA-100", "PA-200"], resumed["target_load"]["result"]["patent_ids"])
            self.assertEqual(1, len(connector.loaded_batches))

    def test_resume_requires_trusted_checkpoint_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(run_root=Path(tmp) / "runs", audit_path=Path(tmp) / "audit.jsonl")

            resumed = engine.resume_with_human_decision(
                "forged-run-id",
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="forged json",
                    approved_record_ids=("PA-100",),
                ),
            )

            self.assertEqual("blocked", resumed["state"])
            self.assertEqual("trusted_checkpoint_not_found", resumed["reason"])

    def test_resume_rejects_records_outside_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )
            result = engine.run_patent_asset_replacement(period="current_month")

            resumed = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="invalid approval",
                    approved_record_ids=("PA-999",),
                ),
            )

            self.assertEqual("blocked", resumed["state"])
            self.assertEqual("approved_records_not_in_checkpoint", resumed["reason"])
            self.assertEqual([], connector.loaded_batches)

    def test_rejecting_checkpoint_closes_run_and_prevents_later_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )
            result = engine.run_patent_asset_replacement(period="current_month")

            rejected = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="reject_workflow",
                    policy_basis="not approved",
                    approved_record_ids=(),
                ),
            )
            approved_after_reject = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="late approval attempt",
                    approved_record_ids=("PA-100",),
                ),
            )

            self.assertEqual("closed", rejected["state"])
            self.assertEqual("blocked", approved_after_reject["state"])
            self.assertEqual("trusted_checkpoint_not_found", approved_after_reject["reason"])
            self.assertEqual([], connector.loaded_batches)

    def test_target_load_receives_copy_of_checkpoint_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MutatingFailingLoadConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )
            result = engine.run_patent_asset_replacement(period="current_month")

            failed = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="first attempt",
                    approved_record_ids=("PA-100",),
                ),
            )
            retried = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="retry attempt",
                    approved_record_ids=("PA-100",),
                ),
            )

            self.assertEqual("failed", failed["state"])
            self.assertEqual("failed", retried["state"])
            self.assertEqual(["ip_ops", "ip_ops"], connector.owners_seen)

    def test_mutating_returned_result_does_not_mutate_trusted_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )
            result = engine.run_patent_asset_replacement(period="current_month")
            result["reconciliation"]["records"]["PA-999"] = {
                "patent_id": "PA-999",
                "replacement_asset_id": "RA-999",
                "owner": "attacker",
                "period": "current_month",
            }

            resumed = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="attempted forged mutation",
                    approved_record_ids=("PA-999",),
                ),
            )

            self.assertEqual("blocked", resumed["state"])
            self.assertEqual("approved_records_not_in_checkpoint", resumed["reason"])
            self.assertEqual([], connector.loaded_batches)

    def test_run_patent_asset_replacement_enriches_c_when_required_info_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(run_root=Path(tmp) / "runs", audit_path=Path(tmp) / "audit.jsonl")

            result = engine.run_patent_asset_replacement(period="current_month")

            enrich_step = self._step(result, "enrich_missing_fields")
            self.assertEqual("completed", enrich_step["state"])
            self.assertEqual(1, enrich_step["details"]["requested_count"])
            self.assertEqual("RA-901", result["reconciliation"]["records"]["PA-200"]["replacement_asset_id"])

    def test_run_patent_asset_replacement_pauses_at_human_gate_when_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(system_c={"current_month": []})
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertEqual("unresolved", result["reconciliation"]["status"])
            self.assertEqual(["PA-200"], result["reconciliation"]["missing_required"])
            self.assertTrue(result["human_gate"]["required"])
            self.assertEqual("paused", result["human_gate"]["state"])
            self.assertEqual("blocked", result["target_load"]["state"])
            self.assertEqual("human_gate_unresolved", result["target_load"]["reason"])
            self.assertEqual([], connector.loaded_batches)

            packet = result["human_gate"]["review_packet"]
            template = load_workflow_template()
            self.assertEqual(set(template.review_packet_required_fields), set(packet))

    def test_run_patent_asset_replacement_reports_deterministic_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(
                system_a={
                    "current_month": [
                        {
                            "patent_id": "PA-300",
                            "replacement_asset_id": "RA-300-A",
                            "owner": "ip_ops",
                            "period": "current_month",
                        }
                    ]
                },
                system_b={
                    "current_month": [
                        {
                            "patent_id": "PA-300",
                            "replacement_asset_id": "RA-300-B",
                            "owner": "ip_ops",
                            "period": "current_month",
                        }
                    ]
                },
            )
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertEqual(
                [
                    {
                        "patent_id": "PA-300",
                        "field": "replacement_asset_id",
                        "values": [
                            {"source": "A", "value": "RA-300-A"},
                            {"source": "B", "value": "RA-300-B"},
                        ],
                    }
                ],
                result["reconciliation"]["conflicts"],
            )

    def test_a_only_record_blocks_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(
                system_a={
                    "current_month": [
                        {
                            "patent_id": "PA-400",
                            "replacement_asset_id": "RA-400",
                            "owner": "ip_ops",
                            "period": "current_month",
                        }
                    ]
                },
                system_b={"current_month": []},
            )
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertEqual("unresolved", result["reconciliation"]["status"])
            self.assertEqual("identity_match", result["reconciliation"]["failed_rules"][0]["rule_id"])
            self.assertEqual([], connector.loaded_batches)

    def test_empty_systems_are_not_replaced_by_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(system_a={}, system_b={}, system_c={})
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("closed", result["state"])
            self.assertEqual("no_records_to_load", result["target_load"]["reason"])
            self.assertEqual(0, result["reconciliation"]["source_counts"]["A"])
            self.assertEqual(0, result["reconciliation"]["source_counts"]["B"])

    def test_asset_status_blocks_load_when_present_and_not_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(
                system_a={
                    "current_month": [
                        {
                            "patent_id": "PA-600",
                            "replacement_asset_id": "RA-600",
                            "owner": "ip_ops",
                            "period": "current_month",
                            "asset_status": "retired",
                        }
                    ]
                },
                system_b={
                    "current_month": [
                        {
                            "patent_id": "PA-600",
                            "replacement_asset_id": "RA-600",
                            "owner": "ip_ops",
                            "period": "current_month",
                            "asset_status": "retired",
                        }
                    ]
                },
            )
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertIn("asset_status_valid", {rule["rule_id"] for rule in result["reconciliation"]["failed_rules"]})

    def test_duplicate_registration_blocks_load_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(
                system_a={
                    "current_month": [
                        {
                            "patent_id": "PA-700",
                            "replacement_asset_id": "RA-700",
                            "owner": "ip_ops",
                            "period": "current_month",
                        }
                    ]
                },
                system_b={
                    "current_month": [
                        {
                            "patent_id": "PA-700",
                            "replacement_asset_id": "RA-700",
                            "owner": "ip_ops",
                            "period": "current_month",
                            "target_registered": True,
                        }
                    ]
                },
            )
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertIn("no_duplicate_registration", {rule["rule_id"] for rule in result["reconciliation"]["failed_rules"]})

    def test_wrong_period_record_blocks_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(
                system_a={
                    "current_month": [
                        {
                            "patent_id": "PA-500",
                            "replacement_asset_id": "RA-500",
                            "owner": "ip_ops",
                            "period": "previous_month",
                        }
                    ]
                },
                system_b={
                    "current_month": [
                        {
                            "patent_id": "PA-500",
                            "replacement_asset_id": "RA-500",
                            "owner": "ip_ops",
                            "period": "previous_month",
                        }
                    ]
                },
            )
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertEqual("period_valid", result["reconciliation"]["failed_rules"][0]["rule_id"])

    def test_malformed_record_is_failed_rule_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            connector = MockPatentAssetConnector(
                system_a={"current_month": [{"owner": "ip_ops", "period": "current_month"}]},
                system_b={"current_month": []},
            )
            engine = WorkflowEngine(
                connector=connector,
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("paused", result["state"])
            self.assertEqual("identity_present", result["reconciliation"]["failed_rules"][0]["rule_id"])
            self.assertEqual(1, len(result["reconciliation"]["malformed_records"]))

    def test_connector_failure_becomes_failed_workflow_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(
                connector=FailingConnector(),
                run_root=Path(tmp) / "runs",
                audit_path=Path(tmp) / "audit.jsonl",
            )

            result = engine.run_patent_asset_replacement(period="current_month")

            self.assertEqual("failed", result["state"])
            self.assertEqual("workflow_failed", result["target_load"]["reason"])
            self.assertTrue(Path(result["status_path"]).exists())

    def test_runtime_template_metadata_matches_json_artifact(self):
        template = load_workflow_template()

        self.assertEqual("patent-asset-replacement-registration", template.template_id)
        self.assertEqual(1, template.template_version)
        self.assertEqual("patent_asset_replacement_registration", template.workflow_id)
        self.assertEqual(("patent_id", "replacement_asset_id", "owner", "period"), template.required_fields)
        node_ids = [node["node_id"] for node in template.nodes]
        self.assertIn("lookup_source_a", node_ids)
        self.assertIn("pre_load_checkpoint", node_ids)
        self.assertIn("workflow_template_selected", template.audit_required_events)

    def test_required_audit_events_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine = WorkflowEngine(run_root=tmp_path / "runs", audit_path=tmp_path / "audit.jsonl")

            result = engine.run_patent_asset_replacement(period="current_month")

            audit_text = Path(result["audit_path"]).read_text(encoding="utf-8")
            self.assertIn("workflow_template_selected", audit_text)
            self.assertIn("workflow_node_started", audit_text)
            self.assertIn("workflow_node_completed", audit_text)
            self.assertIn("target_load_checkpoint_requested", audit_text)
            self.assertIn("workflow_completed", audit_text)

    def test_monitor_tracks_checkpoint_pause_and_resume_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            connector = MockPatentAssetConnector()
            engine = WorkflowEngine(
                connector=connector,
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
            )
            result = engine.run_patent_asset_replacement(period="current_month")
            checkpoint_status = json.loads(Path(result["status_path"]).read_text(encoding="utf-8"))

            resumed = engine.resume_with_human_decision(
                result["run_id"],
                HumanDecision(
                    actor="reviewer@example.com",
                    action="approve_load",
                    policy_basis="validated checkpoint packet",
                    approved_record_ids=("PA-100", "PA-200"),
                ),
            )
            completed_status = json.loads(Path(result["status_path"]).read_text(encoding="utf-8"))
            event_text = Path(result["events_path"]).read_text(encoding="utf-8")

            self.assertEqual("checkpoint_required", checkpoint_status["state"])
            self.assertEqual("completed", resumed["state"])
            self.assertEqual("completed", completed_status["state"])
            self.assertIn("run_paused", event_text)
            self.assertIn("human_decision_recorded", event_text)
            self.assertIn("run_finished", event_text)

    def _step(self, result, step_id):
        return next(step for step in result["steps"] if step["step_id"] == step_id)


class FailingConnector:
    def lookup_a(self, period):
        raise RuntimeError("source unavailable")

    def lookup_b(self, period):
        return []

    def enrich_c(self, period, records):
        return []

    def load_d(self, period, records):
        raise AssertionError("load_d must not run")


class MutatingFailingLoadConnector(MockPatentAssetConnector):
    def __init__(self):
        super().__init__()
        self.owners_seen = []

    def load_d(self, period, records):
        self.owners_seen.append(records[0]["owner"])
        records[0]["owner"] = "mutated-by-target"
        raise RuntimeError("target unavailable")


if __name__ == "__main__":
    unittest.main()

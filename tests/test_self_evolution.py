import json
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from agent_runtime.eval_runner import EVAL_RESULT_SCHEMA_VERSION, EvalCaseResult, EvalRunResult
from agent_runtime.redaction import REDACTION, redact
from agent_runtime.self_evolution import (
    DRIFT_RESULT_SCHEMA_VERSION,
    IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
    MEMORY_RECORD_SCHEMA_VERSION,
    ROLLBACK_PLAN_SCHEMA_VERSION,
    ImprovementCandidateRecord,
    MemoryRecord,
    RollbackPlan,
    evaluate_self_evolution_gate,
    load_drift_cases,
    load_memory_record,
    run_drift_checks,
)
from agent_runtime.trace import ArtifactVersions


DRIFT_FIXTURE = Path("artifacts/evals/drift/self-evolution-drift-v1.json")
MEMORY_RECORD = Path("artifacts/memory/runtime-memory.v1.json")


class SelfEvolutionTests(unittest.TestCase):
    def test_artifact_manifest_loads_memory_provenance_version(self):
        versions = ArtifactVersions.from_manifest()

        self.assertEqual("1", versions.prompt_versions["intent_classifier"]["version"])
        self.assertEqual("1", versions.policy_versions["redaction_policy"]["version"])
        self.assertEqual(
            "artifacts/memory/runtime-memory.v1.json",
            versions.memory_versions["runtime_memory"]["path"],
        )
        self.assertEqual("1", versions.memory_versions["runtime_memory"]["version"])

    def test_loads_memory_record_with_required_provenance(self):
        record = load_memory_record(MEMORY_RECORD)

        self.assertEqual(MEMORY_RECORD_SCHEMA_VERSION, record.schema_version)
        self.assertEqual("active", record.status)
        self.assertEqual("approved", record.provenance.review_status)
        self.assertEqual("project_decision", record.provenance.source_type)
        self.assertEqual(1.0, record.provenance.confidence)

    def test_active_memory_requires_approved_review(self):
        payload = _memory_payload()
        payload["provenance"]["review_status"] = "pending"

        with self.assertRaisesRegex(ValueError, "active memory requires approved"):
            MemoryRecord.from_dict(payload)

    def test_improvement_candidate_requires_provenance_and_artifacts(self):
        candidate = ImprovementCandidateRecord.from_dict(_candidate_payload())

        self.assertEqual(IMPROVEMENT_CANDIDATE_SCHEMA_VERSION, candidate.schema_version)
        self.assertEqual("proposed", candidate.status)
        self.assertEqual("prompt", candidate.candidate_type)
        self.assertEqual("approved", candidate.review.decision)
        self.assertEqual("eval_failure", candidate.trigger_type)
        self.assertEqual("artifacts/prompts/intent-classifier.md", candidate.affected_artifacts[0].path)

    def test_candidate_validation_rejects_missing_artifacts(self):
        payload = _candidate_payload()
        payload["affected_artifacts"] = []

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            ImprovementCandidateRecord.from_dict(payload)

    def test_rollback_plan_loads_and_covers_candidate(self):
        plan = RollbackPlan.from_dict(_rollback_payload())

        self.assertEqual(ROLLBACK_PLAN_SCHEMA_VERSION, plan.schema_version)
        self.assertEqual("candidate-prompt-001", plan.candidate_id)
        self.assertEqual("artifacts/prompts/intent-classifier.md", plan.artifacts[0].path)

    def test_acceptance_gate_passes_only_with_review_eval_drift_and_rollback(self):
        candidate = ImprovementCandidateRecord.from_dict(_candidate_payload())
        rollback = RollbackPlan.from_dict(_rollback_payload())
        eval_result = _full_eval_result(passed=True)
        drift_result = _full_drift_result(passed=True)

        report = evaluate_self_evolution_gate(
            candidate,
            rollback_plan=rollback,
            eval_result=eval_result,
            drift_result=drift_result,
        )

        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual("passed", report.status)
        self.assertEqual((), report.reasons)

    def test_acceptance_gate_blocks_failed_eval_missing_review_and_rollback(self):
        payload = _candidate_payload()
        payload["review"]["decision"] = "pending"
        payload["review"].pop("reviewer")
        payload["review"].pop("reviewed_at")
        payload["provenance"]["review_status"] = "pending"
        payload["affected_artifacts"].append(
            {
                "path": "artifacts/policies/redaction-policy.json",
                "artifact_type": "policy",
                "current_version": "1",
                "proposed_version": "2",
            }
        )
        candidate = ImprovementCandidateRecord.from_dict(payload)
        rollback = RollbackPlan.from_dict(_rollback_payload())

        report = evaluate_self_evolution_gate(
            candidate,
            rollback_plan=rollback,
            eval_result=_full_eval_result(passed=False),
            drift_result=_full_drift_result(passed=False),
        )

        self.assertFalse(report.passed)
        rendered = " ".join(report.reasons)
        self.assertIn("review decision must be approved", rendered)
        self.assertIn("provenance review_status must be approved", rendered)
        self.assertIn("frozen evals must pass", rendered)
        self.assertIn("drift checks must pass", rendered)
        self.assertIn("rollback plan missing", rendered)
        self.assertIn("one artifact type at a time", rendered)
        self.assertIn("candidate_type must match", rendered)

    def test_candidate_approved_review_requires_reviewer_and_timestamp(self):
        payload = _candidate_payload()
        payload["review"].pop("reviewed_at")

        with self.assertRaisesRegex(ValueError, "approved review requires"):
            ImprovementCandidateRecord.from_dict(payload)

    def test_acceptance_gate_blocks_wrong_rollback_versions(self):
        candidate = ImprovementCandidateRecord.from_dict(_candidate_payload())
        rollback_payload = _rollback_payload()
        rollback_payload["artifacts"][0]["version_before"] = "0"
        rollback_payload["artifacts"][0]["version_after"] = "3"
        rollback_payload["artifacts"][0]["artifact_type"] = "policy"
        rollback = RollbackPlan.from_dict(rollback_payload)

        report = evaluate_self_evolution_gate(
            candidate,
            rollback_plan=rollback,
            eval_result=_full_eval_result(passed=True),
            drift_result=_full_drift_result(passed=True),
        )

        self.assertFalse(report.passed)
        rendered = " ".join(report.reasons)
        self.assertIn("rollback artifact type mismatch", rendered)
        self.assertIn("rollback version_before mismatch", rendered)
        self.assertIn("rollback version_after mismatch", rendered)

    def test_acceptance_gate_blocks_synthetic_or_wrong_fixture_eval_results(self):
        candidate = ImprovementCandidateRecord.from_dict(_candidate_payload())
        rollback = RollbackPlan.from_dict(_rollback_payload())
        synthetic_eval = _eval_result(passed=True, fixture_dir="/tmp/synthetic", artifact_versions={})

        report = evaluate_self_evolution_gate(
            candidate,
            rollback_plan=rollback,
            eval_result=synthetic_eval,
            drift_result=_full_drift_result(passed=True),
        )

        self.assertFalse(report.passed)
        rendered = " ".join(report.reasons)
        self.assertIn("artifacts/evals/golden", rendered)
        self.assertIn("artifact_versions", rendered)

    def test_acceptance_gate_blocks_synthetic_drift_results(self):
        candidate = ImprovementCandidateRecord.from_dict(_candidate_payload())
        rollback = RollbackPlan.from_dict(_rollback_payload())

        report = evaluate_self_evolution_gate(
            candidate,
            rollback_plan=rollback,
            eval_result=_full_eval_result(passed=True),
            drift_result=_drift_result(passed=True),
        )

        self.assertFalse(report.passed)
        rendered = " ".join(report.reasons)
        self.assertIn("drift result fixture_id", rendered)
        self.assertIn("drift result fixture_path", rendered)

    def test_drift_fixture_runs_repeated_prompts_without_signature_drift(self):
        fixture_id, cases = load_drift_cases(DRIFT_FIXTURE)
        self.assertEqual("self-evolution-drift-v1", fixture_id)
        self.assertEqual(2, len(cases))

        with tempfile.TemporaryDirectory() as tmp:
            result = run_drift_checks(DRIFT_FIXTURE, output_dir=Path(tmp))
            self.assertEqual(DRIFT_RESULT_SCHEMA_VERSION, result.schema_version)
            self.assertTrue(result.passed, result.to_dict())
            self.assertEqual(2, len(result.case_results))
            for case_result in result.case_results:
                self.assertEqual(2, len(case_result.signatures))
                self.assertEqual(case_result.signatures[0], case_result.signatures[1])
                if case_result.case_id == "stable_sh_product_month_plan":
                    signature = case_result.signatures[0]
                    self.assertIn("proposed_sql_sha256", signature["query_plan"])
                    self.assertIn("dimensions", signature["query_plan"])
                    self.assertIn("measures", signature["query_plan"])
                    self.assertIn("explanation_sha256", signature["result_explanation"])
                    trace = json.loads(Path(case_result.trace_paths[0]).read_text(encoding="utf-8"))
                    self.assertEqual(
                        str(DRIFT_FIXTURE),
                        trace["artifact_versions"]["eval_versions"]["drift_fixture"]["path"],
                    )

    def test_drift_result_detects_signature_changes(self):
        drift = _drift_result(passed=True)
        changed_case = replace(
            drift.case_results[0],
            passed=False,
            mismatches=("repeat 2 signature drifted from repeat 1",),
        )
        failed = replace(drift, case_results=(changed_case,))

        self.assertFalse(failed.passed)

    def test_redaction_preserves_status_passed_but_hides_password_fields(self):
        payload = redact({"passed": True, "db_user_pass": "secret-value"})

        self.assertIs(payload["passed"], True)
        self.assertEqual(REDACTION, payload["db_user_pass"])


def _candidate_payload():
    return {
        "schema_version": IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": "candidate-prompt-001",
        "candidate_type": "prompt",
        "status": "proposed",
        "trigger_type": "eval_failure",
        "summary": "Clarify database-analysis prompt wording.",
        "proposed_change": "Narrow intent-classifier wording for ambiguous DB requests.",
        "affected_artifacts": [
            {
                "path": "artifacts/prompts/intent-classifier.md",
                "artifact_type": "prompt",
                "current_version": "1",
                "proposed_version": "2",
            }
        ],
        "provenance": {
            "source_type": "eval_failure",
            "source_id": "eval-output/mock-intents-workflow-v1",
            "author": "unit-test",
            "recorded_at": "2026-05-18T00:00:00+00:00",
            "confidence": 0.8,
            "evidence": ["tests/test_self_evolution.py"],
            "scope": "project",
            "expires_at": None,
            "review_status": "approved",
        },
        "risk_level": "medium",
        "review": {
            "decision": "approved",
            "reviewer": "expert-review",
            "reviewed_at": "2026-05-18T00:00:00+00:00",
            "notes": "Fixture candidate only.",
        },
    }


def _memory_payload():
    return json.loads(MEMORY_RECORD.read_text(encoding="utf-8"))


def _rollback_payload():
    return {
        "schema_version": ROLLBACK_PLAN_SCHEMA_VERSION,
        "candidate_id": "candidate-prompt-001",
        "artifacts": [
            {
                "path": "artifacts/prompts/intent-classifier.md",
                "artifact_type": "prompt",
                "version_before": "1",
                "version_after": "2",
                "rollback_source_path": "artifacts/prompts/intent-classifier.md@version:1",
            }
        ],
        "validation_commands": [
            "UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest discover -s tests"
        ],
        "notes": "Restore the previous prompt artifact and rerun frozen evals.",
    }


def _eval_result(*, passed: bool, fixture_dir="artifacts/evals/golden", artifact_versions=None):
    return EvalRunResult(
        schema_version=EVAL_RESULT_SCHEMA_VERSION,
        fixture_dir=fixture_dir,
        artifact_versions=artifact_versions if artifact_versions is not None else ArtifactVersions.from_manifest().to_dict(),
        case_results=[
            EvalCaseResult(
                fixture_id="mock-intents-workflow-v1",
                case_id="case",
                passed=passed,
                mismatches=[] if passed else ["mismatch"],
            )
        ],
    )


def _drift_result(*, passed: bool):
    from agent_runtime.self_evolution import DriftCaseResult, DriftCheckResult

    return DriftCheckResult(
        schema_version=DRIFT_RESULT_SCHEMA_VERSION,
        fixture_id="unit-drift",
        case_results=(
            DriftCaseResult(
                case_id="case",
                passed=passed,
                signatures=({"stable": True}, {"stable": True}),
                mismatches=() if passed else ("drift",),
            ),
        ),
    )


def _full_eval_result(*, passed: bool):
    fixture_path = Path("artifacts/evals/golden/mock-intents-workflow-v1.json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    return EvalRunResult(
        schema_version=EVAL_RESULT_SCHEMA_VERSION,
        fixture_dir="artifacts/evals/golden",
        artifact_versions=ArtifactVersions.from_manifest().to_dict(),
        case_results=[
            EvalCaseResult(
                fixture_id=fixture["fixture_id"],
                case_id=case["case_id"],
                passed=passed,
                mismatches=[] if passed else ["mismatch"],
            )
            for case in fixture["cases"]
        ],
    )


def _full_drift_result(*, passed: bool):
    from agent_runtime.self_evolution import DriftCaseResult, DriftCheckResult

    fixture = json.loads(DRIFT_FIXTURE.read_text(encoding="utf-8"))
    return DriftCheckResult(
        schema_version=DRIFT_RESULT_SCHEMA_VERSION,
        fixture_id=fixture["fixture_id"],
        fixture_path=str(DRIFT_FIXTURE),
        fixture_sha256=sha256(DRIFT_FIXTURE.read_bytes()).hexdigest(),
        case_results=tuple(
            DriftCaseResult(
                case_id=case["case_id"],
                passed=passed,
                signatures=({"stable": True}, {"stable": True}),
                mismatches=() if passed else ("drift",),
            )
            for case in fixture["cases"]
        ),
    )


if __name__ == "__main__":
    unittest.main()

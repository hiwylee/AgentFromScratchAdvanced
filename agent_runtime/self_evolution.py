"""Self-evolution control records and gates.

This module records and validates improvement candidates. It intentionally does
not apply prompt, policy, memory, eval, or code changes. Acceptance is a gate:
approved review, passing frozen evals, rollback coverage, and drift checks must
all be present before a behavior-shaping candidate can be accepted.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Literal

from .eval_runner import EvalRunResult
from .loop import AgentLoop
from .model import MockModel
from .redaction import redact
from .trace import ArtifactVersions, SecretLeakError, TraceRecord, assert_no_known_secret_values, write_trace
from .types import IntentResult, utc_now


IMPROVEMENT_CANDIDATE_SCHEMA_VERSION = "agent-runtime.improvement-candidate.v1"
MEMORY_RECORD_SCHEMA_VERSION = "agent-runtime.memory-record.v1"
ROLLBACK_PLAN_SCHEMA_VERSION = "agent-runtime.rollback-plan.v1"
DRIFT_FIXTURE_SCHEMA_VERSION = "agent-runtime.drift-fixture.v1"
DRIFT_RESULT_SCHEMA_VERSION = "agent-runtime.drift-result.v1"
SELF_EVOLUTION_GATE_SCHEMA_VERSION = "agent-runtime.self-evolution-gate.v1"


CandidateType = Literal["prompt", "policy", "memory", "eval", "schema_context", "docs"]
CandidateStatus = Literal["proposed", "accepted", "rejected", "superseded"]
ReviewDecision = Literal["pending", "approved", "changes_requested", "rejected"]
MemoryStatus = Literal["proposed", "active", "rejected", "expired"]

BEHAVIOR_SHAPING_ARTIFACT_TYPES = {"prompt", "policy", "memory", "eval", "schema_context"}


@dataclass(frozen=True)
class MemoryProvenance:
    source_type: str
    source_id: str
    author: str
    recorded_at: str = field(default_factory=utc_now)
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()
    scope: str = "project"
    expires_at: str | None = None
    review_status: ReviewDecision = "pending"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str = "provenance") -> "MemoryProvenance":
        confidence = _number(data.get("confidence", 0.0), f"{path}.confidence")
        if confidence < 0 or confidence > 1:
            raise ValueError(f"{path}.confidence must be between 0 and 1")
        review_status = _one_of(
            data.get("review_status", "pending"),
            {"pending", "approved", "changes_requested", "rejected"},
            f"{path}.review_status",
        )
        return cls(
            source_type=_required_str(data, "source_type", path),
            source_id=_required_str(data, "source_id", path),
            author=_required_str(data, "author", path),
            recorded_at=str(data.get("recorded_at") or utc_now()),
            confidence=confidence,
            evidence=_string_tuple(data.get("evidence", ()), f"{path}.evidence"),
            scope=str(data.get("scope") or "project"),
            expires_at=_optional_str(data.get("expires_at"), f"{path}.expires_at"),
            review_status=review_status,  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class MemoryRecord:
    schema_version: str
    memory_id: str
    key: str
    value: str
    status: MemoryStatus
    provenance: MemoryProvenance
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryRecord":
        _require_schema(data, MEMORY_RECORD_SCHEMA_VERSION, "memory record")
        status = _one_of(data.get("status"), {"proposed", "active", "rejected", "expired"}, "memory.status")
        provenance = MemoryProvenance.from_dict(_required_mapping(data, "provenance", "memory"))
        if status == "active" and provenance.review_status != "approved":
            raise ValueError("active memory requires approved provenance review")
        return cls(
            schema_version=MEMORY_RECORD_SCHEMA_VERSION,
            memory_id=_required_str(data, "memory_id", "memory"),
            key=_required_str(data, "key", "memory"),
            value=_required_str(data, "value", "memory"),
            status=status,  # type: ignore[arg-type]
            provenance=provenance,
            tags=_string_tuple(data.get("tags", ()), "memory.tags"),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class ArtifactChange:
    path: str
    artifact_type: CandidateType
    current_version: str
    proposed_version: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str) -> "ArtifactChange":
        artifact_type = _one_of(
            data.get("artifact_type"),
            {"prompt", "policy", "memory", "eval", "schema_context", "docs"},
            f"{path}.artifact_type",
        )
        return cls(
            path=_required_str(data, "path", path),
            artifact_type=artifact_type,  # type: ignore[arg-type]
            current_version=_required_str(data, "current_version", path),
            proposed_version=_required_str(data, "proposed_version", path),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class CandidateReview:
    decision: ReviewDecision = "pending"
    reviewer: str | None = None
    reviewed_at: str | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "CandidateReview":
        if data is None:
            return cls()
        decision = _one_of(
            data.get("decision", "pending"),
            {"pending", "approved", "changes_requested", "rejected"},
            "review.decision",
        )
        reviewer = _optional_str(data.get("reviewer"), "review.reviewer")
        reviewed_at = _optional_str(data.get("reviewed_at"), "review.reviewed_at")
        if decision == "approved" and (not reviewer or not reviewed_at):
            raise ValueError("approved review requires reviewer and reviewed_at")
        return cls(
            decision=decision,  # type: ignore[arg-type]
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            notes=str(data.get("notes") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class ReviewRecord:
    """Immutable record of a single review action on an improvement candidate."""

    reviewer_id: str
    reviewer_timestamp: str
    decision: ReviewDecision
    sequence_no: int
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str = "review_record") -> "ReviewRecord":
        reviewer_id = _required_str(data, "reviewer_id", path)
        if not reviewer_id.strip():
            raise ValueError(f"{path}.reviewer_id must not be empty")
        reviewer_timestamp = _required_str(data, "reviewer_timestamp", path)
        decision = _one_of(
            data.get("decision"),
            {"pending", "approved", "changes_requested", "rejected"},
            f"{path}.decision",
        )
        sequence_no = int(data.get("sequence_no", 0))
        return cls(
            reviewer_id=reviewer_id.strip(),
            reviewer_timestamp=reviewer_timestamp,
            decision=decision,
            sequence_no=sequence_no,
            notes=str(data.get("notes") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_candidate_content_hash(
    candidate_id: str,
    candidate_type: str,
    summary: str,
    proposed_change: str,
    affected_artifacts: "Iterable[ArtifactChange]",
    trigger_type: str,
) -> str:
    """Return SHA-256 hex digest of the candidate's stable content fields.

    Excludes mutable fields: status, review, created_at, content_hash.
    The canonical form is compact JSON with sorted keys.
    """
    canonical = {
        "candidate_id": candidate_id,
        "candidate_type": candidate_type,
        "summary": summary,
        "proposed_change": proposed_change,
        "affected_artifacts": [
            {
                "artifact_path": a.path,  # intentional: 'artifact_path' not 'path' — do not change without re-hashing all candidates
                "artifact_type": a.artifact_type,
                "current_version": a.current_version,
                "proposed_version": a.proposed_version,
            }
            for a in affected_artifacts
        ],
        "trigger_type": trigger_type,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class ImprovementCandidateRecord:
    schema_version: str
    candidate_id: str
    candidate_type: CandidateType
    status: CandidateStatus
    trigger_type: str
    summary: str
    proposed_change: str
    affected_artifacts: tuple[ArtifactChange, ...]
    provenance: MemoryProvenance
    risk_level: str = "medium"
    created_at: str = field(default_factory=utc_now)
    review: CandidateReview = field(default_factory=CandidateReview)
    content_hash: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImprovementCandidateRecord":
        _require_schema(data, IMPROVEMENT_CANDIDATE_SCHEMA_VERSION, "improvement candidate")
        candidate_type = _one_of(
            data.get("candidate_type"),
            {"prompt", "policy", "memory", "eval", "schema_context", "docs"},
            "candidate.candidate_type",
        )
        status = _one_of(
            data.get("status"),
            {"proposed", "accepted", "rejected", "superseded"},
            "candidate.status",
        )
        artifacts = tuple(
            ArtifactChange.from_dict(item, path=f"candidate.affected_artifacts[{index}]")
            for index, item in enumerate(_required_list(data, "affected_artifacts", "candidate"))
        )
        if not artifacts:
            raise ValueError("candidate.affected_artifacts must not be empty")
        return cls(
            schema_version=IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
            candidate_id=_required_str(data, "candidate_id", "candidate"),
            candidate_type=candidate_type,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            trigger_type=_required_str(data, "trigger_type", "candidate"),
            summary=_required_str(data, "summary", "candidate"),
            proposed_change=_required_str(data, "proposed_change", "candidate"),
            affected_artifacts=artifacts,
            provenance=MemoryProvenance.from_dict(_required_mapping(data, "provenance", "candidate")),
            risk_level=str(data.get("risk_level") or "medium"),
            created_at=str(data.get("created_at") or utc_now()),
            review=CandidateReview.from_dict(data.get("review") if isinstance(data.get("review"), Mapping) else None),
            content_hash=str(data.get("content_hash") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


def verify_candidate_hash(record: "ImprovementCandidateRecord") -> bool:
    """Return True when the record's content_hash matches recomputed hash.

    Returns False if content_hash is empty (no hash recorded).
    """
    if not record.content_hash:
        return False
    expected = compute_candidate_content_hash(
        candidate_id=record.candidate_id,
        candidate_type=record.candidate_type,
        summary=record.summary,
        proposed_change=record.proposed_change,
        affected_artifacts=record.affected_artifacts,
        trigger_type=record.trigger_type,
    )
    return record.content_hash == expected


@dataclass(frozen=True)
class RollbackArtifact:
    path: str
    artifact_type: CandidateType
    version_before: str
    version_after: str
    rollback_source_path: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, path: str) -> "RollbackArtifact":
        artifact_type = _one_of(
            data.get("artifact_type"),
            {"prompt", "policy", "memory", "eval", "schema_context", "docs"},
            f"{path}.artifact_type",
        )
        return cls(
            path=_required_str(data, "path", path),
            artifact_type=artifact_type,  # type: ignore[arg-type]
            version_before=_required_str(data, "version_before", path),
            version_after=_required_str(data, "version_after", path),
            rollback_source_path=_required_str(data, "rollback_source_path", path),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class RollbackPlan:
    schema_version: str
    candidate_id: str
    artifacts: tuple[RollbackArtifact, ...]
    validation_commands: tuple[str, ...] = ()
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RollbackPlan":
        _require_schema(data, ROLLBACK_PLAN_SCHEMA_VERSION, "rollback plan")
        artifacts = tuple(
            RollbackArtifact.from_dict(item, path=f"rollback.artifacts[{index}]")
            for index, item in enumerate(_required_list(data, "artifacts", "rollback"))
        )
        if not artifacts:
            raise ValueError("rollback.artifacts must not be empty")
        return cls(
            schema_version=ROLLBACK_PLAN_SCHEMA_VERSION,
            candidate_id=_required_str(data, "candidate_id", "rollback"),
            artifacts=artifacts,
            validation_commands=_string_tuple(data.get("validation_commands", ()), "rollback.validation_commands"),
            notes=str(data.get("notes") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class DriftCase:
    case_id: str
    input_text: str
    repeats: int
    expected_signature_subset: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DriftCaseResult:
    case_id: str
    passed: bool
    signatures: tuple[Mapping[str, Any], ...]
    mismatches: tuple[str, ...] = ()
    trace_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class DriftCheckResult:
    schema_version: str
    fixture_id: str
    case_results: tuple[DriftCaseResult, ...]
    fixture_path: str = ""
    fixture_sha256: str = ""

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.case_results)

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SelfEvolutionGateReport:
    schema_version: str
    candidate_id: str
    status: Literal["passed", "blocked"]
    reasons: tuple[str, ...]
    eval_passed: bool
    drift_passed: bool
    review_decision: ReviewDecision
    rollback_covered_paths: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


def load_improvement_candidate(path: Path) -> ImprovementCandidateRecord:
    return ImprovementCandidateRecord.from_dict(_load_json(path))


def build_improvement_candidate(
    *,
    candidate_id: str | None = None,
    candidate_type: CandidateType,
    trigger_type: str,
    summary: str,
    proposed_change: str,
    affected_artifacts: Iterable[ArtifactChange],
    source_type: str = "unknown",
    source_id: str,
    author: str,
    confidence: float = 0.5,
    evidence: Iterable[str] = (),
    risk_level: str = "medium",
) -> ImprovementCandidateRecord:
    import uuid

    resolved_id = candidate_id if candidate_id is not None else str(uuid.uuid4())
    artifacts_list = list(affected_artifacts)
    payload = {
        "schema_version": IMPROVEMENT_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": resolved_id,
        "candidate_type": candidate_type,
        "status": "proposed",
        "trigger_type": trigger_type,
        "summary": summary,
        "proposed_change": proposed_change,
        "affected_artifacts": [artifact.to_dict() for artifact in artifacts_list],
        "provenance": {
            "source_type": source_type,
            "source_id": source_id,
            "author": author,
            "recorded_at": utc_now(),
            "confidence": confidence,
            "evidence": list(evidence),
            "scope": "project",
            "expires_at": None,
            "review_status": "pending",
        },
        "risk_level": risk_level,
        "review": {
            "decision": "pending",
            "reviewer": None,
            "reviewed_at": None,
            "notes": "",
        },
    }
    record = ImprovementCandidateRecord.from_dict(payload)
    content_hash = compute_candidate_content_hash(
        candidate_id=record.candidate_id,
        candidate_type=record.candidate_type,
        summary=record.summary,
        proposed_change=record.proposed_change,
        affected_artifacts=record.affected_artifacts,
        trigger_type=record.trigger_type,
    )
    return dataclasses.replace(record, content_hash=content_hash)


def write_improvement_candidate(
    candidate: ImprovementCandidateRecord,
    path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    if path.exists() and not overwrite:
        raise FileExistsError(f"improvement candidate already exists: {path}")
    payload = candidate.to_dict()
    assert_no_known_secret_values(payload, context="improvement candidate")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_memory_record(path: Path) -> MemoryRecord:
    return MemoryRecord.from_dict(_load_json(path))


def load_active_memories(memory_dir: Path) -> list[MemoryRecord]:
    """Load all approved active memories from memory_dir.

    Only returns records where:
      - status == "active"
      - provenance.review_status == "approved"

    Skips: missing dir, non-.json files, malformed/invalid records (logs skip reason).
    Never raises — returns empty list on any error.
    Preserves existing self-evolution gate: pending_review records are excluded.
    """
    import logging

    logger = logging.getLogger(__name__)

    if not memory_dir.exists():
        return []

    try:
        paths = sorted(memory_dir.glob("*.json"))
    except OSError as exc:
        logger.debug("load_active_memories: cannot list %s: %s", memory_dir, exc)
        return []

    records: list[MemoryRecord] = []
    for path in paths:
        try:
            record = load_memory_record(path)
        except (ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
            logger.debug("load_active_memories: skipping %s: %s", path.name, exc)
            continue
        if record.status == "active" and record.provenance.review_status == "approved":
            records.append(record)

    return sorted(records, key=lambda r: r.memory_id)


def load_rollback_plan(path: Path) -> RollbackPlan:
    return RollbackPlan.from_dict(_load_json(path))


def evaluate_self_evolution_gate(
    candidate: ImprovementCandidateRecord,
    *,
    rollback_plan: RollbackPlan,
    eval_result: EvalRunResult,
    drift_result: DriftCheckResult,
) -> SelfEvolutionGateReport:
    reasons: list[str] = []
    if candidate.status != "proposed":
        reasons.append("candidate must be proposed before the acceptance gate runs")
    if candidate.review.decision != "approved":
        reasons.append("candidate review decision must be approved")

    # Verify content hash has not been tampered with
    if candidate.content_hash:
        expected_hash = compute_candidate_content_hash(
            candidate_id=candidate.candidate_id,
            candidate_type=candidate.candidate_type,
            summary=candidate.summary,
            proposed_change=candidate.proposed_change,
            affected_artifacts=candidate.affected_artifacts,
            trigger_type=candidate.trigger_type,
        )
        if candidate.content_hash != expected_hash:
            reasons.append("candidate content_hash does not match recomputed hash — possible tampering")
    else:
        reasons.append("candidate content_hash is missing — hash must be set before gate evaluation")

    # Verify reviewer identity for approved review
    if candidate.review.decision == "approved" and not (candidate.review.reviewer or "").strip():
        reasons.append("approved candidate review must have a non-empty reviewer identity")

    if candidate.provenance.review_status != "approved":
        reasons.append("candidate provenance review_status must be approved")
    if not eval_result.case_results:
        reasons.append("frozen eval result must include at least one case")
    if eval_result.schema_version != "agent-runtime.eval-result.v1":
        reasons.append("frozen eval result schema_version is unsupported")
    if eval_result.fixture_dir != "artifacts/evals/golden":
        reasons.append("frozen eval result must come from artifacts/evals/golden")
    reasons.extend(_eval_artifact_version_mismatches(candidate, eval_result))
    reasons.extend(_frozen_eval_result_mismatches(eval_result))
    if not eval_result.passed:
        reasons.append("frozen evals must pass")
    if not drift_result.case_results:
        reasons.append("drift check result must include at least one case")
    if drift_result.schema_version != DRIFT_RESULT_SCHEMA_VERSION:
        reasons.append("drift result schema_version is unsupported")
    reasons.extend(_drift_result_mismatches(drift_result))
    if not drift_result.passed:
        reasons.append("drift checks must pass")
    if rollback_plan.candidate_id != candidate.candidate_id:
        reasons.append("rollback plan candidate_id must match candidate")

    affected_paths = {artifact.path for artifact in candidate.affected_artifacts}
    rollback_paths = {artifact.path for artifact in rollback_plan.artifacts}
    missing_rollback = sorted(affected_paths - rollback_paths)
    if missing_rollback:
        reasons.append(f"rollback plan missing affected artifact paths: {', '.join(missing_rollback)}")
    reasons.extend(_rollback_mismatches(candidate, rollback_plan))

    behavior_types = {
        artifact.artifact_type
        for artifact in candidate.affected_artifacts
        if artifact.artifact_type in BEHAVIOR_SHAPING_ARTIFACT_TYPES
    }
    if len(behavior_types) > 1:
        reasons.append(
            "behavior-shaping candidates must change one artifact type at a time: "
            + ", ".join(sorted(behavior_types))
        )
    affected_types = {artifact.artifact_type for artifact in candidate.affected_artifacts}
    if candidate.candidate_type == "docs" and affected_types != {"docs"}:
        reasons.append("docs candidates may only affect docs artifacts")
    if affected_types != {candidate.candidate_type}:
        reasons.append("candidate_type must match all affected artifact types")

    status = "blocked" if reasons else "passed"
    return SelfEvolutionGateReport(
        schema_version=SELF_EVOLUTION_GATE_SCHEMA_VERSION,
        candidate_id=candidate.candidate_id,
        status=status,
        reasons=tuple(reasons),
        eval_passed=eval_result.passed,
        drift_passed=drift_result.passed,
        review_decision=candidate.review.decision,
        rollback_covered_paths=tuple(sorted(rollback_paths & affected_paths)),
    )


def load_drift_cases(path: Path) -> tuple[str, tuple[DriftCase, ...]]:
    data = _load_json(path)
    _require_schema(data, DRIFT_FIXTURE_SCHEMA_VERSION, "drift fixture")
    cases = []
    for index, item in enumerate(_required_list(data, "cases", "drift fixture")):
        item_path = f"drift.cases[{index}]"
        repeats = int(item.get("repeats", 2))
        if repeats < 2:
            raise ValueError(f"{item_path}.repeats must be at least 2")
        expected = item.get("expected_signature_subset", {})
        if not isinstance(expected, Mapping):
            raise ValueError(f"{item_path}.expected_signature_subset must be an object")
        cases.append(
            DriftCase(
                case_id=_required_str(item, "case_id", item_path),
                input_text=_required_str(item, "input", item_path),
                repeats=repeats,
                expected_signature_subset=expected,
            )
        )
    return _required_str(data, "fixture_id", "drift fixture"), tuple(cases)


def run_drift_checks(
    fixture_path: Path,
    *,
    output_dir: Path,
    loop_factory: Callable[[Path], AgentLoop] | None = None,
) -> DriftCheckResult:
    fixture_id, cases = load_drift_cases(fixture_path)
    case_results = tuple(
        _run_drift_case(
            case,
            fixture_id=fixture_id,
            fixture_path=fixture_path,
            output_dir=output_dir,
            loop_factory=loop_factory,
        )
        for case in cases
    )
    result = DriftCheckResult(
        schema_version=DRIFT_RESULT_SCHEMA_VERSION,
        fixture_id=fixture_id,
        case_results=case_results,
        fixture_path=str(fixture_path),
        fixture_sha256=_file_sha256(fixture_path),
    )
    payload = result.to_dict()
    assert_no_known_secret_values(payload, context="drift result")
    summary_path = output_dir / fixture_id / "drift-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _run_drift_case(
    case: DriftCase,
    *,
    fixture_id: str,
    fixture_path: Path,
    output_dir: Path,
    loop_factory: Callable[[Path], AgentLoop] | None,
) -> DriftCaseResult:
    signatures: list[Mapping[str, Any]] = []
    trace_paths: list[str] = []
    mismatches: list[str] = []
    for index in range(case.repeats):
        case_dir = output_dir / fixture_id / case.case_id / f"repeat-{index + 1}"
        loop = loop_factory(case_dir) if loop_factory else AgentLoop(
            model=MockModel(),
            run_root=case_dir / "runs",
            audit_path=case_dir / "audit.jsonl",
        )
        result = loop.run(case.input_text)
        trace = TraceRecord.from_agent_result(
            result,
            artifact_versions=_drift_artifact_versions(fixture_path),
        )
        try:
            trace_path = str(write_trace(trace, case_dir / "traces"))
            trace_paths.append(trace_path)
            trace_data = trace.to_dict()
            assert_no_known_secret_values(trace_data, context=f"drift trace {case.case_id}")
        except SecretLeakError:
            raise  # SecretLeakError must never be silenced
        signatures.append(_trace_signature(trace_data))

    first = signatures[0]
    for index, signature in enumerate(signatures[1:], start=2):
        if signature != first:
            mismatches.append(f"repeat {index} signature drifted from repeat 1")
    mismatches.extend(_compare_subset(first, case.expected_signature_subset, path="signature"))
    return DriftCaseResult(
        case_id=case.case_id,
        passed=not mismatches,
        signatures=tuple(signatures),
        mismatches=tuple(mismatches),
        trace_paths=tuple(trace_paths),
    )


def _drift_artifact_versions(fixture_path: Path) -> ArtifactVersions:
    versions = ArtifactVersions.from_manifest()
    return ArtifactVersions(
        prompt_versions=versions.prompt_versions,
        policy_versions=versions.policy_versions,
        memory_versions=versions.memory_versions,
        eval_versions={
            **versions.eval_versions,
            "drift_fixture": {
                "path": str(fixture_path),
                "version": versions.eval_versions.get("drift_fixture", {}).get("version", "1"),
            },
        },
    )


def _eval_artifact_version_mismatches(
    candidate: ImprovementCandidateRecord,
    eval_result: EvalRunResult,
) -> list[str]:
    versions = _artifact_versions_by_path(eval_result.artifact_versions)
    reasons: list[str] = []
    if not versions:
        return ["frozen eval result must include artifact_versions from the artifact manifest"]
    for artifact in candidate.affected_artifacts:
        evaluated_version = versions.get(artifact.path)
        if evaluated_version is None:
            reasons.append(f"frozen eval result missing artifact version for {artifact.path}")
        elif evaluated_version != artifact.current_version:
            reasons.append(
                f"frozen eval result version mismatch for {artifact.path}: "
                f"expected {artifact.current_version}, got {evaluated_version}"
            )
    return reasons


def _artifact_versions_by_path(artifact_versions: Mapping[str, Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for section_name in ("prompt_versions", "policy_versions", "memory_versions", "eval_versions"):
        section = artifact_versions.get(section_name)
        if not isinstance(section, Mapping):
            continue
        for record in section.values():
            if not isinstance(record, Mapping):
                continue
            path = record.get("path")
            version = record.get("version")
            if isinstance(path, str) and isinstance(version, str):
                versions[path] = version
    return versions


def _frozen_eval_result_mismatches(eval_result: EvalRunResult) -> list[str]:
    reasons: list[str] = []
    manifest = ArtifactVersions.from_manifest()
    expected_golden = manifest.eval_versions.get("golden_fixture", {})
    if expected_golden.get("path") != "artifacts/evals/golden":
        reasons.append("artifact manifest golden_fixture path must be artifacts/evals/golden")
    eval_versions = eval_result.artifact_versions.get("eval_versions")
    if not isinstance(eval_versions, Mapping):
        return ["frozen eval result must include eval_versions"]
    golden_version = eval_versions.get("golden_fixture")
    if not isinstance(golden_version, Mapping):
        reasons.append("frozen eval result must include eval_versions.golden_fixture")
    else:
        if golden_version.get("path") != expected_golden.get("path"):
            reasons.append("frozen eval result golden_fixture path must match artifact manifest")
        if golden_version.get("version") != expected_golden.get("version"):
            reasons.append("frozen eval result golden_fixture version must match artifact manifest")

    expected_cases = _frozen_eval_case_ids(Path("artifacts/evals/golden"))
    actual_cases = {
        (case.fixture_id, case.case_id)
        for case in eval_result.case_results
    }
    missing_cases = sorted(expected_cases - actual_cases)
    extra_cases = sorted(actual_cases - expected_cases)
    if missing_cases:
        reasons.append(f"frozen eval result missing fixture cases: {_format_case_ids(missing_cases)}")
    if extra_cases:
        reasons.append(f"frozen eval result includes unknown fixture cases: {_format_case_ids(extra_cases)}")
    return reasons


def _frozen_eval_case_ids(fixture_dir: Path) -> set[tuple[str, str]]:
    expected: set[tuple[str, str]] = set()
    for path in sorted(fixture_dir.glob("*.json")):
        data = _load_json(path)
        fixture_id = _required_str(data, "fixture_id", str(path))
        for index, case in enumerate(_required_list(data, "cases", str(path))):
            if not isinstance(case, Mapping):
                raise ValueError(f"{path}.cases[{index}] must be an object")
            expected.add((fixture_id, _required_str(case, "case_id", f"{path}.cases[{index}]")))
    return expected


def _format_case_ids(case_ids: list[tuple[str, str]]) -> str:
    return ", ".join(f"{fixture_id}/{case_id}" for fixture_id, case_id in case_ids)


def _drift_result_mismatches(drift_result: DriftCheckResult) -> list[str]:
    reasons: list[str] = []
    manifest = ArtifactVersions.from_manifest()
    expected = manifest.eval_versions.get("drift_fixture", {})
    expected_path = expected.get("path")
    if not isinstance(expected_path, str):
        reasons.append("artifact manifest drift_fixture path is missing")
        return reasons
    fixture_path = Path(expected_path)
    expected_fixture_id, expected_cases = load_drift_cases(fixture_path)
    if drift_result.fixture_id != expected_fixture_id:
        reasons.append("drift result fixture_id must match configured drift fixture")
    if drift_result.fixture_path != expected_path:
        reasons.append("drift result fixture_path must match artifact manifest")
    expected_hash = _file_sha256(fixture_path)
    if drift_result.fixture_sha256 != expected_hash:
        reasons.append("drift result fixture_sha256 must match configured drift fixture")
    expected_case_ids = {case.case_id for case in expected_cases}
    actual_case_ids = {case.case_id for case in drift_result.case_results}
    missing_cases = sorted(expected_case_ids - actual_case_ids)
    extra_cases = sorted(actual_case_ids - expected_case_ids)
    if missing_cases:
        reasons.append(f"drift result missing fixture cases: {', '.join(missing_cases)}")
    if extra_cases:
        reasons.append(f"drift result includes unknown fixture cases: {', '.join(extra_cases)}")
    return reasons


def _rollback_mismatches(
    candidate: ImprovementCandidateRecord,
    rollback_plan: RollbackPlan,
) -> list[str]:
    rollback_by_path = {artifact.path: artifact for artifact in rollback_plan.artifacts}
    reasons: list[str] = []
    for artifact in candidate.affected_artifacts:
        rollback = rollback_by_path.get(artifact.path)
        if rollback is None:
            continue
        if rollback.artifact_type != artifact.artifact_type:
            reasons.append(f"rollback artifact type mismatch for {artifact.path}")
        if rollback.version_before != artifact.current_version:
            reasons.append(f"rollback version_before mismatch for {artifact.path}")
        if rollback.version_after != artifact.proposed_version:
            reasons.append(f"rollback version_after mismatch for {artifact.path}")
    return reasons


def _sha256_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _intent_signature(intent: Any) -> dict[str, Any]:
    """Extract the deterministic subset of an intent for drift hashing.

    Handles two shapes:
    - IntentResult instance: use .signature_dict() directly.
    - dict with 'capabilities' key (serialized IntentResult): keep only
      capabilities, slots, primary_route; drop confidence, rationale,
      alternatives, clarification_prompt, needs_clarification.
    - Legacy UserIntent dict (no 'capabilities' key): keep all fields
      as before for backward compatibility.
    """
    if isinstance(intent, IntentResult):
        return intent.signature_dict()
    if isinstance(intent, Mapping) and "capabilities" in intent:
        return {
            "capabilities": sorted(intent.get("capabilities") or []),
            "slots": intent.get("slots"),
            "primary_route": intent.get("primary_route"),
        }
    # Legacy UserIntent path — keep existing fields unchanged.
    if not isinstance(intent, Mapping):
        return {}
    return {
        "intent_type": intent.get("intent_type"),
        "task_type": intent.get("task_type"),
        "safety_level": intent.get("safety_level"),
        "next_action": intent.get("next_action"),
    }


def _trace_signature(trace_data: Mapping[str, Any]) -> dict[str, Any]:
    tool_output = _first_tool_output(trace_data.get("events", []))
    query_plan = tool_output.get("query_plan", {}) if isinstance(tool_output, Mapping) else {}
    result_explanation = tool_output.get("result_explanation", {}) if isinstance(tool_output, Mapping) else {}
    signature = {
        "intent": _intent_signature(trace_data.get("intent")),
        "action": {
            "kind": _get_path(trace_data, ("action", "kind")),
        },
        "final_answer": {
            "next_action": _get_path(trace_data, ("final_answer", "next_action")),
        },
    }
    if query_plan:
        signature["query_plan"] = {
            "status": query_plan.get("status"),
            "selected_table_ids": query_plan.get("selected_table_ids", []),
            "proposed_sql_sha256": _sha256_text(query_plan.get("proposed_sql")),
            "dimensions": query_plan.get("dimensions", []),
            "measures": query_plan.get("measures", []),
            "assumptions": query_plan.get("assumptions", []),
            "refusal_reason": query_plan.get("refusal_reason"),
            "policy_code": _get_path(query_plan, ("policy_validation", "code")),
            "execution_status": _get_path(query_plan, ("execution", "status")),
        }
    if result_explanation:
        signature["result_explanation"] = {
            "status": result_explanation.get("status"),
            "source": result_explanation.get("source"),
            "real_database_execution": result_explanation.get("real_database_execution"),
            "sql_execution_backend": result_explanation.get("sql_execution_backend"),
            "columns": result_explanation.get("columns", []),
            "fixture_id": _get_path(result_explanation, ("adapter_response_metadata", "fixture_id")),
            "summary": result_explanation.get("summary"),
            "explanation_sha256": _sha256_text(result_explanation.get("explanation")),
        }
    return redact(signature)


def _first_tool_output(events: Any) -> Mapping[str, Any]:
    if not isinstance(events, Iterable) or isinstance(events, (str, bytes, Mapping)):
        return {}
    for event in events:
        if not isinstance(event, Mapping) or event.get("event_type") != "tool_completed":
            continue
        output = _get_path(event, ("payload", "result", "output"))
        if isinstance(output, Mapping):
            return output
    return {}


def _compare_subset(actual: Any, expected: Any, *, path: str) -> list[str]:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        mismatches: list[str] = []
        for key, expected_value in expected.items():
            if key not in actual:
                mismatches.append(f"{path}.{key}: missing")
                continue
            mismatches.extend(_compare_subset(actual[key], expected_value, path=f"{path}.{key}"))
        return mismatches
    if isinstance(expected, list):
        if actual != expected:
            return [f"{path}: expected {expected!r}, got {actual!r}"]
        return []
    if actual != expected:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def _get_path(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _require_schema(data: Mapping[str, Any], schema_version: str, label: str) -> None:
    actual = data.get("schema_version")
    if actual != schema_version:
        raise ValueError(f"{label} uses unsupported schema {actual!r}")


def _required_str(data: Mapping[str, Any], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value


def _optional_str(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string or null")
    return value


def _required_mapping(data: Mapping[str, Any], key: str, path: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}.{key} must be an object")
    return value


def _required_list(data: Mapping[str, Any], key: str, path: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{path}.{key} must be an array")
    return value


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{path} must be an array")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{path} must contain only non-empty strings")
    return tuple(value)


def _number(value: Any, path: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be a finite number")
    return number


def _one_of(value: Any, allowed: set[str], path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{path} must be one of {', '.join(sorted(allowed))}")
    return value


__all__ = [
    "DRIFT_FIXTURE_SCHEMA_VERSION",
    "DRIFT_RESULT_SCHEMA_VERSION",
    "IMPROVEMENT_CANDIDATE_SCHEMA_VERSION",
    "MEMORY_RECORD_SCHEMA_VERSION",
    "ROLLBACK_PLAN_SCHEMA_VERSION",
    "SELF_EVOLUTION_GATE_SCHEMA_VERSION",
    "ArtifactChange",
    "CandidateReview",
    "ReviewRecord",
    "DriftCase",
    "DriftCaseResult",
    "DriftCheckResult",
    "ImprovementCandidateRecord",
    "MemoryProvenance",
    "MemoryRecord",
    "RollbackArtifact",
    "RollbackPlan",
    "SelfEvolutionGateReport",
    "build_improvement_candidate",
    "compute_candidate_content_hash",
    "evaluate_self_evolution_gate",
    "load_drift_cases",
    "load_improvement_candidate",
    "load_active_memories",
    "load_memory_record",
    "load_rollback_plan",
    "run_drift_checks",
    "verify_candidate_hash",
    "write_improvement_candidate",
]

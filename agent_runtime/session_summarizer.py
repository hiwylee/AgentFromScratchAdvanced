"""Session summarizer — extracts failure patterns and proposes MemoryRecord entries.

After a session completes, ``SessionSummarizer`` scans the per-run plan-shadow
step results, groups failed verifications by ``FailureReason``, and writes
candidate ``MemoryRecord`` JSON files into a memory directory.

The written records are deliberately created with
``status="proposed"`` and ``provenance.review_status="pending"`` so that they
never bypass the self-evolution gate — ``load_active_memories()`` will only
pick them up after a human reviewer flips status/review_status to
``active``/``approved``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .self_evolution import (
    MEMORY_RECORD_SCHEMA_VERSION,
    MemoryProvenance,
    MemoryRecord,
)
from .trace import assert_no_known_secret_values


# Mapping from FailureReason -> human-readable suggested fix.
# Used as the ``value`` field for proposed MemoryRecord entries.
_FIX_MAP: dict[str, str] = {
    "tool_error": "retry with alternative tool or increase max_attempts",
    "timeout": "reduce query complexity or increase timeout_seconds budget",
    "policy_denied": "request operator approval or use read-only alternative",
    "missing_context": "inject additional schema context before query execution",
    "ambiguous_request": "add clarification step to intent classification",
    "schema_or_contract_mismatch": "update tool input schema or plan step arguments",
    "budget_exceeded": "increase cost_budget_usd or reduce step count",
    "data_mismatch": "verify expected output schema matches actual tool output",
}
_DEFAULT_FIX = "investigate failure pattern and add a targeted recovery step"


@dataclass
class FailurePattern:
    """A grouped failure observation derived from a session's run results."""

    pattern_id: str
    failure_reason: str
    query_context: str
    suggested_fix: str
    occurrence_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionSummary:
    """Output of ``SessionSummarizer.summarize()``."""

    session_id: str
    total_runs: int
    failed_runs: int
    success_rate: float
    failure_patterns: list[FailurePattern] = field(default_factory=list)
    proposed_memory_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "total_runs": self.total_runs,
            "failed_runs": self.failed_runs,
            "success_rate": self.success_rate,
            "failure_patterns": [p.to_dict() for p in self.failure_patterns],
            "proposed_memory_paths": list(self.proposed_memory_paths),
        }


class SessionSummarizer:
    """Analyzes a session's run results to extract failure patterns.

    For every distinct ``failure_reason`` encountered, it writes one proposed
    ``MemoryRecord`` JSON file into ``memory_dir``. These records are NEVER
    auto-applied — they require manual review (review_status="approved")
    before ``load_active_memories()`` will surface them.
    """

    def summarize(
        self,
        session_id: str,
        run_results: list[dict[str, Any]],
        memory_dir: Path,
        author: str = "session_summarizer",
    ) -> SessionSummary:
        """Build a ``SessionSummary`` and persist proposed MemoryRecord files.

        Args:
            session_id: identifies this session.
            run_results: list of ``AgentResult.to_dict()`` outputs.
            memory_dir: directory where proposed MemoryRecord JSON files are
                written. Created if missing.
            author: provenance author field for the written records.
        """
        total_runs = len(run_results)
        failed_runs = 0
        # Group failures by failure_reason; collect query contexts per group.
        groups: dict[str, dict[str, Any]] = {}

        for run in run_results:
            if not isinstance(run, Mapping):
                continue
            run_failed = False
            plan_shadow = run.get("plan_shadow")
            step_results = (
                plan_shadow.get("step_results")
                if isinstance(plan_shadow, Mapping)
                else None
            )
            if not isinstance(step_results, list):
                step_results = []
            query_context = _extract_query_context(run)

            for step in step_results:
                if not isinstance(step, Mapping):
                    continue
                verification = step.get("verification")
                if not isinstance(verification, Mapping):
                    continue
                if verification.get("success") is not False:
                    continue
                run_failed = True
                reason = verification.get("failure_reason")
                if not isinstance(reason, str) or not reason:
                    continue
                bucket = groups.setdefault(
                    reason,
                    {"count": 0, "contexts": []},
                )
                bucket["count"] += 1
                if query_context and query_context not in bucket["contexts"]:
                    bucket["contexts"].append(query_context)

            if run_failed:
                failed_runs += 1

        success_rate = (
            (total_runs - failed_runs) / total_runs if total_runs > 0 else 1.0
        )

        memory_dir.mkdir(parents=True, exist_ok=True)
        recorded_at = datetime.now(timezone.utc).isoformat()
        failure_patterns: list[FailurePattern] = []
        proposed_paths: list[str] = []

        # Stable iteration order for deterministic output.
        for reason in sorted(groups.keys()):
            bucket = groups[reason]
            contexts = bucket["contexts"]
            query_context = "|".join(contexts) if contexts else "unknown"
            suggested_fix = _FIX_MAP.get(reason, _DEFAULT_FIX)
            pattern_id = f"session-failure-{reason}-{uuid.uuid4().hex[:8]}"
            pattern = FailurePattern(
                pattern_id=pattern_id,
                failure_reason=reason,
                query_context=query_context,
                suggested_fix=suggested_fix,
                occurrence_count=int(bucket["count"]),
            )
            failure_patterns.append(pattern)

            record = MemoryRecord(
                schema_version=MEMORY_RECORD_SCHEMA_VERSION,
                memory_id=pattern_id,
                key=f"known_failure.{reason}",
                value=suggested_fix,
                status="proposed",
                tags=("session_summary", "failure_pattern", reason),
                provenance=MemoryProvenance(
                    source_type="self_evolution",
                    source_id=session_id,
                    author=author,
                    recorded_at=recorded_at,
                    confidence=0.6,
                    evidence=(
                        f"failure_reason={reason} in session {session_id}",
                    ),
                    scope="project",
                    expires_at=None,
                    review_status="pending",
                ),
            )
            path = memory_dir / f"{record.memory_id}.json"
            _write_memory_record(record, path)
            proposed_paths.append(str(path))

        return SessionSummary(
            session_id=session_id,
            total_runs=total_runs,
            failed_runs=failed_runs,
            success_rate=success_rate,
            failure_patterns=failure_patterns,
            proposed_memory_paths=proposed_paths,
        )


def _extract_query_context(run: Mapping[str, Any]) -> str:
    """Build a short ``intent_type+task_type`` style label for a run."""
    intent = run.get("intent")
    if not isinstance(intent, Mapping):
        return ""
    primary_route = intent.get("primary_route") or intent.get("intent_type") or ""
    task_type = intent.get("task_type") or ""
    capabilities = intent.get("capabilities")
    cap_str = ""
    if isinstance(capabilities, list) and capabilities:
        cap_str = ",".join(str(c) for c in capabilities[:3])
    parts = [str(p) for p in (primary_route, task_type, cap_str) if p]
    return "+".join(parts)


def _write_memory_record(record: MemoryRecord, path: Path) -> Path:
    """Persist a MemoryRecord to JSON, mirroring write_improvement_candidate()."""
    payload = record.to_dict()
    assert_no_known_secret_values(payload, context="memory record")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = ["FailurePattern", "SessionSummary", "SessionSummarizer"]

"""Local golden eval runner for the mock agent runtime."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .loop import AgentLoop
from .model import MockModel
from .redaction import redact
from .trace import (
    ArtifactVersions,
    SecretLeakError,
    TraceRecord,
    assert_no_known_secret_values,
    write_trace,
)


EVAL_FIXTURE_SCHEMA_VERSION = "agent-runtime.eval-fixture.v1"
EVAL_RESULT_SCHEMA_VERSION = "agent-runtime.eval-result.v1"
DEFAULT_GOLDEN_DIR = Path("artifacts/evals/golden")
DEFAULT_EVAL_OUTPUT_DIR = Path(".agent/evals/latest")


@dataclass(frozen=True)
class EvalCase:
    fixture_id: str
    case_id: str
    input_text: str
    expected: dict[str, Any]


@dataclass(frozen=True)
class EvalCaseResult:
    fixture_id: str
    case_id: str
    passed: bool
    mismatches: list[str] = field(default_factory=list)
    secret_leak_detected: bool = False
    trace_path: str = ""
    actual: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class EvalRunResult:
    schema_version: str
    fixture_dir: str
    artifact_versions: dict[str, Any]
    case_results: list[EvalCaseResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.case_results)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "fixture_dir": self.fixture_dir,
            "artifact_versions": self.artifact_versions,
            "passed": self.passed,
            "case_count": len(self.case_results),
            "case_results": [result.to_dict() for result in self.case_results],
        }
        return redact(data)


def run_golden_evals(
    fixture_dir: Path = DEFAULT_GOLDEN_DIR,
    *,
    output_dir: Path | None = None,
) -> EvalRunResult:
    artifact_versions = ArtifactVersions(
        eval_versions={
            "golden_fixture": {
                "path": str(fixture_dir),
                "version": "1",
            },
        }
    )
    run_output_dir = output_dir or DEFAULT_EVAL_OUTPUT_DIR
    run_output_dir.mkdir(parents=True, exist_ok=True)
    cases = load_eval_cases(fixture_dir)
    case_results = [
        _run_case(case, run_output_dir, artifact_versions)
        for case in cases
    ]
    result = EvalRunResult(
        schema_version=EVAL_RESULT_SCHEMA_VERSION,
        fixture_dir=str(fixture_dir),
        artifact_versions=artifact_versions.to_dict(),
        case_results=case_results,
    )
    summary = result.to_dict()
    try:
        assert_no_known_secret_values(summary, context="eval result")
    except SecretLeakError:
        case_results = [
            EvalCaseResult(
                fixture_id="eval_runner",
                case_id="summary_redaction",
                passed=False,
                mismatches=["eval result contains an unredacted known secret value"],
                secret_leak_detected=True,
            ),
            *case_results,
        ]
        result = EvalRunResult(
            schema_version=EVAL_RESULT_SCHEMA_VERSION,
            fixture_dir=str(fixture_dir),
            artifact_versions=artifact_versions.to_dict(),
            case_results=case_results,
        )
        summary = result.to_dict()
    _write_summary(summary, run_output_dir / "eval-summary.json")
    return result


def load_eval_cases(fixture_dir: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for path in sorted(fixture_dir.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        schema_version = fixture.get("schema_version")
        if schema_version != EVAL_FIXTURE_SCHEMA_VERSION:
            raise ValueError(f"{path} uses unsupported eval fixture schema: {schema_version}")
        fixture_id = _required_str(fixture, "fixture_id", path)
        for case in fixture.get("cases", []):
            cases.append(
                EvalCase(
                    fixture_id=fixture_id,
                    case_id=_required_str(case, "case_id", path),
                    input_text=_required_str(case, "input", path),
                    expected=_required_dict(case, "expected", path),
                )
            )
    if not cases:
        raise ValueError(f"no eval cases found in {fixture_dir}")
    return cases


def _run_case(
    case: EvalCase,
    output_dir: Path,
    artifact_versions: ArtifactVersions,
) -> EvalCaseResult:
    case_dir = output_dir / case.fixture_id / case.case_id
    loop = AgentLoop(
        model=MockModel(),
        run_root=case_dir / "runs",
        audit_path=case_dir / "audit.jsonl",
    )
    result = loop.run(case.input_text)
    trace = TraceRecord.from_agent_result(result, artifact_versions=artifact_versions)
    trace_path = ""
    mismatches: list[str] = []
    secret_leak_detected = False
    try:
        trace_path = str(write_trace(trace, case_dir / "traces"))
        actual = {
            "input": case.input_text,
            "intent": result.intent,
            "action": result.action,
            "final_answer": result.final_answer,
            "trace_path": trace_path,
        }
        actual = redact(actual)
        assert_no_known_secret_values(trace.to_dict(), context=f"trace {case.case_id}")
        assert_no_known_secret_values(actual, context=f"eval case {case.case_id}")
    except SecretLeakError:
        secret_leak_detected = True
        actual = redact({
            "input": case.input_text,
            "intent": result.intent,
            "action": result.action,
            "final_answer": result.final_answer,
            "trace_path": trace_path,
        })
        mismatches.append("trace or eval output contains an unredacted known secret value")

    mismatches.extend(_compare_expected(actual, redact(case.expected)))
    return EvalCaseResult(
        fixture_id=case.fixture_id,
        case_id=case.case_id,
        passed=not mismatches and not secret_leak_detected,
        mismatches=mismatches,
        secret_leak_detected=secret_leak_detected,
        trace_path=trace_path,
        actual=actual,
    )


def _compare_expected(actual: Any, expected: Any, path: str = "actual") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        mismatches: list[str] = []
        for key, expected_value in expected.items():
            if key not in actual:
                mismatches.append(f"{path}.{key}: missing")
                continue
            mismatches.extend(_compare_expected(actual[key], expected_value, f"{path}.{key}"))
        return mismatches
    if actual != expected:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def _required_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} requires non-empty string field {key!r}")
    return value


def _required_dict(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{path} requires object field {key!r}")
    return value


def _write_summary(summary: dict[str, Any], path: Path) -> None:
    assert_no_known_secret_values(summary, context="eval summary")
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

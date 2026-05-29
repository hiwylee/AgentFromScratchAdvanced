"""Command-line interface for the prototype agent."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Sequence

from . import __version__
from .audit import RunRecord, append_audit
from .loop import AgentLoop
from .model import MockModel, OpenAIResponsesConfig, OpenAIResponsesModel
from .monitor import latest_status
from .oracle_adw import (
    OracleAdwConfig,
    PROTECTED_WORKING_USER_NAMES,
    SH_REQUIRED_TABLES,
    SqlclReadOnlyExecutionSettings,
    validate_read_only_sql,
    verify_sqlcl,
    verify_wallet_paths,
)
from .redaction import redact
from .self_evolution import (
    ArtifactChange,
    CandidateReview,
    approve_candidate,
    build_improvement_candidate,
    load_improvement_candidate,
    reject_candidate,
    write_improvement_candidate,
)
from .sql_execution import SqlExecutionRequest, SqlclReadOnlyAdapter
from .sqlcl_runner import SqlclSubprocessRequest, run_sqlcl_subprocess
from .trace import SecretLeakError
from .types import Budget, utc_now
from .workflow import WorkflowEngine


DEFAULT_RUN_DIR = Path(".agent/runs")
DEFAULT_AUDIT_PATH = Path(".agent/audit.jsonl")
ADW_SMOKE_SQL = "select 1 as smoke_check from dual"
MAX_OPERATOR_SQL_BYTES = 16_384
MAX_ADMIN_PROVISION_STDOUT_BYTES = 1_048_576
MAX_ADMIN_PROVISION_STDERR_BYTES = 65_536
ADMIN_PROVISION_DRIFT_ROLES = ("DBA", "PDB_DBA", "RESOURCE")
ADMIN_PROVISION_DRIFT_SYS_PRIVILEGES = (
    "ALTER ANY TABLE",
    "CREATE ANY TABLE",
    "CREATE TABLE",
    "DELETE ANY TABLE",
    "DROP ANY TABLE",
    "INSERT ANY TABLE",
    "UPDATE ANY TABLE",
)
ADMIN_PRODUCTION_DRIFT_EXTRA_ROLES = ("DWROLE",)
ADMIN_PRODUCTION_DRIFT_EXTRA_SYS_PRIVILEGES = ("SELECT ANY TABLE",)


def main(argv: Sequence[str] | None = None) -> int:
    _load_local_env(Path(".env"))
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="analyze a user request")
    ask_parser.add_argument("text", nargs="+", help="user request text")
    ask_parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    ask_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    ask_parser.add_argument("--max-steps", type=int, default=4)
    ask_parser.add_argument("--timeout-seconds", type=int, default=30)
    ask_parser.add_argument(
        "--model-provider",
        default=_default_model_provider(),
        help="action model provider: mock, openai, or oci; defaults to AGENT_MODEL_PROVIDER, LLM, or mock",
    )
    ask_parser.add_argument(
        "--openai-model",
        default=None,
        help="model id for OpenAI-compatible providers; defaults to provider env",
    )
    ask_parser.add_argument(
        "--openai-base-url",
        default=None,
        help="OpenAI-compatible base URL ending in /v1; defaults to provider env",
    )
    ask_parser.add_argument(
        "--openai-timeout-seconds",
        type=float,
        default=None,
        help="OpenAI-compatible request timeout; defaults to provider env or 30",
    )
    ask_parser.add_argument(
        "--memory-dir",
        default=None,
        help="directory for cross-session memory records; enables session summarization on completion",
    )
    ask_parser.add_argument(
        "--allow-real-query",
        action="store_true",
        default=False,
        help="operator flag: allow adw_query tool to execute real read-only SQL (requires ADW credentials)",
    )

    status_parser = subparsers.add_parser("status", help="show latest run status")
    status_parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))

    workflow_parser = subparsers.add_parser("workflow", help="run or resume a mock workflow")
    workflow_parser.add_argument("text", nargs="*", help="workflow request text (omit when using 'resume' subcommand)")
    workflow_parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    workflow_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    workflow_parser.add_argument("--run-id", default=None, help="run-id of a paused workflow (for resume)")
    workflow_parser.add_argument(
        "--decision",
        default=None,
        choices=("approve_load", "reject_workflow", "request_manual_correction"),
        help="human decision for resume",
    )
    workflow_parser.add_argument("--actor", default=None, help="reviewer name for resume")
    workflow_parser.add_argument("--reason", default="", help="reason/notes for resume")

    tacit_parser = subparsers.add_parser("tacit", help="tacit knowledge — list, reflect, and extract heuristics from verification episodes")
    tacit_subparsers = tacit_parser.add_subparsers(dest="tacit_command", required=True)

    tacit_list_parser = tacit_subparsers.add_parser("list", help="list all verification episodes")
    tacit_list_parser.add_argument(
        "--episodes-dir",
        default="artifacts/verification-episodes",
        help="directory containing verification episode JSONL files",
    )

    tacit_reflect_parser = tacit_subparsers.add_parser("reflect", help="run ReflectionAgent on a specific episode")
    tacit_reflect_parser.add_argument("--episode-id", required=True, help="episode UUID to reflect on")
    tacit_reflect_parser.add_argument(
        "--episodes-dir",
        default="artifacts/verification-episodes",
        help="directory containing verification episode JSONL files",
    )

    tacit_heuristics_parser = tacit_subparsers.add_parser("heuristics", help="extract and deduplicate all heuristics from all episodes")
    tacit_heuristics_parser.add_argument(
        "--episodes-dir",
        default="artifacts/verification-episodes",
        help="directory containing verification episode JSONL files",
    )

    operator_parser = subparsers.add_parser("operator", help="operator-only commands")
    operator_subparsers = operator_parser.add_subparsers(
        dest="operator_command",
        required=True,
    )
    adw_smoke_parser = operator_subparsers.add_parser(
        "adw-smoke",
        help="run the fixed Oracle ADW read-only SQLcl smoke query",
    )
    adw_smoke_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    adw_smoke_parser.add_argument("--timeout-seconds", type=int, default=15)
    adw_smoke_parser.add_argument("--max-output-bytes", type=int, default=4096)
    adw_smoke_parser.add_argument("--max-error-bytes", type=int, default=4096)
    adw_smoke_parser.add_argument(
        "--confirm-live-adw-smoke",
        action="store_true",
        help="explicitly allow this operator-only live ADW smoke query",
    )
    adw_query_parser = operator_subparsers.add_parser(
        "adw-query",
        help="run an operator-only Oracle ADW read-only SQLcl query",
    )
    sql_source = adw_query_parser.add_mutually_exclusive_group(required=True)
    sql_source.add_argument("--sql", help="single read-only SQL statement to run")
    sql_source.add_argument("--sql-file", help="path to a UTF-8 file with one read-only SQL statement")
    sql_source.add_argument(
        "--sql-stdin",
        action="store_true",
        help="read one read-only SQL statement from stdin",
    )
    adw_query_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    adw_query_parser.add_argument("--timeout-seconds", type=int, default=30)
    adw_query_parser.add_argument("--row-limit", type=int, default=100)
    adw_query_parser.add_argument("--max-output-bytes", type=int, default=1_048_576)
    adw_query_parser.add_argument("--max-error-bytes", type=int, default=65_536)
    adw_query_parser.add_argument(
        "--confirm-live-adw-query",
        action="store_true",
        help="explicitly allow this operator-only live ADW read-only query",
    )
    admin_provision_parser = operator_subparsers.add_parser(
        "adw-provision-working-user",
        help="operator-only ADW admin provisioning for the configured working user",
    )
    admin_provision_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    admin_provision_parser.add_argument("--timeout-seconds", type=int, default=60)
    admin_provision_parser.add_argument(
        "--grant-profile",
        choices=("prototype-any-table-read", "production-sh-read"),
        required=True,
        help=(
            "explicit grant profile to apply; "
            "prototype-any-table-read grants DWROLE and SELECT ANY TABLE; "
            "production-sh-read grants only CREATE SESSION and object-level SELECT on SH tables"
        ),
    )
    admin_provision_parser.add_argument(
        "--confirm-live-adw-admin-provision",
        action="store_true",
        help="explicitly allow this operator-only admin provisioning action",
    )
    improvement_parser = operator_subparsers.add_parser(
        "propose-improvement",
        help="record a proposed self-evolution improvement candidate",
    )
    improvement_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    improvement_parser.add_argument(
        "--output-dir",
        default="artifacts/improvement-candidates",
        help="directory for candidate JSON artifacts",
    )
    improvement_parser.add_argument("--candidate-id", required=True)
    improvement_parser.add_argument(
        "--candidate-type",
        required=True,
        choices=("prompt", "policy", "memory", "eval", "schema_context", "docs"),
    )
    improvement_parser.add_argument("--trigger-type", required=True)
    improvement_parser.add_argument("--summary", required=True)
    improvement_parser.add_argument("--proposed-change", required=True)
    improvement_parser.add_argument(
        "--affected-artifact",
        action="append",
        nargs=4,
        metavar=("PATH", "TYPE", "CURRENT_VERSION", "PROPOSED_VERSION"),
        required=True,
        help="affected artifact tuple; repeat for multiple artifacts",
    )
    improvement_parser.add_argument("--source-type", required=True)
    improvement_parser.add_argument("--source-id", required=True)
    improvement_parser.add_argument("--author", default=getpass.getuser())
    improvement_parser.add_argument("--confidence", type=float, default=0.5)
    improvement_parser.add_argument("--evidence", action="append", default=[])
    improvement_parser.add_argument("--risk-level", default="medium")
    improvement_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing candidate artifact with the same id",
    )

    review_parser = operator_subparsers.add_parser(
        "review-candidate",
        help="list, show, approve, or reject improvement candidates",
    )
    review_parser.add_argument(
        "operation",
        choices=("list", "show", "approve", "reject"),
        help="operation to perform",
    )
    review_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    review_parser.add_argument(
        "--candidates-dir",
        default="artifacts/improvement-candidates",
        help="directory containing candidate JSON artifacts",
    )
    review_parser.add_argument("--candidate-id", default=None, help="candidate id to act on")
    review_parser.add_argument("--reviewer", default=None, help="reviewer name")
    review_parser.add_argument("--notes", default="", help="reviewer notes (for reject)")
    review_parser.add_argument(
        "--status",
        default=None,
        choices=("proposed", "accepted", "rejected", "superseded"),
        help="filter candidates by status (list operation only)",
    )

    args = parser.parse_args(argv)

    if args.command == "tacit":
        return _cmd_tacit(args)

    if args.command == "ask":
        return _ask(
            args.text,
            Path(args.run_dir),
            Path(args.audit_log),
            Budget(max_steps=args.max_steps, timeout_seconds=args.timeout_seconds),
            model_provider=args.model_provider,
            openai_model=args.openai_model,
            openai_base_url=args.openai_base_url,
            openai_timeout_seconds=args.openai_timeout_seconds,
            memory_dir=Path(args.memory_dir) if args.memory_dir else None,
            allow_real_query=getattr(args, "allow_real_query", False),
        )
    if args.command == "status":
        return _status(Path(args.run_dir))
    if args.command == "workflow":
        if args.text and args.text[0] == "resume":
            return _cmd_workflow_resume(args, Path(args.run_dir), Path(args.audit_log))
        return _workflow(args.text, Path(args.run_dir), Path(args.audit_log))
    if args.command == "operator" and args.operator_command == "adw-smoke":
        return _operator_adw_smoke(
            audit_path=Path(args.audit_log),
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes,
            max_error_bytes=args.max_error_bytes,
            confirm_live_adw_smoke=args.confirm_live_adw_smoke,
        )
    if args.command == "operator" and args.operator_command == "adw-query":
        return _operator_adw_query(
            sql=args.sql,
            sql_file=args.sql_file,
            sql_stdin=args.sql_stdin,
            audit_path=Path(args.audit_log),
            timeout_seconds=args.timeout_seconds,
            row_limit=args.row_limit,
            max_output_bytes=args.max_output_bytes,
            max_error_bytes=args.max_error_bytes,
            confirm_live_adw_query=args.confirm_live_adw_query,
        )
    if args.command == "operator" and args.operator_command == "adw-provision-working-user":
        return _operator_adw_provision_user(
            audit_path=Path(args.audit_log),
            timeout_seconds=args.timeout_seconds,
            grant_profile=args.grant_profile,
            confirm_admin_provision=args.confirm_live_adw_admin_provision,
        )
    if args.command == "operator" and args.operator_command == "propose-improvement":
        return _operator_propose_improvement(
            audit_path=Path(args.audit_log),
            output_dir=Path(args.output_dir),
            candidate_id=args.candidate_id,
            candidate_type=args.candidate_type,
            trigger_type=args.trigger_type,
            summary=args.summary,
            proposed_change=args.proposed_change,
            affected_artifacts=args.affected_artifact,
            source_type=args.source_type,
            source_id=args.source_id,
            author=args.author,
            confidence=args.confidence,
            evidence=args.evidence,
            risk_level=args.risk_level,
            overwrite=args.overwrite,
        )

    if args.command == "operator" and args.operator_command == "review-candidate":
        return _cmd_review_candidate(args, Path(args.audit_log))

    parser.error(f"unknown command: {args.command}")
    return 2


def _ask(
    text_parts: Sequence[str],
    run_dir: Path,
    audit_path: Path,
    budget: Budget,
    *,
    model_provider: str,
    openai_model: str | None,
    openai_base_url: str | None,
    openai_timeout_seconds: float | None,
    memory_dir: Path | None = None,
    allow_real_query: bool = False,
) -> int:
    user_text = " ".join(text_parts)
    try:
        model = _build_action_model(
            provider=model_provider,
            openai_model=openai_model,
            openai_base_url=openai_base_url,
            openai_timeout_seconds=openai_timeout_seconds,
        )
    except ValueError as exc:
        normalized_provider = model_provider.strip().casefold()
        payload = {
            "state": "configuration_required",
            "provider": normalized_provider,
            "error": str(exc),
            "required_environment": _required_provider_environment(normalized_provider),
        }
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 2

    loop = AgentLoop(
        run_root=run_dir,
        audit_path=audit_path,
        budget=budget,
        model=model,
        memory_dir=memory_dir,  # load approved memories AND write proposed ones
        allow_real_query=allow_real_query,
    )
    result = loop.run(user_text)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if memory_dir is not None:
        summary = loop.summarize_session(
            run_results=[result.to_dict()],
            memory_dir=memory_dir,
            session_id=result.run_id,
        )
        if summary is not None and summary.failure_patterns:
            print(f"[session] {len(summary.failure_patterns)} failure pattern(s) captured → review at {memory_dir}")
            for path in summary.proposed_memory_paths:
                print(f"[session] proposed: {path}")
    return 0


def _build_action_model(
    *,
    provider: str,
    openai_model: str | None,
    openai_base_url: str | None,
    openai_timeout_seconds: float | None,
):
    normalized_provider = provider.strip().casefold()
    if normalized_provider == "mock":
        return MockModel()
    if normalized_provider == "openai":
        config = OpenAIResponsesConfig.from_env(
            model=openai_model,
            base_url=openai_base_url,
            timeout_seconds=openai_timeout_seconds,
        )
        return OpenAIResponsesModel(config)
    if normalized_provider == "oci":
        config = OpenAIResponsesConfig.from_oci_env(
            model=openai_model,
            base_url=openai_base_url,
            timeout_seconds=openai_timeout_seconds,
        )
        return OpenAIResponsesModel(config)
    raise ValueError("model provider must be one of: mock, openai, oci.")


def _required_provider_environment(provider: str) -> list[str]:
    if provider == "openai":
        return ["OPENAI_API_KEY"]
    if provider == "oci":
        return ["OCI_BASE_URL", "OCI_API_KEY or OCI_API_KEY_2"]
    return []


def _default_model_provider() -> str:
    return (
        os.environ.get("AGENT_MODEL_PROVIDER")
        or os.environ.get("LLM")
        or "mock"
    )


def _load_local_env(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _status(run_dir: Path) -> int:
    status = latest_status(run_dir)
    if status is None:
        print(json.dumps({"state": "no_runs", "run_dir": str(run_dir)}, indent=2))
        return 1
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def _workflow(text_parts: Sequence[str], run_dir: Path, audit_path: Path) -> int:
    user_text = " ".join(text_parts)
    if not _is_supported_workflow_request(user_text):
        print(
            json.dumps(
                redact({
                    "state": "unsupported_workflow",
                    "request_text": user_text,
                    "supported_workflows": ["patent_asset_replacement_registration"],
                }),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    # Milestone 2A supports the patent asset workflow as the first mock template.
    engine = WorkflowEngine(run_root=run_dir, audit_path=audit_path)
    result = engine.run_patent_asset_replacement(period="current_month")
    result["request_text"] = user_text
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))
    return 0


def _is_supported_workflow_request(text: str) -> bool:
    return "특허" in text and "대체" in text and "등록" in text


def _cmd_workflow_resume(
    args: argparse.Namespace,
    run_dir: Path,
    audit_path: Path,
) -> int:
    from .workflow import HumanDecision, WorkflowEngine

    run_id = args.run_id
    decision_action = args.decision
    actor = args.actor or ""
    reason = args.reason or ""

    if not run_id:
        print("error: --run-id is required for workflow resume", file=sys.stderr)
        return 1
    if not decision_action:
        print("error: --decision is required for workflow resume", file=sys.stderr)
        return 1
    if not actor.strip():
        print("error: --actor must not be empty", file=sys.stderr)
        return 1

    engine = WorkflowEngine(run_root=run_dir, audit_path=audit_path)
    checkpoint = engine.load_checkpoint_from_disk(run_id)
    if checkpoint is None:
        print(
            json.dumps(redact({
                "state": "blocked",
                "reason": "trusted_checkpoint_not_found",
                "run_id": run_id,
                "run_dir": str(run_dir),
            }), ensure_ascii=False, indent=2),
        )
        return 2

    engine._checkpoint_store[run_id] = checkpoint  # pre-load for resume

    trusted_checkpoint = checkpoint.get("checkpoint", {})
    if decision_action == "approve_load":
        checkpoint_identity = trusted_checkpoint.get("identity", "")
        checkpoint_hash = trusted_checkpoint.get("hash", "")
        approved_record_ids = tuple(trusted_checkpoint.get("record_ids", []))
    else:
        checkpoint_identity = ""
        checkpoint_hash = ""
        approved_record_ids = ()

    decision = HumanDecision(
        actor=actor,
        action=decision_action,
        policy_basis=reason or decision_action,
        approved_record_ids=approved_record_ids,
        checkpoint_identity=checkpoint_identity,
        checkpoint_hash=checkpoint_hash,
    )

    result = engine.resume_with_human_decision(run_id=run_id, decision=decision)
    print(json.dumps(redact(result), ensure_ascii=False, indent=2))
    _append_operator_audit(
        audit_path,
        "workflow.resume",
        redact({
            "run_id": run_id,
            "decision": decision_action,
            "actor": actor,
            "reason": reason,
            "result_state": result.get("state"),
        }),
    )
    return 0 if result.get("state") in {"completed", "closed"} else 2


def _operator_adw_smoke(
    *,
    audit_path: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    max_error_bytes: int,
    confirm_live_adw_smoke: bool,
) -> int:
    if not confirm_live_adw_smoke:
        payload = _operator_live_state_payload(
            state="confirmation_required",
            command="operator adw-smoke",
            requested=False,
            attempted=False,
            succeeded=False,
            extra={"required_flag": "--confirm-live-adw-smoke"},
        )
        _append_operator_audit(audit_path, "operator.adw_smoke", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    config = OracleAdwConfig.from_env()
    limit_error = _validate_operator_adw_limits(
        timeout_seconds=timeout_seconds,
        row_limit=1,
        max_output_bytes=max_output_bytes,
        max_error_bytes=max_error_bytes,
    )
    if limit_error is not None:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-smoke",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={"error": limit_error, "config": config.redacted_status()},
        )
        _append_operator_audit(audit_path, "operator.adw_smoke", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    config_error = _validate_operator_adw_config(config)
    if config_error is not None:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-smoke",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={"error": config_error, "config": config.redacted_status()},
        )
        _append_operator_audit(audit_path, "operator.adw_smoke", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    sqlcl_status = verify_sqlcl(config)
    if not sqlcl_status.ok:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-smoke",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={
                "error": {
                    "code": "sqlcl_verification_failed",
                    "message": "SQLcl verification failed before live ADW smoke.",
                    "status": sqlcl_status.to_redacted_dict(),
                },
                "config": config.redacted_status(),
            },
        )
        _append_operator_audit(audit_path, "operator.adw_smoke", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    settings = SqlclReadOnlyExecutionSettings(
        timeout_seconds=timeout_seconds,
        row_limit=1,
        max_output_bytes=max_output_bytes,
        max_error_bytes=max_error_bytes,
    )
    adapter = SqlclReadOnlyAdapter(
        config,
        settings=settings,
        allow_real_execution=True,
    )
    response = adapter.execute(
        SqlExecutionRequest(
            sql=ADW_SMOKE_SQL,
            purpose="operator_live_adw_smoke",
            metadata={"operator_command": "adw-smoke"},
        )
    )
    response_dict = response.to_redacted_dict()
    live_execution_attempted = (
        response.backend_metadata.get("execution_state") == "executed"
    )
    payload = _operator_live_state_payload(
        state="succeeded" if response.ok else response.status,
        command="operator adw-smoke",
        requested=True,
        attempted=live_execution_attempted,
        succeeded=response.ok,
        extra={
            "smoke_sql_sha256": response.backend_metadata.get("sql_sha256"),
            "response": response_dict,
        },
    )
    _append_operator_audit(audit_path, "operator.adw_smoke", _operator_query_audit_payload(payload))
    print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
    return 0 if response.ok else 1


def _operator_adw_query(
    *,
    sql: str | None,
    sql_file: str | None,
    sql_stdin: bool,
    audit_path: Path,
    timeout_seconds: int,
    row_limit: int,
    max_output_bytes: int,
    max_error_bytes: int,
    confirm_live_adw_query: bool,
) -> int:
    if not confirm_live_adw_query:
        payload = _operator_live_state_payload(
            state="confirmation_required",
            command="operator adw-query",
            requested=False,
            attempted=False,
            succeeded=False,
            extra={"required_flag": "--confirm-live-adw-query"},
        )
        _append_operator_audit(audit_path, "operator.adw_query", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    sql_text, sql_source_kind, sql_error = _load_operator_sql(
        sql=sql,
        sql_file=sql_file,
        sql_stdin=sql_stdin,
    )
    config = OracleAdwConfig.from_env()
    if sql_error is not None:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-query",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={"error": sql_error, "config": config.redacted_status()},
        )
        _append_operator_audit(audit_path, "operator.adw_query", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1
    assert sql_text is not None
    assert sql_source_kind is not None

    sql_sha256 = hashlib.sha256(sql_text.strip().encode("utf-8")).hexdigest()
    policy = validate_read_only_sql(sql_text)
    if not policy.allowed:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-query",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={
                "sql_sha256": sql_sha256,
                "sql_source": sql_source_kind,
                "policy": {
                    "allowed": policy.allowed,
                    "code": policy.code,
                    "reason": policy.reason,
                },
                "config": config.redacted_status(),
            },
        )
        _append_operator_audit(audit_path, "operator.adw_query", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    limit_error = _validate_operator_adw_limits(
        timeout_seconds=timeout_seconds,
        row_limit=row_limit,
        max_output_bytes=max_output_bytes,
        max_error_bytes=max_error_bytes,
    )
    if limit_error is not None:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-query",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={
                "sql_sha256": sql_sha256,
                "sql_source": sql_source_kind,
                "error": limit_error,
                "config": config.redacted_status(),
            },
        )
        _append_operator_audit(audit_path, "operator.adw_query", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    config_error = _validate_operator_adw_config(config)
    if config_error is not None:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-query",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={
                "sql_sha256": sql_sha256,
                "sql_source": sql_source_kind,
                "error": config_error,
                "config": config.redacted_status(),
            },
        )
        _append_operator_audit(audit_path, "operator.adw_query", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    sqlcl_status = verify_sqlcl(config)
    if not sqlcl_status.ok:
        payload = _operator_live_state_payload(
            state="rejected",
            command="operator adw-query",
            requested=True,
            attempted=False,
            succeeded=False,
            extra={
                "sql_sha256": sql_sha256,
                "sql_source": sql_source_kind,
                "error": {
                    "code": "sqlcl_verification_failed",
                    "message": "SQLcl verification failed before live ADW query.",
                    "status": sqlcl_status.to_redacted_dict(),
                },
                "config": config.redacted_status(),
            },
        )
        _append_operator_audit(audit_path, "operator.adw_query", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    settings = SqlclReadOnlyExecutionSettings(
        timeout_seconds=timeout_seconds,
        row_limit=row_limit,
        max_output_bytes=max_output_bytes,
        max_error_bytes=max_error_bytes,
    )
    adapter = SqlclReadOnlyAdapter(
        config,
        settings=settings,
        allow_real_execution=True,
    )
    response = adapter.execute(
        SqlExecutionRequest(
            sql=sql_text,
            purpose="operator_live_adw_read_only_query",
            metadata={
                "operator_command": "adw-query",
                "sql_source": sql_source_kind,
            },
        )
    )
    response_dict = response.to_redacted_dict()
    live_execution_attempted = (
        response.backend_metadata.get("execution_state") == "executed"
    )
    payload = _operator_live_state_payload(
        state="succeeded" if response.ok else response.status,
        command="operator adw-query",
        requested=True,
        attempted=live_execution_attempted,
        succeeded=response.ok,
        extra={
            "sql_sha256": response.backend_metadata.get("sql_sha256", sql_sha256),
            "sql_source": sql_source_kind,
            "response": response_dict,
        },
    )
    _append_operator_audit(
        audit_path,
        "operator.adw_query",
        _operator_query_audit_payload(payload),
    )
    print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
    return 0 if response.ok else 1


def _operator_adw_provision_user(
    *,
    audit_path: Path,
    timeout_seconds: int,
    grant_profile: str,
    confirm_admin_provision: bool,
) -> int:
    command = "operator adw-provision-working-user"
    requested_privileges = _admin_requested_privileges(grant_profile=grant_profile)
    if not confirm_admin_provision:
        payload = {
            "state": "confirmation_required",
            "command": command,
            "required_flag": "--confirm-live-adw-admin-provision",
            "admin_execution_requested": False,
            "admin_execution_attempted": False,
            "admin_execution_succeeded": False,
            "grant_profile": grant_profile,
            "requested_privileges": requested_privileges,
        }
        _append_operator_audit(audit_path, "operator.adw_provision_working_user", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    config = OracleAdwConfig.from_env()
    validation_error = _validate_operator_admin_provision_config(
        config,
        timeout_seconds=timeout_seconds,
    )
    if validation_error is not None:
        payload = {
            "state": "rejected",
            "command": command,
            "admin_execution_requested": True,
            "admin_execution_attempted": False,
            "admin_execution_succeeded": False,
            "grant_profile": grant_profile,
            "requested_privileges": requested_privileges,
            "error": validation_error,
            "config": config.redacted_status(),
        }
        _append_operator_audit(audit_path, "operator.adw_provision_working_user", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    sqlcl_status = verify_sqlcl(config)
    if not sqlcl_status.ok:
        payload = {
            "state": "rejected",
            "command": command,
            "admin_execution_requested": True,
            "admin_execution_attempted": False,
            "admin_execution_succeeded": False,
            "grant_profile": grant_profile,
            "requested_privileges": requested_privileges,
            "error": {
                "code": "sqlcl_verification_failed",
                "message": "SQLcl verification failed before admin provisioning.",
                "status": sqlcl_status.to_redacted_dict(),
            },
            "config": config.redacted_status(),
        }
        _append_operator_audit(audit_path, "operator.adw_provision_working_user", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    completed = _run_admin_provision_sqlcl(
        config,
        timeout_seconds=timeout_seconds,
        grant_profile=grant_profile,
    )
    runner_succeeded = completed["status"] == "completed"
    classification = _classify_admin_provisioning_result(
        config=config,
        grant_profile=grant_profile,
        completed=completed,
    )
    provisioning_succeeded = _admin_provisioning_classification_is_compliant_success(classification)
    state = "succeeded" if provisioning_succeeded else "failed"
    if classification["classification"] == "rejected_drift":
        state = "rejected"
    actions_applied = completed.get("actions_applied", [])
    admin_apply_attempted = bool(actions_applied)
    payload = {
        "state": state,
        "command": command,
        "admin_execution_requested": True,
        "admin_execution_attempted": admin_apply_attempted,
        "admin_execution_succeeded": provisioning_succeeded,
        "runner_succeeded": runner_succeeded,
        "provisioning_succeeded": provisioning_succeeded,
        "admin_metadata_inspection_attempted": True,
        "admin_apply_attempted": admin_apply_attempted,
        "working_user": _safe_oracle_identifier(config.db_user or ""),
        "grant_profile": grant_profile,
        "requested_privileges": requested_privileges,
        "provisioning_classification": classification["classification"],
        "provisioning_outcome": classification["classification"],
        "provisioning_state": classification["state"],
        "actions_applied": actions_applied,
        "runner_status": completed["status"],
        "returncode": completed["returncode"],
        "stdout_bytes": completed["stdout_bytes"],
        "stderr_bytes": completed["stderr_bytes"],
        "stdout": completed["stdout"],
        "stderr": completed["stderr"],
    }
    _append_operator_audit(
        audit_path,
        "operator.adw_provision_working_user",
        {
            **payload,
            "stdout": "[REDACTED_SQLCL_OUTPUT]",
            "stderr": "[REDACTED_SQLCL_OUTPUT]",
        },
    )
    print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
    return 0 if provisioning_succeeded else 1


def _admin_provisioning_classification_is_compliant_success(
    classification: dict[str, object],
) -> bool:
    classification_name = classification.get("classification")
    if classification_name not in {
        "already_compliant",
        "created",
        "granted_missing_privileges",
    }:
        return False
    state = classification.get("state")
    if not isinstance(state, dict):
        return False
    active_prefix = state.get("active_prefix")
    if not isinstance(active_prefix, str):
        return False
    active_state = state.get(active_prefix)
    if not isinstance(active_state, dict):
        return False
    return active_state.get("compliant") is True


def _operator_propose_improvement(
    *,
    audit_path: Path,
    output_dir: Path,
    candidate_id: str,
    candidate_type: str,
    trigger_type: str,
    summary: str,
    proposed_change: str,
    affected_artifacts: Sequence[Sequence[str]],
    source_type: str,
    source_id: str,
    author: str,
    confidence: float,
    evidence: Sequence[str],
    risk_level: str,
    overwrite: bool,
) -> int:
    command = "operator propose-improvement"
    try:
        safe_name = _safe_improvement_candidate_filename(candidate_id)
        artifacts = tuple(
            ArtifactChange.from_dict(
                {
                    "path": artifact[0],
                    "artifact_type": artifact[1],
                    "current_version": artifact[2],
                    "proposed_version": artifact[3],
                },
                path=f"affected_artifacts[{index}]",
            )
            for index, artifact in enumerate(affected_artifacts)
        )
        candidate = build_improvement_candidate(
            candidate_id=candidate_id,
            candidate_type=candidate_type,  # type: ignore[arg-type]
            trigger_type=trigger_type,
            summary=summary,
            proposed_change=proposed_change,
            affected_artifacts=artifacts,
            source_type=source_type,
            source_id=source_id,
            author=author,
            confidence=confidence,
            evidence=evidence,
            risk_level=risk_level,
        )
        output_path = output_dir / f"{safe_name}.json"
        write_improvement_candidate(candidate, output_path, overwrite=overwrite)
    except (FileExistsError, SecretLeakError, ValueError) as exc:
        payload = {
            "state": "rejected",
            "command": command,
            "candidate_id": candidate_id,
            "error": {
                "code": "invalid_improvement_candidate",
                "message": str(exc),
            },
        }
        _append_operator_audit(audit_path, "operator.improvement_candidate", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1
    except OSError as exc:
        payload = {
            "state": "failed",
            "command": command,
            "candidate_id": candidate_id,
            "error": {
                "code": "candidate_write_failed",
                "message": f"candidate artifact could not be written: {exc.__class__.__name__}.",
            },
        }
        _append_operator_audit(audit_path, "operator.improvement_candidate", payload)
        print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
        return 1

    payload = {
        "state": "recorded",
        "command": command,
        "candidate_path": str(output_path),
        "candidate": candidate.to_dict(),
        "acceptance_gate_state": "not_run",
        "applied": False,
    }
    _append_operator_audit(audit_path, "operator.improvement_candidate", payload)
    print(json.dumps(redact(payload), ensure_ascii=False, indent=2))
    return 0


def _safe_improvement_candidate_filename(candidate_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", candidate_id):
        raise ValueError(
            "candidate_id must be 1-128 characters using only letters, numbers, dot, underscore, or hyphen"
        )
    return candidate_id


def _validate_operator_adw_config(
    config: OracleAdwConfig,
) -> dict[str, object] | None:
    if not config.sqlcl_path:
        return {
            "code": "sqlcl_path_required",
            "message": "SQLCL_PATH is required for operator ADW execution.",
        }
    sqlcl_path = Path(config.sqlcl_path).expanduser()
    if not sqlcl_path.is_absolute():
        return {
            "code": "sqlcl_path_must_be_absolute",
            "message": "SQLCL_PATH must be an absolute path for live ADW execution.",
        }
    if not config.db_user:
        return {
            "code": "db_user_required",
            "message": "DB_USER is required for operator ADW execution.",
        }
    if not config.db_user_pass:
        return {
            "code": "db_user_pass_required",
            "message": "DB_USER_PASS is required for operator ADW execution.",
        }
    if not config.db_dsn:
        return {
            "code": "db_dsn_required",
            "message": "DB_DSN is required for operator ADW execution.",
        }
    if not _is_tns_alias(config.db_dsn):
        return {
            "code": "db_dsn_must_be_tns_alias",
            "message": "Operator ADW execution requires DB_DSN to be a wallet TNS alias.",
        }
    if not config.db_wallet_path:
        return {
            "code": "db_wallet_path_required",
            "message": "DB_WALLET_PATH is required for operator ADW execution.",
        }
    wallet_status = verify_wallet_paths(config)
    if not wallet_status.wallet_path_is_dir:
        return {
            "code": "db_wallet_path_invalid",
            "message": "DB_WALLET_PATH must point to an existing wallet directory.",
            "wallet": wallet_status.to_redacted_dict(),
        }
    return None


def _validate_operator_admin_provision_config(
    config: OracleAdwConfig,
    *,
    timeout_seconds: int,
) -> dict[str, object] | None:
    if not 1 <= timeout_seconds <= 300:
        return {
            "code": "invalid_timeout_seconds",
            "message": "timeout_seconds must be between 1 and 300.",
        }
    if not config.sqlcl_path:
        return {
            "code": "sqlcl_path_required",
            "message": "SQLCL_PATH is required for operator ADW admin provisioning.",
        }
    if not Path(config.sqlcl_path).expanduser().is_absolute():
        return {
            "code": "sqlcl_path_must_be_absolute",
            "message": "SQLCL_PATH must be an absolute path for admin provisioning.",
        }
    if not config.admin_user:
        return {
            "code": "admin_user_required",
            "message": "ADMIN_USER is required for admin provisioning.",
        }
    if not config.admin_user_pass:
        return {
            "code": "admin_user_pass_required",
            "message": "ADMIN_USER_PASS is required for admin provisioning.",
        }
    if any(char in config.admin_user_pass for char in "\r\n\x00"):
        return {
            "code": "invalid_admin_user_pass",
            "message": "ADMIN_USER_PASS contains disallowed control characters.",
        }
    if not config.db_user:
        return {
            "code": "db_user_required",
            "message": "DB_USER is required for admin provisioning.",
        }
    try:
        _safe_working_user(config.db_user)
    except ValueError as exc:
        return {"code": "invalid_db_user", "message": str(exc)}
    if not config.db_user_pass:
        return {
            "code": "db_user_pass_required",
            "message": "DB_USER_PASS is required for admin provisioning.",
        }
    if any(char in config.db_user_pass for char in "\r\n\x00'"):
        return {
            "code": "invalid_db_user_pass",
            "message": "DB_USER_PASS contains characters that cannot be safely rendered in the current admin provisioning boundary.",
        }
    if not config.db_dsn:
        return {
            "code": "db_dsn_required",
            "message": "DB_DSN is required for admin provisioning.",
        }
    if not _is_tns_alias(config.db_dsn):
        return {
            "code": "db_dsn_must_be_tns_alias",
            "message": "Admin provisioning requires DB_DSN to be a wallet TNS alias.",
        }
    if not config.db_wallet_path:
        return {
            "code": "db_wallet_path_required",
            "message": "DB_WALLET_PATH is required for admin provisioning.",
        }
    wallet_status = verify_wallet_paths(config)
    if not wallet_status.wallet_path_is_dir:
        return {
            "code": "db_wallet_path_invalid",
            "message": "DB_WALLET_PATH must point to an existing wallet directory.",
            "wallet": wallet_status.to_redacted_dict(),
        }
    return None


def _validate_operator_adw_limits(
    *,
    timeout_seconds: int,
    row_limit: int,
    max_output_bytes: int,
    max_error_bytes: int,
) -> dict[str, object] | None:
    if not 1 <= timeout_seconds <= 300:
        return {
            "code": "invalid_timeout_seconds",
            "message": "timeout_seconds must be between 1 and 300.",
        }
    if not 1 <= row_limit <= 10_000:
        return {
            "code": "invalid_row_limit",
            "message": "row_limit must be between 1 and 10000.",
        }
    if not 1_024 <= max_output_bytes <= 10_485_760:
        return {
            "code": "invalid_max_output_bytes",
            "message": "max_output_bytes must be between 1024 and 10485760.",
        }
    if not 1_024 <= max_error_bytes <= 1_048_576:
        return {
            "code": "invalid_max_error_bytes",
            "message": "max_error_bytes must be between 1024 and 1048576.",
        }
    return None


def _load_operator_sql(
    *,
    sql: str | None,
    sql_file: str | None,
    sql_stdin: bool,
) -> tuple[str | None, str | None, dict[str, object] | None]:
    if sql is not None:
        sql_text, error = _validate_operator_sql_text(sql)
        return sql_text, "inline", error
    if sql_file is not None:
        path = Path(sql_file).expanduser()
        try:
            with path.open("rb") as file:
                sql_bytes = file.read(MAX_OPERATOR_SQL_BYTES + 1)
        except OSError as exc:
            return None, "file", {
                "code": "sql_file_unreadable",
                "message": f"SQL file could not be read: {exc.__class__.__name__}.",
            }
        if len(sql_bytes) > MAX_OPERATOR_SQL_BYTES:
            return None, "file", _operator_sql_too_large_error(len(sql_bytes))
        sql_text, decode_error = _decode_operator_sql_bytes(sql_bytes, source="file")
        if decode_error is not None:
            return None, "file", decode_error
        assert sql_text is not None
        sql_text, error = _validate_operator_sql_text(sql_text)
        return sql_text, "file", error
    if sql_stdin:
        try:
            stdin_buffer = getattr(sys.stdin, "buffer", None)
            if stdin_buffer is not None:
                sql_bytes = stdin_buffer.read(MAX_OPERATOR_SQL_BYTES + 1)
                if len(sql_bytes) > MAX_OPERATOR_SQL_BYTES:
                    return None, "stdin", _operator_sql_too_large_error(len(sql_bytes))
                sql_text, decode_error = _decode_operator_sql_bytes(sql_bytes, source="stdin")
                if decode_error is not None:
                    return None, "stdin", decode_error
                assert sql_text is not None
            else:
                sql_text = sys.stdin.read(MAX_OPERATOR_SQL_BYTES + 1)
        except OSError as exc:
            return None, "stdin", {
                "code": "sql_stdin_unreadable",
                "message": f"SQL stdin could not be read: {exc.__class__.__name__}.",
            }
        sql_text, error = _validate_operator_sql_text(sql_text)
        return sql_text, "stdin", error
    return None, None, {
        "code": "sql_required",
        "message": "Either --sql, --sql-file, or --sql-stdin is required.",
    }


def _decode_operator_sql_bytes(
    sql_bytes: bytes,
    *,
    source: str,
) -> tuple[str | None, dict[str, object] | None]:
    try:
        return sql_bytes.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, {
            "code": "invalid_sql_encoding",
            "message": f"SQL {source} must be valid UTF-8.",
            "encoding": "utf-8",
            "reason": exc.reason,
        }


def _validate_operator_sql_text(sql_text: str) -> tuple[str | None, dict[str, object] | None]:
    byte_length = len(sql_text.encode("utf-8"))
    if byte_length > MAX_OPERATOR_SQL_BYTES:
        return None, _operator_sql_too_large_error(byte_length)
    normalized_sql = sql_text.strip()
    if not normalized_sql:
        return None, {
            "code": "empty_sql",
            "message": "SQL text is empty.",
        }
    return normalized_sql, None


def _operator_sql_too_large_error(byte_length: int) -> dict[str, object]:
    return {
        "code": "sql_too_large",
        "message": f"SQL text must be at most {MAX_OPERATOR_SQL_BYTES} bytes.",
        "sql_bytes": byte_length,
    }


def _run_admin_provision_sqlcl(
    config: OracleAdwConfig,
    *,
    timeout_seconds: int,
    grant_profile: str,
) -> dict[str, object]:
    assert config.sqlcl_path is not None
    assert config.admin_user is not None
    assert config.admin_user_pass is not None
    assert config.db_user is not None
    assert config.db_user_pass is not None
    assert config.db_dsn is not None
    working_user = _safe_working_user(config.db_user)
    admin_user = _safe_oracle_identifier(config.admin_user)
    escaped_password = config.db_user_pass.replace('"', '""')
    required_synonyms = (
        sorted(SH_REQUIRED_TABLES)
        if grant_profile in ("prototype-any-table-read", "production-sh-read")
        else []
    )
    required_object_grants = _admin_required_object_grants(grant_profile=grant_profile)
    pre_result = _run_admin_sqlcl_statements(
        config,
        timeout_seconds=timeout_seconds,
        admin_user=admin_user,
        statements=_admin_inspection_statements(
            working_user=working_user,
            grant_profile=grant_profile,
            prefix="pre",
        ),
    )
    pre_classification = _classify_admin_provisioning_result(
        config=config,
        grant_profile=grant_profile,
        completed=pre_result,
    )
    if pre_result["status"] != "completed":
        return {**pre_result, "phase": "precheck"}
    if pre_classification["classification"] == "rejected_drift":
        return {
            **pre_result,
            "status": "rejected_drift",
            "phase": "precheck",
            "precheck_classification": pre_classification,
            "actions_applied": [],
        }
    if pre_classification["classification"] == "already_compliant":
        return {
            **pre_result,
            "phase": "precheck",
            "precheck_classification": pre_classification,
            "actions_applied": [],
        }

    pre_state = pre_classification["state"]["pre"]
    assert isinstance(pre_state, dict)
    missing_roles = tuple(str(value) for value in pre_state.get("missing_roles", ()))
    missing_sys_privileges = tuple(str(value) for value in pre_state.get("missing_system_privileges", ()))
    missing_synonyms = tuple(str(value) for value in pre_state.get("missing_synonyms", ()))
    missing_object_grants = [
        (str(item[0]), str(item[1]), str(item[2]))
        for item in pre_state.get("missing_object_grants", [])
        if isinstance(item, (list, tuple)) and len(item) == 3
    ]
    user_exists = bool(pre_state.get("exists"))
    account_status = pre_state.get("account_status")
    statements: list[str] = []
    actions_applied: list[str] = []
    if not user_exists:
        statements.append(f'CREATE USER {working_user} IDENTIFIED BY "{escaped_password}";')
        actions_applied.append("create_user")
    elif account_status != "OPEN":
        statements.append(f"ALTER USER {working_user} ACCOUNT UNLOCK;")
        actions_applied.append("unlock_user")
    for privilege in missing_sys_privileges:
        statements.append(f"GRANT {privilege} TO {working_user};")
        actions_applied.append(f"grant_system_privilege:{privilege}")
    for role in missing_roles:
        statements.append(f"GRANT {role} TO {working_user};")
        actions_applied.append(f"grant_role:{role}")
    if "DWROLE" in missing_roles:
        statements.append(f"ALTER USER {working_user} DEFAULT ROLE ALL;")
        actions_applied.append("default_role_all")
    for priv, owner, table_name in missing_object_grants:
        statements.append(f"GRANT {priv} ON {owner}.{table_name} TO {working_user};")
        actions_applied.append(f"grant_object:{priv}:{owner}.{table_name}")
    for table_name in sorted(set(required_synonyms) & set(missing_synonyms)):
        statements.append(f"CREATE OR REPLACE SYNONYM {working_user}.{table_name} FOR SH.{table_name};")
        actions_applied.append(f"create_synonym:{table_name}")
    if not statements:
        return {
            **pre_result,
            "phase": "precheck",
            "precheck_classification": pre_classification,
            "actions_applied": [],
        }
    apply_result = _run_admin_sqlcl_statements(
        config,
        timeout_seconds=timeout_seconds,
        admin_user=admin_user,
        statements=statements,
    )
    if apply_result["status"] != "completed":
        return {
            **apply_result,
            "phase": "apply",
            "precheck_classification": pre_classification,
            "actions_applied": actions_applied,
        }
    post_result = _run_admin_sqlcl_statements(
        config,
        timeout_seconds=timeout_seconds,
        admin_user=admin_user,
        statements=_admin_inspection_statements(
            working_user=working_user,
            grant_profile=grant_profile,
            prefix="post",
        ),
    )
    return {
        **post_result,
        "stdout": "\n".join((str(pre_result["stdout"]), str(apply_result["stdout"]), str(post_result["stdout"]))),
        "stderr": "\n".join((str(pre_result["stderr"]), str(apply_result["stderr"]), str(post_result["stderr"]))),
        "stdout_bytes": int(pre_result["stdout_bytes"]) + int(apply_result["stdout_bytes"]) + int(post_result["stdout_bytes"]),
        "stderr_bytes": int(pre_result["stderr_bytes"]) + int(apply_result["stderr_bytes"]) + int(post_result["stderr_bytes"]),
        "phase": "postcheck",
        "precheck_classification": pre_classification,
        "actions_applied": actions_applied,
    }


def _run_admin_sqlcl_statements(
    config: OracleAdwConfig,
    *,
    timeout_seconds: int,
    admin_user: str,
    statements: list[str],
) -> dict[str, object]:
    stdin = "\n".join(
        (
            "set echo off",
            "set define off",
            "set sqlformat json",
            "set feedback off",
            "set heading on",
            "whenever sqlerror exit sql.sqlcode",
            "whenever oserror exit failure",
            f"connect {admin_user}/\"{config.admin_user_pass.replace(chr(34), chr(34) + chr(34))}\"@{config.db_dsn}",
            *statements,
            "exit",
            "",
        )
    )
    env = _minimal_operator_sqlcl_env()
    if config.db_wallet_path:
        env["TNS_ADMIN"] = str(Path(config.db_wallet_path).expanduser())
    result = run_sqlcl_subprocess(
        SqlclSubprocessRequest(
            command=[str(Path(config.sqlcl_path).expanduser()), "-S", "-L", "-nolog"],
            stdin=stdin,
            env=env,
            timeout_seconds=timeout_seconds,
            max_output_bytes=MAX_ADMIN_PROVISION_STDOUT_BYTES,
            max_error_bytes=MAX_ADMIN_PROVISION_STDERR_BYTES,
            sensitive_values=tuple(
                value
                for value in (
                    stdin,
                    config.admin_user_pass,
                    config.db_user_pass,
                    config.db_dsn,
                    config.db_wallet_pass,
                )
                if value
            ),
        )
    )
    return {
        "status": result.status,
        "returncode": result.returncode,
        "stdout": _redact_admin_sqlcl_output(config, result.stdout, stdin),
        "stderr": _redact_admin_sqlcl_output(config, result.stderr, stdin),
        "timed_out": result.timed_out,
        "stdout_too_large": result.stdout_too_large,
        "stderr_too_large": result.stderr_too_large,
        "stdout_bytes": result.stdout_bytes,
        "stderr_bytes": result.stderr_bytes,
    }


def _admin_inspection_statements(
    *,
    working_user: str,
    grant_profile: str,
    prefix: str,
) -> list[str]:
    required_roles, required_sys_privileges = _admin_required_grants(grant_profile=grant_profile)
    required_object_grants = _admin_required_object_grants(grant_profile=grant_profile)
    required_synonyms = (
        sorted(SH_REQUIRED_TABLES)
        if grant_profile in ("prototype-any-table-read", "production-sh-read")
        else []
    )
    drift_roles = _admin_drift_roles(grant_profile=grant_profile)
    drift_sys_privs = _admin_drift_sys_privileges(grant_profile=grant_profile)
    role_sql_list = _sql_string_list((*required_roles, *drift_roles))
    sys_privilege_sql_list = _sql_string_list((*required_sys_privileges, *drift_sys_privs))
    synonym_sql_list = _sql_string_list(required_synonyms)
    statements = [
        (
            f"select '{prefix}_user' as afs_section, username, account_status from dba_users "
            f"where username = '{working_user}';"
        ),
        (
            f"select '{prefix}_role' as afs_section, granted_role from dba_role_privs "
            f"where grantee = '{working_user}' and granted_role in ({role_sql_list}) "
            "order by granted_role;"
        ),
        (
            f"select '{prefix}_sys_privilege' as afs_section, privilege from dba_sys_privs "
            f"where grantee = '{working_user}' and privilege in ({sys_privilege_sql_list}) "
            "order by privilege;"
        ),
        (
            f"select '{prefix}_synonym' as afs_section, synonym_name, table_owner, table_name "
            f"from dba_synonyms where owner = '{working_user}' "
            f"and synonym_name in ({synonym_sql_list}) order by synonym_name;"
        ),
    ]
    if required_object_grants:
        owners = sorted({owner for _, owner, _ in required_object_grants})
        tables = sorted({tbl for _, _, tbl in required_object_grants})
        statements.append(
            f"select '{prefix}_object_grant' as afs_section, privilege, owner, table_name "
            f"from dba_tab_privs where grantee = '{working_user}' "
            f"and owner in ({_sql_string_list(owners)}) "
            f"and table_name in ({_sql_string_list(tables)}) "
            "order by owner, table_name;"
        )
    return statements


def _classify_admin_provisioning_result(
    *,
    config: OracleAdwConfig,
    grant_profile: str,
    completed: dict[str, object],
) -> dict[str, object]:
    embedded = completed.get("precheck_classification")
    if (
        isinstance(embedded, dict)
        and completed.get("phase") == "precheck"
        and completed.get("status") in {"completed", "rejected_drift"}
    ):
        return embedded
    stdout = str(completed.get("stdout", ""))
    stderr = str(completed.get("stderr", ""))
    if "AFS_REJECTED_DRIFT" in stdout or "AFS_REJECTED_DRIFT" in stderr:
        return {
            "classification": "rejected_drift",
            "state": {
                "reason": "existing_user_has_privileges_outside_selected_profile",
                "drift_policy": {
                    "roles": list(_admin_drift_roles(grant_profile=grant_profile)),
                    "system_privileges": list(_admin_drift_sys_privileges(grant_profile=grant_profile)),
                },
            },
        }

    required_roles, required_sys_privileges = _admin_required_grants(grant_profile=grant_profile)
    required_object_grants = _admin_required_object_grants(grant_profile=grant_profile)
    required_synonyms = (
        set(SH_REQUIRED_TABLES)
        if grant_profile in ("prototype-any-table-read", "production-sh-read")
        else set()
    )
    drift_roles_set = frozenset(_admin_drift_roles(grant_profile=grant_profile))
    drift_sys_privileges_set = frozenset(_admin_drift_sys_privileges(grant_profile=grant_profile))
    sections = _admin_provisioning_sections(stdout)
    pre_state = _admin_account_state(
        sections=sections,
        prefix="pre",
        required_roles=required_roles,
        required_sys_privileges=required_sys_privileges,
        required_synonyms=required_synonyms,
        required_object_grants=required_object_grants,
        drift_roles_set=drift_roles_set,
        drift_sys_privileges_set=drift_sys_privileges_set,
    )
    post_state = _admin_account_state(
        sections=sections,
        prefix="post",
        required_roles=required_roles,
        required_sys_privileges=required_sys_privileges,
        required_synonyms=required_synonyms,
        required_object_grants=required_object_grants,
        drift_roles_set=drift_roles_set,
        drift_sys_privileges_set=drift_sys_privileges_set,
    )
    active_prefix = "post" if post_state["observed"] else "pre"
    active_state = post_state if active_prefix == "post" else pre_state
    classification_state = {
        "pre": pre_state,
        "post": post_state,
        "active_prefix": active_prefix,
        "required": {
            "roles": list(required_roles),
            "system_privileges": list(required_sys_privileges),
            "synonyms": sorted(required_synonyms),
            "object_grants": sorted(
                f"{priv}:ON:{owner}.{tbl}" for priv, owner, tbl in required_object_grants
            ),
        },
    }

    if completed.get("status") != "completed":
        return {
            "classification": "failed",
            "state": classification_state,
        }
    if active_state["drift_reasons"]:
        return {
            "classification": "rejected_drift",
            "state": classification_state,
        }
    if active_prefix == "post" and not post_state["compliant"]:
        return {
            "classification": "failed_incomplete",
            "state": classification_state,
        }
    if active_prefix == "post" and not pre_state["exists"]:
        return {
            "classification": "created",
            "state": classification_state,
        }
    if active_prefix == "post" and not pre_state["compliant"]:
        return {
            "classification": "granted_missing_privileges",
            "state": classification_state,
        }
    if active_state["compliant"]:
        return {
            "classification": "already_compliant",
            "state": classification_state,
        }
    return {
        "classification": "granted_missing_privileges",
        "state": classification_state,
    }


def _admin_provisioning_sections(stdout: str) -> dict[str, list[dict[str, str]]]:
    sections: dict[str, list[dict[str, str]]] = {}
    for item in _extract_sqlcl_json_items(stdout):
        section = item.get("afs_section")
        if not section:
            continue
        sections.setdefault(section, []).append(item)
    return sections


def _extract_sqlcl_json_items(text: str) -> list[dict[str, str]]:
    decoder = json.JSONDecoder()
    index = 0
    items: list[dict[str, str]] = []
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        items.extend(_items_from_sqlcl_json(value))
        index = start + end
    return items


def _items_from_sqlcl_json(value: object) -> list[dict[str, str]]:
    raw_items: list[object] = []
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            raw_items.extend(value["items"])
        results = value.get("results")
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict) and isinstance(result.get("items"), list):
                    raw_items.extend(result["items"])
    normalized: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        row = {str(key).lower(): str(val).upper() for key, val in item.items() if val is not None}
        if "afs_section" in row:
            row["afs_section"] = row["afs_section"].lower()
        normalized.append(row)
    return normalized


def _admin_account_state(
    *,
    sections: dict[str, list[dict[str, str]]],
    prefix: str,
    required_roles: tuple[str, ...],
    required_sys_privileges: tuple[str, ...],
    required_synonyms: set[str],
    required_object_grants: frozenset[tuple[str, str, str]] = frozenset(),
    drift_roles_set: frozenset[str] | None = None,
    drift_sys_privileges_set: frozenset[str] | None = None,
) -> dict[str, object]:
    if drift_roles_set is None:
        drift_roles_set = frozenset(ADMIN_PROVISION_DRIFT_ROLES)
    if drift_sys_privileges_set is None:
        drift_sys_privileges_set = frozenset(ADMIN_PROVISION_DRIFT_SYS_PRIVILEGES)
    user_rows = sections.get(f"{prefix}_user", [])
    role_rows = sections.get(f"{prefix}_role", [])
    sys_privilege_rows = sections.get(f"{prefix}_sys_privilege", [])
    synonym_rows = sections.get(f"{prefix}_synonym", [])
    object_grant_rows = sections.get(f"{prefix}_object_grant", [])
    account_status = user_rows[0].get("account_status") if user_rows else None
    roles = {row.get("granted_role", "") for row in role_rows}
    sys_privileges = {row.get("privilege", "") for row in sys_privilege_rows}
    valid_synonyms = set()
    drift_reasons = []
    for row in synonym_rows:
        synonym_name = row.get("synonym_name", "")
        table_owner = row.get("table_owner", "")
        table_name = row.get("table_name", "")
        if synonym_name in required_synonyms and table_owner == "SH" and table_name == synonym_name:
            valid_synonyms.add(synonym_name)
        elif synonym_name in required_synonyms:
            drift_reasons.append(f"unexpected_synonym_target:{synonym_name}")
    valid_object_grants: set[tuple[str, str, str]] = set()
    for row in object_grant_rows:
        privilege = row.get("privilege", "")
        owner = row.get("owner", "")
        table_name = row.get("table_name", "")
        grant_tuple = (privilege, owner, table_name)
        if grant_tuple in required_object_grants:
            valid_object_grants.add(grant_tuple)
    drift_roles = sorted(roles & drift_roles_set)
    drift_sys_privileges = sorted(sys_privileges & drift_sys_privileges_set)
    drift_reasons.extend(f"unexpected_role:{role}" for role in drift_roles)
    drift_reasons.extend(f"unexpected_system_privilege:{privilege}" for privilege in drift_sys_privileges)
    missing_roles = sorted(set(required_roles) - roles)
    missing_sys_privileges = sorted(set(required_sys_privileges) - sys_privileges)
    missing_synonyms = sorted(required_synonyms - valid_synonyms)
    missing_object_grants = sorted(
        (priv, owner, tbl)
        for priv, owner, tbl in required_object_grants
        if (priv, owner, tbl) not in valid_object_grants
    )
    exists = bool(user_rows)
    compliant = (
        exists
        and account_status == "OPEN"
        and not missing_roles
        and not missing_sys_privileges
        and not missing_synonyms
        and not missing_object_grants
    )
    return {
        "observed": bool(user_rows or role_rows or sys_privilege_rows or synonym_rows or object_grant_rows),
        "exists": exists,
        "account_status": account_status,
        "roles": sorted(roles),
        "system_privileges": sorted(sys_privileges),
        "synonyms": sorted(valid_synonyms),
        "object_grants": sorted(f"{priv}:ON:{owner}.{tbl}" for priv, owner, tbl in valid_object_grants),
        "missing_roles": missing_roles,
        "missing_system_privileges": missing_sys_privileges,
        "missing_synonyms": missing_synonyms,
        "missing_object_grants": missing_object_grants,
        "drift_reasons": drift_reasons,
        "compliant": compliant,
    }


def _operator_query_audit_payload(payload: dict[str, object]) -> dict[str, object]:
    audit_payload = dict(payload)
    response = audit_payload.get("response")
    if isinstance(response, dict):
        audit_response = dict(response)
        audit_response.pop("rows", None)
        audit_response["rows_omitted_from_audit"] = True
        audit_payload["response"] = audit_response
    return audit_payload


def _operator_live_state_payload(
    *,
    state: str,
    command: str,
    requested: bool,
    attempted: bool,
    succeeded: bool,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "state": state,
        "command": command,
        "live_database_execution": attempted,
        "live_execution_requested": requested,
        "live_execution_attempted": attempted,
        "live_execution_succeeded": succeeded,
        **(extra or {}),
    }


def _append_operator_audit(
    audit_path: Path,
    event: str,
    payload: dict[str, object],
) -> None:
    append_audit(
        RunRecord.create(
            event,
            {
                "operator_only": True,
                "operator_context": _operator_context(),
                **payload,
            },
        ),
        audit_path,
    )


def _is_tns_alias(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", value))


def _safe_working_user(value: str) -> str:
    user = _safe_oracle_identifier(value)
    if user in PROTECTED_WORKING_USER_NAMES:
        raise ValueError("DB_USER must not be an administrative, system, or sample schema name.")
    return user


def _safe_oracle_identifier(value: str) -> str:
    upper = value.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,127}", upper):
        raise ValueError("Oracle identifier must be simple and unquoted.")
    return upper


def _admin_required_object_grants(
    *,
    grant_profile: str,
) -> frozenset[tuple[str, str, str]]:
    """Returns frozenset of (privilege, owner, table_name) tuples required by profile."""
    if grant_profile == "production-sh-read":
        return frozenset(
            ("SELECT", "SH", table_name)
            for table_name in SH_REQUIRED_TABLES
        )
    return frozenset()


def _admin_drift_roles(*, grant_profile: str) -> tuple[str, ...]:
    if grant_profile == "production-sh-read":
        return (*ADMIN_PROVISION_DRIFT_ROLES, *ADMIN_PRODUCTION_DRIFT_EXTRA_ROLES)
    return ADMIN_PROVISION_DRIFT_ROLES


def _admin_drift_sys_privileges(*, grant_profile: str) -> tuple[str, ...]:
    if grant_profile == "production-sh-read":
        return (*ADMIN_PROVISION_DRIFT_SYS_PRIVILEGES, *ADMIN_PRODUCTION_DRIFT_EXTRA_SYS_PRIVILEGES)
    return ADMIN_PROVISION_DRIFT_SYS_PRIVILEGES


def _admin_requested_privileges(
    *,
    grant_profile: str,
) -> list[str]:
    privileges = ["CREATE SESSION"]
    if grant_profile == "prototype-any-table-read":
        privileges.append("DWROLE")
        privileges.append("SELECT ANY TABLE")
    elif grant_profile == "production-sh-read":
        for table_name in sorted(SH_REQUIRED_TABLES):
            privileges.append(f"SELECT ON SH.{table_name}")
    return privileges


def _admin_required_grants(
    *,
    grant_profile: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    roles: tuple[str, ...] = ()
    sys_privileges = ("CREATE SESSION",)
    if grant_profile == "prototype-any-table-read":
        roles = ("DWROLE",)
        sys_privileges = ("CREATE SESSION", "SELECT ANY TABLE")
    return roles, sys_privileges


def _sql_string_list(values: Sequence[str]) -> str:
    cleaned = sorted({str(value).upper().replace("'", "''") for value in values})
    if not cleaned:
        return "''"
    return ",".join(f"'{value}'" for value in cleaned)


def _minimal_operator_sqlcl_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "JAVA_HOME", "HOME", "LANG", "LC_ALL"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _redact_admin_sqlcl_output(
    config: OracleAdwConfig,
    text: str,
    stdin: str,
) -> str:
    redacted = text.replace(stdin, "[REDACTED_STDIN]")
    for value in (
        config.admin_user_pass,
        config.db_user_pass,
        config.db_dsn,
        config.db_wallet_pass,
    ):
        if value and len(value) >= 4:
            redacted = redacted.replace(value, "[REDACTED]")
    return redact(redacted)


def _cmd_review_candidate(args: argparse.Namespace, audit_path: Path) -> int:
    candidates_dir = Path(args.candidates_dir)
    operation = args.operation

    if operation == "list":
        candidate_files = sorted(candidates_dir.glob("*.json")) if candidates_dir.is_dir() else []
        if not candidate_files:
            print("(no candidates found)")
            _append_operator_audit(audit_path, "operator.review_candidate_list", {"candidates_dir": str(candidates_dir), "count": 0})
            return 0
        rows = []
        for path in candidate_files:
            try:
                record = load_improvement_candidate(path)
                if args.status and record.status != args.status:
                    continue
                rows.append({
                    "id": record.candidate_id,
                    "type": record.candidate_type,
                    "status": record.status,
                    "review_decision": record.review.decision,
                    "risk": record.risk_level,
                    "created_at": record.created_at,
                })
            except (ValueError, OSError, KeyError):
                rows.append({"id": path.stem, "type": "?", "status": "?", "review_decision": "?", "risk": "?", "created_at": "?"})
        header = f"{'ID':<40} {'type':<16} {'status':<12} {'review_decision':<18} {'risk':<8} {'created_at'}"
        print(header)
        print("-" * len(header))
        for row in rows:
            print(f"{row['id']:<40} {row['type']:<16} {row['status']:<12} {row['review_decision']:<18} {row['risk']:<8} {row['created_at']}")
        _append_operator_audit(audit_path, "operator.review_candidate_list", redact({"candidates_dir": str(candidates_dir), "count": len(rows)}))
        return 0

    if operation == "show":
        if not args.candidate_id:
            print("error: --candidate-id is required for show", file=sys.stderr)
            return 1
        path = _find_candidate_path(candidates_dir, args.candidate_id)
        if path is None:
            print(f"error: candidate not found: {args.candidate_id}", file=sys.stderr)
            return 1
        try:
            record = load_improvement_candidate(path)
        except (ValueError, OSError) as exc:
            print(f"error: could not load candidate: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(redact(record.to_dict()), ensure_ascii=False, indent=2))
        _append_operator_audit(audit_path, "operator.review_candidate_show", redact({"candidate_id": record.candidate_id}))
        return 0

    if operation == "approve":
        if not args.candidate_id:
            print("error: --candidate-id is required for approve", file=sys.stderr)
            return 1
        reviewer = args.reviewer or ""
        if not reviewer.strip():
            print("error: --reviewer must not be empty", file=sys.stderr)
            return 1
        path = _find_candidate_path(candidates_dir, args.candidate_id)
        if path is None:
            print(f"error: candidate not found: {args.candidate_id}", file=sys.stderr)
            return 1
        try:
            record = load_improvement_candidate(path)
        except (ValueError, OSError) as exc:
            print(f"error: could not load candidate: {exc}", file=sys.stderr)
            return 1
        try:
            updated = approve_candidate(record, reviewer_id=reviewer, notes=args.notes or "")
            write_improvement_candidate(updated, path, overwrite=True)
        except (ValueError, OSError, SecretLeakError) as exc:
            print(f"error: could not approve candidate: {exc}", file=sys.stderr)
            return 1
        _append_operator_audit(audit_path, "operator.review_candidate_approved", redact({"candidate_id": record.candidate_id, "reviewer": reviewer, "status": "approved"}))
        print(json.dumps(redact({"state": "approved", "candidate_id": record.candidate_id, "reviewer": reviewer}), ensure_ascii=False, indent=2))
        return 0

    if operation == "reject":
        if not args.candidate_id:
            print("error: --candidate-id is required for reject", file=sys.stderr)
            return 1
        reviewer = args.reviewer or ""
        if not reviewer.strip():
            print("error: --reviewer must not be empty", file=sys.stderr)
            return 1
        path = _find_candidate_path(candidates_dir, args.candidate_id)
        if path is None:
            print(f"error: candidate not found: {args.candidate_id}", file=sys.stderr)
            return 1
        try:
            record = load_improvement_candidate(path)
        except (ValueError, OSError) as exc:
            print(f"error: could not load candidate: {exc}", file=sys.stderr)
            return 1
        try:
            updated = reject_candidate(record, reviewer_id=reviewer, reason=args.notes or "")
            write_improvement_candidate(updated, path, overwrite=True)
        except (ValueError, OSError, SecretLeakError) as exc:
            print(f"error: could not reject candidate: {exc}", file=sys.stderr)
            return 1
        _append_operator_audit(audit_path, "operator.review_candidate_rejected", redact({"candidate_id": record.candidate_id, "reviewer": reviewer, "status": "rejected", "notes": args.notes or ""}))
        print(json.dumps(redact({"state": "rejected", "candidate_id": record.candidate_id, "reviewer": reviewer}), ensure_ascii=False, indent=2))
        return 0

    print(f"error: unknown operation: {operation}", file=sys.stderr)
    return 2


def _find_candidate_path(candidates_dir: Path, candidate_id: str) -> "Path | None":
    if not candidates_dir.is_dir():
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", candidate_id):
        return None
    direct = candidates_dir / f"{candidate_id}.json"
    if direct.exists():
        return direct
    for path in candidates_dir.glob("*.json"):
        if path.stem == candidate_id:
            return path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("candidate_id") == candidate_id:
                return path
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _cmd_tacit(args: argparse.Namespace) -> int:
    from .tacit_knowledge import (
        ReflectionAgent,
        TacitSignalExtractor,
        VerificationEpisode,
        VerificationEpisodeStore,
    )

    episodes_dir = Path(args.episodes_dir)

    if args.tacit_command == "list":
        store = VerificationEpisodeStore(episodes_dir)
        episodes = store.load_all()
        if not episodes:
            print("(no episodes found)")
            return 0
        header = f"{'episode_id':<36}  {'timestamp':<27}  {'session_id':<24}  {'final_resolution'}"
        print(header)
        print("-" * len(header))
        for ep in episodes:
            print(
                f"{ep.get('episode_id', ''):<36}  "
                f"{ep.get('timestamp', ''):<27}  "
                f"{ep.get('session_id', ''):<24}  "
                f"{ep.get('final_resolution', '')}"
            )
        return 0

    if args.tacit_command == "reflect":
        episode_id = args.episode_id
        store = VerificationEpisodeStore(episodes_dir)
        all_episodes = store.load_all()
        match = next((ep for ep in all_episodes if ep.get("episode_id") == episode_id), None)
        if match is None:
            print(f"error: episode not found: {episode_id}", file=sys.stderr)
            return 1
        # Reconstruct VerificationEpisode from dict
        from .tacit_knowledge import CorrectionDiff
        diff_data = match.get("correction_diff")
        diff = None
        if diff_data is not None:
            diff = CorrectionDiff(
                removed=tuple(diff_data.get("removed", [])),
                inserted=tuple(diff_data.get("inserted", [])),
                tone_change=diff_data.get("tone_change"),
                terminology_changes=tuple(diff_data.get("terminology_changes", [])),
                semantic_type=diff_data.get("semantic_type", "other"),
            )
        ep = VerificationEpisode(
            episode_id=match["episode_id"],
            timestamp=match["timestamp"],
            session_id=match["session_id"],
            ai_output=match.get("ai_output", ""),
            final_resolution=match.get("final_resolution", "human_approved"),
            input_context=match.get("input_context", {}),
            retrieved_context=match.get("retrieved_context", {}),
            human_revision=match.get("human_revision"),
            correction_diff=diff,
            confidence_before=match.get("confidence_before"),
            confidence_after=match.get("confidence_after"),
            uncertainty_regions=tuple(match.get("uncertainty_regions", [])),
            consultation_trace=tuple(match.get("consultation_trace", [])),
            reason_tags=tuple(match.get("reason_tags", [])),
            reflection_summary=match.get("reflection_summary"),
        )
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.tacit_command == "heuristics":
        store = VerificationEpisodeStore(episodes_dir)
        all_episodes = store.load_all()
        if not all_episodes:
            print("(no episodes found)")
            return 0
        from .tacit_knowledge import CorrectionDiff
        extractor = TacitSignalExtractor()
        seen: list[str] = []
        for match in all_episodes:
            diff_data = match.get("correction_diff")
            diff = None
            if diff_data is not None:
                diff = CorrectionDiff(
                    removed=tuple(diff_data.get("removed", [])),
                    inserted=tuple(diff_data.get("inserted", [])),
                    tone_change=diff_data.get("tone_change"),
                    terminology_changes=tuple(diff_data.get("terminology_changes", [])),
                    semantic_type=diff_data.get("semantic_type", "other"),
                )
            ep = VerificationEpisode(
                episode_id=match["episode_id"],
                timestamp=match["timestamp"],
                session_id=match["session_id"],
                ai_output=match.get("ai_output", ""),
                final_resolution=match.get("final_resolution", "human_approved"),
                correction_diff=diff,
                uncertainty_regions=tuple(match.get("uncertainty_regions", [])),
                consultation_trace=tuple(match.get("consultation_trace", [])),
                reason_tags=tuple(match.get("reason_tags", [])),
            )
            signal = extractor.extract(ep)
            for h in signal.suspected_heuristics:
                if h not in seen:
                    seen.append(h)
        if not seen:
            print("(no heuristics extracted)")
            return 0
        for h in seen:
            print(f"- {h}")
        return 0

    print(f"error: unknown tacit command: {args.tacit_command}", file=sys.stderr)
    return 2


def _operator_context() -> dict[str, object]:
    return {
        "os_user": getpass.getuser(),
        "cwd": os.getcwd(),
    }

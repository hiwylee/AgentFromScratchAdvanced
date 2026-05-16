"""Command-line interface for the prototype agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import __version__
from .loop import AgentLoop
from .monitor import latest_status
from .redaction import redact
from .types import Budget
from .workflow import WorkflowEngine


DEFAULT_RUN_DIR = Path(".agent/runs")
DEFAULT_AUDIT_PATH = Path(".agent/audit.jsonl")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="analyze a user request")
    ask_parser.add_argument("text", nargs="+", help="user request text")
    ask_parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    ask_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))
    ask_parser.add_argument("--max-steps", type=int, default=4)
    ask_parser.add_argument("--timeout-seconds", type=int, default=30)

    status_parser = subparsers.add_parser("status", help="show latest run status")
    status_parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))

    workflow_parser = subparsers.add_parser("workflow", help="run a mock workflow")
    workflow_parser.add_argument("text", nargs="+", help="workflow request text")
    workflow_parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    workflow_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))

    args = parser.parse_args(argv)

    if args.command == "ask":
        return _ask(
            args.text,
            Path(args.run_dir),
            Path(args.audit_log),
            Budget(max_steps=args.max_steps, timeout_seconds=args.timeout_seconds),
        )
    if args.command == "status":
        return _status(Path(args.run_dir))
    if args.command == "workflow":
        return _workflow(args.text, Path(args.run_dir), Path(args.audit_log))

    parser.error(f"unknown command: {args.command}")
    return 2


def _ask(
    text_parts: Sequence[str],
    run_dir: Path,
    audit_path: Path,
    budget: Budget,
) -> int:
    user_text = " ".join(text_parts)
    loop = AgentLoop(run_root=run_dir, audit_path=audit_path, budget=budget)
    result = loop.run(user_text)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


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

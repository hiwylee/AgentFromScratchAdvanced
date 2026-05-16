"""Command-line interface for the prototype agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import __version__
from .loop import AgentLoop
from .monitor import latest_status
from .types import Budget


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

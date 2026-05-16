"""Command-line interface for the prototype agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import __version__
from .audit import RunRecord, append_audit, write_trace
from .intent import analyze_user_intent


DEFAULT_TRACE_DIR = Path(".agent/traces")
DEFAULT_AUDIT_PATH = Path(".agent/audit.jsonl")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="analyze a user request")
    ask_parser.add_argument("text", nargs="+", help="user request text")
    ask_parser.add_argument("--trace-dir", default=str(DEFAULT_TRACE_DIR))
    ask_parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_PATH))

    args = parser.parse_args(argv)

    if args.command == "ask":
        return _ask(args.text, Path(args.trace_dir), Path(args.audit_log))

    parser.error(f"unknown command: {args.command}")
    return 2


def _ask(text_parts: Sequence[str], trace_dir: Path, audit_path: Path) -> int:
    user_text = " ".join(text_parts)
    intent = analyze_user_intent(user_text)
    record = RunRecord.create(
        event="intent_analyzed",
        data={
            "user_text": user_text,
            "intent": intent.to_dict(),
            "artifacts": {
                "intent_schema": "artifacts/schemas/user-intent.schema.json",
                "intent_prompt": "artifacts/prompts/intent-classifier.md",
            },
        },
    )
    trace_path = write_trace(record, trace_dir)
    append_audit(record, audit_path)

    output = {
        "run_id": record.run_id,
        "intent": intent.to_dict(),
        "trace_path": str(trace_path),
        "audit_path": str(audit_path),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0

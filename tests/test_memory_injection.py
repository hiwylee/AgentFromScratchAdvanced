"""Tests for P6 cross-session memory injection.

Covers:
  - load_active_memories(): filtering, sorting, error handling
  - SessionContext.approved_memories: not persisted across save/load
  - AgentLoop(memory_dir=...): injection into run(), result.memory_summary
  - _format_memory_context(): formatting helpers
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent_runtime.self_evolution import (
    MEMORY_RECORD_SCHEMA_VERSION,
    MemoryProvenance,
    MemoryRecord,
    load_active_memories,
)
from agent_runtime.session import SessionContext
from agent_runtime.loop import AgentLoop
from agent_runtime.types import Budget, Message


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_memory(
    memory_id: str = "test-mem-1",
    key: str = "test_key",
    value: str = "test_value",
    status: str = "active",
    review_status: str = "approved",
) -> MemoryRecord:
    return MemoryRecord(
        schema_version=MEMORY_RECORD_SCHEMA_VERSION,
        memory_id=memory_id,
        key=key,
        value=value,
        status=status,  # type: ignore[arg-type]
        provenance=MemoryProvenance(
            source_type="test",
            source_id="test-source",
            author="tester",
            review_status=review_status,  # type: ignore[arg-type]
        ),
    )


def _write_memory(directory: Path, memory: MemoryRecord) -> Path:
    """Write a MemoryRecord as JSON to the given directory."""
    path = directory / f"{memory.memory_id}.json"
    path.write_text(
        json.dumps(memory.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _events_from_path(events_path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(events_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event_names_from_path(events_path: str) -> list[str]:
    return [e["event"] for e in _events_from_path(events_path)]


# ---------------------------------------------------------------------------
# load_active_memories tests
# ---------------------------------------------------------------------------

class LoadActiveMemoriesTests(unittest.TestCase):

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_active_memories(Path(tmp))
            self.assertEqual([], result)

    def test_missing_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist"
            result = load_active_memories(missing)
            self.assertEqual([], result)

    def test_active_approved_record_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            mem = _make_memory(status="active", review_status="approved")
            _write_memory(mem_dir, mem)

            result = load_active_memories(mem_dir)

            self.assertEqual(1, len(result))
            self.assertEqual("test-mem-1", result[0].memory_id)

    def test_pending_review_record_excluded(self):
        """A record with review_status=pending cannot be status=active (validation error),
        so we write raw JSON that bypasses MemoryRecord.from_dict to test the loader's skip behaviour."""
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            raw = {
                "schema_version": MEMORY_RECORD_SCHEMA_VERSION,
                "memory_id": "pending-mem",
                "key": "k",
                "value": "v",
                "status": "active",
                "provenance": {
                    "source_type": "test",
                    "source_id": "s",
                    "author": "a",
                    "review_status": "pending",
                },
            }
            (mem_dir / "pending-mem.json").write_text(
                json.dumps(raw) + "\n", encoding="utf-8"
            )

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)

    def test_proposed_status_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            # proposed + pending is valid to construct
            mem = _make_memory(
                memory_id="proposed-mem", status="proposed", review_status="pending"
            )
            _write_memory(mem_dir, mem)

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)

    def test_rejected_status_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            mem = _make_memory(
                memory_id="rejected-mem", status="rejected", review_status="pending"
            )
            _write_memory(mem_dir, mem)

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)

    def test_expired_status_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            mem = _make_memory(
                memory_id="expired-mem", status="expired", review_status="pending"
            )
            _write_memory(mem_dir, mem)

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)

    def test_changes_requested_excluded(self):
        """review_status=changes_requested with any non-active status is excluded."""
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            mem = _make_memory(
                memory_id="changes-mem",
                status="proposed",
                review_status="changes_requested",
            )
            _write_memory(mem_dir, mem)

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)

    def test_malformed_json_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            # Write one valid and one broken JSON file
            valid_mem = _make_memory(
                memory_id="aaa-valid-mem", status="active", review_status="approved"
            )
            _write_memory(mem_dir, valid_mem)
            (mem_dir / "broken.json").write_text(
                "{ not valid json @@@ ", encoding="utf-8"
            )

            result = load_active_memories(mem_dir)

            self.assertEqual(1, len(result))
            self.assertEqual("aaa-valid-mem", result[0].memory_id)

    def test_non_json_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            # Write non-.json files that should be ignored entirely
            (mem_dir / "notes.txt").write_text("not a memory", encoding="utf-8")
            (mem_dir / "README.md").write_text("# notes", encoding="utf-8")

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)

    def test_multiple_records_sorted_by_memory_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            for mid in ("zzz-mem", "aaa-mem", "mmm-mem"):
                _write_memory(
                    mem_dir,
                    _make_memory(memory_id=mid, status="active", review_status="approved"),
                )

            result = load_active_memories(mem_dir)

            self.assertEqual(3, len(result))
            self.assertEqual(["aaa-mem", "mmm-mem", "zzz-mem"], [r.memory_id for r in result])

    def test_invalid_schema_version_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = Path(tmp)
            bad = {
                "schema_version": "agent-runtime.memory-record.v99-UNKNOWN",
                "memory_id": "bad-schema-mem",
                "key": "k",
                "value": "v",
                "status": "active",
                "provenance": {
                    "source_type": "test",
                    "source_id": "s",
                    "author": "a",
                    "review_status": "approved",
                },
            }
            (mem_dir / "bad-schema-mem.json").write_text(
                json.dumps(bad) + "\n", encoding="utf-8"
            )

            result = load_active_memories(mem_dir)

            self.assertEqual([], result)


# ---------------------------------------------------------------------------
# SessionContext.approved_memories tests
# ---------------------------------------------------------------------------

class SessionContextApprovedMemoriesTests(unittest.TestCase):

    def test_approved_memories_default_empty(self):
        session = SessionContext(session_id="sess-mem-default")
        self.assertEqual([], session.approved_memories)

    def test_approved_memories_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-mem-persist"
            session = SessionContext(session_id="sess-mem-persist")
            mem = _make_memory(status="active", review_status="approved")
            session.approved_memories = [mem]

            session.save(session_dir)
            loaded = SessionContext.load(session_dir)

            self.assertEqual([], loaded.approved_memories)


# ---------------------------------------------------------------------------
# AgentLoop memory injection tests
# ---------------------------------------------------------------------------

class AgentLoopMemoryInjectionTests(unittest.TestCase):

    def _make_loop(self, tmp_path: Path, memory_dir: Path | None = None) -> AgentLoop:
        return AgentLoop(
            run_root=tmp_path / "runs",
            audit_path=tmp_path / "audit.jsonl",
            budget=Budget(max_steps=2, timeout_seconds=30),
            memory_dir=memory_dir,
        )

    def test_no_memory_dir_no_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_loop(Path(tmp), memory_dir=None)
            result = loop.run("summarize this repository")
            self.assertIsNone(result.memory_summary)

    def test_empty_memory_dir_no_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mem_dir = tmp_path / "memories"
            mem_dir.mkdir()
            loop = self._make_loop(tmp_path, memory_dir=mem_dir)

            result = loop.run("summarize this repository")

            self.assertIsNone(result.memory_summary)

    def test_memory_injected_appears_in_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mem_dir = tmp_path / "memories"
            mem_dir.mkdir()
            mem = _make_memory(
                memory_id="inject-mem-1",
                key="preferred_language",
                value="Korean",
                status="active",
                review_status="approved",
            )
            _write_memory(mem_dir, mem)
            loop = self._make_loop(tmp_path, memory_dir=mem_dir)

            result = loop.run("summarize this repository")

            self.assertIsNotNone(result.memory_summary)
            assert result.memory_summary is not None
            self.assertIn("inject-mem-1", result.memory_summary)
            self.assertIn("preferred_language", result.memory_summary)
            self.assertIn("Korean", result.memory_summary)

    def test_memory_injected_event_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mem_dir = tmp_path / "memories"
            mem_dir.mkdir()
            _write_memory(
                mem_dir,
                _make_memory(
                    memory_id="event-mem-1",
                    status="active",
                    review_status="approved",
                ),
            )
            loop = self._make_loop(tmp_path, memory_dir=mem_dir)

            result = loop.run("summarize this repository")

            event_names = _event_names_from_path(result.events_path)
            self.assertIn("memory_injected", event_names)

    def test_pending_memory_not_injected(self):
        """A memory file with status=active but review_status=pending is skipped
        by load_active_memories, so memory_summary stays None."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mem_dir = tmp_path / "memories"
            mem_dir.mkdir()
            raw = {
                "schema_version": MEMORY_RECORD_SCHEMA_VERSION,
                "memory_id": "pending-inject-mem",
                "key": "k",
                "value": "v",
                "status": "active",
                "provenance": {
                    "source_type": "test",
                    "source_id": "s",
                    "author": "a",
                    "review_status": "pending",
                },
            }
            (mem_dir / "pending-inject-mem.json").write_text(
                json.dumps(raw) + "\n", encoding="utf-8"
            )
            loop = self._make_loop(tmp_path, memory_dir=mem_dir)

            result = loop.run("summarize this repository")

            self.assertIsNone(result.memory_summary)
            event_names = _event_names_from_path(result.events_path)
            self.assertNotIn("memory_injected", event_names)


# ---------------------------------------------------------------------------
# _format_memory_context tests (via public result output)
# ---------------------------------------------------------------------------

class FormatMemoryContextTests(unittest.TestCase):
    """Tests for _format_memory_context via AgentLoop result.memory_summary."""

    def _run_with_memories(self, memories: list[MemoryRecord]) -> str | None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mem_dir = tmp_path / "memories"
            mem_dir.mkdir()
            for mem in memories:
                _write_memory(mem_dir, mem)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=2, timeout_seconds=30),
                memory_dir=mem_dir,
            )
            result = loop.run("summarize this repository")
            return result.memory_summary

    def test_format_memory_context_single(self):
        mem = _make_memory(
            memory_id="fmt-mem-1",
            key="greeting",
            value="hello world",
            status="active",
            review_status="approved",
        )
        summary = self._run_with_memories([mem])

        self.assertIsNotNone(summary)
        assert summary is not None
        # Expected format: "- [<memory_id>] <key>: <value>"
        self.assertIn("- [fmt-mem-1] greeting: hello world", summary)

    def test_format_memory_context_multiple(self):
        mems = [
            _make_memory(
                memory_id="fmt-aaa",
                key="key_a",
                value="val_a",
                status="active",
                review_status="approved",
            ),
            _make_memory(
                memory_id="fmt-bbb",
                key="key_b",
                value="val_b",
                status="active",
                review_status="approved",
            ),
        ]
        summary = self._run_with_memories(mems)

        self.assertIsNotNone(summary)
        assert summary is not None
        lines = summary.splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("- [fmt-aaa] key_a: val_a", summary)
        self.assertIn("- [fmt-bbb] key_b: val_b", summary)


if __name__ == "__main__":
    unittest.main()

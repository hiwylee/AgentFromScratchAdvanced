"""Tests for the operator review-candidate CLI commands."""
import json
import tempfile
import unittest
from pathlib import Path

from agent_runtime.self_evolution import (
    ArtifactChange,
    build_improvement_candidate,
    write_improvement_candidate,
)


def _make_candidate_file(tmp_dir: Path) -> tuple[Path, str]:
    """Write a candidate to tmp_dir, return (path, candidate_id)."""
    record = build_improvement_candidate(
        candidate_id="test-candidate-cli-review-001",
        candidate_type="prompt",
        trigger_type="test",
        summary="Test candidate for CLI review",
        proposed_change="Update the prompt",
        affected_artifacts=[
            ArtifactChange(
                path="artifacts/prompts/intent-classifier.md",
                artifact_type="prompt",
                current_version="v1",
                proposed_version="v2",
            )
        ],
        author="test-author",
        source_type="test",
        source_id="test-src",
        risk_level="low",
    )
    path = write_improvement_candidate(record, tmp_dir / f"{record.candidate_id}.json")
    return path, record.candidate_id


class ReviewCandidateListTests(unittest.TestCase):

    def _run_list(self, candidates_dir: Path, audit_path: Path) -> int:
        from unittest.mock import patch
        import sys
        argv = ["agent", "operator", "review-candidate", "list",
                "--candidates-dir", str(candidates_dir),
                "--audit-log", str(audit_path)]
        with patch.object(sys, "argv", argv):
            from agent_runtime.cli import main
            try:
                return main() or 0
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0

    def test_list_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            code = self._run_list(tmp_path, tmp_path / "audit.jsonl")
            self.assertEqual(code, 0)

    def test_list_with_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _make_candidate_file(tmp_path)
            code = self._run_list(tmp_path, tmp_path / "audit.jsonl")
            self.assertEqual(code, 0)


class ReviewCandidateApproveTests(unittest.TestCase):

    def _run_approve(self, candidate_id: str, reviewer: str,
                     candidates_dir: Path, audit_path: Path) -> int:
        from unittest.mock import patch
        import sys
        argv = ["agent", "operator", "review-candidate", "approve",
                "--candidate-id", candidate_id,
                "--reviewer", reviewer,
                "--candidates-dir", str(candidates_dir),
                "--audit-log", str(audit_path)]
        with patch.object(sys, "argv", argv):
            from agent_runtime.cli import main
            try:
                return main() or 0
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0

    def test_approve_updates_review_decision(self):
        from agent_runtime.self_evolution import load_improvement_candidate
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path, cid = _make_candidate_file(tmp_path)
            code = self._run_approve(cid, "reviewer-alice", tmp_path, tmp_path / "audit.jsonl")
            self.assertEqual(code, 0)
            updated = load_improvement_candidate(path)
            self.assertEqual(updated.review.decision, "approved")
            self.assertEqual(updated.review.reviewer, "reviewer-alice")

    def test_approve_writes_audit_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, cid = _make_candidate_file(tmp_path)
            audit_path = tmp_path / "audit.jsonl"
            self._run_approve(cid, "reviewer-alice", tmp_path, audit_path)
            self.assertTrue(audit_path.exists())
            lines = audit_path.read_text().splitlines()
            events = [json.loads(l)["event"] for l in lines if l.strip()]
            self.assertTrue(any("approved" in e for e in events))

    def test_approve_rejects_empty_reviewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, cid = _make_candidate_file(tmp_path)
            code = self._run_approve(cid, "", tmp_path, tmp_path / "audit.jsonl")
            self.assertNotEqual(code, 0)

    def test_approve_already_approved_candidate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, cid = _make_candidate_file(tmp_path)
            audit = tmp_path / "audit.jsonl"
            self._run_approve(cid, "reviewer-alice", tmp_path, audit)
            code = self._run_approve(cid, "reviewer-bob", tmp_path, audit)
            self.assertNotEqual(code, 0)

    def test_approve_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            code = self._run_approve("../../etc/passwd", "reviewer-alice", tmp_path, tmp_path / "audit.jsonl")
            self.assertNotEqual(code, 0)


class ReviewCandidateRejectTests(unittest.TestCase):

    def _run_reject(self, candidate_id: str, reviewer: str, notes: str,
                    candidates_dir: Path, audit_path: Path) -> int:
        from unittest.mock import patch
        import sys
        argv = ["agent", "operator", "review-candidate", "reject",
                "--candidate-id", candidate_id,
                "--reviewer", reviewer,
                "--notes", notes,
                "--candidates-dir", str(candidates_dir),
                "--audit-log", str(audit_path)]
        with patch.object(sys, "argv", argv):
            from agent_runtime.cli import main
            try:
                return main() or 0
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0

    def test_reject_updates_review_decision(self):
        from agent_runtime.self_evolution import load_improvement_candidate
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path, cid = _make_candidate_file(tmp_path)
            code = self._run_reject(cid, "reviewer-bob", "not ready", tmp_path, tmp_path / "audit.jsonl")
            self.assertEqual(code, 0)
            updated = load_improvement_candidate(path)
            self.assertEqual(updated.review.decision, "rejected")
            self.assertEqual(updated.review.notes, "not ready")

    def test_reject_already_rejected_candidate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, cid = _make_candidate_file(tmp_path)
            audit = tmp_path / "audit.jsonl"
            self._run_reject(cid, "reviewer-bob", "first rejection", tmp_path, audit)
            code = self._run_reject(cid, "reviewer-carol", "second rejection", tmp_path, audit)
            self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

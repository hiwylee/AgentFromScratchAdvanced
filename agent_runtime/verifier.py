"""Deterministic tool result verifier for the agent runtime.

Uses whitelist-based structural verification — no LLM calls.
Follows the _validated_llm_action() pattern from model.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tools import ToolResult
from .types import FailureReason, SuggestedAction


@dataclass
class VerificationResult:
    success: bool
    issues: list[str]
    failure_reason: FailureReason | None
    suggested_action: SuggestedAction
    alternative_tool: str | None = None


class ToolResultVerifier:
    """Verifies ToolResult against success_criteria.

    Uses _validated_llm_action() style: whitelist-based, deterministic.
    No LLM calls — structural verification only at this stage.
    """

    def verify(
        self,
        result: ToolResult,
        success_criteria: list[str],
        fallback_strategy: str = "retry",
    ) -> VerificationResult:
        """Verify a tool result.

        success_criteria examples:
          "tool.state == 'completed'"
          "output.row_count > 0"
          "output.tables is not empty"
        """
        # Resolve fallback_strategy to a valid SuggestedAction; default to "retry".
        _valid: set[SuggestedAction] = {"retry", "use_alternative", "clarify", "proceed", "abort", "skip"}
        resolved_fallback: SuggestedAction = (
            fallback_strategy if fallback_strategy in _valid else "retry"  # type: ignore[assignment]
        )

        # State-based deterministic gates (checked before criteria evaluation).
        if result.state == "blocked":
            return VerificationResult(
                success=False,
                issues=[f"tool blocked: {result.error}"],
                failure_reason="policy_denied",
                suggested_action="abort",
            )
        if result.state == "invalid":
            return VerificationResult(
                success=False,
                issues=[f"tool invalid: {result.error}"],
                failure_reason="schema_or_contract_mismatch",
                suggested_action="abort",
            )
        if result.state == "timed_out":
            return VerificationResult(
                success=False,
                issues=["tool timed out"],
                failure_reason="timeout",
                suggested_action="retry",
            )
        if result.state == "failed":
            return VerificationResult(
                success=False,
                issues=[f"tool failed: {result.error}"],
                failure_reason="tool_error",
                suggested_action="retry",
            )

        # state == "completed" — evaluate success_criteria.
        issues: list[str] = []
        for criterion in success_criteria:
            passed = _evaluate_criterion(criterion, result)
            if passed is False:
                issues.append(f"criterion failed: {criterion}")
            # passed is None means parse failure — skip (safe fallback per spec).

        if issues:
            return VerificationResult(
                success=False,
                issues=issues,
                failure_reason="data_mismatch",
                suggested_action=resolved_fallback,
            )

        return VerificationResult(
            success=True,
            issues=[],
            failure_reason=None,
            suggested_action="proceed",
        )


# ---------------------------------------------------------------------------
# Criterion evaluators
# ---------------------------------------------------------------------------

_IS_NOT_EMPTY_RE = re.compile(r"^output\.(\w+)\s+is\s+not\s+empty$")
_IS_EMPTY_RE = re.compile(r"^output\.(\w+)\s+is\s+empty$")
_IS_NOT_NONE_RE = re.compile(r"^output\.(\w+)\s+is\s+not\s+None$")
_IS_NONE_RE = re.compile(r"^output\.(\w+)\s+is\s+None$")
_OUTPUT_GT_RE = re.compile(r"^output\.(\w+)\s*>\s*(-?\d+(?:\.\d+)?)$")
_OUTPUT_GTE_RE = re.compile(r"^output\.(\w+)\s*>=\s*(-?\d+(?:\.\d+)?)$")
_OUTPUT_LT_RE = re.compile(r"^output\.(\w+)\s*<\s*(-?\d+(?:\.\d+)?)$")
_OUTPUT_LTE_RE = re.compile(r"^output\.(\w+)\s*<=\s*(-?\d+(?:\.\d+)?)$")
_OUTPUT_EQ_RE = re.compile(r"^output\.(\w+)\s*==\s*(-?\d+(?:\.\d+)?)$")
_TOOL_STATE_EQ_RE = re.compile(r"^tool\.state\s*==\s*'([^']+)'$")


def _evaluate_criterion(criterion: str, result: ToolResult) -> bool | None:
    """Evaluate a single criterion string against a ToolResult.

    Returns:
        True  — criterion passed
        False — criterion failed
        None  — criterion could not be parsed; caller should skip
    """
    criterion = criterion.strip()

    # tool.state == 'completed'
    m = _TOOL_STATE_EQ_RE.match(criterion)
    if m:
        expected_state = m.group(1)
        return result.state == expected_state

    # output.X is not empty
    m = _IS_NOT_EMPTY_RE.match(criterion)
    if m:
        key = m.group(1)
        return bool(result.output.get(key))

    # output.X is empty
    m = _IS_EMPTY_RE.match(criterion)
    if m:
        key = m.group(1)
        return not bool(result.output.get(key))

    # output.X is not None
    m = _IS_NOT_NONE_RE.match(criterion)
    if m:
        key = m.group(1)
        return result.output.get(key) is not None

    # output.X is None
    m = _IS_NONE_RE.match(criterion)
    if m:
        key = m.group(1)
        return result.output.get(key) is None

    # output.X > N
    m = _OUTPUT_GT_RE.match(criterion)
    if m:
        key, threshold = m.group(1), float(m.group(2))
        val = result.output.get(key, 0)
        try:
            return float(val) > threshold
        except (TypeError, ValueError):
            return False

    # output.X >= N
    m = _OUTPUT_GTE_RE.match(criterion)
    if m:
        key, threshold = m.group(1), float(m.group(2))
        val = result.output.get(key, 0)
        try:
            return float(val) >= threshold
        except (TypeError, ValueError):
            return False

    # output.X < N
    m = _OUTPUT_LT_RE.match(criterion)
    if m:
        key, threshold = m.group(1), float(m.group(2))
        val = result.output.get(key, 0)
        try:
            return float(val) < threshold
        except (TypeError, ValueError):
            return False

    # output.X <= N
    m = _OUTPUT_LTE_RE.match(criterion)
    if m:
        key, threshold = m.group(1), float(m.group(2))
        val = result.output.get(key, 0)
        try:
            return float(val) <= threshold
        except (TypeError, ValueError):
            return False

    # output.X == N
    m = _OUTPUT_EQ_RE.match(criterion)
    if m:
        key, threshold = m.group(1), float(m.group(2))
        val = result.output.get(key, 0)
        try:
            return float(val) == threshold
        except (TypeError, ValueError):
            return False

    # Unparseable criterion — skip (safe fallback).
    return None

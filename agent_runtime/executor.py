"""Shadow-mode step executor.

In shadow mode, StepExecutor builds an ExecutionPlan and records it
in the trace without affecting actual execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .planner import ExecutionPlan, PlanStep
from .verifier import ToolResultVerifier, VerificationResult
from .tools import ToolResult


@dataclass
class StepResult:
    step_id: str
    tool_name: str | None
    tool_result: ToolResult | None
    verification: VerificationResult | None
    skipped: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "skipped": self.skipped,
            "error": self.error,
        }
        if self.tool_result is not None:
            result["tool_result"] = self.tool_result.to_dict()
        else:
            result["tool_result"] = None
        if self.verification is not None:
            result["verification"] = {
                "success": self.verification.success,
                "issues": list(self.verification.issues),
                "failure_reason": self.verification.failure_reason,
                "suggested_action": self.verification.suggested_action,
                "alternative_tool": self.verification.alternative_tool,
            }
        else:
            result["verification"] = None
        return result


class StepExecutor:
    """Executes an ExecutionPlan step by step.

    Uses ThreadPoolExecutor for parallel groups derived from
    ExecutionPlan.topological_groups().
    """

    def __init__(self, verifier: ToolResultVerifier | None = None) -> None:
        self._verifier = verifier or ToolResultVerifier()

    def run_plan_shadow(self, plan: ExecutionPlan) -> list[StepResult]:
        """Shadow mode: validate plan structure, return stub results.

        Does NOT execute any tools. Used to test plan generation
        before committing to actual execution.
        """
        errors = plan.validate()
        error_str = "; ".join(errors) if errors else ""
        results: list[StepResult] = []
        for step in plan.steps:
            results.append(StepResult(
                step_id=step.step_id,
                tool_name=None,
                tool_result=None,
                verification=None,
                skipped=True,
                error=error_str,
            ))
        return results

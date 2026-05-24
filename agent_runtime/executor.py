"""Shadow-mode step executor.

In shadow mode, StepExecutor builds an ExecutionPlan and records it
in the trace without affecting actual execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from .planner import ExecutionPlan, PlanStep
from .verifier import ToolResultVerifier, VerificationResult
from .tools import ToolCall, ToolResult

if TYPE_CHECKING:
    from .tools import ToolRegistry, ToolRunner, ToolSpec


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

    def run_plan(
        self,
        plan: ExecutionPlan,
        tool_runner: "ToolRunner",
        *,
        tool_registry: "ToolRegistry | None" = None,
        approval_callback: Callable[[PlanStep], bool] | None = None,
    ) -> list[StepResult]:
        """Real execution: calls tools, verifies results, applies fallback strategies.

        Uses topological_groups() for parallel-group ordering.
        Each step: find tool by primary_capability -> run -> verify -> retry/skip/abort.
        Returns list[StepResult] with real tool results.
        """
        registry = tool_registry if tool_registry is not None else tool_runner.registry
        groups = plan.topological_groups()
        results_by_id: dict[str, StepResult] = {}
        aborted_by: str | None = None

        for group in groups:
            for step in group:
                if aborted_by is not None:
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=None,
                        tool_result=None,
                        verification=None,
                        skipped=True,
                        error=f"aborted_by_step:{aborted_by}",
                    )
                    continue

                if step.requires_approval:
                    if approval_callback is None:
                        results_by_id[step.step_id] = StepResult(
                            step_id=step.step_id,
                            tool_name=None,
                            tool_result=None,
                            verification=None,
                            skipped=True,
                            error=f"approval_required_no_callback:{step.step_id}",
                        )
                        continue
                    if not approval_callback(step):
                        results_by_id[step.step_id] = StepResult(
                            step_id=step.step_id,
                            tool_name=None,
                            tool_result=None,
                            verification=None,
                            skipped=True,
                            error=f"approval_denied:{step.step_id}",
                        )
                        continue

                tool_spec = _find_tool_for_capability(step.primary_capability, registry)
                if tool_spec is None:
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=None,
                        tool_result=None,
                        verification=None,
                        skipped=True,
                        error=f"no_tool_for_capability:{step.primary_capability}",
                    )
                    continue

                tool_call = ToolCall(
                    name=tool_spec.name,
                    arguments={
                        "step_id": step.step_id,
                        "capability": step.primary_capability,
                    },
                )
                max_attempts = int(step.retry_policy.get("max_attempts", 1))
                tool_result = tool_runner.run(tool_call, max_attempts=max_attempts)
                verification = self._verifier.verify(
                    tool_result,
                    step.success_criteria,
                    step.fallback_strategy,
                )

                action = verification.suggested_action
                if action in ("proceed", "retry"):
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=tool_spec.name,
                        tool_result=tool_result,
                        verification=verification,
                        skipped=False,
                        error="",
                    )
                elif action == "skip":
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=tool_spec.name,
                        tool_result=tool_result,
                        verification=verification,
                        skipped=True,
                        error="",
                    )
                elif action == "abort":
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=tool_spec.name,
                        tool_result=tool_result,
                        verification=verification,
                        skipped=False,
                        error="",
                    )
                    aborted_by = step.step_id
                elif action == "clarify":
                    issues_str = ",".join(verification.issues) if verification.issues else ""
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=tool_spec.name,
                        tool_result=tool_result,
                        verification=verification,
                        skipped=True,
                        error=f"clarification_needed:{issues_str}",
                    )
                elif action == "use_alternative":
                    alt_name = verification.alternative_tool
                    alt_spec = None
                    if alt_name:
                        try:
                            alt_spec = registry.get(alt_name).spec
                        except KeyError:
                            alt_spec = None
                    if alt_spec is None:
                        results_by_id[step.step_id] = StepResult(
                            step_id=step.step_id,
                            tool_name=tool_spec.name,
                            tool_result=tool_result,
                            verification=verification,
                            skipped=True,
                            error="",
                        )
                    else:
                        alt_call = ToolCall(
                            name=alt_spec.name,
                            arguments={
                                "step_id": step.step_id,
                                "capability": step.primary_capability,
                            },
                        )
                        alt_result = tool_runner.run(alt_call, max_attempts=max_attempts)
                        alt_verification = self._verifier.verify(
                            alt_result,
                            step.success_criteria,
                            step.fallback_strategy,
                        )
                        results_by_id[step.step_id] = StepResult(
                            step_id=step.step_id,
                            tool_name=alt_spec.name,
                            tool_result=alt_result,
                            verification=alt_verification,
                            skipped=False,
                            error="",
                        )
                else:
                    results_by_id[step.step_id] = StepResult(
                        step_id=step.step_id,
                        tool_name=tool_spec.name,
                        tool_result=tool_result,
                        verification=verification,
                        skipped=False,
                        error="",
                    )

        return [results_by_id[s.step_id] for s in plan.steps if s.step_id in results_by_id]


def _find_tool_for_capability(
    cap: str,
    registry: "ToolRegistry",
) -> "ToolSpec | None":
    for registered in registry.all_registered():
        if cap in registered.spec.capabilities:
            return registered.spec
    return None

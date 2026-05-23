"""Deterministic execution planner for the intent-first agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .types import IntentResult


@dataclass
class PlanStep:
    step_id: str
    description: str
    required_capabilities: list[str]
    primary_capability: str
    depends_on: list[str]
    success_criteria: list[str]
    expected_output: str
    retry_policy: dict[str, Any]
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_approval: bool = False
    fallback_strategy: Literal["retry", "skip", "clarify", "abort"] = "retry"

    def __post_init__(self) -> None:
        if not self.primary_capability and self.required_capabilities:
            self.primary_capability = self.required_capabilities[0]
        if self.risk_level == "high":
            self.requires_approval = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "required_capabilities": list(self.required_capabilities),
            "primary_capability": self.primary_capability,
            "depends_on": list(self.depends_on),
            "success_criteria": list(self.success_criteria),
            "expected_output": self.expected_output,
            "retry_policy": dict(self.retry_policy),
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "fallback_strategy": self.fallback_strategy,
        }


@dataclass
class ExecutionPlan:
    request_id: str
    goal: str
    primary_route: str
    steps: list[PlanStep]
    assumptions: list[str] = field(default_factory=list)

    def topological_groups(self) -> list[list[PlanStep]]:
        """DAG topological sort via Kahn's algorithm — yields parallel execution groups."""
        step_map = {s.step_id: s for s in self.steps}
        in_degree: dict[str, int] = {s.step_id: 0 for s in self.steps}
        dependents: dict[str, list[str]] = {s.step_id: [] for s in self.steps}

        for step in self.steps:
            for dep in step.depends_on:
                if dep in in_degree:
                    in_degree[step.step_id] += 1
                    dependents[dep].append(step.step_id)

        groups: list[list[PlanStep]] = []
        current_group = [step_map[sid] for sid, deg in in_degree.items() if deg == 0]

        while current_group:
            groups.append(current_group)
            next_group: list[PlanStep] = []
            for step in current_group:
                for dependent_id in dependents[step.step_id]:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        next_group.append(step_map[dependent_id])
            current_group = next_group

        return groups

    def validate(self) -> list[str]:
        """Validate the plan graph. Returns list of error messages, empty if valid."""
        errors: list[str] = []
        step_ids = {s.step_id for s in self.steps}

        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    errors.append(
                        f"step '{step.step_id}' depends_on unknown step_id '{dep}'"
                    )

        # Cycle detection via DFS
        visited: set[str] = set()
        in_stack: set[str] = set()
        adj: dict[str, list[str]] = {s.step_id: list(s.depends_on) for s in self.steps}

        def dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for neighbour in adj.get(node, []):
                if neighbour not in step_ids:
                    continue
                if neighbour not in visited:
                    if dfs(neighbour):
                        return True
                elif neighbour in in_stack:
                    return True
            in_stack.discard(node)
            return False

        for step in self.steps:
            if step.step_id not in visited:
                if dfs(step.step_id):
                    errors.append("cycle detected in depends_on graph")
                    break

        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "goal": self.goal,
            "primary_route": self.primary_route,
            "steps": [s.to_dict() for s in self.steps],
            "assumptions": list(self.assumptions),
        }


_DEFAULT_RETRY_POLICY: dict[str, Any] = {"max_attempts": 3}


class KeywordPlanner:
    """Deterministic planner that builds a simple 1-2 step ExecutionPlan from IntentResult."""

    def build(self, intent_result: IntentResult, request_id: str) -> ExecutionPlan:
        """Build an ExecutionPlan from an IntentResult.

        database_analysis  → [inspect_schema, execute_query]  2 steps
        business_workflow  → [select_workflow, execute_workflow]  2 steps
        general_answer     → [answer]  1 step
        """
        route = intent_result.primary_route
        goal = f"route={route}"

        if route == "database_analysis":
            steps = [
                PlanStep(
                    step_id="inspect_schema",
                    description="Inspect the database schema to identify relevant tables and columns.",
                    required_capabilities=["schema_inspection", "database_read"],
                    primary_capability="schema_inspection",
                    depends_on=[],
                    success_criteria=["output.tables_found > 0"],
                    expected_output="schema context with table and column metadata",
                    retry_policy=dict(_DEFAULT_RETRY_POLICY),
                    risk_level="low",
                ),
                PlanStep(
                    step_id="execute_query",
                    description="Execute the analytic query against the database.",
                    required_capabilities=["sql_execution", "database_read"],
                    primary_capability="sql_execution",
                    depends_on=["inspect_schema"],
                    success_criteria=["output.row_count > 0", "tool.state == 'completed'"],
                    expected_output="query result rows with column values",
                    retry_policy=dict(_DEFAULT_RETRY_POLICY),
                    risk_level="low",
                ),
            ]
        elif route == "business_workflow":
            steps = [
                PlanStep(
                    step_id="select_workflow",
                    description="Select the appropriate workflow template for the request.",
                    required_capabilities=["workflow_selection"],
                    primary_capability="workflow_selection",
                    depends_on=[],
                    success_criteria=["output.workflow_id is not None"],
                    expected_output="workflow template identifier and parameters",
                    retry_policy=dict(_DEFAULT_RETRY_POLICY),
                    risk_level="high",
                ),
                PlanStep(
                    step_id="execute_workflow",
                    description="Execute the selected workflow with checkpoint gates.",
                    required_capabilities=["workflow_execution"],
                    primary_capability="workflow_execution",
                    depends_on=["select_workflow"],
                    success_criteria=["tool.state == 'completed'"],
                    expected_output="workflow execution result with audit trail",
                    retry_policy=dict(_DEFAULT_RETRY_POLICY),
                    risk_level="high",
                ),
            ]
        else:
            steps = [
                PlanStep(
                    step_id="answer",
                    description="Generate a direct answer to the user request.",
                    required_capabilities=["general_answer"],
                    primary_capability="general_answer",
                    depends_on=[],
                    success_criteria=["output.content is not None"],
                    expected_output="natural language answer",
                    retry_policy=dict(_DEFAULT_RETRY_POLICY),
                    risk_level="low",
                ),
            ]

        return ExecutionPlan(
            request_id=request_id,
            goal=goal,
            primary_route=route,
            steps=steps,
            assumptions=[],
        )

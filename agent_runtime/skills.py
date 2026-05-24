"""Skill registry for the agent runtime.

Skills are high-level capability patterns built on top of tools.
A Skill declares which capabilities it needs and provides a handler
that orchestrates them. Unlike Tools, Skills are not gated by _policy_error()
directly — they compose Tool calls through ToolRunner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

SkillHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SkillSpec:
    """Specification for a registered skill."""
    name: str
    description: str
    required_capabilities: tuple[str, ...]  # capabilities this skill needs
    handler: SkillHandler
    version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required_capabilities": list(self.required_capabilities),
            "version": self.version,
        }


class SkillRegistry:
    """Register and discover skills by required capabilities."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        """Register a skill. Raises ValueError on duplicate name or invalid spec."""
        if not spec.name or not spec.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("skill name must be non-empty alphanumeric with '-' or '_'")
        if spec.name in self._skills:
            raise ValueError(f"skill already registered: {spec.name}")
        if not callable(spec.handler):
            raise ValueError("skill handler must be callable")
        self._skills[spec.name] = spec

    def get(self, name: str) -> SkillSpec:
        """Get skill by name. Raises KeyError if not found."""
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {name}") from exc

    def find_by_capabilities(self, required: list[str]) -> list[SkillSpec]:
        """Return skills whose required_capabilities intersect with required.

        Returns empty list if required is empty.
        """
        if not required:
            return []
        required_set = set(required)
        return [
            spec for spec in self._skills.values()
            if not required_set.isdisjoint(set(spec.required_capabilities))
        ]

    def all_registered(self) -> list[SkillSpec]:
        """Return all registered skills."""
        return list(self._skills.values())

    def specs(self) -> list[dict[str, Any]]:
        """Return all skill specs as dicts."""
        return [spec.to_dict() for spec in self._skills.values()]

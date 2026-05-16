# Harness Engineering Notes

## Working Definition

Harness engineering is the work around the model that makes an agent reliable:
instructions, context layout, tools, tests, constraints, documentation, and
operational workflow.

For this project, the harness is not an afterthought. The harness is the system
that lets a small model loop become a useful agent.

## Applied Principles

- Keep root instructions short and durable.
- Move detailed plans and background into structured docs.
- Make the agent navigate by filenames and sections, not by a giant prompt.
- Prefer checkable constraints over prose-only expectations.
- Convert repeated mistakes into tests, linters, or project guidance.
- Track decisions close to the code they affect.

## Documentation Layers

- `AGENTS.md`: stable guidance and navigation.
- Product specs: what experience we are building.
- Design docs: how the runtime is shaped.
- Exec plans: what we are doing now.
- References: distilled notes from Codex and external material.

## Early Harness Requirements

- Every milestone gets an exec plan.
- Every new subsystem gets a short design note before broad implementation.
- Every command used for verification is recorded in the final status.
- Generated files live under `docs/generated/` or another explicit generated
  path.

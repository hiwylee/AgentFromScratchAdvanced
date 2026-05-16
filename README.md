# AgentFromScrach

An incremental project to build an agent runtime from scratch, using OpenAI
Codex concepts as a reference and applying harness engineering from the start.

The first goal is not to reproduce Codex. The first goal is to create a small,
testable agent loop that can:

1. accept a user task,
2. maintain state,
3. choose a next action,
4. call a controlled tool,
5. observe the result,
6. produce a final answer.

The project will grow from that loop into planning, sandboxed execution, memory,
multi-step workflows, and stronger verification.

The first domain specialization is natural-language access to database data:
schema-aware question answering, safe query generation, result explanation, and
evaluation fixtures for natural-language-to-SQL behavior.

## Repository Map

- `AGENTS.md`: root instructions and harness map.
- `docs/product-specs/`: what the agent should do and not do.
- `docs/design-docs/`: architecture and tradeoff records.
- `docs/exec-plans/active/`: current implementation plans.
- `docs/references/`: notes from `../codex` and external references.

## First Discussion Topics

- Runtime language and packaging.
- Minimum tool interface.
- Whether the first model adapter should be mocked, API-backed, or both.
- What "done" means for milestone 1.
- Which database dialect should be supported first.

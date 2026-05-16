# Todo

## Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done
- `[?]` Needs decision

## Project Setup

- `[x]` Create private GitHub repository.
- `[x]` Add root `AGENTS.md` guidance.
- `[x]` Add initial README.
- `[x]` Add product spec and architecture notes.
- `[x]` Add Oracle ADW connection design.
- `[x]` Add `.gitignore` and `.env.example`.
- `[x]` Add continuity tracking files.
- `[ ]` Resolve normal worktree `.git` setup if the read-only mount is removed.

## Implementation Decisions

- `[?]` Choose primary runtime language.
- `[?]` Choose first CLI command shape.
- `[?]` Choose mock-model-first versus API-model-first sequencing.
- `[?]` Choose first Oracle ADW execution backend: SQLcl subprocess or direct
  driver.
- `[?]` Choose initial test framework.
- `[?]` Choose prompt, policy, memory, and eval artifact formats.
- `[?]` Choose schema retrieval strategy for compact Oracle ADW context.

## Milestone 1: Minimal Agent Loop

- `[ ]` Create the first compilable package.
- `[ ]` Define message, action, observation, and final-answer types.
- `[ ]` Define structured user intent types.
- `[ ]` Implement a mock model adapter.
- `[ ]` Implement the basic agent loop and stop conditions.
- `[ ]` Add append-only audit event recording.
- `[ ]` Add cancellation and timeout primitives.
- `[ ]` Add token, cost, row, and latency budget placeholders.
- `[ ]` Add focused tests for state transitions.
- `[ ]` Add a CLI entry point that can run with the mock model.

## Milestone 2: Tool Loop

- `[ ]` Define a structured tool interface.
- `[ ]` Add tool registry and validation.
- `[ ]` Add retry and max-step limits.
- `[ ]` Add observable progress reporting.

## Milestone 3: Observability And Eval Skeleton

- `[ ]` Add structured trace output for agent steps.
- `[ ]` Add eval fixture file format.
- `[ ]` Add frozen golden eval set location.
- `[ ]` Add eval runner skeleton with mock-model fixtures.
- `[ ]` Add prompt, policy, and memory version fields to traces.
- `[ ]` Add redaction tests for secrets.

## Milestone 4: Oracle ADW Read-Only Foundation

- `[ ]` Load Oracle ADW config from environment variables.
- `[ ]` Verify SQLcl exists without printing secrets.
- `[ ]` Verify wallet paths without printing wallet contents.
- `[ ]` Implement working-user read-only query execution.
- `[ ]` Add database least-privilege expectations for the working user.
- `[ ]` Add query policy that blocks writes, DDL, `SELECT ... FOR UPDATE`,
  procedural blocks, database links, resource-heavy hints, and unsafe
  multi-statement input.
- `[ ]` Add schema introspection queries.
- `[ ]` Add tests with fixtures that do not require real credentials.

## Milestone 5: Compact Schema Context

- `[ ]` Define schema metadata storage format.
- `[ ]` Add curated table and glossary seed format.
- `[ ]` Add table/column retrieval over names, comments, and business terms.
- `[ ]` Add on-demand table expansion.
- `[ ]` Add sample-value masking policy.
- `[ ]` Record schema context used for each answer.

## Milestone 6: Natural Language To SQL

- `[ ]` Build compact schema context.
- `[ ]` Generate candidate query plans.
- `[ ]` Validate generated SQL before execution.
- `[ ]` Explain query assumptions and results.
- `[ ]` Add NL-to-SQL evaluation fixtures.

## Milestone 7: Self-Evolution Controls

- `[ ]` Add improvement candidate records.
- `[ ]` Add memory provenance fields.
- `[ ]` Add prompt, policy, and memory rollback path.
- `[ ]` Add drift detection fixtures for repeated questions.
- `[ ]` Require frozen eval pass before accepting behavior-shaping changes.

## Ongoing Harness Work

- `[ ]` Move completed exec plans to `docs/exec-plans/completed/`.
- `[ ]` Record durable decisions in `docs/tracking/decisions.md`.
- `[ ]` Update `docs/tracking/change-log.md` after meaningful changes.
- `[ ]` Keep `docs/tracking/current-state.md` accurate before ending sessions.

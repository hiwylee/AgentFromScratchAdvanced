# 0001 Project Bootstrap

## Objective

Create the project harness before writing runtime code so future implementation
work has a clear map, decision trail, and verification habit.

## Status

Completed.

## Scope

- Add repository-level agent instructions.
- Add product and architecture notes.
- Define the first milestone ladder.
- Identify the first decisions to make with the user.
- Add continuity tracking so future sessions can resume from project files.

## Decisions Needed

- Runtime language.
- First CLI interface.
- Mock-model-first or API-model-first.
- Minimal tool set for milestone 1.
- Testing framework.

## Outcome

The bootstrap harness is complete. The project now has stable repository
instructions, product and design docs, tracking files, a uv-managed Python
3.13+ prototype, audit/trace output, workflow and Oracle ADW design boundaries,
eval fixtures, and follow-on runtime milestones tracked in `docs/tracking/`.

## Verification

Original bootstrap verification was documentation-only. Runtime verification is
now tracked in `docs/tracking/current-state.md` and `docs/tracking/change-log.md`.

Tracking verification:

- `docs/tracking/current-state.md` records the resume point.
- `docs/tracking/todo.md` records the full todo list and current status.
- `docs/tracking/change-log.md` records major changes.
- `docs/tracking/decisions.md` records durable project decisions.

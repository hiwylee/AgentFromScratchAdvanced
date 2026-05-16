# Self-Evolution Design

## Objective

Let the agent improve over time without allowing it to silently rewrite its own
behavior in unsafe ways.

Self-evolution means proposing and tracking improvements to prompts, policies,
memory, fixtures, and docs. It does not mean unreviewed code or policy changes.

## Safe Improvement Loop

1. Run a task.
2. Record structured trace and audit events.
3. Detect failure, ambiguity, drift, or user correction.
4. Classify the cause.
5. Propose one improvement candidate.
6. Run regression evals, including frozen golden fixtures.
7. Require approval or an explicit acceptance rule.
8. Commit the accepted change with versioned artifacts.

## Phase 1 Requirement

The full improvement loop can wait, but append-only recording cannot. From the
first executable runtime, record enough information to reconstruct:

- user intent;
- model output;
- tool calls;
- policy decisions;
- observations;
- errors;
- improvement candidates;
- prompt, policy, memory, and schema-context versions.

## Guardrails

- Keep a frozen golden eval set. Do not edit it just to make a new change pass.
- Change prompt, policy, memory, or schema retrieval one at a time when possible.
- Make rollback cheap by versioning all behavior-shaping artifacts.
- Store memory with provenance: source, timestamp, author, confidence, and
  supporting evidence.
- Treat user corrections as candidates, not automatically trusted truth.
- Detect drift when repeated questions start producing materially different
  query plans or answers.

## Improvement Targets

- Prompt text and structured-output schemas.
- Query safety policy.
- Domain glossary entries.
- Schema retrieval ranking hints.
- Eval fixtures.
- Ambiguity handling rules.
- Result explanation templates.

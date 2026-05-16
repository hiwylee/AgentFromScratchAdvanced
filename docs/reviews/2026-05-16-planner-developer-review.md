# Planner And Developer Review

## Context

The project is designing an agent runtime from scratch, with Oracle ADW
natural-language database analysis as the first domain specialization.

This review records planner feedback, developer feedback, and PM decisions.

## Planner Feedback

- The product direction is strong, but the primary user should be explicit.
- The MVP should avoid promising full natural-language-to-SQL too early.
- The first value moment should be easy to demo and explain.
- User intent analysis should be treated as a visible product capability, not
  just internal routing.
- Clarifying questions are part of the experience and should be designed early.
- Result explanations should include assumptions and limits so users can trust
  the answer.

## Developer Feedback

- Artifact formats need to be chosen early enough to prevent churn.
- Milestones need acceptance criteria, not only task lists.
- The first runtime should include audit and trace events before complex tools.
- Oracle ADW work should use SQLcl first, but hide it behind an interface.
- Query safety should rely on DB least privilege first, then parser or policy
  validation as defense in depth.
- Prompt, policy, memory, and eval data should be hot-swappable without
  recompiling the core runtime.
- Eval skeleton should land before NL-to-SQL so prompt and schema-context
  changes can be gated.

## PM Decisions

- Primary user: a technical analyst or developer who has access to Oracle ADW
  and wants reliable natural-language assistance for schema exploration and
  read-only analysis.
- MVP scope: agent runtime foundation plus visible intent analysis, not full
  autonomous NL-to-SQL.
- First demo path:
  1. accept a user question;
  2. classify intent into a structured object;
  3. identify whether Oracle ADW context is required;
  4. emit audit and trace records;
  5. return next action or clarification request.
- First Oracle demo path:
  1. load environment configuration;
  2. verify SQLcl;
  3. verify wallet paths without printing secrets;
  4. run a safe read-only smoke query with the working user;
  5. explain the result and record trace metadata.
- Full NL-to-SQL remains after compact schema context and eval skeleton are in
  place.

## PM Changes To Track

- Add product personas and MVP boundaries to the product spec.
- Add milestone acceptance criteria.
- Treat intent output as a first-class product artifact.
- Add project artifact format decisions to the decision backlog.
- Keep SQLcl implementation behind a connector interface.
- Keep eval and observability ahead of NL-to-SQL work.

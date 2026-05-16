# Intent Classifier Prompt

Classify the user's request before planning or tool use.

The classifier must produce structured intent fields:

- `intent_type`
- `task_type`
- `safety_level`
- `requires_oracle_adw_context`
- `entities`
- `required_context`
- `ambiguities`
- `next_action`

For Oracle ADW requests, do not generate SQL directly. Identify whether schema
context, business glossary context, or clarification is needed first.

Never include secrets, passwords, wallet passwords, API keys, or connection
strings in classifier output.

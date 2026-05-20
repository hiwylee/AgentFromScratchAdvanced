# AgentFromScratch

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

The first domain specialization is natural-language access to Oracle Autonomous
Data Warehouse data: schema-aware question answering, safe query generation,
result explanation, and evaluation fixtures for natural-language-to-SQL
behavior.

## Repository Map

- `AGENTS.md`: root instructions and harness map.
- `docs/product-specs/`: what the agent should do and not do.
- `docs/design-docs/`: architecture and tradeoff records.
- `docs/exec-plans/active/`: current implementation plans.
- `docs/tracking/`: current state, todo list, decisions, and change log.
- `docs/references/`: notes from `../codex` and external references.

## Resume Point

Start every resumed session with:

1. [docs/tracking/current-state.md](docs/tracking/current-state.md)
2. [docs/tracking/todo.md](docs/tracking/todo.md)
3. [docs/tracking/change-log.md](docs/tracking/change-log.md)

## Local Database Configuration

Local Oracle ADW credentials are read from `.env`, which is intentionally
ignored by git. Passwords, wallet passwords, API keys, wallet files, and
secret-bearing connection strings must not be printed or committed.

SQLcl is expected at:

```text
/home/opc/.local/share/sqlcl/sqlcl/bin/sql
```

## Running The Prototype

The current executable is a Python 3.12+ prototype run through `uv`.

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m agent_runtime ask "지난달 상품별 매출 추이를 보여줘"
```

or:

```bash
bin/agent ask "지난달 상품별 매출 추이를 보여줘"
```

Monitor the latest run with:

```bash
bin/agent status
```

Run tests with:

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest discover -s tests
```

## Optional Live LLM Provider

The default action model can remain deterministic mock mode, or route through
an OpenAI-compatible Responses API provider. For OpenAI, set `OPENAI_API_KEY`
and opt in explicitly:

```bash
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --model-provider openai
```

For OCI Generative AI's OpenAI-compatible endpoint, set `OCI_BASE_URL` and
`OCI_API_KEY` or `OCI_API_KEY_2`, then use:

```bash
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --model-provider oci
```

Useful environment variables:

- `AGENT_MODEL_PROVIDER=mock`, `openai`, or `oci`
- `LLM=mock`, `openai`, or `oci`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`, default `gpt-5.2`
- `OPENAI_BASE_URL`, default `https://api.openai.com/v1`
- `OPENAI_TIMEOUT_SECONDS`, default `30`
- `OCI_BASE_URL`
- `OCI_API_KEY` or `OCI_API_KEY_2`
- `OCI_MODEL`, default `xai.grok-4-1-fast-non-reasoning`
- `OCI_TIMEOUT_SECONDS`, default `30`

Live LLM planning does not enable live Oracle ADW execution or workflow writes.
Those remain behind their explicit operator-only confirmation commands.
OCI-specific setup and troubleshooting are documented in
`docs/runbooks/oci-responses-api.md`.

## First Discussion Topics

- Runtime language and packaging.
- Minimum tool interface.
- Whether the first model adapter should be mocked, API-backed, or both.
- What "done" means for milestone 1.
- How much Oracle ADW metadata and sample data can safely be exposed to the
  model.

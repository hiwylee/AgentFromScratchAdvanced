# OCI Responses API Runbook

## Purpose

This runbook documents how AgentFromScratch connects `agent ask` to OCI
Generative AI through the OpenAI-compatible Responses API.

Normal agent behavior remains safe by default:

- `agent ask` can use `mock`, `openai`, or `oci` action planning.
- OCI LLM planning never enables live Oracle ADW execution.
- OCI LLM planning never enables workflow target-system writes.
- Returned model actions are validated against local allowed action kinds
  before the agent accepts them.

## Official OCI API Shape

Oracle documents the OCI OpenAI-compatible base endpoint as:

```text
https://inference.generativeai.${region}.oci.oraclecloud.com/openai/v1
```

The Responses API endpoint path is:

```text
/responses
```

For this project, the expected full primary URL is:

```text
https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/openai/v1/responses
```

The OCI Responses API requires:

- an OCI Generative AI project;
- an OpenAI-compatible base URL for the target region;
- API key or IAM authentication;
- a supported model in the selected region;
- a project identifier for the request.

Oracle's OpenAI SDK example passes the project OCID as the SDK `project`
parameter. The local no-dependency HTTP adapter maps `OCI_PROJECT_OCID` to the
`OpenAI-Project` request header.

## Local Environment

Use `.env` for local development. Do not commit `.env`.

Required for OCI:

```bash
AGENT_MODEL_PROVIDER=oci
LLM=oci
OCI_BASE_URL=https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/openai/v1
OCI_PROJECT_OCID=ocid1.generativeaiproject.oc1.us-chicago-1...
OCI_API_KEY=...
OCI_MODEL=xai.grok-4-1-fast-non-reasoning
OCI_TIMEOUT_SECONDS=30
```

Optional:

```bash
OCI_API_KEY_2=...
OCI_CONVERSATION_STORE_ID=...
```

`OCI_API_KEY_2` is used only when `OCI_API_KEY` is absent or intentionally
blanked in the process environment. `OCI_CONVERSATION_STORE_ID`, when present,
is sent as `opc-conversation-store-id`.

## Run A Smoke Test

Use an explicit provider flag when testing so shell or `.env` defaults are not
ambiguous:

```bash
bin/agent ask "hello" --model-provider oci --run-dir /tmp/afs-oci-smoke --audit-log /tmp/afs-oci-smoke.jsonl
```

Expected successful action shape:

```json
{
  "kind": "final_answer",
  "payload": {
    "llm_action_validated": true,
    "model_provider": "oci"
  }
}
```

Test the secondary key without printing either key:

```bash
OCI_API_KEY= bin/agent ask "hello" --model-provider oci --run-dir /tmp/afs-oci-key2-smoke --audit-log /tmp/afs-oci-key2-smoke.jsonl
```

## Endpoint Behavior In This Runtime

The adapter first calls the documented OpenAI-compatible endpoint:

```text
${OCI_BASE_URL}/responses
```

If OCI returns HTTP 404 for that primary request, the adapter retries the OCI
API-key actions route:

```text
https://inference.generativeai.${region}.oci.oraclecloud.com/20231130/actions/v1/responses
```

This fallback exists because the local API-key smoke test reached OCI with the
documented `/openai/v1/responses` route but received
`Authorization failed or requested resource not found`; the same request
succeeded through the API-key actions route. Keep the documented route first so
future OCI endpoint behavior can work without the compatibility fallback.

## Troubleshooting

`400 Non-OpenAI models require 'OpenAI-Project' or 'opc-conversation-store-id'`

- Ensure `OCI_PROJECT_OCID` is set.
- Alternatively set `OCI_CONVERSATION_STORE_ID` if using OCI conversation
  state.

`404 Authorization failed or requested resource not found`

- Confirm `OCI_BASE_URL` region and `OCI_PROJECT_OCID` region match.
- Confirm the API key is authorized for the project.
- Confirm the model is available in the selected region.
- Confirm the request includes `OpenAI-Project` or
  `opc-conversation-store-id`.
- If the documented `/openai/v1/responses` route returns this error, the local
  adapter will try the API-key actions fallback route.

`configuration_required`

- The provider did not find required local env values.
- For OCI, check `OCI_BASE_URL` and either `OCI_API_KEY` or `OCI_API_KEY_2`.

## Verification Commands

Focused tests:

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_model tests.test_cli tests.test_intent tests.test_runtime_controls
```

Full suite:

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest discover -s tests
```


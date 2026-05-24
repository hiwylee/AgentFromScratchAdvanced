"""Model adapters for the first agent loop."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable, Protocol
import urllib.error
import urllib.request

from .intent import UserIntent
from .redaction import redact
from .types import Action


class ActionModel(Protocol):
    name: str
    version: str

    def choose_action(self, intent: UserIntent, *, context: dict[str, Any] | None = None) -> Action:
        ...


class ModelInvocationError(RuntimeError):
    """Raised when a live model provider cannot return a validated action."""

    def __init__(
        self,
        code: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, object]:
        return redact({
            "code": self.code,
            "message": str(self),
            "metadata": self.metadata,
        })


class MockModel:
    """Deterministic model boundary used before API-backed models exist."""

    name = "mock-intent-planner"
    version = "1"

    def choose_action(self, intent: UserIntent, *, context: dict[str, Any] | None = None) -> Action:
        if intent.intent_type == "workflow_execution":
            return Action(
                kind="select_workflow",
                reason="The request requires a versioned workflow template and checkpointed execution.",
                payload={
                    "required_context": intent.required_context,
                    "ambiguities": intent.ambiguities,
                    "next_action": intent.next_action,
                },
            )
        if intent.safety_level == "blocked_write_request":
            return Action(
                kind="refuse",
                reason="The request appears to require write or destructive database access.",
                payload={"next_action": intent.next_action},
            )
        if intent.requires_oracle_adw_context and intent.ambiguities:
            return Action(
                kind="ask_clarification",
                reason="The request needs Oracle ADW schema or business glossary context.",
                payload={
                    "ambiguities": intent.ambiguities,
                    "required_context": intent.required_context,
                },
            )
        if intent.requires_oracle_adw_context:
            return Action(
                kind="inspect_schema",
                reason="The request can proceed by inspecting Oracle ADW schema context.",
                payload={"required_context": intent.required_context},
            )
        return Action(
            kind="final_answer",
            reason="The request does not require Oracle ADW context.",
            payload={"next_action": intent.next_action},
        )


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    api_key: str
    model: str = "gpt-5.2"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 30.0
    max_response_bytes: int = 131_072
    provider: str = "openai"
    api_key_env_name: str = "OPENAI_API_KEY"
    extra_headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        env: dict[str, str] | None = None,
    ) -> "OpenAIResponsesConfig":
        source = os.environ if env is None else env
        api_key = source.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when --model-provider openai is used.")

        configured_timeout = timeout_seconds
        if configured_timeout is None and source.get("OPENAI_TIMEOUT_SECONDS"):
            try:
                configured_timeout = float(source["OPENAI_TIMEOUT_SECONDS"])
            except ValueError as exc:
                raise ValueError("OPENAI_TIMEOUT_SECONDS must be a number.") from exc

        final_timeout = configured_timeout if configured_timeout is not None else 30.0
        if final_timeout <= 0 or final_timeout > 300:
            raise ValueError("OpenAI timeout must be greater than 0 and at most 300 seconds.")

        final_model = (model or source.get("OPENAI_MODEL") or cls.model).strip()
        if not final_model:
            raise ValueError("OpenAI model must not be empty.")

        final_base_url = (base_url or source.get("OPENAI_BASE_URL") or cls.base_url).strip()
        if not final_base_url.startswith(("https://", "http://")):
            raise ValueError("OPENAI_BASE_URL must start with http:// or https://.")

        return cls(
            api_key=api_key,
            model=final_model,
            base_url=final_base_url.rstrip("/"),
            timeout_seconds=final_timeout,
            provider="openai",
            api_key_env_name="OPENAI_API_KEY",
        )

    @classmethod
    def from_oci_env(
        cls,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        env: dict[str, str] | None = None,
    ) -> "OpenAIResponsesConfig":
        source = os.environ if env is None else env
        api_key = source.get("OCI_API_KEY", "").strip()
        api_key_env_name = "OCI_API_KEY"
        if not api_key:
            api_key = source.get("OCI_API_KEY_2", "").strip()
            api_key_env_name = "OCI_API_KEY_2"
        if not api_key:
            raise ValueError("OCI_API_KEY or OCI_API_KEY_2 is required when --model-provider oci is used.")

        configured_timeout = timeout_seconds
        if configured_timeout is None and source.get("OCI_TIMEOUT_SECONDS"):
            try:
                configured_timeout = float(source["OCI_TIMEOUT_SECONDS"])
            except ValueError as exc:
                raise ValueError("OCI_TIMEOUT_SECONDS must be a number.") from exc

        final_timeout = configured_timeout if configured_timeout is not None else 30.0
        if final_timeout <= 0 or final_timeout > 300:
            raise ValueError("OCI timeout must be greater than 0 and at most 300 seconds.")

        final_model = (
            model
            or source.get("OCI_MODEL")
            or source.get("LLM_MODEL")
            or "xai.grok-4-1-fast-non-reasoning"
        ).strip()
        if not final_model:
            raise ValueError("OCI model must not be empty.")

        final_base_url = (base_url or source.get("OCI_BASE_URL") or "").strip()
        if not final_base_url:
            raise ValueError("OCI_BASE_URL is required when --model-provider oci is used.")
        if not final_base_url.startswith(("https://", "http://")):
            raise ValueError("OCI_BASE_URL must start with http:// or https://.")

        extra_headers: list[tuple[str, str]] = []
        project_ocid = source.get("OCI_PROJECT_OCID", "").strip()
        conversation_store_id = source.get("OCI_CONVERSATION_STORE_ID", "").strip()
        if project_ocid:
            extra_headers.append(("OpenAI-Project", project_ocid))
        if conversation_store_id:
            extra_headers.append(("opc-conversation-store-id", conversation_store_id))

        return cls(
            api_key=api_key,
            model=final_model,
            base_url=final_base_url.rstrip("/"),
            timeout_seconds=final_timeout,
            provider="oci",
            api_key_env_name=api_key_env_name,
            extra_headers=tuple(extra_headers),
        )

    @property
    def responses_url(self) -> str:
        return f"{self.base_url}/responses"

    def redacted_status(self) -> dict[str, object]:
        return redact({
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "extra_header_names": [name for name, _value in self.extra_headers],
            self.api_key_env_name: self.api_key,
        })


OpenAITransport = Callable[[dict[str, object], OpenAIResponsesConfig], dict[str, object]]


class OpenAIResponsesModel:
    """OpenAI Responses API action planner with local safety validation."""

    name = "openai-responses-action-planner"
    version = "1"

    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        transport: OpenAITransport | None = None,
        baseline_model: MockModel | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or _default_openai_transport
        self.baseline_model = baseline_model or MockModel()

    def choose_action(self, intent: UserIntent, *, context: dict[str, Any] | None = None) -> Action:
        baseline = self.baseline_model.choose_action(intent, context=context)
        allowed_kinds = _allowed_action_kinds(intent, baseline)
        memory_summary = (context or {}).get("memory_summary") if context else None
        instructions = _OPENAI_ACTION_INSTRUCTIONS
        if isinstance(memory_summary, str) and memory_summary:
            instructions = instructions + f"\n\n## Active Memories\n{memory_summary}"
        payload = {
            "model": self.config.model,
            "instructions": instructions,
            "input": json.dumps(
                {
                    "intent": intent.to_dict(),
                    "allowed_action_kinds": allowed_kinds,
                    "baseline_action": baseline.to_dict(),
                    "output_contract": {
                        "kind": "one of allowed_action_kinds",
                        "reason": "short operator-readable reason",
                        "payload": "object with next_action and optional notes",
                    },
                },
                ensure_ascii=False,
            ),
            "store": False,
            "max_output_tokens": 500,
        }
        response = self.transport(payload, self.config)
        response_text = _extract_response_text(response)
        action_data = _parse_action_json(response_text)
        return _validated_llm_action(action_data, allowed_kinds, baseline, self.config.provider)


_OPENAI_ACTION_INSTRUCTIONS = """You are the action planner for a local agent runtime.
Return only one JSON object with keys: kind, reason, payload.
The kind must be one of allowed_action_kinds. Do not generate SQL.
Do not claim that live Oracle ADW, workflow writes, or target-system loads are enabled.
For write/destructive requests, choose refuse. For database analysis, choose a schema-context or clarification action.
Never include secrets, API keys, passwords, wallet values, or connection strings."""


def _allowed_action_kinds(intent: UserIntent, baseline: Action) -> list[str]:
    if intent.safety_level == "blocked_write_request":
        return ["refuse"]
    if intent.intent_type == "workflow_execution":
        return ["select_workflow"]
    if intent.requires_oracle_adw_context:
        if intent.ambiguities:
            return ["ask_clarification", "inspect_schema"]
        return ["inspect_schema", "ask_clarification"]
    return [baseline.kind]


def _validated_llm_action(
    action_data: dict[str, object],
    allowed_kinds: list[str],
    baseline: Action,
    provider: str,
) -> Action:
    proposed_kind = action_data.get("kind")
    if not isinstance(proposed_kind, str) or proposed_kind not in allowed_kinds:
        payload = dict(baseline.payload)
        payload["llm_action_validated"] = False
        payload["llm_validation_error"] = "kind_not_allowed"
        if isinstance(proposed_kind, str):
            payload["llm_rejected_kind"] = proposed_kind
        return Action(
            kind=baseline.kind,
            reason=f"{baseline.reason} LLM action was rejected by local policy validation.",
            payload=payload,
        )

    reason = action_data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = baseline.reason

    proposed_payload = action_data.get("payload")
    payload = dict(baseline.payload)
    if isinstance(proposed_payload, dict):
        payload.update(proposed_payload)
    payload["llm_action_validated"] = True
    payload["model_provider"] = provider

    return Action(kind=proposed_kind, reason=reason.strip(), payload=payload)


def _parse_action_json(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelInvocationError(
            "invalid_model_json",
            "OpenAI model response was not valid JSON.",
            {"parse_error": str(exc), "response_preview": cleaned[:500]},
        ) from exc
    if not isinstance(parsed, dict):
        raise ModelInvocationError(
            "invalid_model_json_shape",
            "OpenAI model response JSON must be an object.",
            {"response_type": type(parsed).__name__},
        )
    return parsed


def _extract_response_text(response: dict[str, object]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    texts: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for content_item in content:
                    if not isinstance(content_item, dict):
                        continue
                    text = content_item.get("text")
                    if isinstance(text, str):
                        texts.append(text)
            text = item.get("text")
            if isinstance(text, str):
                texts.append(text)

    if texts:
        return "\n".join(texts)

    raise ModelInvocationError(
        "missing_model_text",
        "OpenAI response did not contain text output.",
        {"response_keys": sorted(response.keys())},
    )


def _default_openai_transport(
    payload: dict[str, object],
    config: OpenAIResponsesConfig,
) -> dict[str, object]:
    try:
        return _post_openai_compatible_response(payload, config, config.responses_url)
    except ModelInvocationError as exc:
        fallback_url = _oci_api_key_fallback_responses_url(config)
        if (
            config.provider == "oci"
            and exc.code == "openai_http_error"
            and exc.metadata.get("status_code") == 404
            and fallback_url
        ):
            # Oracle documents /openai/v1/responses as the primary path, but
            # local API-key smoke currently succeeds through the versioned OCI
            # actions route after /openai/v1 returns an OCI 404.
            try:
                return _post_openai_compatible_response(payload, config, fallback_url)
            except ModelInvocationError as fallback_exc:
                fallback_exc.metadata["primary_status_code"] = exc.metadata.get("status_code")
                fallback_exc.metadata["primary_reason"] = exc.metadata.get("reason")
                fallback_exc.metadata["fallback_attempted"] = True
                fallback_exc.metadata["fallback_path"] = "/20231130/actions/v1/responses"
                raise fallback_exc
        raise


def _post_openai_compatible_response(
    payload: dict[str, object],
    config: OpenAIResponsesConfig,
    url: str,
) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            **dict(config.extra_headers),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            raw = response.read(config.max_response_bytes + 1)
    except urllib.error.HTTPError as exc:
        error_raw = exc.read(4096)
        raise ModelInvocationError(
            "openai_http_error",
            "OpenAI Responses API returned an HTTP error.",
            {
                "status_code": exc.code,
                "reason": exc.reason,
                "body": error_raw.decode("utf-8", errors="replace"),
            },
        ) from exc
    except urllib.error.URLError as exc:
        raise ModelInvocationError(
            "openai_connection_error",
            "OpenAI Responses API request failed before a response was returned.",
            {"reason": str(exc.reason)},
        ) from exc
    if len(raw) > config.max_response_bytes:
        raise ModelInvocationError(
            "openai_response_too_large",
            "OpenAI Responses API response exceeded the configured byte limit.",
            {"max_response_bytes": config.max_response_bytes},
        )
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelInvocationError(
            "openai_response_not_json",
            "OpenAI Responses API returned a non-JSON response.",
            {"parse_error": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise ModelInvocationError(
            "openai_response_shape_not_supported",
            "OpenAI Responses API response JSON must be an object.",
            {"response_type": type(parsed).__name__},
        )
    return parsed


def _oci_api_key_fallback_responses_url(config: OpenAIResponsesConfig) -> str | None:
    marker = "/openai/v1"
    if config.provider != "oci" or marker not in config.base_url:
        return None
    root = config.base_url.split(marker, 1)[0]
    return f"{root}/20231130/actions/v1/responses"

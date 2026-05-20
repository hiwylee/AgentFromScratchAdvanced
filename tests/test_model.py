import json
import unittest
import urllib.error
from unittest.mock import patch

from agent_runtime.intent import analyze_user_intent
from agent_runtime.model import (
    OpenAIResponsesConfig,
    OpenAIResponsesModel,
    _default_openai_transport,
)


class OpenAIResponsesModelTests(unittest.TestCase):
    def test_openai_model_accepts_valid_schema_action_without_leaking_key(self):
        calls = []
        config = OpenAIResponsesConfig(
            api_key="test-openai-secret",
            model="gpt-test",
            timeout_seconds=1,
        )

        def fake_transport(payload, config):
            calls.append(payload)
            return {
                "output_text": json.dumps({
                    "kind": "inspect_schema",
                    "reason": "Schema context should be inspected before planning SQL.",
                    "payload": {"notes": ["read-only planning only"]},
                })
            }

        model = OpenAIResponsesModel(config, transport=fake_transport)
        action = model.choose_action(
            analyze_user_intent("show Oracle ADW revenue by product by month trend")
        )

        self.assertEqual("inspect_schema", action.kind)
        self.assertTrue(action.payload["llm_action_validated"])
        self.assertEqual("openai", action.payload["model_provider"])
        self.assertIn("oracle_adw_schema", action.payload["required_context"])
        self.assertNotIn("test-openai-secret", json.dumps(calls, ensure_ascii=False))

    def test_openai_model_rejects_action_kind_that_weakens_write_safety(self):
        config = OpenAIResponsesConfig(api_key="test-openai-secret")

        def fake_transport(payload, config):
            return {
                "output_text": json.dumps({
                    "kind": "final_answer",
                    "reason": "Unsafe proposed action.",
                    "payload": {},
                })
            }

        model = OpenAIResponsesModel(config, transport=fake_transport)
        action = model.choose_action(analyze_user_intent("고객 테이블에서 오래된 데이터를 삭제해줘"))

        self.assertEqual("refuse", action.kind)
        self.assertFalse(action.payload["llm_action_validated"])
        self.assertEqual("kind_not_allowed", action.payload["llm_validation_error"])
        self.assertEqual("final_answer", action.payload["llm_rejected_kind"])

    def test_openai_model_reads_text_from_responses_output_items(self):
        config = OpenAIResponsesConfig(api_key="test-openai-secret")

        def fake_transport(payload, config):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({
                                    "kind": "final_answer",
                                    "reason": "No ADW context required.",
                                    "payload": {"next_action": "answer_directly"},
                                }),
                            }
                        ],
                    }
                ]
            }

        model = OpenAIResponsesModel(config, transport=fake_transport)
        action = model.choose_action(analyze_user_intent("hello"))

        self.assertEqual("final_answer", action.kind)
        self.assertTrue(action.payload["llm_action_validated"])

    def test_oci_config_uses_oci_endpoint_key_and_grok_model(self):
        config = OpenAIResponsesConfig.from_oci_env(
            env={
                "OCI_BASE_URL": "https://example.oci.oraclecloud.com/openai/v1",
                "OCI_API_KEY": "test-oci-secret",
                "OCI_PROJECT_OCID": "ocid1.generativeaiproject.oc1..example",
            }
        )

        self.assertEqual("oci", config.provider)
        self.assertEqual("xai.grok-4-1-fast-non-reasoning", config.model)
        self.assertEqual("https://example.oci.oraclecloud.com/openai/v1/responses", config.responses_url)
        self.assertEqual(
            (("OpenAI-Project", "ocid1.generativeaiproject.oc1..example"),),
            config.extra_headers,
        )
        self.assertEqual("[REDACTED]", config.redacted_status()["OCI_API_KEY"])
        self.assertEqual(["OpenAI-Project"], config.redacted_status()["extra_header_names"])

    def test_oci_model_marks_validated_action_with_oci_provider(self):
        config = OpenAIResponsesConfig.from_oci_env(
            env={
                "OCI_BASE_URL": "https://example.oci.oraclecloud.com/openai/v1",
                "OCI_API_KEY": "test-oci-secret",
                "OCI_MODEL": "xai.grok-4-1-fast-non-reasoning",
            }
        )

        def fake_transport(payload, config):
            return {
                "output_text": json.dumps({
                    "kind": "final_answer",
                    "reason": "No ADW context required.",
                    "payload": {"next_action": "answer_directly"},
                })
            }

        model = OpenAIResponsesModel(config, transport=fake_transport)
        action = model.choose_action(analyze_user_intent("hello"))

        self.assertEqual("final_answer", action.kind)
        self.assertEqual("oci", action.payload["model_provider"])

    def test_oci_transport_falls_back_to_api_key_actions_path_after_404(self):
        config = OpenAIResponsesConfig.from_oci_env(
            env={
                "OCI_BASE_URL": "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/openai/v1",
                "OCI_API_KEY": "test-oci-secret",
                "OCI_PROJECT_OCID": "ocid1.generativeaiproject.oc1.us-chicago-1.example",
            }
        )
        urls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, limit):
                return json.dumps({
                    "output_text": json.dumps({
                        "kind": "final_answer",
                        "reason": "fallback ok",
                        "payload": {},
                    })
                }).encode("utf-8")

        def fake_urlopen(request, timeout):
            urls.append(request.full_url)
            if len(urls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    404,
                    "Not Found",
                    hdrs={},
                    fp=None,
                )
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            response = _default_openai_transport({"model": config.model}, config)

        self.assertIn("/openai/v1/responses", urls[0])
        self.assertIn("/20231130/actions/v1/responses", urls[1])
        self.assertIn("output_text", response)


if __name__ == "__main__":
    unittest.main()

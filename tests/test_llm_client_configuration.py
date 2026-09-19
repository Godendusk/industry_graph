import os
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llm_client import LLMClient


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FailingCompletions:
    def create(self, **_kwargs):
        raise RuntimeError("provider unavailable")


class LLMClientQueryResultTest(unittest.TestCase):
    def _client_with_response(self, response):
        client = LLMClient.__new__(LLMClient)
        client.model = "test-model"
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=_FakeCompletions(response))
        )
        client._log_info = lambda *_args, **_kwargs: None
        return client

    def test_query_result_keeps_empty_content_and_response_metadata(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=None),
                finish_reason="length",
            )],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46),
        )
        result = self._client_with_response(response).query_result("测试请求")

        self.assertEqual(result.content, "")
        self.assertEqual(result.finish_reason, "length")
        self.assertEqual(result.prompt_tokens, 12)
        self.assertEqual(result.completion_tokens, 34)
        self.assertEqual(result.error_message, "")

    def test_query_result_is_immutable(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="正常正文"),
                finish_reason="stop",
            )],
            usage=None,
        )
        result = self._client_with_response(response).query_result("测试请求")

        with self.assertRaises(FrozenInstanceError):
            result.content = "不应修改"

    def test_default_extra_body_is_fresh_for_each_request(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="正常正文"),
                finish_reason="stop",
            )],
            usage=None,
        )
        client = self._client_with_response(response)

        client.query_result("第一次请求")
        first_extra_body = client.client.chat.completions.calls[0]["extra_body"]
        first_extra_body["thinking"]["type"] = "disabled"
        client.query_result("第二次请求")
        second_extra_body = client.client.chat.completions.calls[1]["extra_body"]

        self.assertIsNot(first_extra_body, second_extra_body)
        self.assertEqual(second_extra_body, {"thinking": {"type": "enabled"}})

    def test_doubao_model_forces_thinking_and_omits_reasoning_effort(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="正常正文"),
                finish_reason="stop",
            )],
            usage=None,
        )
        client = self._client_with_response(response)
        client.model = "doubao-seed-test"

        client.query_result("测试请求", extra_body={"thinking": {"type": "disabled"}})

        request = client.client.chat.completions.calls[0]
        self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertNotIn("reasoning_effort", request)

    def test_query_preserves_legacy_nonempty_string_contract(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="正常正文"),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        )
        result = self._client_with_response(response).query("测试请求")

        self.assertEqual(result, "正常正文")

    def test_query_returns_none_for_blank_content(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=""),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        )
        result = self._client_with_response(response).query("测试请求")

        self.assertIsNone(result)

    def test_query_result_exposes_request_error_message(self):
        client = LLMClient.__new__(LLMClient)
        client.model = "test-model"
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=_FailingCompletions())
        )
        client._log_info = lambda *_args, **_kwargs: None

        result = client.query_result("测试请求")

        self.assertEqual(result.content, "")
        self.assertIn("provider unavailable", result.error_message)

    def test_query_returns_none_for_failed_request(self):
        client = LLMClient.__new__(LLMClient)
        client.model = "test-model"
        client.client = SimpleNamespace(
            chat=SimpleNamespace(completions=_FailingCompletions())
        )
        client._log_info = lambda *_args, **_kwargs: None

        self.assertIsNone(client.query("测试请求"))


class LLMEnvironmentConfigurationTest(unittest.TestCase):
    def test_env_example_keeps_api_key_blank_and_contains_no_secret_literal(self):
        example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
        values = dict(
            line.split("=", 1)
            for line in example.splitlines()
            if line and not line.startswith("#")
        )

        self.assertEqual(values["LLM_API_KEY"], "")
        self.assertNotRegex(example, r"sk-[A-Za-z0-9]{8,}")
        self.assertNotRegex(example, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

    def test_client_reads_environment_and_verifies_tls_by_default(self):
        values = {
            "LLM_API_KEY": "test-key",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "test-model",
        }
        with patch.dict(os.environ, values, clear=True), \
             patch("llm_client.httpx.Client") as http_client, \
             patch("llm_client.OpenAI"):
            client = LLMClient()

        self.assertEqual(client.model, "test-model")
        self.assertEqual(client.base_url, "https://example.invalid/v1")
        self.assertTrue(http_client.call_args.kwargs["verify"])

    def test_proxy_configuration_does_not_log_proxy_url(self):
        proxy_url = "http://proxy.example.invalid:8080"
        values = {
            "LLM_API_KEY": "test-key",
            "LLM_PROXY_URL": proxy_url,
        }
        with patch.dict(os.environ, values, clear=True), \
             patch("llm_client.httpx.Client"), \
             patch("llm_client.OpenAI"), \
             patch("builtins.print") as printer, \
             patch.object(LLMClient, "_log_info") as log_info:
            LLMClient()

        emitted = "\n".join(
            str(call.args)
            for mock in (printer, log_info)
            for call in mock.call_args_list
        )
        self.assertIn("代理已配置", emitted)
        self.assertNotIn(proxy_url, emitted)

    def test_missing_key_returns_configuration_error_before_request(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("llm_client.DEFAULT_API_KEY", ""), \
             patch("llm_client.httpx.Client") as http_client, \
             patch("llm_client.OpenAI") as openai:
            result = LLMClient().query_result("需求")

        self.assertEqual(result.error_message, "LLM_API_KEY is not configured")
        http_client.assert_not_called()
        openai.assert_not_called()


if __name__ == "__main__":
    unittest.main()

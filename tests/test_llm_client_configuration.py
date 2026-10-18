import os
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llm_client import LLMClient
from report_generation.runtime_budget import RuntimeBudget


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


class _ConfigurableFakeSDK:
    def __init__(self, response, after_request=None):
        self.options = []
        self.completions = _FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)
        self.after_request = after_request

    def with_options(self, **options):
        self.options.append(options)
        outer = self

        class ConfiguredCompletions:
            def create(self, **kwargs):
                response = outer.completions.create(**kwargs)
                if outer.after_request:
                    outer.after_request()
                return response

        return SimpleNamespace(chat=SimpleNamespace(completions=ConfiguredCompletions()))


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

    def _client_with_configurable_sdk(self, after_request=None):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="正常正文"), finish_reason="stop")],
            usage=None,
        )
        client = self._client_with_response(response)
        client.client = _ConfigurableFakeSDK(response, after_request=after_request)
        return client

    def test_report_call_uses_remaining_stage_timeout_without_sdk_retries(self):
        now = [0.0]
        budget = RuntimeBudget(consumed_seconds=550, clock=lambda: now[0])
        client = self._client_with_configurable_sdk()
        shared_sdk = client.client

        with budget.activate("coordinator"):
            result = client.query_result("测试请求")

        self.assertEqual(result.content, "正常正文")
        self.assertIs(client.client, shared_sdk)
        self.assertEqual(shared_sdk.options, [{"timeout": 10.0, "max_retries": 0}])

    def test_explicit_timeout_is_capped_by_report_and_forwarded_by_query(self):
        budget = RuntimeBudget(consumed_seconds=790, clock=lambda: 0)
        client = self._client_with_configurable_sdk()
        with budget.activate("body"):
            self.assertEqual(client.query("测试请求", timeout=25), "正常正文")
        self.assertEqual(client.client.options, [{"timeout": 10.0, "max_retries": 0}])

    def test_explicit_timeout_outside_report_uses_isolated_sdk_configuration(self):
        client = self._client_with_configurable_sdk()
        result = client.query_result("测试请求", timeout=12)
        self.assertEqual(result.content, "正常正文")
        self.assertEqual(client.client.options, [{"timeout": 12.0, "max_retries": 0}])

    def test_default_call_outside_report_preserves_sdk_configuration(self):
        client = self._client_with_configurable_sdk()
        self.assertEqual(client.query_result("测试请求").content, "正常正文")
        self.assertEqual(client.client.options, [])

    def test_expired_report_returns_clear_error_without_starting_request(self):
        budget = RuntimeBudget(consumed_seconds=560, clock=lambda: 0)
        client = self._client_with_configurable_sdk()
        with budget.activate("coordinator"):
            result = client.query_result("测试请求")
        self.assertIn("runtime budget exhausted", result.error_message)
        self.assertEqual(client.client.completions.calls, [])
        self.assertEqual(client.client.options, [])

    def test_late_result_after_stage_deadline_is_not_accepted(self):
        now = [0.0]
        budget = RuntimeBudget(consumed_seconds=550, clock=lambda: now[0])
        client = self._client_with_configurable_sdk(after_request=lambda: now.__setitem__(0, 11))
        with budget.activate("coordinator"):
            result = client.query_result("测试请求")
        self.assertEqual(result.content, "")
        self.assertIn("runtime budget exhausted", result.error_message)


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

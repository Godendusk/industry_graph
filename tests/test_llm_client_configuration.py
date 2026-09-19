import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()

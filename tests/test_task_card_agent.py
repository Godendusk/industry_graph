import unittest
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation.task_card_agent import (
    REPORT_REQUIREMENT_FALLBACK_MESSAGE,
    _requirement_failure_reason,
    generate_report_requirement,
    generate_writing_task_card,
)


VALID_TASK_CARD_JSON = """{
  "suggested_titles": ["具身智能上市公司估值变化研判", "具身智能产业链企业投资表现研究"],
  "recognized_industry": "具身智能",
  "industry_candidates": [{"key": "embodied", "reason": "标题和需求明确关注具身智能"}]
}"""

VALID_REQUIREMENT = (
    "围绕具身智能产业，研究沪深两市相关上市公司近年的股价与市值变化，"
    "分析资本预期、经营表现、估值分化和龙头企业表现，比较不同企业在技术路线、产品落地和商业化进程中的差异，"
    "明确行业景气变化对投资价值的影响，不延伸至非上市公司融资及用户未要求的其他领域，"
    "并统一采用公开市场数据和可核验资料，说明样本范围、时间口径与数据限制，形成面向企业决策的产业洞察报告，服务管理层决策。"
)


def _result(content="", finish_reason="stop", error_message=""):
    return LLMQueryResult(
        content=content,
        finish_reason=finish_reason,
        error_message=error_message,
    )


class ReportRequirementTest(unittest.TestCase):
    def test_requirement_failure_reason_classification(self):
        overlong = "具身智能产业研究" * 50 + "。"
        cases = [
            (_result("可见正文", error_message="provider unavailable"), "可见正文", "llm_request_failed"),
            (_result(""), "", "empty_visible_content"),
            (_result("", "length"), "", "truncated"),
            (_result("正文", "length"), "正文", "truncated"),
            (_result(overlong), overlong, "truncated"),
            (_result("不完整正文"), "不完整正文", "incomplete"),
            (_result("完整内容但英文句号."), "完整内容但英文句号.", "incomplete"),
            (_result(VALID_REQUIREMENT), VALID_REQUIREMENT, ""),
        ]
        for result, text, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(_requirement_failure_reason(result, text), expected)

    def test_retries_empty_visible_requirement_once(self):
        with patch(
            "report_generation.task_card_agent.llm.query_result",
            side_effect=[_result(""), _result(VALID_REQUIREMENT)],
        ) as query:
            result = generate_report_requirement(
                "具身智能投资状况", "关注沪深上市公司", "embodied", "具身智能"
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "model_retry")
        self.assertEqual(result["report_requirement"], VALID_REQUIREMENT)
        self.assertEqual(query.call_count, 2)
        self.assertTrue(all(call.kwargs["max_tokens"] == 900 for call in query.call_args_list))
        self.assertTrue(all(call.kwargs["reasoning_effort"] is None for call in query.call_args_list))
        self.assertTrue(all(
            call.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
            for call in query.call_args_list
        ))

    def test_retries_length_limited_incomplete_requirement_once(self):
        with patch(
            "report_generation.task_card_agent.llm.query_result",
            side_effect=[
                _result("围绕具身智能产业分析沪深上市公司的估值与关键", "length"),
                _result(VALID_REQUIREMENT),
            ],
        ) as query:
            result = generate_report_requirement(
                "具身智能投资状况", "关注沪深上市公司", "embodied", "具身智能"
            )

        self.assertEqual(result["source"], "model_retry")
        self.assertEqual(result["report_requirement"][-1], "。")
        self.assertEqual(query.call_count, 2)

    def test_does_not_accept_overlong_or_unfinished_model_content(self):
        overlong = "围绕具身智能产业开展研究，" + "分析资本市场表现、企业经营情况和产业链竞争格局，" * 30
        unfinished = "围绕具身智能产业研究沪深上市公司的资本市场表现与龙头企业变化"
        for invalid_content in (overlong, unfinished):
            with self.subTest(invalid_content=invalid_content[:20]), patch(
                "report_generation.task_card_agent.llm.query_result",
                side_effect=[_result(invalid_content), _result(VALID_REQUIREMENT)],
            ) as query:
                result = generate_report_requirement(
                    "具身智能投资状况", "关注沪深上市公司", "embodied", "具身智能"
                )

            self.assertEqual(result["source"], "model_retry")
            self.assertEqual(query.call_count, 2)

    def test_falls_back_after_two_invalid_requirement_responses(self):
        with patch(
            "report_generation.task_card_agent.llm.query_result",
            side_effect=[_result(""), _result("未完成需求")],
        ):
            result = generate_report_requirement(
                "具身智能投资状况", "关注沪深上市公司", "embodied", "具身智能"
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "fallback")
        self.assertIn("关注沪深上市公司", result["report_requirement"])
        self.assertEqual(result["warnings"][0]["code"], "report_requirement_fallback")
        self.assertEqual(result["warnings"][0]["reason"], "incomplete")
        self.assertEqual(result["warnings"][0]["message"], REPORT_REQUIREMENT_FALLBACK_MESSAGE)

    def test_unsupported_industry_remains_local_error(self):
        with patch("report_generation.task_card_agent.llm.query_result") as query:
            result = generate_report_requirement("报告标题", "需求", "not-supported")

        self.assertEqual(result["status"], "error")
        self.assertIn("unsupported industry", result["message"])
        self.assertEqual(query.call_count, 0)


class TaskCardTest(unittest.TestCase):
    def test_keeps_valid_card_after_two_requirement_failures(self):
        with patch(
            "report_generation.task_card_agent.llm.query_result",
            side_effect=[_result(VALID_TASK_CARD_JSON), _result(""), _result("")],
        ) as query:
            result = generate_writing_task_card(
                "具身智能投资状况", "关注沪深上市公司", "embodied"
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_card"]["selected_industry"], "embodied")
        self.assertIn("关注沪深上市公司", result["task_card"]["report_requirement"])
        self.assertEqual(result["task_card"]["report_requirement_source"], "fallback")
        self.assertEqual(result["warnings"][0]["code"], "report_requirement_fallback")
        self.assertEqual(query.call_count, 3)

    def test_retries_malformed_json_before_generating_requirement(self):
        with patch(
            "report_generation.task_card_agent.llm.query_result",
            side_effect=[
                _result("not json"),
                _result(VALID_TASK_CARD_JSON),
                _result(VALID_REQUIREMENT),
            ],
        ) as query:
            result = generate_writing_task_card(
                "具身智能投资状况", "关注沪深上市公司", "embodied"
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_card"]["report_requirement_source"], "model")
        self.assertEqual(query.call_count, 3)

    def test_rejects_empty_title_without_calling_model(self):
        with patch("report_generation.task_card_agent.llm.query_result") as query:
            result = generate_writing_task_card("", "关注沪深上市公司", "embodied")

        self.assertEqual(result["status"], "error")
        self.assertEqual(query.call_count, 0)

    def test_accepts_page_industry_display_name_alias(self):
        with patch(
            "report_generation.task_card_agent.llm.query_result",
            side_effect=[_result(VALID_TASK_CARD_JSON), _result(VALID_REQUIREMENT)],
        ) as query:
            result = generate_writing_task_card(
                "具身智能投资状况", "关注沪深上市公司", "具身智能"
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["task_card"]["page_industry"], "embodied")
        self.assertEqual(query.call_count, 2)


if __name__ == "__main__":
    unittest.main()

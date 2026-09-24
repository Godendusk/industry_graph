import unittest
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation import body_agent


def _writing_task():
    return {
        "outline_id": "S3.1",
        "parent_level1_id": "S3",
        "parent_level1_title": "龙头企业股价走势、市值规模与估值水平",
        "title": "龙头企业的界定标准与名单确定",
        "writing_system_prompt": "只写当前小节正文。",
        "graph_retrieval": {"status": "error", "graph_context_text": ""},
        "external_rag_retrieval": {"status": "success", "rag_context_text": "上市公司筛选材料"},
    }


class BodyAgentTest(unittest.TestCase):
    def test_retries_empty_or_length_limited_body_and_keeps_valid_section(self):
        retry_text = "龙头企业应以沪深上市身份、具身智能业务实质和产品落地进度为筛选标准，并据此形成可复核的公司名单。"
        with patch.object(
            body_agent.llm,
            "query_result",
            side_effect=[
                LLMQueryResult(content="", finish_reason="length", completion_tokens=5000),
                LLMQueryResult(content=retry_text, finish_reason="stop", completion_tokens=320),
            ],
        ) as query:
            result = body_agent.generate_body_section(
                writing_task=_writing_task(),
                user_prompt="分析具身智能龙头企业",
                report_title="具身智能上市公司研究",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["body_text"], retry_text)
        self.assertEqual(query.call_count, 2)
        self.assertEqual(query.call_args_list[1].kwargs["max_tokens"], body_agent.RETRY_MAX_TOKENS)
        self.assertEqual(
            query.call_args_list[1].kwargs["extra_body"],
            {"thinking": {"type": "disabled"}},
        )

    def test_empty_body_does_not_become_success(self):
        with patch.object(
            body_agent.llm,
            "query_result",
            return_value=LLMQueryResult(content="", finish_reason="length"),
        ):
            result = body_agent.generate_body_section(
                writing_task=_writing_task(),
                user_prompt="分析具身智能龙头企业",
                report_title="具身智能上市公司研究",
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["body_text"], "")
        self.assertIn("重试", result["message"])

    def test_stream_report_bodies_emits_section_progress_and_completion(self):
        with patch.object(
            body_agent.llm,
            "query_result",
            return_value=LLMQueryResult(content="流式生成正文。", finish_reason="stop"),
        ):
            events = list(body_agent.stream_report_bodies(
                user_prompt="分析具身智能龙头企业",
                report_title="具身智能上市公司研究",
                writing_tasks=[_writing_task()],
                industry="embodied",
                max_workers=1,
                references=[],
            ))

        self.assertEqual(events[0]["event"], "started")
        self.assertIn("section_started", [event["event"] for event in events])
        self.assertIn("section_completed", [event["event"] for event in events])
        self.assertEqual(events[-1]["event"], "completed")
        self.assertEqual(events[-1]["status"], "success")
        self.assertEqual(events[-1]["body_sections"][0]["body_text"], "流式生成正文。")


if __name__ == "__main__":
    unittest.main()

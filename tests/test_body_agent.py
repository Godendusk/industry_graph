import threading
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


def _task(outline_id):
    return {
        "outline_id": outline_id,
        "parent_level1_id": outline_id.split(".")[0],
        "parent_level1_title": f"一级标题 {outline_id.split('.')[0]}",
        "title": f"小节 {outline_id}",
        "writing_system_prompt": "只写当前小节正文。",
        "graph_retrieval": {"status": "error", "graph_context_text": ""},
        "external_rag_retrieval": {"status": "success", "rag_context_text": "", "evidence_blocks": []},
    }


def _section_for(task):
    return {
        "outline_id": task["outline_id"],
        "parent_level1_id": task["parent_level1_id"],
        "parent_level1_title": task["parent_level1_title"],
        "title": task["title"],
        "status": "success",
        "body_text": f"{task['title']}正文。",
        "warnings": [],
        "citation_ids": [],
        "graph_evidence_blocks": [],
        "external_evidence_blocks": [],
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

    def test_generates_level1_groups_in_parallel_but_keeps_group_order_and_output_order(self):
        tasks = [_task("S1.1"), _task("S1.2"), _task("S2.1")]
        second_group_started = threading.Event()
        call_order = []
        call_lock = threading.Lock()

        def generate_section(*, writing_task, **_kwargs):
            outline_id = writing_task["outline_id"]
            with call_lock:
                call_order.append(outline_id)
            if outline_id == "S2.1":
                second_group_started.set()
            if outline_id == "S1.1":
                if not second_group_started.wait(timeout=1):
                    self.fail("S1.1 did not observe S2.1 starting concurrently")
            return _section_for(writing_task)

        with patch.object(body_agent, "generate_body_section", side_effect=generate_section):
            result = body_agent.generate_report_bodies(
                user_prompt="生成报告",
                report_title="测试报告",
                writing_tasks=tasks,
                max_workers=2,
                references=[],
            )

        self.assertEqual(result["max_workers"], 2)
        self.assertLess(call_order.index("S1.1"), call_order.index("S1.2"))
        self.assertEqual([section["outline_id"] for section in result["body_sections"]], ["S1.1", "S1.2", "S2.1"])

    def test_stream_report_bodies_reports_actual_group_workers(self):
        tasks = [_task("S1.1"), _task("S2.1")]
        with patch.object(body_agent, "generate_body_section", side_effect=lambda writing_task, **_kwargs: _section_for(writing_task)):
            events = list(body_agent.stream_report_bodies(
                user_prompt="生成报告",
                report_title="测试报告",
                writing_tasks=tasks,
                max_workers=6,
                references=[],
            ))

        self.assertEqual(events[0]["event"], "started")
        self.assertEqual(events[0]["group_count"], 2)
        self.assertEqual(events[0]["max_workers"], 2)
        self.assertEqual(events[-1]["event"], "completed")
        self.assertEqual(events[-1]["group_count"], 2)
        self.assertEqual(events[-1]["max_workers"], 2)
        self.assertEqual([section["outline_id"] for section in events[-1]["body_sections"]], ["S1.1", "S2.1"])


if __name__ == "__main__":
    unittest.main()

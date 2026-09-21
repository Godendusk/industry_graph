import unittest
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation import body_agent


def _task(outline_id, evidence_blocks):
    return {
        "outline_id": outline_id,
        "parent_level1_id": "S1",
        "parent_level1_title": "现状",
        "title": f"小节 {outline_id}",
        "writing_system_prompt": "只写当前小节正文。",
        "graph_retrieval": {"status": "error", "graph_context_text": ""},
        "external_rag_retrieval": {
            "status": "success",
            "rag_context_text": "[C1]\n政策材料",
            "evidence_blocks": evidence_blocks,
        },
    }


class ReportBodyCitationsTest(unittest.TestCase):
    def test_removes_unknown_marker_and_records_used_ids(self):
        evidence = [{"citation_id": "C1", "title": "政策甲"}]
        with patch.object(
            body_agent.llm,
            "query_result",
            return_value=LLMQueryResult(
                content="政策提出扩大应用范围[C1]，市场规模达到百亿元[C8]。",
                finish_reason="stop",
            ),
        ):
            result = body_agent.generate_body_section(
                writing_task=_task("S1.1", evidence),
                user_prompt="生成报告",
                report_title="测试报告",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["body_text"], "政策提出扩大应用范围[C1]，市场规模达到百亿元。")
        self.assertEqual(result["citation_ids"], ["C1"])
        self.assertEqual(result["warnings"][-1]["invalid_citation_ids"], ["C8"])

    def test_returns_only_references_used_by_successful_sections(self):
        tasks = [
            _task("S1.1", [{"citation_id": "C2", "title": "案例乙"}]),
            _task("S1.2", [{"citation_id": "C1", "title": "政策甲"}]),
        ]
        responses = [
            LLMQueryResult(content="案例说明[C2]。", finish_reason="stop"),
            LLMQueryResult(content="政策说明[C1]。", finish_reason="stop"),
        ]
        references = [
            {"citation_id": "C1", "title": "政策甲"},
            {"citation_id": "C2", "title": "案例乙"},
            {"citation_id": "C3", "title": "未使用"},
        ]
        with patch.object(body_agent.llm, "query_result", side_effect=responses):
            result = body_agent.generate_report_bodies(
                user_prompt="生成报告",
                report_title="测试报告",
                writing_tasks=tasks,
                industry="embodied",
                max_workers=1,
                references=references,
            )

        self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C2"])


if __name__ == "__main__":
    unittest.main()

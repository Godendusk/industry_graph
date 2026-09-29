import unittest
from unittest.mock import patch

from report_generation import rewrite_agent


class ReportRewriteCitationsTest(unittest.TestCase):
    def test_reuses_existing_id_and_appends_new_material(self):
        body_section = {
            "outline_id": "S1.1",
            "parent_level1_id": "S1",
            "parent_level1_title": "现状",
            "title": "政策",
            "body_text": "旧正文。",
        }
        references = [
            {"citation_id": "C1", "library": "policy", "material_id": "m1", "vector_ids": ["v1"]},
            {"citation_id": "C4", "library": "company_case", "material_id": "m4", "vector_ids": ["v4"]},
        ]
        selected = [
            {"library": "policy", "material_id": "m1", "vector_id": "v2", "title": "政策甲", "text": "旧材料"},
            {"library": "company_case", "material_id": "m5", "vector_id": "v5", "title": "案例新", "text": "新材料"},
        ]
        with patch.object(
            rewrite_agent.llm,
            "query",
            return_value="新材料说明[C5]，并结合政策[C1]。",
        ):
            result = rewrite_agent.rewrite_body_section(
                rewrite_prompt="补充最新材料",
                report_title="测试报告",
                body_section=body_section,
                graph_retrieval={"graph_context_text": ""},
                selected_external_evidence_blocks=selected,
                references=references,
                industry="embodied",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["citation_ids"], ["C5", "C1"])
        self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C4", "C5"])
        self.assertEqual(
            [row["citation_id"] for row in result["selected_external_evidence_blocks"]],
            ["C1", "C5"],
        )

    def test_prior_facts_are_avoidance_context_and_exclude_current_section(self):
        body_section = {
            "outline_id": "S1.1",
            "parent_level1_id": "S1",
            "parent_level1_title": "现状",
            "title": "政策",
            "body_text": "旧正文。",
        }
        previous = [
            {
                "outline_id": "S1.1",
                "status": "success",
                "title": "政策",
                "body_text": "当前小节旧内容，不应再次放入提示词。",
            },
            {
                "outline_id": "S1.2",
                "status": "success",
                "title": "产业链",
                "body_text": "产业链首句。采用已选资料[C1]的事实。",
            },
        ]
        selected = [
            {"library": "policy", "material_id": "m2", "vector_id": "v2", "title": "政策乙", "text": "材料"},
        ]
        with patch.object(rewrite_agent.llm, "query", return_value="重写正文[C1]。") as query:
            result = rewrite_agent.rewrite_body_section(
                rewrite_prompt="补充最新材料",
                report_title="测试报告",
                body_section=body_section,
                graph_retrieval={"graph_context_text": ""},
                selected_external_evidence_blocks=selected,
                references=[],
                previous_body_sections=previous,
            )

        self.assertEqual(result["status"], "success")
        prompt = query.call_args.kwargs["user_prompt"]
        self.assertIn("产业链首句。", prompt)
        self.assertIn("采用已选资料[C1]的事实。", prompt)
        self.assertNotIn("当前小节旧内容", prompt)
        self.assertIn("仅用于避重，不是引用证据", prompt)
        self.assertIn("只能使用用户选择的外部资料上下文中真实出现的 [C数字]", prompt)
        system_prompt = query.call_args.kwargs["system_prompt"]
        self.assertIn("不是事实证据、引用来源或可直接复述的依据", system_prompt)
        self.assertIn("如果用户明确要求重复某个背景、事实、案例或数据，应按用户要求重复", system_prompt)

    def test_previous_sections_must_be_an_array(self):
        result = rewrite_agent.rewrite_body_section(
            rewrite_prompt="补充",
            report_title="测试报告",
            body_section={"title": "政策", "body_text": "旧正文。"},
            graph_retrieval={},
            selected_external_evidence_blocks=[],
            previous_body_sections="invalid",
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("previous_body_sections", result["message"])

    def test_prior_facts_exclude_current_section_when_outline_id_is_missing(self):
        body_section = {
            "parent_level1_title": "现状",
            "title": "政策",
            "body_text": "没有 ID 的当前正文，不应再次放入提示词。",
        }
        previous = [
            {
                "title": "政策",
                "body_text": "没有 ID 的当前正文，不应再次放入提示词。",
                "status": "success",
            },
            {
                "title": "产业链",
                "body_text": "其他小节首句，应保留在避重上下文。",
                "status": "success",
            },
        ]
        selected = [
            {"library": "policy", "material_id": "m2", "vector_id": "v2", "title": "政策乙", "text": "材料"},
        ]
        with patch.object(rewrite_agent.llm, "query", return_value="重写正文[C1]。") as query:
            result = rewrite_agent.rewrite_body_section(
                rewrite_prompt="补充最新材料",
                report_title="测试报告",
                body_section=body_section,
                graph_retrieval={"graph_context_text": ""},
                selected_external_evidence_blocks=selected,
                references=[],
                previous_body_sections=previous,
            )

        self.assertEqual(result["status"], "success")
        prompt = query.call_args.kwargs["user_prompt"]
        self.assertIn("其他小节首句", prompt)
        self.assertEqual(prompt.count("没有 ID 的当前正文"), 1)


if __name__ == "__main__":
    unittest.main()

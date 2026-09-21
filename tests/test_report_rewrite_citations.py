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


if __name__ == "__main__":
    unittest.main()

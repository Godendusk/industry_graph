import unittest
from unittest.mock import patch

from report_generation import coordinator_agent


class ReportCoordinatorCitationsTest(unittest.TestCase):
    def test_registers_sources_in_outline_order_and_rebuilds_context(self):
        outline = [{
            "section_type": "body",
            "level1_id": "S1",
            "level1_title": "现状",
            "subsections": [
                {"outline_id": "S1.1", "title": "政策"},
                {"outline_id": "S1.2", "title": "案例"},
            ],
        }]

        def task_for_subsection(*, subsection, **_kwargs):
            blocks = [{
                "library": "policy" if subsection["outline_id"] == "S1.1" else "company_case",
                "material_id": "m1" if subsection["outline_id"] == "S1.1" else "m2",
                "vector_id": f"v-{subsection['outline_id']}",
                "title": "政策甲" if subsection["outline_id"] == "S1.1" else "案例乙",
                "text": "证据片段",
            }]
            if subsection["outline_id"] == "S1.2":
                blocks.insert(0, {
                    "library": "policy",
                    "material_id": "m1",
                    "vector_id": "v-S1.2-policy",
                    "title": "政策甲",
                    "text": "第二个片段",
                })
            return ({
                "outline_id": subsection["outline_id"],
                "parent_level1_id": subsection["parent_level1_id"],
                "parent_level1_title": subsection["parent_level1_title"],
                "title": subsection["title"],
                "external_rag_retrieval": {
                    "status": "success",
                    "evidence_blocks": blocks,
                    "rag_context_text": "旧上下文",
                },
                "writing_system_prompt": "prompt",
                "warnings": [],
            }, [])

        with patch.object(coordinator_agent, "_generate_writing_task_for_subsection", side_effect=task_for_subsection):
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告",
                report_title="测试报告",
                outline=outline,
                industry="embodied",
            )

        tasks = result["writing_tasks"]
        self.assertEqual(tasks[0]["external_rag_retrieval"]["evidence_blocks"][0]["citation_id"], "C1")
        self.assertEqual(
            [row["citation_id"] for row in tasks[1]["external_rag_retrieval"]["evidence_blocks"]],
            ["C1", "C2"],
        )
        self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C2"])
        self.assertIn("[C1]", tasks[0]["external_rag_retrieval"]["rag_context_text"])
        self.assertIn("[C2]", tasks[1]["external_rag_retrieval"]["rag_context_text"])


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from report_generation import graph_retriever


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mixed_depth_graph.json"


class DynamicGraphRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.graph = graph_retriever._AIGraph(FIXTURE_PATH)

    def test_candidate_rows_include_terminal_levels_three_to_five(self):
        self.assertEqual(set(self.graph.terminal_segments), {20, 30, 40})
        rows = self.graph.terminal_prompt_rows()
        self.assertIn("一级甲 > 二级甲 > 三级叶子", rows[0])
        self.assertTrue(any("三级分支 > 四级叶子" in row for row in rows))
        self.assertTrue(any("三级深分支 > 四级分支 > 五级叶子" in row for row in rows))

    def test_terminal_evidence_keeps_complete_path_and_direct_company(self):
        self.assertEqual(
            [item["id"] for item in self.graph.get_downward_entities(30)],
            [101],
        )
        self.assertEqual(
            [item["name"] for item in self.graph.get_segment_path(40)],
            ["一级甲", "二级甲", "三级深分支", "四级分支", "五级叶子"],
        )

    def test_retrieval_response_uses_terminal_segment_contract(self):
        llm_response = json.dumps([
            {"id": 30, "name": "四级叶子", "reason": "命中", "score": 0.9},
        ], ensure_ascii=False)
        with patch.object(graph_retriever, "AI_GRAPH_PATH", FIXTURE_PATH), patch.object(
            graph_retriever.llm, "query", return_value=llm_response
        ):
            result = graph_retriever.retrieve_ai_graph("四级叶子")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["matched_segments"][0]["id"], 30)
        self.assertNotIn("matched_level3", result)
        block = result["evidence_blocks"][0]
        self.assertEqual(block["segment"]["level"], 4)
        self.assertEqual(block["segment_path"][-1]["id"], 30)
        self.assertEqual(block["downward_entities"][0]["id"], 101)
        self.assertIn("一级甲 > 二级甲 > 三级分支 > 四级叶子", block["chain_path"])


if __name__ == "__main__":
    unittest.main()

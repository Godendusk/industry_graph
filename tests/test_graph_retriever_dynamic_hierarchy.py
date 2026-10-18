import json
import unittest
from pathlib import Path
from unittest.mock import patch

from report_generation import graph_retriever


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mixed_depth_graph.json"


class DynamicGraphRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.graph = graph_retriever._IndustryGraph(FIXTURE_PATH)

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

    def test_graph_evidence_refs_are_exposed_when_sidecar_contains_them(self):
        fake_index = type(
            "EvidenceIndex",
            (),
            {
                "for_node": lambda self, node_id, properties=None: (
                    {"material_id": "m1", "chunk_id": f"node-{node_id}"},
                )
                if node_id == 101
                else (),
                "for_relationship": lambda self, rel: (
                    {"material_id": "m2", "chunk_id": "edge-101-30"},
                )
                if rel.get("source") == 101 and rel.get("target") == 30
                else (),
            },
        )()
        with patch.object(graph_retriever.GraphEvidenceIndex, "from_path", return_value=fake_index):
            graph = graph_retriever._IndustryGraph(FIXTURE_PATH)

        entities = graph.get_downward_entities(30)

        self.assertEqual(
            {ref["chunk_id"] for ref in entities[0]["evidence_refs"]},
            {"node-101", "edge-101-30"},
        )

    def test_retrieval_response_uses_terminal_segment_contract(self):
        llm_response = json.dumps([
            {"id": 30, "name": "四级叶子", "reason": "命中", "score": 0.9},
        ], ensure_ascii=False)
        with patch.object(graph_retriever, "get_industry_config", return_value={"name": "人工智能", "graph_path": FIXTURE_PATH}), patch.object(
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

    def test_non_ai_retrieval_keeps_industry_and_terminal_paths(self):
        llm_response = json.dumps([
            {"id": 40, "name": "五级叶子", "reason": "命中", "score": 0.9},
        ], ensure_ascii=False)
        with patch.object(graph_retriever, "get_industry_config", return_value={
            "name": "具身智能", "graph_path": FIXTURE_PATH,
        }), patch.object(graph_retriever.llm, "query", return_value=llm_response) as query:
            result = graph_retriever.retrieve_industry_graph("五级叶子", industry="embodied")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["industry"], "embodied")
        self.assertEqual(result["industry_name"], "具身智能")
        self.assertEqual(result["evidence_blocks"][0]["segment"]["level"], 5)
        self.assertEqual(result["evidence_blocks"][0]["downward_entities"][0]["id"], 102)
        self.assertIn("具身智能", query.call_args.kwargs["system_prompt"])

    def test_selection_uses_compact_non_thinking_contract(self):
        llm_response = json.dumps([20])
        with patch.object(graph_retriever, "get_industry_config", return_value={"name": "人工智能", "graph_path": FIXTURE_PATH}), patch.object(
            graph_retriever.llm, "query", return_value=llm_response
        ) as query:
            result = graph_retriever.retrieve_ai_graph("三级叶子")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["matched_segments"][0]["id"], 20)
        self.assertEqual(query.call_args.kwargs["max_tokens"], 800)
        self.assertIsNone(query.call_args.kwargs["reasoning_effort"])
        self.assertEqual(query.call_args.kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertIn("只返回选中末级环节的数字 ID", query.call_args.kwargs["system_prompt"])


if __name__ == "__main__":
    unittest.main()

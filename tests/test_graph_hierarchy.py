import json
import unittest
from pathlib import Path

from graph_hierarchy import GraphHierarchy


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mixed_depth_graph.json"


class GraphHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.graph = GraphHierarchy.from_path(FIXTURE_PATH)

    def test_terminal_segments_are_derived_from_children(self):
        self.assertEqual(self.graph.terminal_segment_ids(), [20, 30, 40])

    def test_incomplete_level_one_branch_is_not_a_terminal_segment(self):
        self.assertEqual(self.graph.terminal_segment_ids(0), [20, 30, 40])

    def test_path_supports_mixed_depths(self):
        self.assertEqual(self.graph.segment_path_ids(20), [1, 10, 20])
        self.assertEqual(self.graph.segment_path_ids(30), [1, 10, 21, 30])
        self.assertEqual(self.graph.segment_path_ids(40), [1, 10, 22, 31, 40])

    def test_descendants_include_every_supported_depth(self):
        self.assertEqual(
            self.graph.descendant_segment_ids(10),
            [20, 21, 22, 30, 31, 40],
        )

    def test_company_ids_are_deduplicated_and_sorted(self):
        self.assertEqual(
            self.graph.company_ids_for_segments([20, 30, 40]),
            [100, 101, 102],
        )

    def test_relationship_extra_properties_are_ignored(self):
        self.assertEqual(self.graph.node_summary(30)["name"], "四级叶子")

    def test_from_data_does_not_mutate_input(self):
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        original = json.dumps(data, ensure_ascii=False, sort_keys=True)
        GraphHierarchy.from_data(data)
        self.assertEqual(json.dumps(data, ensure_ascii=False, sort_keys=True), original)


if __name__ == "__main__":
    unittest.main()

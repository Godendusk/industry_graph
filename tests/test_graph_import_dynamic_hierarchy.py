import json
import unittest
from pathlib import Path

from graph_import_script import build_terminal_segment_paths


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mixed_depth_graph.json"


class GraphImportDynamicHierarchyTests(unittest.TestCase):
    def test_dictionary_contains_only_unambiguous_terminal_paths(self):
        graph = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        records = build_terminal_segment_paths(graph)
        self.assertEqual(
            records,
            [
                {
                    "id": 20,
                    "level": 3,
                    "path": "一级甲 > 二级甲 > 三级叶子",
                    "path_ids": [1, 10, 20],
                },
                {
                    "id": 30,
                    "level": 4,
                    "path": "一级甲 > 二级甲 > 三级分支 > 四级叶子",
                    "path_ids": [1, 10, 21, 30],
                },
                {
                    "id": 40,
                    "level": 5,
                    "path": "一级甲 > 二级甲 > 三级深分支 > 四级分支 > 五级叶子",
                    "path_ids": [1, 10, 22, 31, 40],
                },
            ],
        )
        self.assertNotIn(21, [record["id"] for record in records])
        self.assertNotIn(22, [record["id"] for record in records])
        self.assertNotIn(31, [record["id"] for record in records])


if __name__ == "__main__":
    unittest.main()

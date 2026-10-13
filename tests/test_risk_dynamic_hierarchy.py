import unittest
from pathlib import Path

from risk_inference.risk import SpecializedChainRiskEngine


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mixed_depth_graph.json"


class RiskDynamicHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.engine = SpecializedChainRiskEngine(str(FIXTURE_PATH))

    def test_l2_analysis_counts_all_terminal_segments(self):
        result = self.engine.analyze_internal_composition(10)
        self.assertEqual(result["terminal_segment_count"], 3)
        self.assertEqual(
            set(result["terminal_segment_details"]),
            {"三级叶子", "四级叶子", "五级叶子"},
        )

    def test_l2_analysis_counts_companies_below_level_four_and_five(self):
        result = self.engine.analyze_internal_composition(10)
        self.assertEqual(result["company_count"], 3)
        self.assertEqual(
            set(result["company_examples"]),
            {"甲公司", "乙公司", "丙公司"},
        )


if __name__ == "__main__":
    unittest.main()

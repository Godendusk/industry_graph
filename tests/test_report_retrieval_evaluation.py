import unittest
from scripts.evaluate_report_retrieval import evaluate_ranked_materials
from scripts.build_report_retrieval_label_set import allocate_library_samples

class ReportRetrievalEvaluationTest(unittest.TestCase):
    def test_recall_mrr_and_ndcg(self):
        metrics = evaluate_ranked_materials(["m2", "m1", "m3"], {"m1", "m4"}, 3)
        self.assertEqual(metrics["recall_at_k"], 0.5)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertGreater(metrics["ndcg_at_k"], 0.0)
    def test_sixty_examples_are_balanced_across_five_libraries(self):
        values = allocate_library_samples(["policy", "speech", "expert_view", "company_case", "research_report"], 60)
        self.assertEqual(sum(values.values()), 60)
        self.assertTrue(all(value == 12 for value in values.values()))

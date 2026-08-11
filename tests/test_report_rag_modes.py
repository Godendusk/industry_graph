import unittest
from unittest.mock import patch

from report_generation.external_rag.retriever import retrieve_external_rag


class ReportRagModesTest(unittest.TestCase):
    def test_legacy_returns_existing_result(self):
        with patch("report_generation.external_rag.retriever._mode", return_value="legacy"), patch(
            "report_generation.external_rag.retriever._retrieve_legacy",
            return_value={"status": "success", "evidence_blocks": [{"citation_id": "外部资料1"}]},
        ) as legacy:
            result = retrieve_external_rag("查询", top_k=10)
        self.assertEqual(result["status"], "success")
        legacy.assert_called_once()

    def test_compare_returns_legacy_and_logs_v2_difference(self):
        with patch("report_generation.external_rag.retriever._mode", return_value="compare"), patch(
            "report_generation.external_rag.retriever._retrieve_legacy", return_value={"status": "success", "evidence_blocks": []}
        ), patch("report_generation.external_rag.retriever._retrieve_hybrid", return_value={"status": "success", "evidence_blocks": [{"material_id": "m1"}]}), patch(
            "report_generation.external_rag.retriever._log_comparison"
        ) as log:
            result = retrieve_external_rag("查询", top_k=10)
        self.assertEqual(result["evidence_blocks"], [])
        log.assert_called_once()

    def test_hybrid_failure_can_fallback_to_legacy(self):
        with patch("report_generation.external_rag.retriever._mode", return_value="hybrid_v2"), patch(
            "report_generation.external_rag.retriever._retrieve_hybrid", return_value={"status": "error", "message": "not ready"}
        ), patch("report_generation.external_rag.retriever._retrieve_legacy", return_value={"status": "success", "evidence_blocks": []}):
            result = retrieve_external_rag("查询", top_k=10)
        self.assertEqual(result["retrieval_fallback"], "legacy")


if __name__ == "__main__":
    unittest.main()

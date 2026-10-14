import unittest
from unittest.mock import patch, PropertyMock

from report_generation.external_rag.retriever import retrieve_external_rag


class ReportRagModesTest(unittest.TestCase):
    def test_default_dispatches_to_hybrid_v2(self):
        with patch.dict("os.environ", {}, clear=True), patch(
            "report_generation.external_rag.retriever._retrieve_hybrid",
            return_value={"status": "success", "retrieval_version": "hybrid_v2", "evidence_blocks": []},
        ) as hybrid, patch(
            "report_generation.external_rag.retriever._retrieve_legacy"
        ) as legacy:
            result = retrieve_external_rag("查询", top_k=10)

        self.assertEqual(result["retrieval_version"], "hybrid_v2")
        hybrid.assert_called_once_with("查询", 10)
        legacy.assert_not_called()

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

    def test_empty_embodied_collection_is_reported_as_unavailable(self):
        empty = {"status": "success", "evidence_blocks": [],
                 "warnings": [{"code": "rag_store_empty"}], "retrieval_version": "hybrid_v2"}
        with patch("report_generation.external_rag.retriever._retrieve_news_hybrid", return_value=empty):
            result = retrieve_external_rag("查询", top_k=10, industry="embodied")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["evidence_blocks"], [])
        self.assertTrue(any(item.get("code") == "rag_store_empty" for item in result["warnings"]))

    def test_news_industry_dispatches_to_its_news_collection(self):
        raw = {
            "ids": [["news-1"]],
            "documents": [["低空经济资料"]],
            "metadatas": [[{"title": "资料标题", "source_id": "m1", "url": "https://example.test"}]],
            "distances": [[0.1]],
        }
        from report_generation.external_rag.news_retrieval import NewsDenseStore
        with patch.dict("os.environ", {"REPORT_RETRIEVAL_MODE": "hybrid_v2"}), patch(
            "report_generation.external_rag.news_retrieval.check_news_index", return_value={"status": "ready"}
        ), patch("report_generation.external_rag.news_retrieval.local_models") as models, patch(
            "report_generation.external_rag.news_retrieval.NewsLexicalStore.search", return_value=[]
        ), patch.object(NewsDenseStore, "collection", new_callable=PropertyMock) as collection:
            models.return_value.embed_documents.return_value = [[1.0] + [0.0] * 767]
            models.return_value.rerank_pairs.return_value = [0.9]
            collection.return_value.count.return_value = 1
            collection.return_value.query.return_value = raw
            result = retrieve_external_rag("低空经济产业链", top_k=3, industry="low_altitude")
        self.assertEqual(collection.return_value.query.call_args.kwargs['n_results'], 1)
        self.assertEqual(result["retrieval_version"], "hybrid_v2")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["evidence_blocks"]), 1)


if __name__ == "__main__":
    unittest.main()

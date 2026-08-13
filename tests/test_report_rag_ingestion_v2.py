import unittest
from unittest.mock import Mock, patch

from report_generation.external_rag.ingestion import _ingest_record


class ReportRagIngestionV2Test(unittest.TestCase):
    def _client(self):
        client = Mock()
        text = "这是一段用于验证 v2 双写与 manifest 记录的政策资料正文。" * 5
        client.query_by_id.return_value = {"title": "政策", "contentWithTag": f"<p>{text}</p>"}
        return client

    def test_success_manifest_contains_v2_chunk_ids(self):
        with patch("report_generation.external_rag.ingestion.upsert_paragraphs"), patch(
            "report_generation.external_rag.ingestion._v2_enabled", return_value=True
        ), patch("report_generation.external_rag.ingestion._upsert_v2_material", return_value=["external:v2:policy:m1:c:0:abcd1234"]):
            result = _ingest_record("policy", {"classification_type": "1", "classification_name": "政策法规"}, self._client(), {"id": "m1"}, None)
        self.assertEqual(result["manifest_record"]["v2_chunk_ids"], ["external:v2:policy:m1:c:0:abcd1234"])
        self.assertEqual(result["manifest_record"]["v2_status"], "success")

    def test_v2_failure_preserves_legacy_write_and_marks_partial(self):
        with patch("report_generation.external_rag.ingestion.upsert_paragraphs") as legacy, patch(
            "report_generation.external_rag.ingestion._v2_enabled", return_value=True
        ), patch("report_generation.external_rag.ingestion._upsert_v2_material", side_effect=RuntimeError("v2 failed")):
            result = _ingest_record("policy", {"classification_type": "1", "classification_name": "政策法规"}, self._client(), {"id": "m1"}, None)
        legacy.assert_called_once()
        self.assertEqual(result["manifest_record"]["status"], "success")
        self.assertEqual(result["manifest_record"]["v2_status"], "error")
        self.assertIn("v2 failed", result["manifest_record"]["v2_error"])


if __name__ == "__main__":
    unittest.main()

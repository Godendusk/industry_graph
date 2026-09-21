import tempfile
import unittest
from pathlib import Path

from docx import Document

from report_generation.word_export_agent import export_report_docx


class WordExportCitationsTest(unittest.TestCase):
    def test_writes_used_reference_section_and_keeps_body_marker(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = export_report_docx(
                report_title="测试报告",
                abstract_text="摘要正文",
                body_sections=[{
                    "parent_level1_id": "S1",
                    "parent_level1_title": "现状",
                    "title": "政策",
                    "body_text": "规划提出扩大应用[C1]。",
                    "citation_ids": ["C1"],
                }],
                references=[{
                    "citation_id": "C1",
                    "title": "政策甲",
                    "publish_date": "2026-06-29",
                    "retrieved_at": "2026-09-21T14:30:00+08:00",
                    "source_address": "https://example.test/policy",
                }],
                output_dir=output_dir,
            )
            text = "\n".join(p.text for p in Document(result["docx_path"]).paragraphs)

        self.assertEqual(result["status"], "success")
        self.assertIn("规划提出扩大应用[C1]。", text)
        self.assertIn("参考资料", text)
        self.assertIn("[C1] 政策甲", text)
        self.assertIn("检索于 2026-09-21T14:30:00+08:00", text)
        self.assertIn("https://example.test/policy", text)

    def test_removes_unknown_marker_and_warns(self):
        with tempfile.TemporaryDirectory() as output_dir:
            result = export_report_docx(
                report_title="测试报告",
                abstract_text="摘要正文",
                body_sections=[{
                    "parent_level1_id": "S1",
                    "parent_level1_title": "现状",
                    "title": "政策",
                    "body_text": "规划提出扩大应用[C9]。",
                }],
                references=[{"citation_id": "C1", "title": "政策甲"}],
                output_dir=output_dir,
            )

        self.assertEqual(result["status"], "success")
        self.assertTrue(any(w.get("stage") == "word_export_citation_validation" for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()

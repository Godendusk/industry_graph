import unittest

from report_generation.word_export_agent import export_report_docx


class WordExportAgentTest(unittest.TestCase):
    def test_rejects_reports_with_empty_body_sections_instead_of_silently_skipping_them(self):
        result = export_report_docx(
            report_title="测试报告",
            abstract_text="测试摘要",
            body_sections=[
                {
                    "outline_id": "S1.1",
                    "parent_level1_title": "第一章",
                    "title": "空小节",
                    "body_text": "",
                },
                {
                    "outline_id": "S1.2",
                    "parent_level1_title": "第一章",
                    "title": "完整小节",
                    "body_text": "完整正文。",
                },
            ],
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("empty body_text", result["message"])


if __name__ == "__main__":
    unittest.main()

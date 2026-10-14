import io
import json
import unittest
import zipfile
from unittest.mock import patch

from report_generation.outline_agent import (
    generate_report_outline,
    import_outline_template,
    validate_outline_template,
)


def make_docx(paragraphs, styles=""):
    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as document:
        document.writestr("word/document.xml", f"<w:document {namespace}><w:body>{paragraphs}</w:body></w:document>")
        document.writestr("word/styles.xml", f"<w:styles {namespace}>{styles}</w:styles>")
    return output.getvalue()


class OutlineTemplateTest(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(validate_outline_template({"level1_titles": [" 范围 "]}), ["范围"])
        for titles in ([], [""], ["甲", "甲"], ["甲" * 121], [str(i) for i in range(31)], [123]):
            with self.subTest(titles=titles), self.assertRaises(ValueError):
                validate_outline_template({"level1_titles": titles})

    def test_import_styles_inheritance_and_explicit_level(self):
        styles = '<w:style w:styleId="Base"><w:name w:val="heading 1"/></w:style><w:style w:styleId="Custom"><w:basedOn w:val="Base"/></w:style>'
        paragraphs = '<w:p><w:pPr><w:pStyle w:val="Custom"/></w:pPr><w:r><w:t>产业</w:t></w:r><w:r><w:t>范围</w:t></w:r></w:p>'
        paragraphs += '<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>趋势</w:t></w:r></w:p>'
        paragraphs += '<w:p><w:r><w:t>普通正文</w:t></w:r></w:p>'
        paragraphs += '<w:p><w:pPr><w:pStyle w:val="Custom"/><w:outlineLvl w:val="1"/></w:pPr><w:r><w:t>二级标题</w:t></w:r></w:p>'
        self.assertEqual(import_outline_template(make_docx(paragraphs, styles)), ["产业范围", "趋势"])

    def test_import_does_not_guess_body_or_loop_on_cyclic_styles(self):
        styles = '<w:style w:styleId="A"><w:basedOn w:val="B"/></w:style><w:style w:styleId="B"><w:basedOn w:val="A"/></w:style>'
        with self.assertRaises(ValueError):
            import_outline_template(make_docx('<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr><w:r><w:t>一、正文</w:t></w:r></w:p>', styles))
        with self.assertRaises(zipfile.BadZipFile):
            import_outline_template(b"not a Word file")

    def test_template_counts_are_not_default_limited(self):
        for count in (1, 2, 7, 30):
            titles = [f"章节 {i}" for i in range(count)]
            response = json.dumps({"chapters": [{"level1_id": f"S{index}", "subsections": [{"title": "范围"}, {"title": "趋势"}]} for index in range(1, count + 1)]})
            with self.subTest(count=count), patch("report_generation.outline_agent.llm.query", return_value=response):
                result = generate_report_outline("报告", "研究产业", industry_confirmed=True, outline_template={"level1_titles": titles})
                self.assertEqual(result["status"], "success")
                self.assertEqual([item["level1_title"] for item in result["outline"]], titles)

    def test_missing_duplicate_unknown_or_invalid_ids_fail(self):
        for ids in (["S1"], ["S1", "S1"], ["S1", "S3"], ["S1", "S2", "S3"], [None, "S2"], [[], "S2"]):
            with self.subTest(ids=ids), patch("report_generation.outline_agent.llm.query", return_value=json.dumps({"chapters": [{"level1_id": section_id, "subsections": [{"title": "小节"}]} for section_id in ids]})):
                result = generate_report_outline("报告", "研究产业", industry_confirmed=True, outline_template={"level1_titles": ["甲", "乙"]})
                self.assertEqual(result["status"], "error")

    def test_titles_are_program_owned_and_results_are_matched_by_id(self):
        chapters = [
            {"level1_id": "S2", "level1_title": "模型改写", "subsections": [{"title": "乙的小节"}]},
            {"level1_id": "S1", "level1_title": "另一个改写", "subsections": [{"title": "甲的小节"}]},
        ]
        with patch("report_generation.outline_agent.llm.query", return_value=json.dumps({"chapters": chapters})) as query:
            result = generate_report_outline("报告", "研究产业", industry_confirmed=True, outline_template={"level1_titles": ["甲", "乙"]})
        self.assertEqual(result["status"], "success")
        self.assertEqual([item["level1_title"] for item in result["outline"]], ["甲", "乙"])
        self.assertEqual([item["level1_id"] for item in result["outline"]], ["S1", "S2"])
        self.assertEqual(result["outline"][0]["subsections"][0]["title"], "甲的小节")
        self.assertIn('"level1_id": "S1"', query.call_args.kwargs["user_prompt"])
        self.assertNotIn('"level1_title": "一级章节标题"', query.call_args.kwargs["user_prompt"])

    def test_invalid_subsections_fail(self):
        for subsections in (None, [], "text", [{}], [{"title": ""}]):
            with self.subTest(subsections=subsections), patch("report_generation.outline_agent.llm.query", return_value=json.dumps({"chapters": [{"level1_id": "S1", "subsections": subsections}]})):
                result = generate_report_outline("报告", "研究产业", industry_confirmed=True, outline_template={"level1_titles": ["甲"]})
                self.assertEqual(result["status"], "error")

    def test_invalid_template_fails_before_model_call(self):
        with patch("report_generation.outline_agent.llm.query") as query:
            result = generate_report_outline("报告", "研究产业", industry_confirmed=True, outline_template={"level1_titles": []})
            self.assertEqual(result["status"], "error")
            query.assert_not_called()

    def test_invalid_json_does_not_fall_back_to_default_template(self):
        with patch("report_generation.outline_agent.llm.query", return_value="{") as query:
            result = generate_report_outline("报告", "研究产业", industry_confirmed=True, outline_template={"level1_titles": ["甲"]})
            self.assertEqual(result["status"], "error")
            self.assertEqual(query.call_count, 1)

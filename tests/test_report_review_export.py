from pathlib import Path

from docx import Document

from report_generation.word_export_agent import export_report_docx


def test_word_uses_final_body_and_appends_adjustment_note(tmp_path):
    result = export_report_docx(
        report_title='测试报告', abstract_text='最终正文摘要',
        body_sections=[{'outline_id':'S1.1','parent_level1_title':'现状','title':'布局',
                        'body_text':'审查后的正文。','status':'success','citation_ids':[]}],
        output_dir=str(tmp_path), adjustment_notes=[
            {'kind':'body_edit','outline_ids':['S1.1'],'reason':'压缩重复背景'}])
    assert result['status'] == 'success'
    text = '\n'.join(p.text for p in Document(Path(result['docx_path'])).paragraphs)
    assert '审查后的正文' in text
    assert '报告调整说明' in text
    assert '压缩重复背景' in text

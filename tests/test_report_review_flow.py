from unittest.mock import patch

from report_generation import body_agent


def task(outline_id):
    return {'outline_id': outline_id, 'title': outline_id, 'parent_level1_id': 'S1',
            'parent_level1_title': '第一章', 'writing_system_prompt': '写作任务'}


def section(outline_id):
    return {'outline_id': outline_id, 'title': outline_id, 'status': 'success',
            'body_text': '初稿', 'citation_ids': [], 'external_evidence_blocks': []}


def reviewed(sections):
    final = [dict(row, body_text='审查后正文') for row in sections]
    return {'body_sections': final, 'references': [],
            'review': {'status': 'completed', 'changed_outline_ids': ['S1.1']},
            'adjustment_notes': [{'kind': 'body_edit', 'outline_ids': ['S1.1'], 'reason': '压缩重复背景'}],
            'warnings': []}


def test_regular_and_stream_return_reviewed_body():
    tasks = [task('S1.1')]
    with patch.object(body_agent, 'generate_body_section', return_value=section('S1.1')), \
         patch.object(body_agent, 'review_report_bodies', side_effect=lambda **kw: reviewed(kw['body_sections'])) as review:
        regular = body_agent.generate_report_bodies('需求', '报告', tasks)
        events = list(body_agent.stream_report_bodies('需求', '报告', tasks))
    assert review.call_count == 2
    assert regular['body_sections'][0]['body_text'] == '审查后正文'
    assert events[-1]['event'] == 'completed'
    assert events[-1]['body_sections'][0]['body_text'] == '审查后正文'
    assert events[-1]['review']['status'] == 'completed'

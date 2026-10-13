import copy
import json
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation.review_agent import review_report_bodies


def section(outline_id, body_text):
    return {'outline_id': outline_id, 'title': outline_id, 'status': 'success',
            'body_text': body_text, 'citation_ids': ['C1'],
            'external_evidence_blocks': [{'citation_id': 'C1', 'text': '联盟成立'}]}


def input_data():
    sections = [section('S1.1', '联盟成立，有三项任务。[C1]'),
                section('S2.1', '联盟成立，有三项任务。[C1]\n\n本节分析机制。')]
    return {'body_sections': sections, 'writing_tasks': [], 'report_title': '报告',
            'user_prompt': '研究联盟', 'references': [{'citation_id': 'C1'}]}


def test_no_issues_makes_one_call_and_keeps_sections():
    data = input_data()
    before = copy.deepcopy(data['body_sections'])
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content='{"issues": []}', finish_reason='stop')) as call:
        result = review_report_bodies(**data)
    assert call.call_count == 1
    assert result['body_sections'] == before
    assert result['review']['changed_outline_ids'] == []


def test_repeated_background_changes_only_target_section():
    data = input_data()
    issue = {'issues': [{'reason': '重复完整介绍联盟任务', 'keep_paragraph_ids': ['S1.1:P1'],
              'edits': [{'outline_id': 'S2.1', 'paragraph_ids': ['S2.1:P1'],
                         'instruction': '压缩联盟介绍，保留机制分析',
                         'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    answers = [LLMQueryResult(content=json.dumps(issue, ensure_ascii=False), finish_reason='stop'),
               LLMQueryResult(content=json.dumps({'outline_id': 'S2.1',
                 'body_text': '该联盟提供协作载体。[C1]\n\n本节分析机制。'}, ensure_ascii=False), finish_reason='stop')]
    with patch('report_generation.review_agent.llm.query_result', side_effect=answers) as call:
        result = review_report_bodies(**data)
    assert call.call_count == 2
    assert result['body_sections'][0] == data['body_sections'][0]
    assert result['body_sections'][1]['body_text'].startswith('该联盟')
    assert result['review']['changed_outline_ids'] == ['S2.1']
    assert len(result['adjustment_notes']) == 1


def test_truncated_check_keeps_original():
    data = input_data()
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content='{"issues": [', finish_reason='length')):
        result = review_report_bodies(**data)
    assert result['body_sections'] == data['body_sections']
    assert result['review']['status'] == 'failed'


def test_failed_body_section_makes_review_partial_even_if_check_succeeds():
    data = input_data()
    data['body_sections'].append({'outline_id':'S3.1','title':'缺失','status':'error','body_text':''})
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content='{"issues":[]}', finish_reason='stop')):
        result = review_report_bodies(**data)
    assert result['review']['status'] == 'partial'
    assert result['review']['checked_outline_ids'] == ['S1.1','S2.1']


def test_edit_cleans_malformed_citation_marker_and_keeps_reviewed_text():
    data = input_data()
    issue = {'issues': [{'reason': '重复背景', 'keep_paragraph_ids': ['S1.1:P1'],
              'edits': [{'outline_id': 'S2.1', 'paragraph_ids': ['S2.1:P1'],
                         'instruction': '压缩重复背景', 'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    answers = [LLMQueryResult(content=json.dumps(issue, ensure_ascii=False), finish_reason='stop'),
               LLMQueryResult(content=json.dumps({'outline_id': 'S2.1',
                 'body_text': '压缩后的背景[citation:4]\n\n本节分析机制。'}, ensure_ascii=False), finish_reason='stop')]
    with patch('report_generation.review_agent.llm.query_result', side_effect=answers):
        result = review_report_bodies(**data)
    assert '[citation:4]' not in result['body_sections'][1]['body_text']
    assert result['review']['changed_outline_ids'] == ['S2.1']
    assert any(w.get('malformed_citation_markers') == ['[citation:4]'] for w in result['warnings'])


def test_check_and_edit_share_content_preservation_rules_with_writing():
    from report_generation import repetition_context as rc, review_agent as review
    assert hasattr(rc, 'COMMON_REUSE_RULES')
    assert rc.COMMON_REUSE_RULES in rc.REUSE_RULES
    assert rc.COMMON_REUSE_RULES in review._CHECK_PROMPT
    assert rc.COMMON_REUSE_RULES in review._EDIT_PROMPT

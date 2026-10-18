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
    issue = {'issues': [{'reason': '重复完整介绍联盟任务', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
              'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
                         'instruction': '压缩联盟介绍，保留机制分析',
                         'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    answers = [LLMQueryResult(content=json.dumps(issue, ensure_ascii=False), finish_reason='stop'),
               LLMQueryResult(content=json.dumps({'outline_id': 'S2.1',
                 'patches': [{'span_index': 0, 'replacement': '该联盟提供协作载体。[C1]'}]}, ensure_ascii=False), finish_reason='stop')]
    answers.append(LLMQueryResult(content=json.dumps({'resolved_issue_indexes': [0], 'unresolved': []}), finish_reason='stop'))
    with patch('report_generation.review_agent.llm.query_result', side_effect=answers) as call:
        result = review_report_bodies(**data)
    assert call.call_count == 3
    assert result['body_sections'][0] == data['body_sections'][0]
    assert result['body_sections'][1]['body_text'].startswith('该联盟')
    assert result['review']['changed_outline_ids'] == ['S2.1']
    assert len(result['adjustment_notes']) == 1
    assert result['review']['verification']['status'] == 'completed'


def test_review_verification_reports_unresolved_instruction_without_replacing_edit():
    data = input_data()
    issue = {'issues': [{'reason': '重复背景', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
              'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
                         'instruction': '删除重复背景，保留机制分析', 'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    answers = [
        LLMQueryResult(content=json.dumps(issue, ensure_ascii=False), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id': 'S2.1', 'patches': [{'span_index': 0, 'replacement': '仍有重复背景。[C1]'}]}, ensure_ascii=False), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'resolved_issue_indexes': [], 'unresolved': [{'issue_index': 0, 'reason': '重复背景仍存在'}]}, ensure_ascii=False), finish_reason='stop'),
    ]
    with patch('report_generation.review_agent.llm.query_result', side_effect=answers):
        result = review_report_bodies(**data)
    assert result['body_sections'][1]['body_text'].startswith('仍有重复背景')
    assert result['review']['verification']['unresolved_issue_indexes'] == [0]
    assert any(w.get('reason') == 'edit_verification_failed' for w in result['warnings'])


def test_unchanged_requested_section_cannot_pass_model_verification():
    data = input_data()
    issue = {'issues': [{'reason': '重复联盟背景', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
        'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
                   'instruction': '压缩重复介绍，保留机制分析', 'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    other_issue = copy.deepcopy(issue['issues'][0])
    other_issue['reason'] = '同一小节还有重复场景介绍'
    issue['issues'].append(other_issue)
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps(issue), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id': 'S2.1', 'patches': []}), finish_reason='stop'),
        LLMQueryResult(content='{"resolved_issue_indexes":[0,1],"unresolved":[]}', finish_reason='stop'),
    ]):
        result = review_report_bodies(**data)
    assert result['body_sections'] == data['body_sections']
    assert result['review']['status'] == 'partial'
    assert result['review']['verification']['unresolved_issue_indexes'] == [0, 1]
    assert sum('未产生修改' in n['reason'] for n in result['adjustment_notes']) == 1


def test_review_accepts_evidence_warnings_and_keeps_them_separate_from_repetition_edits():
    data = input_data()
    response = {'issues': [], 'evidence_warnings': [{'outline_id': 'S2.1', 'reason': '不同日期资料对标准状态表述不一致', 'citation_ids': ['C1']}]}
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content=json.dumps(response, ensure_ascii=False), finish_reason='stop')):
        result = review_report_bodies(**data)
    assert result['review']['issue_count'] == 0
    assert result['review']['evidence_warning_count'] == 1
    assert any(w.get('reason') == 'evidence_consistency_warning' for w in result['warnings'])


def test_check_receives_cited_evidence_dates_and_records_truncation():
    data = input_data()
    data['body_sections'][0]['external_evidence_blocks'][0].update(
        publish_date='2025-10-03', text='证据' * 1000)
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content='{"issues":[]}', finish_reason='stop')) as query:
        review_report_bodies(**data)
    payload = json.loads(query.call_args.kwargs['user_prompt'])
    block = payload['evidence']['blocks'][0]
    assert block['publish_date'] == '2025-10-03'
    assert block['truncated'] is True


def test_verification_reverts_section_when_patch_changes_claim_meaning():
    data = input_data()
    issue = {'issues': [{'reason': '重复背景', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
        'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
                   'instruction': '删除背景，保留机制', 'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps(issue, ensure_ascii=False), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id':'S2.1','patches':[{'span_index': 0, 'replacement': '该联盟提供协作载体。[C1]'}]}), finish_reason='stop'),
        LLMQueryResult(content='{"resolved_issue_indexes":[],"unresolved":[{"issue_index":0,"reason":"替换后的事实含义有误","revert_outline_ids":["S2.1"]}]}', finish_reason='stop'),
    ]) as query:
        result = review_report_bodies(**data)
    assert result['body_sections'] == data['body_sections']
    assert result['review']['changed_outline_ids'] == []
    assert result['review']['failed_outline_ids'] == ['S2.1']
    payload = json.loads(query.call_args.kwargs['user_prompt'])
    assert payload['original_sections'][1]['body_text'] == data['body_sections'][1]['body_text']


def test_bare_source_code_is_reported_without_guessing_citation_placement():
    data = input_data()
    data['body_sections'][1]['body_text'] = 'C1认为应逐步推进。'
    events = []
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content='{"issues":[]}', finish_reason='stop')):
        result = review_report_bodies(**data, on_event=events.append)
    assert any(w.get('reason') == 'bare_citation_code' for w in result['warnings'])
    assert any('引用标记' in n['reason'] for n in result['adjustment_notes'])
    assert events[-1]['status'] == result['review']['status'] == 'partial'


def test_incomplete_verification_is_not_reported_as_completed():
    from report_generation.review_agent import _verify_edits
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content='{"resolved_issue_indexes":[],"unresolved":[]}', finish_reason='stop')):
        import pytest
        with pytest.raises(ValueError, match='incomplete_verification'):
            _verify_edits([{'edits': []}], [], [])


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
    issue = {'issues': [{'reason': '重复背景', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
              'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
                         'instruction': '压缩重复背景', 'preserve_paragraph_ids': ['S2.1:P2']}]}]}
    answers = [LLMQueryResult(content=json.dumps(issue, ensure_ascii=False), finish_reason='stop'),
               LLMQueryResult(content=json.dumps({'outline_id': 'S2.1',
                 'patches': [{'span_index': 0, 'replacement': '压缩后的背景[citation:4]'}]}, ensure_ascii=False), finish_reason='stop')]
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


def span_issue(quote='联盟成立，有三项任务。[C1]'):
    return {'issues': [{'reason': '重复背景',
        'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '联盟成立，有三项任务。[C1]'}],
        'edits': [{'outline_id': 'S2.1',
            'spans': [{'paragraph_id': 'S2.1:P1', 'quote': quote}],
            'instruction': '只压缩该重复片段', 'preserve_paragraph_ids': []}]}]}


def run_span_review(data, issue, patches):
    answers = [issue, {'outline_id': 'S2.1', 'patches': patches},
               {'resolved_issue_indexes': [0], 'unresolved': []}]
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps(a, ensure_ascii=False), finish_reason='stop') for a in answers]):
        return review_report_bodies(**data)


def test_minimal_patch_preserves_unique_facts_qualifiers_citations_and_whitespace():
    data = input_data()
    original = '  联盟成立，有三项任务。[C1]南网科技另有应用；湖北拟设基金。[C1]  \n\n  独有分析。  '
    data['body_sections'][1]['body_text'] = original
    result = run_span_review(data, span_issue(), [{'span_index': 0, 'replacement': ''}])
    assert result['body_sections'][1]['body_text'] == original.replace('联盟成立，有三项任务。[C1]', '')
    assert result['review']['changed_outline_ids'] == ['S2.1']


def test_missing_keep_quote_cannot_authorize_deletion():
    data = input_data()
    issue = span_issue()
    issue['issues'][0]['keep_spans'][0]['quote'] = '正文中没有的案例'
    result = run_span_review(data, issue, [])
    assert result['body_sections'] == data['body_sections']
    assert result['review']['status'] == 'failed'


def test_missing_edit_quote_cannot_authorize_deletion():
    data = input_data()
    result = run_span_review(data, span_issue('正文中没有的重复句'), [])
    assert result['body_sections'] == data['body_sections']
    assert result['review']['status'] == 'failed'


def test_invalid_span_patches_keep_original_and_provide_notice():
    data = input_data()
    cases = [
        [{'span_index': 99, 'replacement': ''}],
        [{'span_index': 0, 'replacement': ''},
         {'span_index': 0, 'replacement': ''}],
        [{'span_index': '0', 'replacement': ''}],
    ]
    for patches in cases:
        result = run_span_review(data, span_issue(), patches)
        assert result['body_sections'] == data['body_sections']
        assert result['review']['failed_outline_ids'] == ['S2.1']
        assert any('精简未采用' in n['reason'] for n in result['adjustment_notes'])


def test_ambiguous_authorized_span_does_not_choose_an_arbitrary_occurrence():
    data = input_data()
    data['body_sections'][1]['body_text'] = '联盟成立，联盟成立，有三项任务。[C1]'
    result = run_span_review(data, span_issue('联盟成立'), [{'span_index': 0, 'replacement': ''}])
    assert result['body_sections'] == data['body_sections']
    assert result['review']['status'] == 'failed'


def test_multiple_patches_use_original_positions_without_cascading_replacement():
    data = input_data()
    issue = span_issue()
    issue['issues'][0]['edits'][0]['spans'] = [
        {'paragraph_id': 'S2.1:P1', 'quote': '联盟成立'},
        {'paragraph_id': 'S2.1:P1', 'quote': '三项任务'}]
    result = run_span_review(data, issue, [
        {'span_index': 1, 'replacement': '协作任务'},
        {'span_index': 0, 'replacement': '三项任务'}])
    assert result['body_sections'][1]['body_text'] == '三项任务，有协作任务。[C1]\n\n本节分析机制。'


def test_intra_paragraph_repetition_keeps_other_span_in_same_paragraph():
    data = input_data()
    data['body_sections'][1]['body_text'] = '完整介绍联盟任务。[C1]分析条件。再次完整介绍联盟任务。[C1]'
    issue = span_issue('再次完整介绍联盟任务。[C1]')
    issue['issues'][0]['keep_spans'] = [{'paragraph_id': 'S2.1:P1', 'quote': '完整介绍联盟任务。[C1]'}]
    # Include punctuation to make the kept occurrence unambiguous.
    issue['issues'][0]['keep_spans'][0]['quote'] = '完整介绍联盟任务。[C1]分析条件。'
    result = run_span_review(data, issue, [{'span_index': 0, 'replacement': ''}])
    assert result['body_sections'][1]['body_text'] == '完整介绍联盟任务。[C1]分析条件。'


def test_editor_cannot_replace_raw_text_outside_numbered_authorization():
    data = input_data()
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps(span_issue('联盟成立')), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id':'S2.1','patches':[
            {'paragraph_id':'S2.1:P1','original':'联盟成立，有三项任务。[C1]','replacement':''}]}), finish_reason='stop'),
        LLMQueryResult(content='{"resolved_issue_indexes":[0],"unresolved":[]}', finish_reason='stop')]):
        result = review_report_bodies(**data)
    assert result['body_sections'] == data['body_sections']
    assert result['review']['failed_outline_ids'] == ['S2.1']


def test_targeted_review_cannot_edit_another_section():
    data = input_data()
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
        content=json.dumps(span_issue()), finish_reason='stop')) as call:
        result = review_report_bodies(**data, target_outline_id='S1.1')
    assert call.call_count == 1
    assert result['body_sections'] == data['body_sections']
    assert result['review']['status'] == 'failed'


def test_whole_section_response_is_rejected_with_notice():
    data = input_data()
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps(span_issue()), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id': 'S2.1', 'body_text': '整节重写'}), finish_reason='stop'),
        LLMQueryResult(content='{"resolved_issue_indexes":[0],"unresolved":[]}', finish_reason='stop')]):
        result = review_report_bodies(**data)
    assert result['body_sections'] == data['body_sections']
    assert result['review']['failed_outline_ids'] == ['S2.1']
    assert result['review']['status'] == 'partial'


def test_preserve_paragraph_applies_to_its_own_instruction():
    data = input_data()
    data['body_sections'][1]['body_text'] = '联盟成立，有三项任务。[C1]\n\n另一重复背景。独有分析。'
    issue = span_issue()
    issue['issues'][0]['edits'][0]['preserve_paragraph_ids'] = ['S2.1:P2']
    second = copy.deepcopy(issue['issues'][0])
    second['edits'][0]['spans'] = [{'paragraph_id': 'S2.1:P2', 'quote': '另一重复背景。'}]
    second['edits'][0]['preserve_paragraph_ids'] = ['S2.1:P1']
    issue['issues'].append(second)
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps(issue), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id':'S2.1','patches':[
            {'span_index': 0, 'replacement': ''},
            {'span_index': 1, 'replacement': ''}]}), finish_reason='stop'),
        LLMQueryResult(content='{"resolved_issue_indexes":[0,1],"unresolved":[]}', finish_reason='stop')]):
        result = review_report_bodies(**data)
    assert result['body_sections'][1]['body_text'] == '\n\n独有分析。'
    assert result['review']['status'] == 'completed'


def test_one_invalid_issue_does_not_block_other_valid_edits():
    data = input_data()
    issue = span_issue()
    invalid = copy.deepcopy(issue['issues'][0])
    invalid['keep_spans'][0]['quote'] = '正文不存在'
    issue['issues'].append(invalid)
    result = run_span_review(data, issue, [{'span_index': 0, 'replacement': '该联盟。[C1]'}])
    assert result['body_sections'][1]['body_text'].startswith('该联盟。')
    assert result['review']['status'] == 'partial'
    assert any('1项' in n['reason'] for n in result['adjustment_notes'])


def test_unedited_issue_cannot_hide_behind_another_patch_in_same_section():
    data = input_data()
    data['body_sections'][0]['body_text'] = '重复背景甲。重复背景乙。'
    data['body_sections'][1]['body_text'] = '重复背景甲。重复背景乙。独有分析。'
    issues = []
    for quote in ['重复背景甲。', '重复背景乙。']:
        issues.append({'reason': quote, 'keep_spans':[{'paragraph_id':'S1.1:P1','quote':quote}],
            'edits':[{'outline_id':'S2.1','spans':[{'paragraph_id':'S2.1:P1','quote':quote}],
                'instruction':'删除重复句','preserve_paragraph_ids':[]}]})
    with patch('report_generation.review_agent.llm.query_result', side_effect=[
        LLMQueryResult(content=json.dumps({'issues':issues}), finish_reason='stop'),
        LLMQueryResult(content=json.dumps({'outline_id':'S2.1','patches':[{'span_index':0,'replacement':''}]}), finish_reason='stop'),
        LLMQueryResult(content='{"resolved_issue_indexes":[0,1],"unresolved":[]}', finish_reason='stop')]):
        result = review_report_bodies(**data)
    assert result['body_sections'][1]['body_text'] == '重复背景乙。独有分析。'
    assert result['review']['verification']['unresolved_issue_indexes'] == [1]
    assert result['review']['status'] == 'partial'
    assert any('片段' in n['reason'] for n in result['adjustment_notes'])


def test_patch_that_introduces_broken_punctuation_keeps_original_with_notice():
    data = input_data()
    data['body_sections'][1]['body_text'] = '条件。联盟成立，有三项任务。[C1]，因此需验证。'
    result = run_span_review(data, span_issue(), [{'span_index':0,'replacement':''}])
    assert result['body_sections'] == data['body_sections']
    assert result['review']['failed_outline_ids'] == ['S2.1']
    assert any('精简未采用' in n['reason'] for n in result['adjustment_notes'])


def test_cross_section_dated_state_warning_is_repaired_and_rechecked_with_new_evidence():
    from llm_client import LLMQueryResult
    old = {'outline_id': 'S1.1', 'title': '准入', 'status': 'success',
        'body_text': '甲公司预计2025年取得许可[C1]。', 'external_evidence_blocks': [
            {'citation_id': 'C1', 'text': '2024年研报预计甲公司2025年取得许可。', 'vector_id': 'old:1'}]}
    new = {'outline_id': 'S2.1', 'title': '交付', 'status': 'success',
        'body_text': '甲公司2025年已取得许可[C2]。', 'external_evidence_blocks': [
            {'citation_id': 'C2', 'text': '甲公司2025年已取得许可。', 'vector_id': 'new:1'}]}
    edited = []
    def answer(**kw):
        p = json.loads(kw['user_prompt'])
        if 'claim_verification' in p:
            rows = []
            for s in p['claim_verification']:
                for c in s['claims']:
                    supports = [{'evidence_id': e['evidence_id'], 'quote': e['text']} for e in s['evidence']
                                if e['citation_id'] in c['citation_ids']]
                    rows.append({'claim_id': c['claim_id'], 'status': 'supported', 'reason': '日期状态支持', 'supports': supports})
            result = {'claim_checks': rows}
            if 'original_sections' in p:
                assert p['original_sections'][0]['consistency_warnings']
                result['information_loss'] = [{'outline_id': s['outline_id'], 'lost': False,
                    'reason': '保留原预测并补充实际节点，已消除状态冲突', 'consistency_resolved': True,
                    'consistency_checks': [{'warning_index': 0, 'resolved': True, 'final_quote': s['body_text'],
                        'supports': [{'citation_id': e['citation_id'], 'quote': e['text']} for e in s['evidence']]}]}
                    for s in p['claim_verification']]
        elif 'sections' in p:
            result = {'issues': [], 'evidence_warnings': [{'outline_id': 'S1.1',
                'reason': '旧预测缺少日期，与已取得许可混淆', 'citation_ids': ['C1', 'C2']}]}
        else:
            assert {e['citation_id'] for e in p['evidence_blocks']} == {'C1', 'C2'}
            edited.append(p)
            result = {'outline_id': 'S1.1', 'patches': [{'span_index': 0,
                'replacement': '2024年研报曾预计甲公司2025年取得许可[C1]；2025年资料已确认取得许可[C2]。'}]}
        return LLMQueryResult(content=json.dumps(result, ensure_ascii=False), finish_reason='stop')
    with patch('report_generation.review_agent.llm.query_result', side_effect=answer):
        result = review_report_bodies(body_sections=[old, new], writing_tasks=[], report_title='报告', user_prompt='比较', references=[])
    assert edited
    assert '2024年研报曾预计' in result['body_sections'][0]['body_text']
    assert result['review']['evidence_warning_count'] == 0
    assert result['review']['status'] == 'completed'


def test_patch_cannot_duplicate_the_unchanged_leading_clause():
    import pytest
    from report_generation.review_agent import _apply_patches
    body = '综合上述证据，可以作如下收窄表述：传统产业仍占主导，但缺少增量数据。'
    section = {'outline_id': 'S1.1', 'body_text': body, 'external_evidence_blocks': []}
    instructions = [{'spans': [{'paragraph_id': 'S1.1:P1', 'quote': '传统产业仍占主导，但缺少增量数据。'}]}]
    with pytest.raises(ValueError, match='duplicated_patch_clause'):
        _apply_patches({'outline_id': 'S1.1', 'patches': [{'span_index': 0,
            'replacement': '综合上述证据，可以作如下收窄表述：传统产业仍占主导。'}]}, section, instructions)


def test_identical_consistency_quotes_use_each_original_position():
    from report_generation.review_agent import _merge_consistency_edits, _paragraphs
    from report_generation.agentic_rag.verification import prepare_section
    s = {'outline_id': 'S1.1', 'status': 'success', 'body_text': '甲公司预计2025年取证[C1]。甲公司预计2025年取证[C1]。',
         'external_evidence_blocks': [{'citation_id': 'C1', 'text': '预计2025年取证'}]}
    warnings = {'S1.1': [{'citation_ids': ['C1'], 'message': '时点待核对'}]}
    edits = _merge_consistency_edits({}, [s], {'S1.1': prepare_section(s)}, warnings, _paragraphs([s]))
    assert len(edits['S1.1']) == 2
    spans = [item['spans'][0] for item in edits['S1.1']]
    assert spans[0]['start'] == 0
    assert spans[1]['start'] == len(spans[0]['quote'])
    assert all(s['body_text'][span['start']:span['end']] == span['quote'] for span in spans)
    assert not warnings['S1.1'][0].get('corrected')


def test_consistency_repair_sees_later_source_even_when_warning_names_old_source_only():
    from report_generation.review_agent import _consistency_source_candidates
    sections = [{'external_evidence_blocks': [{'citation_id': 'C1', 'title': '2024预测', 'text': '预计取得许可'}]},
                {'external_evidence_blocks': [{'citation_id': 'C2', 'title': '2025实际进展', 'text': '甲公司已取得许可'}]}]
    candidates = _consistency_source_candidates(sections)
    assert {e['citation_id'] for e in candidates} == {'C1', 'C2'}
    assert any('已取得许可' in e['text'] for e in candidates)


def test_unchanged_body_can_clear_false_consistency_warning_only_after_independent_recheck():
    from llm_client import LLMQueryResult
    s = {'outline_id': 'S1.1', 'title': '准入', 'status': 'success',
         'body_text': '甲公司2025年已取得许可[C1]。',
         'external_evidence_blocks': [{'citation_id': 'C1', 'text': '甲公司2025年已取得许可。'}]}
    checked = []
    def answer(**kw):
        p = json.loads(kw['user_prompt'])
        if 'claim_verification' in p:
            rows = [{'claim_id': c['claim_id'], 'status': 'supported', 'reason': '原文支持',
                     'supports': [{'evidence_id': x['evidence'][0]['evidence_id'], 'quote': x['evidence'][0]['text']}]}
                    for x in p['claim_verification'] for c in x['claims']]
            result = {'claim_checks': rows}
            if 'original_sections' in p:
                checked.append(True)
                result['information_loss'] = [{'outline_id': 'S1.1', 'lost': False,
                    'consistency_resolved': True, 'reason': '原正文已明确日期与实际状态，疑点不成立',
                    'consistency_checks': [{'warning_index': 0, 'resolved': True, 'final_quote': s['body_text'],
                        'supports': [{'citation_id': 'C1', 'quote': s['external_evidence_blocks'][0]['text']}]}]}]
        elif 'sections' in p:
            result = {'issues': [], 'evidence_warnings': [{'outline_id': 'S1.1', 'reason': '日期待核对', 'citation_ids': ['C1']}]}
        else:
            result = {'outline_id': 'S1.1', 'patches': []}
        return LLMQueryResult(content=json.dumps(result, ensure_ascii=False), finish_reason='stop')
    with patch('report_generation.review_agent.llm.query_result', side_effect=answer):
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='比较', references=[])
    assert checked
    assert result['body_sections'][0]['body_text'] == s['body_text']
    assert result['review']['status'] == 'completed'
    assert result['review']['changed_outline_ids'] == []


def test_overlapping_targets_form_one_original_range_before_model_edit():
    from report_generation.review_agent import _editable_spans, _apply_patches
    body = '甲公司2025年已经投产。[C1]保留分析。'
    instructions = [{'spans': [{'paragraph_id': 'S1.1:P1', 'quote': '甲公司2025年已经投产。'},
                               {'paragraph_id': 'S1.1:P1', 'quote': '已经投产。[C1]'}],
                     'keep_spans': [], 'instruction': '修正并压缩'}]
    spans = _editable_spans(instructions, {'S1.1:P1': body})
    assert len(spans) == 1
    assert spans[0]['quote'] == '甲公司2025年已经投产。[C1]'
    section = {'outline_id': 'S1.1', 'body_text': body, 'external_evidence_blocks': [{'citation_id': 'C1', 'text': '计划投产'}]}
    result = _apply_patches({'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': '甲公司计划投产。[C1]'}]}, section, instructions)
    assert result[0] == '甲公司计划投产。[C1]保留分析。'


def test_consistency_boolean_without_final_text_and_source_proof_cannot_clear_warning():
    from report_generation.review_agent import _consistency_proven
    section = {'body_text': '甲公司计划2025年取证[C1]。', 'external_evidence_blocks': [
        {'citation_id': 'C1', 'text': '2024年预计2025年取证。'}]}
    loss = [{'consistency_resolved': True, 'reason': '已经修复'}]
    assert not _consistency_proven(loss, section, 1)
    loss[0]['consistency_checks'] = [{'warning_index': 0, 'resolved': True,
        'final_quote': section['body_text'], 'supports': [{'citation_id': 'C1', 'quote': '2024年预计2025年取证。'}]}]
    assert _consistency_proven(loss, section, 1)
    loss[0]['consistency_checks'][0]['final_quote'] = '甲公司已取证[C1]。'
    assert not _consistency_proven(loss, section, 1)


def test_repetition_rollback_restores_consistency_warning_after_fact_recheck():
    from llm_client import LLMQueryResult
    old = {'outline_id': 'S1.1', 'title': '准入', 'status': 'success',
        'body_text': '甲公司预计2025年取得许可[C1]。', 'external_evidence_blocks': [
            {'citation_id': 'C1', 'text': '2024年研报预计甲公司2025年取得许可。', 'vector_id': 'old:1'}]}
    new = {'outline_id': 'S2.1', 'title': '交付', 'status': 'success',
        'body_text': '甲公司2025年已取得许可[C2]。', 'external_evidence_blocks': [
            {'citation_id': 'C2', 'text': '甲公司2025年已取得许可。', 'vector_id': 'new:1'}]}
    edited = []
    def answer(**kw):
        p = json.loads(kw['user_prompt'])
        if 'claim_verification' in p:
            rows = []
            for s in p['claim_verification']:
                for c in s['claims']:
                    supports = [{'evidence_id': e['evidence_id'], 'quote': e['text']} for e in s['evidence']
                                if e['citation_id'] in c['citation_ids']]
                    rows.append({'claim_id': c['claim_id'], 'status': 'supported', 'reason': '日期状态支持', 'supports': supports})
            result = {'claim_checks': rows}
            if 'original_sections' in p:
                assert p['original_sections'][0]['consistency_warnings']
                result['information_loss'] = [{'outline_id': s['outline_id'], 'lost': False,
                    'reason': '保留原预测并补充实际节点，已消除状态冲突', 'consistency_resolved': True,
                    'consistency_checks': [{'warning_index': 0, 'resolved': True, 'final_quote': s['body_text'],
                        'supports': [{'citation_id': e['citation_id'], 'quote': e['text']} for e in s['evidence']]}]}
                    for s in p['claim_verification']]
        elif 'final_sections' in p:
            result = {'resolved_issue_indexes': [], 'unresolved': [{'issue_index': 0, 'reason': '误删必要限定', 'revert_outline_ids': ['S1.1']}]}
        elif 'sections' in p:
            result = {'issues': [{'reason': '状态重复', 'keep_spans': [{'paragraph_id': 'S2.1:P1', 'quote': new['body_text']}], 'edits': [{'outline_id': 'S1.1', 'spans': [{'paragraph_id': 'S1.1:P1', 'quote': old['body_text']}], 'instruction': '压缩重复但保留历史时点', 'preserve_paragraph_ids': []}]}], 'evidence_warnings': [{'outline_id': 'S1.1',
                'reason': '旧预测缺少日期，与已取得许可混淆', 'citation_ids': ['C1', 'C2']}]}
        else:
            assert {e['citation_id'] for e in p['evidence_blocks']} == {'C1', 'C2'}
            edited.append(p)
            result = {'outline_id': 'S1.1', 'patches': [{'span_index': 0,
                'replacement': '2024年研报曾预计甲公司2025年取得许可[C1]；2025年资料已确认取得许可[C2]。'}]}
        return LLMQueryResult(content=json.dumps(result, ensure_ascii=False), finish_reason='stop')
    with patch('report_generation.review_agent.llm.query_result', side_effect=answer):
        result = review_report_bodies(body_sections=[old, new], writing_tasks=[], report_title='报告', user_prompt='比较', references=[])
    assert edited
    assert result['body_sections'][0]['body_text'] == old['body_text']
    assert result['review']['evidence_warning_count'] == 1
    assert any('证据待核实' in n['reason'] for n in result['adjustment_notes'])
    assert result['review']['status'] == 'partial'



def test_final_repetition_verification_receives_authorized_fact_corrections():
    from report_generation.review_agent import _verify_edits
    seen = []
    original = [{'outline_id': 'S1.1', 'body_text': '甲公司已投产。', 'status': 'success'}]
    final = [{'outline_id': 'S1.1', 'body_text': '甲公司计划投产。', 'status': 'success',
              'claim_verification': {'claims': [{'quote': '甲公司计划投产。', 'status': 'supported',
                  'reason': '原文是计划', 'supports': [{'citation_id': 'C1', 'quote': '甲公司计划投产。'}]}]}}]
    def query(text, prompt, tokens):
        seen.append(json.loads(text)); return {'resolved_issue_indexes': [], 'unresolved': []}
    with patch('report_generation.review_agent._query', side_effect=query):
        _verify_edits([], original, final, authorized_edits={'S1.1': [{'reason': '状态误写', 'spans': [],
            'instruction': '改为计划', 'keep_spans': [], 'preserve_paragraph_ids': []}]})
    assert seen[0]['authorized_edits']['S1.1'][0]['reason'] == '状态误写'
    assert seen[0]['final_sections'][0]['claim_verification']['claims'][0]['status'] == 'supported'


def test_partial_edit_can_preserve_remainder_of_its_same_paragraph():
    from report_generation.review_agent import _validate_issues, _apply_patches
    paragraphs = {'S1.1:P1': '重复背景。', 'S2.1:P1': '重复背景。独有分析。'}
    issue = {'issues': [{'reason': '背景重复', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '重复背景。'}],
        'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '重复背景。'}],
            'instruction': '删重复，保留本段分析', 'preserve_paragraph_ids': ['S2.1:P1']}]}]}
    edits, accepted, rejected = _validate_issues(issue, paragraphs, None)
    assert len(accepted) == 1 and not rejected
    section = {'outline_id': 'S2.1', 'body_text': paragraphs['S2.1:P1'], 'external_evidence_blocks': []}
    body, _, _, _ = _apply_patches({'outline_id': 'S2.1', 'patches': [{'span_index': 0, 'replacement': ''}]}, section, edits['S2.1'])
    assert body == '独有分析。'


def test_whole_paragraph_edit_conflicting_with_preservation_is_still_rejected():
    import pytest
    from report_generation.review_agent import _validate_issue
    paragraphs = {'S1.1:P1': '重复背景。', 'S2.1:P1': '重复背景。'}
    issue = {'issues': [{'reason': '背景重复', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': '重复背景。'}],
        'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '重复背景。'}],
            'instruction': '删除', 'preserve_paragraph_ids': ['S2.1:P1']}]}]}
    with pytest.raises(ValueError, match='conflicting_span_instructions'):
        _validate_issue(issue, paragraphs, None)


def test_only_remaining_citation_does_not_count_as_preserved_paragraph_content():
    import pytest
    from report_generation.review_agent import _validate_issue
    paragraphs = {'S1.1:P1': '企业甲2025年已经投产。[C1]', 'S2.1:P1': '企业甲2025年已经投产。[C1]'}
    issue = {'issues': [{'reason': '重复', 'keep_spans': [{'paragraph_id': 'S1.1:P1', 'quote': paragraphs['S1.1:P1']}],
        'edits': [{'outline_id': 'S2.1', 'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '企业甲2025年已经投产。'}],
            'instruction': '删除重复', 'preserve_paragraph_ids': ['S2.1:P1']}]}]}
    with pytest.raises(ValueError, match='conflicting_span_instructions'):
        _validate_issue(issue, paragraphs, None)

import copy
import json
from unittest.mock import patch

import pytest

from llm_client import LLMQueryResult
from report_generation import task_coordination as tc
from report_generation import writing_decisions as wd


def decision(question='资源怎样转化？'):
    return {'section_question': question,
            'evidence_uses': [{'topic': '中国移动产业联盟', 'basis': 'external',
                               'citation_ids': ['C14'], 'use': '分析组织载体',
                               'support_limit': '成立不证明成效'}],
            'content_scope': {'full_exposition': [], 'carry_over': []},
            'judgment_limits': ['不判断协同成效']}


def task(outline_id='S3.2'):
    return {'outline_id': outline_id, 'title': '资源禀赋',
            'parent_level1_title': '布局',
            'writing_decision': decision(), 'writing_system_prompt': '旧长任务书',
            'repetition_focus_terms': ['旧焦点对象'],
            'graph_retrieval': {'status': 'skipped', 'raw_output': '图谱实体清单'},
            'external_rag_retrieval': {'evidence_blocks': [
                {'citation_id': 'C14', 'text': '中国移动产业联盟的原始材料全文'},
                {'citation_id': 'C15', 'text': '合作项目成果的原始材料全文'}]}}


def change(outline_id='S3.2', **overrides):
    return {'outline_id': outline_id, 'reason': '转向转化条件',
            'set': {'section_question': '组织资源如何转化？'}, **overrides}


def respond(value):
    return LLMQueryResult(content=json.dumps(value, ensure_ascii=False), finish_reason='stop')


def test_coordination_uses_shared_configured_client():
    assert tc.llm is wd.llm


def test_scope_payload_does_not_repeat_full_support_passages():
    tasks = [task()]
    tasks[0]['evidence_pack'] = {'status': 'assessed', 'requirements': [
        {'id': 'r1', 'requirement': '经营比较', 'status': 'supported', 'reason': '原文支持',
         'support': [{'citation_id': 'C14', 'quote': '完整原文' * 2000}]}]}
    payload = tc.build_coordination_payload(tasks, '经营比较', '报告', [])
    quote = payload['sections'][0]['evidence']['requirements'][0]['support'][0]['quote']
    assert len(quote) <= 160
    assert tasks[0]['evidence_pack']['requirements'][0]['support'][0]['quote'] == '完整原文' * 2000


def test_payload_has_only_outline_decision_and_allowed_ids():
    payload = tc.build_coordination_payload([task()])
    assert payload['outline'] == [{'outline_id': 'S3.2', 'parent_title': '布局', 'title': '资源禀赋'}]
    assert payload['sections'][0]['allowed_citation_ids'] == ['C14', 'C15']
    assert set(payload['sections'][0]) == {'outline_id', 'decision', 'allowed_citation_ids'}
    text = json.dumps(payload, ensure_ascii=False)
    assert all(x not in text for x in ['原始材料全文', '旧长任务书', '图谱实体清单'])


def test_budget_skips_call_and_preserves_tasks():
    tasks = [task()]
    with patch.object(tc, 'MAX_COORDINATION_INPUT_CHARS', 10), patch.object(tc.llm, 'query_result') as call:
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert not call.called and final == tasks
    assert meta['status'] == 'skipped_budget' and warnings


def test_duplicate_task_ids_preserve_decisions_without_model_call():
    tasks=[task(), task()]
    tasks[1]['title']='新增小节'
    with patch.object(tc.llm,'query_result',return_value=respond({'changes':[change()]})) as call:
        final,meta,warnings=tc.coordinate_writing_tasks(tasks)
    assert not call.called and final==tasks
    assert meta['status']=='failed'
    assert warnings[0]['reason']=='duplicate_outline_id'


def test_success_changes_prompt_focus_not_evidence_and_calls_once():
    tasks = [task()]
    original = copy.deepcopy(tasks)
    updated = change()
    updated['set']['evidence_uses'] = [dict(decision()['evidence_uses'][0], topic='合作项目成果', citation_ids=['C15'])]
    with patch.object(tc.llm, 'query_result', return_value=respond({'changes': [updated]})) as call:
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert tasks == original
    assert final[0]['external_rag_retrieval'] == original[0]['external_rag_retrieval']
    assert final[0]['graph_retrieval'] == original[0]['graph_retrieval']
    assert final[0]['repetition_focus_terms'] == ['合作项目成果']
    assert '组织资源如何转化' in final[0]['writing_system_prompt']
    assert final[0]['decision_review_status'] == 'adjusted'
    assert meta['status'] == 'completed' and meta['changed_outline_ids'] == ['S3.2'] and not warnings
    assert call.call_count == 1
    kwargs = call.call_args.kwargs
    assert kwargs['max_tokens'] == 5000 and kwargs['reasoning_effort'] is None
    assert kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert len(kwargs['user_prompt']) == meta['input_chars']
    assert json.loads(kwargs['user_prompt']) == tc.build_coordination_payload(tasks)


def test_valid_empty_changes_is_completed():
    tasks = [task()]
    with patch.object(tc.llm, 'query_result', return_value=respond({'changes': []})):
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert final[0]['writing_decision'] == tasks[0]['writing_decision']
    assert final[0]['decision_review_status'] == 'unchanged'
    assert meta['status'] == 'completed' and meta['changed_outline_ids'] == [] and not warnings


def test_coordination_returns_proposed_outline_operation_without_applying_it():
    operation = {'kind': 'merge', 'source_ids': ['S3.3'], 'target_id': 'S3.2',
                 'reason': '两节重复介绍同一事实'}
    tasks = [task(), task('S3.3')]
    with patch.object(tc.llm, 'query_result', return_value=respond({
            'changes': [], 'outline_operations': [operation]})):
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert not warnings
    assert len(final) == 2
    assert meta['outline_operations'] == [operation]


def test_partial_invalid_keeps_valid_change():
    tasks = [task(), task('S3.3')]
    bad = change('S3.3')
    bad['set']['evidence_uses'] = [dict(decision()['evidence_uses'][0], citation_ids=['C99'])]
    with patch.object(tc.llm, 'query_result', return_value=respond({'changes': [change(), bad]})):
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert meta['status'] == 'partial'
    assert meta['changed_outline_ids'] == ['S3.2'] and meta['rejected_outline_ids'] == ['S3.3']
    assert final[1]['writing_decision'] == tasks[1]['writing_decision'] and warnings


@pytest.mark.parametrize('fault', ['duplicate', 'unknown', 'reason_empty', 'reason_long', 'extra', 'graph', 'not_object'])
def test_invalid_change_is_rejected(fault):
    changes = [change()]
    if fault == 'duplicate': changes.append(change())
    if fault == 'unknown': changes[0]['outline_id'] = 'S99'
    if fault == 'reason_empty': changes[0]['reason'] = ' '
    if fault == 'reason_long': changes[0]['reason'] = '长' * 161
    if fault == 'extra': changes[0]['delete_evidence'] = True
    if fault == 'graph': changes[0]['set']['evidence_uses'] = [dict(decision()['evidence_uses'][0], basis='graph')]
    if fault == 'not_object': changes = ['bad']
    final, changed, rejected, warnings = tc.apply_coordination_changes([task()], changes, {'S3.2'})
    assert final[0]['writing_decision'] == task()['writing_decision']
    assert not changed and warnings
    if fault != 'not_object': assert rejected


def test_unchanged_decision_is_not_effective_change():
    final, changed, rejected, warnings = tc.apply_coordination_changes([task()], [change(set={'section_question': decision()['section_question']})], {'S3.2'})
    assert not changed and not rejected and not warnings
    assert final[0]['decision_review_status'] == 'unchanged'


def test_scope_topics_are_grounded_and_unrelated_topics_discarded():
    tasks = [task(), task('S3.1')]
    updated = change()
    updated['set']['evidence_uses'] = [dict(decision()['evidence_uses'][0], topic='不存在的组织资源')]
    updated['set']['content_scope'] = {
        'full_exposition': ['合作项目成果'],
        'carry_over': [{'topic': '中国移动产业联盟', 'section_id': 'S3.1', 'use': '短句承接'}]}
    final, changed, rejected, warnings = tc.apply_coordination_changes(tasks, [updated], {'S3.1', 'S3.2'})
    assert final[0]['repetition_focus_terms'] == ['合作项目成果', '中国移动产业联盟']
    assert changed == ['S3.2'] and not rejected and not warnings


def test_duplicate_id_all_rejected_while_other_change_applies():
    tasks = [task(), task('S3.3')]
    final, changed, rejected, warnings = tc.apply_coordination_changes(
        tasks, [change(), change('S3.3'), change()], {'S3.2', 'S3.3'})
    assert changed == ['S3.3'] and rejected == ['S3.2'] and warnings
    assert final[0]['writing_decision'] == tasks[0]['writing_decision']
    assert final[1]['decision_review_status'] == 'adjusted'


@pytest.mark.parametrize('response', [LLMQueryResult(content='', finish_reason='stop'),
    LLMQueryResult(content='{}', finish_reason='length'),
    LLMQueryResult(error_message='模型失败'), respond({'changes': 'bad'}),
    respond({'changes': [], 'extra': True}), LLMQueryResult(content='not json')])
def test_failed_model_or_top_level_is_once_and_preserves_tasks(response):
    tasks = [task()]
    with patch.object(tc.llm, 'query_result', return_value=response) as call:
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert call.call_count == 1 and final == tasks
    assert meta['status'] == 'failed' and warnings


def test_model_exception_preserves_tasks_without_retry():
    tasks = [task()]
    with patch.object(tc.llm, 'query_result', side_effect=RuntimeError('失败')) as call:
        final, meta, warnings = tc.coordinate_writing_tasks(tasks)
    assert call.call_count == 1 and final == tasks and warnings
    assert meta['status'] == 'failed'


def test_production_payload_contains_actual_support_and_retrieval_state():
    candidate = task()
    candidate['evidence_pack'] = {'status': 'unavailable', 'requirements': [
        {'id': 'r1', 'requirement': '企业收入比较', 'status': 'unknown',
         'reason': '服务失败，不能判断资料存在', 'support': []}]}
    payload = tc.build_coordination_payload([candidate], user_prompt='比较收入', report_title='企业比较', outline=[])
    assert payload['user_prompt'] == '比较收入'
    assert payload['sections'][0]['evidence']['requirements'][0]['requirement'] == '企业收入比较'
    assert payload['sections'][0]['evidence']['assessment_status'] == 'unavailable'
    assert '原始材料全文' in payload['sections'][0]['evidence']['snippets'][0]['text']


def test_missing_production_scope_is_explicitly_incomplete():
    with patch.object(tc.llm, 'query_result', return_value=respond({'changes': []})):
        _, meta, warnings = tc.coordinate_writing_tasks([task()], user_prompt='比较收入', report_title='企业比较')
    assert meta['status'] == 'incomplete' and warnings


def test_production_coordination_adopts_source_bound_report_facts_in_same_call():
    tasks = [task()]
    tasks[0]['external_rag_retrieval']['evidence_blocks'][0]['text'] = '甲公司产品A已取得证书。'
    def model(**kw):
        payload = json.loads(kw['user_prompt'])
        source = payload['fact_sources'][0]
        return respond({'changes': [], 'outline_operations': [], 'report_scope': {}, 'effective_outline': [],
            'report_facts': [{'subject': '甲公司产品A', 'attribute': '证书', 'value': '已取得',
                'event_time': '', 'published_at': '', 'modality': 'actual', 'applicability': '仅产品A',
                'supports': [{'evidence_id': source['evidence_id'], 'citation_id': 'C14', 'quote': '甲公司产品A已取得证书。'}]}]})
    with patch.object(tc.llm, 'query_result', side_effect=model) as call:
        final, meta, warnings = tc.coordinate_writing_tasks(tasks, user_prompt='研究产品A', report_title='报告', outline=[])
    assert call.call_count == 1
    assert meta['report_facts'][0]['value'] == '已取得'
    assert not warnings

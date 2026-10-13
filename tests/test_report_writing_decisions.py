import copy
from unittest.mock import patch

import pytest

from llm_client import LLMQueryResult
from report_generation import writing_decisions as wd


def task():
    return {'outline_id': 'S3.2', 'title': '资源禀赋',
            'graph_retrieval': {'status': 'skipped', 'graph_context_text': ''},
            'external_rag_retrieval': {'evidence_blocks': [
                {'citation_id': 'C14', 'text': '联盟成立原文'}],
                'rag_context_text': '[C14] 联盟成立原文'}}


def decision():
    return {'section_question': '组织资源如何转化？',
            'evidence_uses': [{'topic': '中国移动具身智能产业联盟', 'basis': 'external',
                               'citation_ids': ['C14'], 'use': '分析组织载体',
                               'support_limit': '成立不证明成效'}],
            'content_scope': {'full_exposition': ['组织载体用途'], 'carry_over': [
                {'topic': '联盟成员', 'section_id': 'S3.1', 'use': '短句承接'}]},
            'judgment_limits': ['不据行业短板评价央企群体能力']}


IDS = {'S3.1', 'S3.2', 'S5.2'}


def test_normalization_deduplicates_and_does_not_mutate_inputs():
    d = decision()
    d['section_question'] = '  组织资源如何转化？  '
    d['evidence_uses'][0]['citation_ids'] = [' C14 ', 'C14']
    d['content_scope']['full_exposition'] *= 2
    original = copy.deepcopy(d)
    normalized = wd.validate_decision(d, task(), IDS)
    assert normalized['section_question'] == '组织资源如何转化？'
    assert normalized['evidence_uses'][0]['citation_ids'] == ['C14']
    assert normalized['content_scope']['full_exposition'] == ['组织载体用途']
    assert wd.validate_decision(normalized, task(), IDS) == normalized
    assert d == original


@pytest.mark.parametrize('fault', [
    'foreign_citation', 'self_scope', 'unknown_scope', 'missing_question',
    'long_use', 'unknown_field', 'empty_external_ids', 'bad_basis',
    'empty_topic', 'wrong_list', 'extra_use_field', 'too_many_uses'])
def test_invalid_decision_rejected(fault):
    d = decision()
    e = d['evidence_uses'][0]
    if fault == 'foreign_citation': e['citation_ids'] = ['C99']
    if fault == 'self_scope': d['content_scope']['carry_over'][0]['section_id'] = 'S3.2'
    if fault == 'unknown_scope': d['content_scope']['carry_over'][0]['section_id'] = 'S9.9'
    if fault == 'missing_question': d.pop('section_question')
    if fault == 'long_use': e['use'] = '长' * 121
    if fault == 'unknown_field': d['writing_system_prompt'] = '旧任务书'
    if fault == 'empty_external_ids': e['citation_ids'] = []
    if fault == 'bad_basis': e['basis'] = 'other'
    if fault == 'empty_topic': e['topic'] = ' '
    if fault == 'wrong_list': d['judgment_limits'] = '边界'
    if fault == 'extra_use_field': e['conclusion'] = '预设结论'
    if fault == 'too_many_uses': d['evidence_uses'] *= 5
    with pytest.raises(ValueError): wd.validate_decision(d, task(), IDS)


def test_graph_requires_success_and_does_not_supply_external_citations():
    d = decision()
    d['evidence_uses'][0].update(basis='graph', citation_ids=[])
    with pytest.raises(ValueError): wd.validate_decision(d, task(), IDS)
    t = task()
    t['graph_retrieval']['status'] = 'success'
    assert wd.validate_decision(d, t, IDS)['evidence_uses'][0]['citation_ids'] == []
    assert '图谱只证明记录的产业关系' in wd.render_decision_prompt(d)


def test_empty_evidence_and_forward_scope_are_valid():
    d = decision()
    d['evidence_uses'] = []
    d['content_scope']['carry_over'][0]['section_id'] = 'S5.2'
    assert wd.validate_decision(d, task(), IDS) == d


def test_complete_decision_over_old_budget_keeps_valid_evidence():
    d = decision()
    d['evidence_uses'] = [dict(d['evidence_uses'][0], topic=str(i) * 60,
                               use='用' * 120, support_limit='界' * 120) for i in range(4)]
    assert len(wd.compact_json(d)) > 1000
    assert wd.validate_decision(d, task(), IDS)['evidence_uses'] == d['evidence_uses']


def test_fallback_has_same_structure_and_long_title_uses_generic_question():
    t = task()
    t['title'] = '长' * 101
    d = wd.fallback_decision(t)
    assert wd.validate_decision(d, t, IDS) == d
    assert d['section_question'] == '回答当前二级标题的问题'
    rendered = wd.render_decision_prompt(d)
    assert '允许缩短' in rendered and '不是事实证据' in rendered
    assert '联盟成立原文' not in rendered


def test_renderer_checks_shape_without_revalidating_citation_eligibility():
    assert '分析组织载体' in wd.render_decision_prompt(decision())
    d = decision()
    d['content_scope'] = []
    with pytest.raises(ValueError): wd.render_decision_prompt(d)
    assert wd.decision_topics(decision()) == ['中国移动具身智能产业联盟', '组织载体用途', '联盟成员']


def test_prior_ledger_contains_arrangements_not_evidence_or_judgments():
    previous = task() | {'outline_id': 'S3.1', 'writing_decision': decision(),
                         'writing_system_prompt': '旧长任务书'}
    ledger = wd.build_prior_ledger([previous])
    for text in ['S3.1', '组织资源如何转化', '组织载体用途', '分析组织载体', '不是事实证据']:
        assert text in ledger
    for text in ['联盟成立原文', '不据行业短板', '成立不证明', '旧长任务书']:
        assert text not in ledger


def test_prior_budget_falls_back_without_call_or_dropping_sections():
    previous = [task() | {'writing_decision': decision()}]
    with patch.object(wd, 'MAX_PRIOR_LEDGER_CHARS', 10), patch.object(wd.llm, 'query_result') as call:
        with pytest.raises(ValueError): wd.build_prior_ledger(previous)
        r = wd.request_decision(task(), '需求', '标题', '大纲', previous, IDS)
    assert not call.called
    assert r['status'] == 'fallback'
    assert r['warnings'][0]['reason'] == 'prior_budget'


def test_single_call_receives_current_evidence_and_prior_arrangements():
    previous = task() | {'outline_id': 'S3.1', 'writing_decision': decision()}
    with patch.object(wd.llm, 'query_result', return_value=LLMQueryResult(
            content=wd.compact_json(decision()), finish_reason='stop')) as call:
        r = wd.request_decision(task(), '需求', '标题', 'S3.1 布局\nS3.2 资源', [previous], IDS)
    assert r == {'decision': decision(), 'status': 'generated', 'warnings': []}
    assert call.call_count == 1
    kwargs = call.call_args.kwargs
    assert kwargs['max_tokens'] == 3000 and kwargs['reasoning_effort'] is None
    assert kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert kwargs['extra_log_info'] == 'report_generation.writing_decisions outline=S3.2'
    assert '[C14] 联盟成立原文' in kwargs['user_prompt']
    assert '此前写作安排，不是事实证据' in kwargs['user_prompt']
    assert '当前图谱状态：skipped' in kwargs['user_prompt']


@pytest.mark.parametrize('response,reason', [
    (LLMQueryResult(content='', finish_reason='stop'), 'empty'),
    (LLMQueryResult(content='{}', finish_reason='length'), 'length'),
    (LLMQueryResult(content='非JSON', finish_reason='stop'), 'invalid_decision'),
    (LLMQueryResult(content='{}', finish_reason='stop'), 'invalid_decision'),
    (LLMQueryResult(error_message='secret-key'), 'model_error'),
    (RuntimeError('secret-key'), 'model_error'),
])
def test_request_failures_use_fallback_once_and_do_not_expose_errors(response, reason):
    options = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
    with patch.object(wd.llm, 'query_result', **options) as call:
        r = wd.request_decision(task(), '需求', '标题', '大纲', [], IDS)
    assert call.call_count == 1
    assert r['status'] == 'fallback' and r['decision'] == wd.fallback_decision(task())
    assert r['warnings'][0]['reason'] == reason
    assert r['warnings'][0]['stage'] == 'writing_prompt_generation'
    assert r['warnings'][0]['outline_id'] == 'S3.2'
    assert 'secret-key' not in wd.compact_json(r)

import json
from unittest.mock import patch

from report_generation.agentic_rag import verification as v
from report_generation.review_agent import review_report_bodies
from llm_client import LLMQueryResult


def section(text='甲公司是2025年最大供应商。[C1]'):
    return {'outline_id': 'S1.1', 'title': '竞争格局', 'status': 'success',
            'body_text': text, 'citation_ids': ['C1'], 'external_evidence_blocks': [
                {'citation_id': 'C1', 'library': 'report', 'material_id': 'a', 'vector_id': 'a:1',
                 'text': '甲公司是供应商。2025年计划扩产，尚未投产。'},
                {'citation_id': 'C1', 'library': 'report', 'material_id': 'a', 'vector_id': 'a:2',
                 'text': '乙公司是2025年最大供应商。'}]}


def check(payload, status='unsupported', quote='甲公司是供应商。'):
    claim = payload['claims'][0]
    return {'claim_id': claim['claim_id'], 'status': status, 'reason': '原文没有甲公司的最大排名依据',
            'supports': [{'evidence_id': payload['evidence'][0]['evidence_id'], 'quote': quote}]}


def test_exact_positions_and_same_source_different_chunks():
    s = section(); payload = v.prepare_section(s)
    c = payload['claims'][0]
    assert s['body_text'][c['start']:c['end']] == c['quote']
    assert len(payload['evidence']) == 2
    result = v.validate_checks(payload, [check(payload)])
    row = result['claims'][0]
    assert row['status'] == 'unsupported'
    assert row['supports'][0]['citation_id'] == 'C1'
    assert row['supports'][0]['vector_id'] == 'a:1'
    assert result['status'] == 'needs_confirmation'


def test_forged_quote_and_missing_check_are_unknown():
    payload = v.prepare_section(section())
    row = check(payload, 'supported', '甲公司是2025年最大供应商。')
    assert v.validate_checks(payload, [row])['claims'][0]['status'] == 'unknown'
    assert v.validate_checks(payload, [])['claims'][0]['status'] == 'unknown'


def test_truncation_does_not_prove_unsupported():
    s = section(); s['external_evidence_blocks'][0]['text'] = '背景。' * 4000
    payload = v.prepare_section(s, evidence_budget=500)
    assert payload['incomplete_evidence']
    row = check(payload, 'unsupported', payload['evidence'][0]['text'][:3])
    assert v.validate_checks(payload, [row])['claims'][0]['status'] == 'unknown'


def test_supported_must_bind_to_claim_citation():
    s = section('甲公司计划在2025年扩产。[C2]')
    payload = v.prepare_section(s)
    row = {'claim_id': payload['claims'][0]['claim_id'], 'status': 'supported', 'reason': '错误绑定',
           'supports': [{'evidence_id': 'S1.1:E1', 'quote': '甲公司是供应商。'}]}
    assert v.validate_checks(payload, [row])['claims'][0]['status'] == 'unknown'


def test_unknown_does_not_authorize_edit_and_overlaps_merge():
    s = section(); payload = v.prepare_section(s)
    result = v.validate_checks(payload, [check(payload)])
    edits, deferred = v.merge_edits({}, [s], {'S1.1': result})
    assert edits['S1.1'][0]['spans'][0]['quote'] == payload['claims'][0]['quote']
    old = {'S1.1': [{'spans': edits['S1.1'][0]['spans'], 'keep_spans': [], 'instruction': '保留', 'reason': '重复', 'preserve_paragraph_ids': []}]}
    merged, deferred = v.merge_edits(old, [s], {'S1.1': result})
    assert len(merged['S1.1']) == 1
    assert not deferred
    assert '事实优先' in merged['S1.1'][0]['instruction']
    assert not v.merge_edits({}, [s], {'S1.1': v.validate_checks(payload, [])})[0]


def test_review_corrects_planned_as_realized_and_rechecks_final_text():
    s = section('甲公司在2025年已经投产。[C1]另有独立分析。')
    def model(**kw):
        p = json.loads(kw['user_prompt'])
        if 'claim_verification' in p:
            payload = p['claim_verification'][0]
            realized = '已经投产' in payload['claims'][0]['quote']
            row = check(payload, 'conflicting' if realized else 'supported', '2025年计划扩产，尚未投产。')
            return LLMQueryResult(content=json.dumps({'issues': [], 'claim_checks': [row], 'information_loss': [{'outline_id': 'S1.1', 'lost': False, 'reason': '独立分析与限定均保留'}]}), finish_reason='stop')
        if 'sections' in p:
            return LLMQueryResult(content='{"issues":[]}', finish_reason='stop')
        assert 'editable_spans' in p
        return LLMQueryResult(content=json.dumps({'outline_id': 'S1.1', 'patches': [
            {'span_index': 0, 'replacement': '甲公司在2025年计划扩产，尚未投产。[C1]'}]}), finish_reason='stop')
    with patch('report_generation.review_agent.llm.query_result', side_effect=model) as call:
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    final = result['body_sections'][0]
    assert '尚未投产' in final['body_text'] and '另有独立分析。' in final['body_text']
    assert final['claim_verification']['status'] == 'completed'
    assert final['claim_verification']['body_text'] == final['body_text']
    assert call.call_count == 4


def test_check_failure_never_leaves_old_passed_verification():
    s = section(); s['claim_verification'] = {'status': 'completed', 'body_text': '旧正文'}
    with patch('report_generation.review_agent.llm.query_result', side_effect=RuntimeError('offline')):
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    assert result['body_sections'][0]['claim_verification']['status'] == 'needs_confirmation'
    assert result['body_sections'][0]['claim_verification']['claims'][0]['status'] == 'unknown'


def test_claim_overflow_is_retained_for_later_batches():
    payload = v.prepare_section(section('\n'.join(f'第{i}家公司计划扩产。[C1]' for i in range(30))))
    assert len(payload['claims']) == 30 and payload['omitted_claim_count'] == 0
    assert v.validate_checks(payload, [])['status'] == 'needs_confirmation'


def test_no_evidence_and_model_failure_do_not_prove_unsupported():
    s = section(); s['external_evidence_blocks'] = []
    payload = v.prepare_section(s)
    row = {'claim_id': payload['claims'][0]['claim_id'], 'status': 'unsupported', 'reason': '没有原文', 'supports': []}
    assert v.validate_checks(payload, [row])['claims'][0]['status'] == 'unknown'


def test_rewrite_returns_fresh_verification():
    from report_generation.rewrite_agent import rewrite_body_section
    s = section(); s['claim_verification'] = {'status': 'completed', 'body_text': '旧正文'}
    checked = {'status': 'needs_confirmation', 'body_text': '重写后2025年动态。[C1]', 'claims': []}
    with patch('report_generation.rewrite_agent.llm.query', return_value=checked['body_text']), \
         patch('report_generation.rewrite_agent.review_report_bodies', return_value={
            'body_sections': [{**s, 'body_text': checked['body_text'], 'claim_verification': checked}],
            'review': {}, 'adjustment_notes': [], 'warnings': []}):
        result = rewrite_body_section('补充动态', '报告', s, {}, s['external_evidence_blocks'], industry='embodied')
    assert result['claim_verification'] == checked


def test_failed_recheck_or_information_loss_restores_original():
    for recheck_answer in ({}, {'claim_checks': [], 'information_loss': [{'outline_id': 'S1.1', 'lost': True, 'reason': '误删独有事实'}]}):
        s = section('甲公司在2025年已经投产。[C1]另有独立分析。')
        payload = v.prepare_section(s)
        answers = [LLMQueryResult(content=json.dumps({'issues': [], 'claim_checks': [
                        check(payload, 'conflicting', '2025年计划扩产，尚未投产。')]}), finish_reason='stop'),
                   LLMQueryResult(content='{"issues":[]}', finish_reason='stop'),
                   LLMQueryResult(content=json.dumps({'outline_id': 'S1.1', 'patches': [
                        {'span_index': 0, 'replacement': '甲公司计划扩产。[C1]'}]}), finish_reason='stop'),
                   LLMQueryResult(content=json.dumps(recheck_answer), finish_reason='stop')]
        with patch('report_generation.review_agent.llm.query_result', side_effect=answers) as call:
            result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
        assert result['body_sections'][0]['body_text'] == s['body_text']
        assert result['body_sections'][0]['claim_verification']['correction_status'] == 'reverted'
        assert result['review']['status'] == 'partial'
        assert call.call_count == 5


def test_local_review_does_not_recheck_other_sections():
    first, second = section(), section('乙公司2025年产品发布。[C1]')
    second['outline_id'] = 'S2.1'
    second['claim_verification'] = {'status': 'completed', 'body_text': second['body_text']}
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
            content='{"issues":[],"claim_checks":[]}', finish_reason='stop')) as call:
        result = review_report_bodies(body_sections=[first, second], writing_tasks=[], report_title='报告', user_prompt='产业', references=[], target_outline_id='S1.1')
    payloads = [json.loads(c.kwargs['user_prompt']) for c in call.call_args_list]
    claim_payloads = [p for p in payloads if 'claim_verification' in p]
    assert len(claim_payloads) == 2
    assert len(claim_payloads[0]['claim_verification']) == 1
    assert result['body_sections'][1] == second


def test_missing_current_claim_evidence_stays_unknown_even_when_other_claim_has_evidence():
    s = section('甲公司2025年已经投产。[C1]乙公司2025年营收10亿元。[C2]')
    payload = v.prepare_section(s)
    claim = payload['claims'][1]
    row = {'claim_id': claim['claim_id'], 'status': 'unsupported', 'reason': '没有乙公司证据', 'supports': []}
    result = v.validate_checks(payload, [row])
    assert result['claims'][1]['status'] == 'unknown'
    assert not v.merge_edits({}, [s], {'S1.1': result})[0]


def test_semicolon_product_list_uses_sentence_end_citations():
    s = section('产品层面，甲公司供应谐波减速器；乙公司供应行星减速器[C1]。')
    payload = v.prepare_section(s)
    assert len(payload['claims']) == 1
    assert payload['claims'][0]['citation_ids'] == ['C1']


def test_eight_sections_share_budget_without_skipping_existing_review():
    sections = []
    for i in range(8):
        s = section('2025年甲公司计划扩产。[C1]' * 10)
        s['outline_id'] = f'S{i+1}.1'
        s['external_evidence_blocks'] = [{**s['external_evidence_blocks'][0], 'text': '2025年计划扩产。' * 500} for _ in range(8)]
        sections.append(s)
    with patch('report_generation.review_agent.llm.query_result', return_value=LLMQueryResult(
            content='{"issues":[],"claim_checks":[]}', finish_reason='stop')) as call:
        result = review_report_bodies(body_sections=sections, writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    assert result['review']['status'] != 'skipped_budget'
    payloads = [json.loads(c.kwargs['user_prompt']) for c in call.call_args_list]
    claim_payloads = [p for p in payloads if 'claim_verification' in p]
    assert any('sections' in p for p in payloads)
    assert len({c['claim_id'] for p in claim_payloads for s in p['claim_verification'] for c in s['claims']}) == 80
    assert sum(len(s['claims']) for p in claim_payloads for s in p['claim_verification']) <= 160
    assert all(sum(len(e['text']) for s in p['claim_verification'] for e in s['evidence']) <= 24000 for p in claim_payloads)


def test_cited_company_status_is_included_without_number_keyword():
    payload = v.prepare_section(section('科达利谐波减速器处于产能爬坡和客户验证阶段[C1]。'))
    assert len(payload['claims']) == 1


def test_unchanged_unknown_claim_does_not_revert_valid_correction():
    s = section('甲公司是2025年最大供应商。[C1]行业排名需要进一步研究。')
    before = v.prepare_section(s)
    def model(**kw):
        p = json.loads(kw['user_prompt'])
        if 'editable_spans' in p:
            return LLMQueryResult(content=json.dumps({'outline_id': 'S1.1', 'patches': [
                {'span_index': 0, 'replacement': '甲公司是供应商之一。[C1]'}]}), finish_reason='stop')
        if 'sections' in p:
            return LLMQueryResult(content='{"issues":[]}', finish_reason='stop')
        current = p['claim_verification'][0]
        first = check(current, 'supported' if 'original_sections' in p else 'unsupported')
        if '行业排名' in current['claims'][0]['quote']:
            first.update(status='unknown', reason='研究边界含义待确认', supports=[])
        return LLMQueryResult(content=json.dumps({'issues': [], 'claim_checks': [first],
            'information_loss': [{'outline_id': 'S1.1', 'lost': False, 'reason': '原分析保留'}]}), finish_reason='stop')
    with patch('report_generation.review_agent.llm.query_result', side_effect=model):
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    assert '最大供应商' not in result['body_sections'][0]['body_text']
    assert result['body_sections'][0]['claim_verification']['status'] == 'needs_confirmation'


def test_indented_body_claim_matches_review_paragraph_without_losing_offsets():
    s = section('  甲公司2025年计划扩产。[C1]  ')
    p = v.prepare_section(s)
    c = p['claims'][0]
    assert c['quote'] == s['body_text'].strip()
    assert s['body_text'][c['start']:c['end']] == c['quote']


def test_partial_entity_list_cannot_pass_with_quotes_covering_only_one_company():
    s = section('供应商包括甲公司、乙公司。[C1]')
    payload = v.prepare_section(s)
    row = check(payload, 'supported', '甲公司是供应商。')
    result = v.validate_checks(payload, [row])
    assert result['claims'][0]['status'] == 'unknown'
    assert not v.merge_edits({}, [s], {'S1.1': result})[0]
    assert '乙公司' in result['claims'][0]['reason']


def test_list_modifiers_are_abstentions_not_automatic_edit_authorizations():
    s = section('RV路线有双环传动、其分拆的环动科技及中大力德等[C1]。')
    s['external_evidence_blocks'][0]['text'] = '双环传动分拆环动科技上市。中大力德覆盖RV减速器。'
    p = v.prepare_section(s)
    result = v.validate_checks(p, [check(p, 'supported', s['external_evidence_blocks'][0]['text'])])
    assert result['claims'][0]['status'] == 'unknown'
    assert not v.merge_edits({}, [s], {'S1.1': result})[0]


def test_non_list_prose_with_another_source_is_not_name_matching():
    s = section('另有资料称其订单充足、产能利用率高位运行[C1]。')
    s['external_evidence_blocks'][0]['text'] = '该公司订单充足，产能利用率高位运行。'
    p = v.prepare_section(s)
    result = v.validate_checks(p, [check(p, 'supported', s['external_evidence_blocks'][0]['text'])])
    assert result['claims'][0]['status'] == 'supported'


def test_pure_method_boundary_and_conditional_analysis_can_complete_as_not_factual():
    texts = ['本节以公开业务材料选样。', '未检索到不代表没有业务。', '若供应能力达到要求，则可考虑合作。']
    for text in texts:
        payload = v.prepare_section(section(text))
        assert payload['claims']
        row = {'claim_id': payload['claims'][0]['claim_id'], 'status': 'not_factual',
               'reason': '纯研究方法、检索边界或条件分析，不断言外部事实', 'supports': []}
        checked = v.validate_checks(payload, [row])
        assert checked['status'] == 'completed'
        assert checked['claims'][0]['status'] == 'not_factual'
        assert v.merge_edits({}, [section(text)], {'S1.1': checked}) == ({}, [])


def test_mixed_enterprise_numeric_fact_and_analysis_still_requires_factual_evidence():
    payload = v.prepare_section(section('甲公司2025年营收10亿元，因此可能具备扩产条件。[C1]'))
    checked = v.validate_checks(payload, [check(payload, 'partial', '甲公司是供应商。')])
    assert checked['status'] == 'needs_confirmation'
    assert checked['claims'][0]['status'] == 'partial'
    assert '事实部分' in v.PROMPT
    assert '分析不要求逐字出现在证据中' in v.PROMPT
    assert '不能用not_factual' in v.PROMPT
    assert '包含“可能”' in v.PROMPT


def test_reason_text_cannot_turn_unknown_into_not_factual():
    payload = v.prepare_section(section('甲公司2025年营收10亿元。[C1]'))
    row = check(payload, 'unknown')
    row['reason'] = '属于分析推断，非外部事实，不需要外部引用'
    assert v.validate_checks(payload, [row])['claims'][0]['status'] == 'unknown'


def test_evidence_quote_whitespace_recovery_binds_exact_source_substring():
    s = section('甲公司2025年计划扩产。[C1]')
    source = '说明：甲公司 2025 年\n计划扩产，尚未投产。另有业务。'
    s['external_evidence_blocks'][0]['text'] = source
    payload = v.prepare_section(s)
    row = check(payload, 'supported', '甲公司2025年计划扩产，尚未投产。')
    checked = v.validate_checks(payload, [row])
    assert checked['status'] == 'completed'
    support = checked['claims'][0]['supports'][0]
    assert support['quote'] == '甲公司 2025 年\n计划扩产，尚未投产。'
    assert support['quote'] in source
    assert support['vector_id'] == 'a:1'


def test_evidence_quote_recovery_does_not_rewrite_punctuation_or_cross_fragments():
    s = section('甲公司2025年计划扩产。[C1]')
    s['external_evidence_blocks'][0]['text'] = '甲公司 2025 年计划扩产，'
    s['external_evidence_blocks'][1]['text'] = '尚未投产。'
    payload = v.prepare_section(s)
    for quote in ['甲公司2025年计划扩产,', '甲公司2025年计划扩产，尚未投产。']:
        assert v.validate_checks(payload, [check(payload, 'supported', quote)])['claims'][0]['status'] == 'unknown'


def test_factual_recheck_accepts_new_pure_method_text_as_not_factual():
    s = section('甲公司2025年已经投产。[C1]另有独有分析。')
    def model(**kw):
        payload = json.loads(kw['user_prompt'])
        if 'sections' in payload:
            return LLMQueryResult(content='{"issues":[]}', finish_reason='stop')
        if 'editable_spans' in payload:
            answer = {'outline_id': 'S1.1', 'patches': [{'span_index': 0,
                'replacement': '甲公司2025年计划扩产，尚未投产。[C1]本节以公开业务材料选样。'}]}
        else:
            prepared = payload['claim_verification'][0]
            recheck = 'original_sections' in payload
            rows = [check(prepared, 'supported' if recheck else 'conflicting', '2025年计划扩产，尚未投产。')]
            if recheck:
                rows.extend({'claim_id': c['claim_id'], 'status': 'not_factual', 'reason': '研究方法', 'supports': []}
                            for c in prepared['claims'][1:])
            answer = {'claim_checks': rows, 'information_loss': [{'outline_id': 'S1.1', 'lost': False,
                       'reason': '独有分析、时间和计划限定保留'}]}
        return LLMQueryResult(content=json.dumps(answer, ensure_ascii=False), finish_reason='stop')
    with patch('report_generation.review_agent.llm.query_result', side_effect=model):
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    final = result['body_sections'][0]
    assert '尚未投产' in final['body_text'] and '独有分析。' in final['body_text']
    assert final['claim_verification']['status'] == 'completed'
    assert {c['status'] for c in final['claim_verification']['claims']} == {'supported', 'not_factual'}


def test_paragraph_citation_supports_unmarked_intro_without_borrowing_other_paragraph():
    s = section('甲公司是运营企业。其运营机队。[C1]\n\n乙公司是制造企业。')
    s['external_evidence_blocks'][0]['text'] = '甲公司运营机队。'
    p = v.prepare_section(s)
    intro = p['claims'][0]
    assert intro['citation_ids'] == []
    assert intro['context_citation_ids'] == ['C1']
    row = {'claim_id': intro['claim_id'], 'status': 'supported', 'reason': '本段引用支持角色判断',
           'supports': [{'evidence_id': p['evidence'][0]['evidence_id'], 'quote': '甲公司运营机队。'}]}
    assert v.validate_checks(p, [row])['claims'][0]['status'] == 'supported'
    assert p['claims'][-1]['context_citation_ids'] == []


def test_graph_participation_is_verifiable_evidence_with_limited_scope():
    s = section('图谱记录显示甲公司参与整机制造环节。')
    s['graph_evidence_blocks'] = [{'segment': {'id': 11, 'name': '整机制造'},
       'chain_path': '上游 > 整机制造', 'downward_entities': [
           {'id': 32, 'name': '甲公司', 'edge_type': '参与环节'}]}]
    p = v.prepare_section(s)
    graph = next(e for e in p['evidence'] if e.get('evidence_type') == 'graph')
    row = {'claim_id': p['claims'][0]['claim_id'], 'status': 'supported', 'reason': '仅核对记录关系',
           'supports': [{'evidence_id': graph['evidence_id'], 'quote': '甲公司'}]}
    assert v.validate_checks(p, [row])['claims'][0]['status'] == 'supported'
    assert '不证明' in graph['evidence_scope']


def test_explicit_citation_cannot_be_approved_as_pure_method():
    p = v.prepare_section(section())
    row = {'claim_id': p['claims'][0]['claim_id'], 'status': 'not_factual',
           'reason': '误判为分析', 'supports': []}
    assert v.validate_checks(p, [row])['claims'][0]['status'] == 'unknown'


def test_graph_review_does_not_spend_budget_on_unused_node_metadata():
    s = section('图谱记录显示甲公司参与整机制造环节。')
    s['graph_evidence_blocks'] = [{'segment': {'id': 11, 'name': '整机制造', 'evidence_refs': ['来源' * 9000]},
        'chain_path': '上游 > 整机制造', 'downward_entities': [
        {'id': 32, 'name': '甲公司', 'edge_type': '参与环节', 'evidence_refs': ['来源' * 9000]}]}]
    p = v.prepare_section(s)
    assert any(e.get('evidence_type') == 'graph' for e in p['evidence'])


def test_graph_review_keeps_late_named_entity_within_real_evidence_budget():
    s = section('图谱记录显示末尾公司参与整机制造环节。')
    entities = [{'id': n, 'name': f'无关主体{n}', 'edge_type': '参与环节'} for n in range(300)]
    entities.append({'id': 301, 'name': '末尾公司', 'edge_type': '参与环节'})
    s['graph_evidence_blocks'] = [{'segment': {'id': 11, 'name': '整机制造'}, 'downward_entities': entities}]
    p = v.prepare_section(s, evidence_budget=1000)
    graph = next(e for e in p['evidence'] if e.get('evidence_type') == 'graph')
    assert '末尾公司' in graph['text']
    assert '无关主体299' not in graph['text']
    assert json.loads(graph['text'])['recorded_entity_count'] == 301


def test_list_final_conjunction_uses_individually_quoted_names():
    s = section('供应商包括甲公司、乙公司和丙公司[C1]。')
    s['external_evidence_blocks'][0]['text'] = '供应商：甲公司、乙公司、丙公司。'
    p = v.prepare_section(s)
    assert v.validate_checks(p, [check(p, 'supported', s['external_evidence_blocks'][0]['text'])])['claims'][0]['status'] == 'supported'


def test_uncited_section_synthesis_can_bind_existing_section_fact_without_borrowing_explicit_wrong_citation():
    s = section('甲公司2025年计划扩产[C1]。\n\n据此，甲公司的扩产仍为计划。')
    p = v.prepare_section(s)
    claim = p['claims'][-1]
    row = {'claim_id': claim['claim_id'], 'status': 'supported', 'reason': '综合本节已引事实，不新增状态',
           'supports': [{'evidence_id': p['evidence'][0]['evidence_id'], 'quote': '2025年计划扩产，尚未投产。'}]}
    assert v.validate_checks(p, [row])['claims'][-1]['status'] == 'supported'


def test_unrelated_truncated_citation_does_not_downgrade_complete_claim():
    s = section()
    s['external_evidence_blocks'].append({'citation_id': 'C2', 'text': '乙公司背景。' * 2000})
    s['body_text'] += '\n乙公司背景。[C2]'
    payload = v.prepare_section(s)
    assert payload['incomplete_evidence']
    result = v.validate_checks(payload, [check(payload)])
    assert result['claims'][0]['status'] == 'unsupported'


def test_factual_error_in_protected_keep_span_can_be_corrected():
    s = section(); payload = v.prepare_section(s)
    result = v.validate_checks(payload, [check(payload)])
    span = {'paragraph_id': payload['claims'][0]['paragraph_id'], 'quote': payload['claims'][0]['quote']}
    old = {'S2.1': [{'spans': [{'paragraph_id': 'S2.1:P1', 'quote': '重复事实。'}],
        'keep_spans': [span], 'instruction': '删除重复', 'reason': '重复', 'preserve_paragraph_ids': []}]}
    merged, deferred = v.merge_edits(old, [s], {'S1.1': result})
    assert not deferred
    assert merged['S1.1'][0]['spans'] == [{**span, 'start': 0, 'end': len(span['quote'])}]
    assert not merged['S2.1'][0]['keep_spans']


def test_graph_candidates_are_not_attached_to_unrelated_numeric_analysis():
    s = section('甲公司2025年收入10亿元。[C1]\n2025年收入不能与订单金额直接比较。')
    s['graph_evidence_blocks'] = [{'segment': {'id': 'g', 'name': '航空器'},
        'downward_entities': [{'id': 'a', 'name': '乙公司', 'edge_type': '参与'}]}]
    payload = v.prepare_section(s)
    assert 'G1' not in payload['claims'][-1]['context_citation_ids']


def test_failed_semantic_candidate_gets_one_targeted_repair_before_rollback():
    s = section('甲公司2025年已经投产。[C1]独有分析。')
    rechecks, repairs = [], []
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            prepared = p['claim_verification'][0]
            if 'original_sections' in p:
                rechecks.append(True)
            final = '计划扩产，尚未投产' in prepared['body_text'] if 'body_text' in prepared else False
            row = check(prepared, 'supported' if final else 'conflicting', '2025年计划扩产，尚未投产。')
            return {'claim_checks': [row], 'information_loss': [{'outline_id': 'S1.1', 'lost': False, 'reason': '分析保留'}]}
        if 'editable_spans' in p:
            if p.get('repair_failure_reasons'):
                repairs.append(p)
                replacement = '甲公司2025年计划扩产，尚未投产。[C1]'
            else:
                replacement = '甲公司2025年已量产。[C1]'
            return {'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': replacement}]}
        return {'issues': []}
    with patch('report_generation.review_agent._query', side_effect=query):
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    assert len(repairs) == 1
    assert len(rechecks) == 2
    assert result['body_sections'][0]['body_text'] == '甲公司2025年计划扩产，尚未投产。[C1]独有分析。'
    assert result['body_sections'][0]['claim_verification']['status'] == 'completed'


def test_invalid_patch_is_retried_once_with_exact_rejection_reason():
    s = section('甲公司2025年已经投产。[C1]独有分析。')
    patch_calls = []
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            prepared = p['claim_verification'][0]
            row = check(prepared, 'supported' if 'original_sections' in p else 'conflicting', '2025年计划扩产，尚未投产。')
            return {'claim_checks': [row], 'information_loss': [{'outline_id': 'S1.1', 'lost': False, 'reason': '分析保留'}]}
        if 'editable_spans' in p:
            patch_calls.append(p)
            if len(patch_calls) == 1:
                replacement = '甲公司计划扩产。[C999]'
            else:
                assert p['patch_failure_reason'] == 'invalid_citation'
                replacement = '甲公司2025年计划扩产，尚未投产。[C1]'
            return {'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': replacement}]}
        return {'issues': []}
    with patch('report_generation.review_agent._query', side_effect=query):
        result = review_report_bodies(body_sections=[s], writing_tasks=[], report_title='报告', user_prompt='产业', references=[])
    assert len(patch_calls) == 2
    assert '尚未投产' in result['body_sections'][0]['body_text']
    assert result['review']['changed_outline_ids'] == ['S1.1']


def test_upward_graph_path_can_support_its_exact_relationship_claim():
    s = section('图谱记录材料生产业务属于上游环节。')
    s['graph_evidence_blocks'] = [{'segment': {'name': '动力电池'}, 'upward_path': [
        {'source_name': '材料生产业务', 'type': '属于', 'target_name': '上游环节'}]}]
    payload = v.prepare_section(s)
    graph = next(e for e in payload['evidence'] if e['citation_id'] == 'G1')
    row = {'claim_id': payload['claims'][0]['claim_id'], 'status': 'supported', 'reason': '图谱仅证明记录关系',
        'supports': [{'evidence_id': graph['evidence_id'], 'quote': graph['text']}]}
    assert v.validate_checks(payload, [row])['claims'][0]['status'] == 'supported'


def test_collaboration_list_does_not_treat_leading_preposition_as_part_of_company_name():
    s = section('公司包括与峰飞航空、奥科赛航空等达成战略合作。[C1]')
    s['external_evidence_blocks'] = [{'citation_id': 'C1', 'text': '公司与上海峰飞航空、奥科赛航空等行业头部企业达成战略合作。'}]
    payload = v.prepare_section(s)
    checked = v.validate_checks(payload, [check(payload, 'supported', s['external_evidence_blocks'][0]['text'])])
    assert checked['claims'][0]['status'] == 'supported'


def test_collaboration_list_still_requires_each_company_in_verified_quotes():
    s = section('公司包括与峰飞航空、奥科赛航空等达成战略合作。[C1]')
    s['external_evidence_blocks'] = [{'citation_id': 'C1', 'text': '公司与上海峰飞航空达成战略合作。'}]
    payload = v.prepare_section(s)
    checked = v.validate_checks(payload, [check(payload, 'supported', s['external_evidence_blocks'][0]['text'])])
    assert checked['claims'][0]['status'] == 'unknown'
    assert '奥科赛航空' in checked['claims'][0]['reason']


def test_company_name_starting_with_yu_is_preserved_in_plain_list():
    s = section('供应商包括与光科技、乙公司等。[C1]')
    s['external_evidence_blocks'] = [{'citation_id': 'C1', 'text': '供应商包括光科技、乙公司。'}]
    payload = v.prepare_section(s)
    checked = v.validate_checks(payload, [check(payload, 'supported', s['external_evidence_blocks'][0]['text'])])
    assert checked['claims'][0]['status'] == 'unknown'
    assert '与光科技' in checked['claims'][0]['reason']


def test_business_actions_are_not_misparsed_as_an_entity_list():
    s = section('公司布局包括主办产业研讨会、推出出行服务平台、开启无人机业务。[C1]')
    s['external_evidence_blocks'] = [{'citation_id': 'C1', 'text': '公司主办产业研讨会，推出出行服务平台，并开启了无人机业务。'}]
    p = v.prepare_section(s)
    assert v.validate_checks(p,[check(p,'supported',s['external_evidence_blocks'][0]['text'])])['claims'][0]['status'] == 'supported'


def test_duplicate_query_rankings_do_not_consume_claim_source_budget_twice():
    s=section('甲公司收入10亿元。[C1]乙公司交付12台。[C2]')
    first={'citation_id':'C1','library':'news','material_id':'a','vector_id':'a:1','text':'甲公司收入10亿元。'}
    last={'citation_id':'C2','library':'news','material_id':'b','vector_id':'b:1','text':'乙公司交付12台。'}
    s['external_evidence_blocks']=[first,{**first,'distance':0.8},last]
    payload=v.prepare_section(s,evidence_budget=len(first['text'])+len(last['text']))
    assert [e['citation_id'] for e in payload['evidence']]==['C1','C2']
    assert payload['unavailable_citation_ids']==[]
    assert not payload['incomplete_evidence']


def test_approval_eligibility_and_commercialization_assertions_are_checked():
    text='这一通知规定征集资格。[C1]这意味着食品侧的门槛是安全证明与审批资格的前置筛选，未通过者不进入商业化序列。'
    s=section(text)
    s['external_evidence_blocks']=[{'citation_id':'C1','text':'征集对象已进入小批量试产或规模化生产，达到或即将达到三新食品申报条件但尚未获批。'}]
    p=v.prepare_section(s)
    assert any('未通过者不进入商业化序列' in c['quote'] for c in p['claims'])

import json
from types import SimpleNamespace
import pytest

from report_generation.agentic_rag.assessment import assess_evidence, reconcile_allocation, bind_citations, render_evidence_pack


def plan():
    return {'outline_id':'S1.1','industry':'embodied','input':{'content_requirements':['企业产品','市场排名'],
             'chapter_title':'竞争格局','time_requirement':'2025年','user_prompt':'比较企业','use_external_rag':True},
            'sub_queries':[{'id':'q1','question':'企业产品和市场排名','evidence_requirements':['企业产品','市场排名']}]}


def blocks():
    return [{'library':'news','material_id':'m1','vector_id':'v1','text':'甲企业生产减速器。', 'industry':'embodied',
             'title':'产品消息','publish_date':'2025-05-01','source_address':'https://example.org/a'},
            {'library':'news','material_id':'m2','vector_id':'v2','text':'甲企业2025年市场份额10%。','industry':'embodied'}]


def model(rows):
    return lambda **kwargs: SimpleNamespace(content=json.dumps({'requirements':rows},ensure_ascii=False), finish_reason='stop',error_message='')


def response(id,status='supported',evidence='e1',quote='甲企业生产减速器。',**extra):
    return dict(id=id,status=status,support=[{'evidence_id':evidence,'quote':quote}] if quote else [],reason='实际片段依据',**extra)


def test_many_mentions_do_not_automatically_support_ranking():
    pack=assess_evidence(plan(),blocks(),retrieval_status='success',query_model=model([
        response('r1'),response('r2','insufficient',quote='',follow_up_query='甲企业2025年市场份额排名',strategy='hybrid')]))
    assert [r['status'] for r in pack['requirements']]==['supported','insufficient']
    assert pack['requirements'][0]['support'][0]['evidence_key']['vector_id']=='v1'
    assert any('市场排名' in c for c in pack['writing_constraints'])


def test_supported_claim_requires_real_verbatim_quote():
    pack=assess_evidence(plan(),blocks(),retrieval_status='success',query_model=model([
        response('r1',quote='甲企业全球第一'),response('r2',evidence='invented')]))
    assert all(r['status']=='unknown' for r in pack['requirements'])
    assert pack['warnings']


def test_conflict_keeps_both_quotes_and_not_a_single_chosen_number():
    b=blocks();b[1]['text']='甲企业份额20%。';b[0]['text']='甲企业份额10%。'
    rows=[response('r1','unknown',quote=''),dict(id='r2',status='conflicting',reason='同年同口径数字不同',support=[
        {'evidence_id':'e1','quote':b[0]['text']},{'evidence_id':'e2','quote':b[1]['text']}])]
    pack=assess_evidence(plan(),b,retrieval_status='success',query_model=model(rows))
    assert pack['requirements'][1]['status']=='conflicting'
    assert len(pack['requirements'][1]['support'])==2
    assert any('差异' in c for c in pack['writing_constraints'])


def test_graph_only_or_missing_document_is_never_fact_support():
    p=plan();p['input']['use_external_rag']=False
    pack=assess_evidence(p,[],retrieval_status='skipped',query_model=lambda **kw:pytest.fail('no model'))
    assert pack['status']=='skipped'
    assert all(r['status']=='unknown' for r in pack['requirements'])


def test_unavailable_store_differs_from_empty_success_and_does_not_call_model():
    fail=assess_evidence(plan(),[],retrieval_status='error',query_model=lambda **kw:pytest.fail('no model'))
    empty=assess_evidence(plan(),[],retrieval_status='success',query_model=lambda **kw:pytest.fail('no model'))
    assert fail['status']=='unavailable'
    assert empty['status']=='assessed'
    assert all(r['status']=='insufficient' for r in empty['requirements'])


def test_evaluator_failure_is_unknown_and_does_not_invent_followups():
    def broken(**kw):raise TimeoutError('assessment timeout')
    pack=assess_evidence(plan(),blocks(),retrieval_status='success',query_model=broken)
    assert pack['status']=='failed'
    assert all(r['status']=='unknown' and not r.get('follow_up_query') for r in pack['requirements'])


def test_truncated_input_is_marked_and_missing_support_stays_unknown():
    b=blocks();b[0]['text']='甲企业生产减速器。'+'说明'*2000
    seen=[]
    def ask(**kw):
        seen.append(json.loads(kw['user_prompt']))
        return model([response('r1'),response('r2','insufficient',quote='')])()
    pack=assess_evidence(plan(),b,retrieval_status='success',query_model=ask)
    assert seen[0]['evidence'][0]['truncated'] is True
    assert pack['requirements'][1]['status']=='unknown'


def test_allocation_restores_required_chunk_without_exceeding_capacity_and_binds_citation():
    b=blocks()
    pack=assess_evidence(plan(),b,retrieval_status='success',query_model=model([
        response('r1'),response('r2','insufficient',quote='')]))
    selected,updated=reconcile_allocation(pack,[b[1]],b,1)
    assert len(selected)==1 and selected[0]['vector_id']=='v1'
    selected[0]['citation_id']='C7'
    bound=bind_citations(updated,selected)
    assert bound['requirements'][0]['support'][0]['citation_id']=='C7'
    assert '[C7]' in render_evidence_pack(bound)
    assert '市场排名' in render_evidence_pack(bound)


def test_insufficient_capacity_downgrades_requirement_and_retains_gap():
    b=blocks()
    rows=[dict(id='r1',status='supported',reason='需要两段联合证明',support=[
        {'evidence_id':'e1','quote':b[0]['text']},{'evidence_id':'e2','quote':b[1]['text']}]),response('r2','unknown',quote='')]
    pack=assess_evidence(plan(),b,retrieval_status='success',query_model=model(rows))
    selected,updated=reconcile_allocation(pack,[b[0]],b,1)
    assert len(selected)==1
    assert updated['requirements'][0]['status']=='unknown'
    assert '容量' in updated['requirements'][0]['reason']


def test_allocation_preserves_valid_partial_facts_even_if_overall_requirement_insufficient():
    b=blocks()
    pack=assess_evidence(plan(),b,retrieval_status='success',query_model=model([
        response('r1','insufficient'),response('r2','unknown',quote='')]))
    assert pack['requirements'][0]['status']=='insufficient'
    selected,updated=reconcile_allocation(pack,[b[1]],b,1)
    assert selected[0]['vector_id']=='v1'
    assert updated['requirements'][0]['status']=='insufficient'
    selected[0]['citation_id']='C8'
    bound=bind_citations(updated,selected)
    assert bound['requirements'][0]['support'][0]['citation_id']=='C8'
    assert bound['requirements'][0]['status']=='insufficient'


def test_partial_support_does_not_displace_fully_supported_requirement():
    b=blocks()
    pack=assess_evidence(plan(),b,retrieval_status='success',query_model=model([
        response('r1','insufficient'),response('r2','supported',evidence='e2',quote=b[1]['text'])]))
    selected,updated=reconcile_allocation(pack,[b[0]],b,1)
    assert selected[0]['vector_id']=='v2'
    assert updated['requirements'][1]['status']=='supported'

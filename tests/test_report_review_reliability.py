import copy
import pytest
from unittest.mock import patch

from report_generation import body_agent, review_agent, delivery
from report_generation.agentic_rag.verification import prepare_section


def task(oid, blocks):
    return {'outline_id': oid, 'title': '企业业务', 'writing_system_prompt': '写正文',
            'external_rag_retrieval': {'evidence_blocks': blocks}}


def test_report_source_is_bound_before_citation_cleanup():
    tasks = [task('S1.1', [{'citation_id': 'C5', 'vector_id': 'doc:1', 'text': '东进航科从事空管业务。'}]),
             task('S1.2', [{'citation_id': 'C1', 'text': '行业概况。'}])]
    before = copy.deepcopy(tasks)
    def review(**kw):
        return {'body_sections': kw['body_sections'], 'warnings': [], 'review': {'status': 'completed'}, 'adjustment_notes': []}
    with patch.object(body_agent, '_generate_body_text_with_retry', return_value=('东进航科从事空管业务。[C5]无来源。[C999]', [], '')), patch.object(body_agent, 'review_report_bodies', side_effect=review):
        result = body_agent.generate_report_bodies('研究业务', '比较', tasks)
        events = list(body_agent.stream_report_bodies('研究业务', '比较', tasks))
    for sections in [result['body_sections'], events[-1]['body_sections']]:
        section = sections[1]
        assert '[C5]' in section['body_text']
        assert '[C999]' not in section['body_text']
        assert any(b['text'] == '东进航科从事空管业务。' for b in section['external_evidence_blocks'])
        assert any(e['citation_id'] == 'C5' for e in prepare_section(section)['evidence'])
    assert tasks == before


def test_restore_only_paragraph_with_new_unresolved_claim():
    original = {'body_text': '公司业务介绍。重复介绍。\n\n公司计划2027年投产。[C1]'}
    current = {'outline_id': 'S1.1', 'body_text': '公司业务介绍。\n\n公司已于2027年投产。[C1]'}
    claim = {**prepare_section(current)['claims'][-1], 'status': 'conflicting'}
    restored = review_agent._restore_unverified_paragraphs(original, current, {'claims': [claim]})
    assert restored == '公司业务介绍。\n\n公司计划2027年投产。[C1]'


def test_existing_unresolved_claim_does_not_undo_other_edits():
    original = {'body_text': '公司业务介绍。重复介绍。\n\n公司计划2027年投产。[C1]'}
    current = {'outline_id': 'S1.1', 'body_text': '公司业务介绍。\n\n公司计划2027年投产。[C1]'}
    claim = {**prepare_section(current)['claims'][-1], 'status': 'unknown'}
    assert review_agent._restore_unverified_paragraphs(original, current, {'claims': [claim]}) is None


def test_changed_paragraph_structure_falls_back_to_full_review():
    original = {'body_text': '公司背景。\n\n公司计划投产。'}
    current = {'outline_id': 'S1.1', 'body_text': '公司已投产。'}
    claim = {**prepare_section(current)['claims'][0], 'status': 'conflicting'}
    assert review_agent._restore_unverified_paragraphs(original, current, {'claims': [claim]}) is None


def test_delivery_explains_pending_facts_and_failed_repairs():
    state = delivery.delivery_state([{'status':'success','body_text':'正文'}],
        {'status':'partial','failed_outline_ids':['S1.1'],
         'claim_verification':{'pending_outline_ids':['S1.1']},
         'verification':{'status':'partial','unresolved_issue_indexes':[0]}}, {'status':'completed'})
    assert state['delivery_status'] == 'incomplete'
    reasons = '；'.join(state['delivery_reasons'])
    assert '修正' in reasons and '事实' in reasons and '重复' in reasons


def test_failed_review_is_not_reported_as_a_content_disagreement():
    state = delivery.delivery_state([{'status':'success','body_text':'正文'}],{'status':'failed'}, {'status':'completed'})
    assert '执行' in '；'.join(state['delivery_reasons'])


@pytest.mark.parametrize("recheck_failure", [False, True])
def test_review_retains_independent_edit_only_after_mixed_body_recheck(recheck_failure):
    section = {'outline_id':'S1.1','title':'进展','status':'success',
        'body_text':'公司成立2020年。[C1]重复背景。\n\n公司2027年投产。[C1]',
        'external_evidence_blocks':[{'citation_id':'C1','text':'公司成立2020年。公司计划2027年投产。'}]}
    seen = []
    def check(prepared, *args, originals=None, **kwargs):
        rows = {}; losses = {}
        for p in prepared:
            seen.append(p['body_text']); evidence = p['evidence'][0]
            rows[p['outline_id']] = [{'claim_id':c['claim_id'],
                'status':'partial' if '投产' in c['quote'] else 'supported',
                'reason':'投产仅为计划' if '投产' in c['quote'] else '原文支持',
                'supports':[{'evidence_id':evidence['evidence_id'],'quote':evidence['text']}]}
                for c in p['claims']]
            if originals:losses[p['outline_id']] = [{'outline_id':p['outline_id'],'lost':False,'reason':'独有信息保留'}]
        if recheck_failure and seen[-1] == '公司成立2020年。[C1]\n\n公司2027年投产。[C1]':
            return {}, {'S1.1:K1':'model_output_unavailable'}, {}
        return rows, {}, losses
    issues = {'issues':[{'reason':'重复','keep_spans':[{'paragraph_id':'S1.1:P1','quote':'公司成立2020年。[C1]'}], 'edits':[{'outline_id':'S1.1',
        'spans':[{'paragraph_id':'S1.1:P1','quote':'重复背景。'}],
        'instruction':'删除重复','preserve_paragraph_ids':[]}]}], 'evidence_warnings':[]}
    verified_spans = []
    def verify(*args, **kwargs):
        verified_spans.extend(args[3]['S1.1'])
        return {'status':'completed','unresolved':[],'unresolved_issue_indexes':[]}
    def query(prompt,*args):
        import json
        p=json.loads(prompt)
        return {'outline_id':'S1.1','patches':[{'span_index':i,'replacement':
            '' if t['quote']=='重复背景。' else '公司已经2027年投产。[C1]'}
            for i,t in enumerate(p['editable_spans'])]}
    with patch.object(review_agent,'check_claim_batches',side_effect=check), \
         patch.object(review_agent,'repetition_responses',return_value=[(issues,None)]), \
         patch.object(review_agent,'_query',side_effect=query), \
         patch.object(review_agent,'_verify_edits',side_effect=verify):
        result=review_agent.review_report_bodies(body_sections=[section],writing_tasks=[],report_title='进展',user_prompt='比较',references=[])
    final=result['body_sections'][0]
    if recheck_failure:
        assert final['body_text'] == section['body_text']
        assert result['review']['execution_status'] == 'partial'
        return
    assert final['body_text']=='公司成立2020年。[C1]\n\n公司2027年投产。[C1]'
    assert seen[-1] == final['body_text']
    assert final['claim_verification']['body_text'] == final['body_text']
    assert result['review']['changed_outline_ids']==['S1.1']
    assert result['review']['status']=='partial'  # original fact still unresolved
    assert any(a.get('kind')=='paragraph_restore' and a['status']=='retained_after_recheck' for a in result['review']['edit_attempts'])

    assert all(span['paragraph_id'] != 'S1.1:P2' for span in verified_spans)


def test_incomplete_body_does_not_hide_legacy_partial_review():
    state=delivery.delivery_state([{'status':'error','body_text':''}], {'status':'partial'}, {'status':'completed'})
    assert any('正文审查' in reason for reason in state['delivery_reasons'])


def test_partial_review_execution_failure_is_explained_separately():
    state=delivery.delivery_state([{'status':'success','body_text':'正文'}],
        {'status':'partial','execution_status':'partial','claim_verification':{'pending_outline_ids':['S1.1']}}, {'status':'completed'})
    assert any('执行' in reason for reason in state['delivery_reasons'])
    assert any('事实' in reason for reason in state['delivery_reasons'])

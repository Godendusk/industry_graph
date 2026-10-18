import copy

from report_generation.report_scope import apply_report_scope
from test_report_scope import fixture


def answer_rows():
    return [{'outline_id': 'S1.1', 'answer': '按同一年度公司总收入比较甲乙规模，不能据此比较相关业务收入。', 'citation_ids': ['C1']}]


def test_scope_attaches_concrete_answer_with_original_sources():
    outline, tasks, coordination = fixture()
    coordination['section_answers'] = answer_rows()
    _, final, scope, _, warnings = apply_report_scope(outline, tasks, coordination, '比较企业', '报告')
    assert scope['status'] == 'completed', warnings
    assert final[0]['section_answer'] == answer_rows()[0]
    assert 'section_answer' not in tasks[0]


def test_missing_answer_for_retained_section_prevents_adopting_scope():
    outline, tasks, coordination = fixture()
    coordination['section_answers'] = []
    final, _, scope, _, warnings = apply_report_scope(outline, tasks, coordination, '比较企业', '报告')
    assert scope['status'] == 'incomplete'
    assert final == outline
    assert '实质回答' in warnings[0]['message']


def test_answer_cannot_reference_a_source_unavailable_to_its_section():
    outline, tasks, coordination = fixture()
    coordination['section_answers'] = answer_rows()
    coordination['section_answers'][0]['citation_ids'] = ['C999']
    _, _, scope, _, warnings = apply_report_scope(outline, tasks, coordination, '比较企业', '报告')
    assert scope['status'] == 'incomplete'
    assert '引用' in warnings[0]['message']


def test_answer_can_use_real_report_source_from_another_retained_section():
    outline, tasks, coordination = fixture()
    coordination['outline_operations'] = []
    coordination['effective_outline'] = copy.deepcopy(outline)
    tasks[1]['external_rag_retrieval']['evidence_blocks'] = [{'citation_id': 'C2', 'title': '乙公司年报', 'text': '乙公司收入5亿元。'}]
    coordination['section_answers'] = [
        {'outline_id': 'S1.1', 'answer': '比较甲乙收入规模。', 'citation_ids': ['C1', 'C2']},
        {'outline_id': 'S1.2', 'answer': '说明乙公司收入对其业务结构的含义。', 'citation_ids': ['C2']}]
    _, final, scope, _, warnings = apply_report_scope(outline,tasks,coordination,'比较企业','报告')
    assert scope['status'] == 'completed', warnings
    shared = final[0]['external_rag_retrieval']
    assert shared['evidence_blocks'][-1] == tasks[1]['external_rag_retrieval']['evidence_blocks'][0]
    assert '[C2]' in shared['rag_context_text']
    assert '乙公司收入5亿元。' in shared['rag_context_text']
    assert len(tasks[0]['external_rag_retrieval']['evidence_blocks']) == 1


def test_answer_sharing_does_not_repeat_same_chunk_from_other_query_rankings():
    outline,tasks,coordination=fixture()
    coordination['outline_operations']=[]
    coordination['effective_outline']=copy.deepcopy(outline)
    original={'citation_id':'C1','library':'news','material_id':'doc','vector_id':'doc:1','text':'甲公司收入10亿元。','distance':0.1}
    tasks[0]['external_rag_retrieval']['evidence_blocks']=[original]
    tasks[1]['external_rag_retrieval']['evidence_blocks']=[{**original,'distance':0.9,'agentic_query_refs':[{'outline_id':'S1.2'}]},
        {**original,'vector_id':'doc:2','text':'甲公司产品交付12台。','distance':0.8}]
    from report_generation.external_rag.report_adapter import build_rag_context_text
    for task in tasks:
        retrieval=task['external_rag_retrieval']
        retrieval['rag_context_text']=build_rag_context_text(retrieval['evidence_blocks'])
    coordination['section_answers']=[{'outline_id':'S1.1','answer':'比较收入和交付口径。','citation_ids':['C1']},
        {'outline_id':'S1.2','answer':'说明交付进度。','citation_ids':['C1']}]
    _,final,scope,_,warnings=apply_report_scope(outline,tasks,coordination,'比较企业','报告')
    assert scope['status']=='completed',warnings
    for task in final:
        blocks=task['external_rag_retrieval']['evidence_blocks']
        assert len(blocks)==2
        assert {b['vector_id'] for b in blocks}=={'doc:1','doc:2'}
        assert task['external_rag_retrieval']['rag_context_text'].count('甲公司收入10亿元。')==1

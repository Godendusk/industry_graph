import copy

from report_generation.agentic_rag.executor import execute_plan


def plan():
    return {'status':'planned', 'industry':'embodied', 'outline_id':'S1.1',
            'elapsed_seconds':0.01, 'fallback_reason':'',
            'sub_queries':[{'id':f'q{i}', 'question':f'问题{i}', 'strategy':'graph_hybrid',
                            'evidence_requirements':['原文'], 'reason':'需要'} for i in (1, 2)]}


def block(vector, **extra):
    return dict(library='embodied_news', material_id='m1', vector_id=vector,
                chunk_id=vector, text='原文 '+vector, source_address='https://source.example/article', **extra)


def row(blocks, status='success'):
    return {'graph_retrieval':{'status':'success', 'graph_context_text':'图谱',
                              'evidence_blocks':[{'segment':{'id':'s1'},'context_text':'图谱', 'graph_evidence_refs':[]}],
                              'matched_segments':[{'id':'s1'}]},
            'external_rag_retrieval':{'status':status, 'evidence_blocks':blocks,
                                      'retrieval_version':'hybrid_v2', 'warnings':[]}}


def test_sequential_merge_keeps_chunks_and_graph_curation_without_mutating_results():
    a = row([block('v1'), block('v2')])
    b = row([block('v1', graph_linked=True, evidence_scope='只证明供应关系', graph_matches=[{'node_id':'n1'}])])
    baseline = copy.deepcopy([a,b]); calls=[]
    def retrieve(query, strategy):
        calls.append((query,strategy))
        return (a if query == '问题1' else b), []
    result, warnings = execute_plan(plan(), retrieve=retrieve)
    blocks = result['external_rag_retrieval']['evidence_blocks']
    assert len(calls) == 2
    assert [b['vector_id'] for b in blocks] == ['v1','v2']
    assert blocks[0]['graph_linked'] is True
    assert blocks[0]['evidence_scope'] == '只证明供应关系'
    assert blocks[0]['agentic_query_ids'] == ['q1','q2']
    assert blocks[0]['source_address'] == baseline[0]['external_rag_retrieval']['evidence_blocks'][0]['source_address']
    assert [a,b] == baseline
    assert warnings == []
    assert len(result['graph_retrieval']['evidence_blocks']) == 1
    assert result['agentic_retrieval']['status'] == 'success'
    assert len(result['agentic_retrieval']['steps']) == 2


def test_failed_subquery_keeps_previous_evidence_and_records_partial_status():
    def retrieve(query, strategy):
        if query == '问题2':
            raise RuntimeError('store unavailable')
        return row([block('v1')]), []
    result, warnings = execute_plan(plan(), retrieve=retrieve)
    assert result['agentic_retrieval']['status'] == 'partial'
    assert result['external_rag_retrieval']['evidence_blocks'][0]['vector_id'] == 'v1'
    assert any('store unavailable' in w['message'] for w in warnings)
    assert result['agentic_retrieval']['steps'][1]['status'] == 'error'


def test_all_retrieval_errors_remain_errors():
    def retrieve(*args):
        result=row([], 'error'); result['graph_retrieval']['status']='error'
        return result, []
    result, _ = execute_plan(plan(), retrieve=retrieve)
    assert result['agentic_retrieval']['status'] == 'error'
    assert result['external_rag_retrieval']['status'] == 'error'


def test_empty_success_is_distinct_from_failed_retrieval():
    result, _ = execute_plan(plan(), retrieve=lambda *args: (row([]), []))
    assert result['agentic_retrieval']['status'] == 'success'
    assert result['external_rag_retrieval']['evidence_blocks'] == []


def test_fallback_executes_one_query_and_keeps_reason():
    p=plan(); p.update(status='fallback', fallback_reason='invalid JSON')
    p['sub_queries']=p['sub_queries'][:1]
    calls=[]
    def retrieve(*args):
        calls.append(args)
        return row([block('v1')]), []
    result, warnings=execute_plan(p, retrieve=retrieve)
    assert calls == [('问题1', 'graph_hybrid')]
    assert result['agentic_retrieval']['plan']['fallback_reason'] == 'invalid JSON'
    assert any(w['stage']=='agentic_planning' for w in warnings)


def test_round_robin_keeps_both_question_candidates_before_allocation():
    def retrieve(query, *args):
        return row([block('a1'),block('a2')] if query=='问题1' else [block('b1')]), []
    result,_=execute_plan(plan(),retrieve=retrieve)
    assert [b['vector_id'] for b in result['external_rag_retrieval']['evidence_blocks']]==['a1','b1','a2']


def test_trace_records_actual_query_and_both_tool_diagnostics():
    r=row([block('v1')]); r['section_retrieval_query']='用户需求：限定2025年\n当前二级标题：企业产品'
    r['external_rag_retrieval'].update(graph_diagnostics={'resolved':1}, graph_keyword_terms=['减速器'])
    result,_=execute_plan(plan(),retrieve=lambda *args:(r,[]))
    step=result['agentic_retrieval']['steps'][0]
    assert step['query']==r['section_retrieval_query']
    assert step['graph_evidence_diagnostics']=={'resolved':1}
    assert step['graph_keyword_terms']==['减速器']


def test_skipped_tools_are_not_reported_as_executed_success():
    r={'graph_retrieval':{'status':'skipped'},'external_rag_retrieval':{'status':'skipped'}}
    result,_=execute_plan(plan(),retrieve=lambda *args:(r,[]))
    assert result['agentic_retrieval']['status']=='skipped'


def test_chunk_query_provenance_includes_outline_id():
    p=plan();p['outline_id']='S2.3'
    result,_=execute_plan(p,retrieve=lambda *args:(row([block('v1')]),[]))
    assert result['external_rag_retrieval']['evidence_blocks'][0]['agentic_query_refs']==[
        {'outline_id':'S2.3','query_id':'q1'},{'outline_id':'S2.3','query_id':'q2'}]

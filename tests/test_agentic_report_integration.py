import json
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation import coordinator_agent as coordinator
from report_generation.writing_decisions import fallback_decision


OUTLINE = [{'section_type':'body', 'level1_id':'S1', 'level1_title':'产业竞争',
            'chapter_goal':'比较产品和订单', 'content_requirements':['产品','订单'],
            'subsections':[{'outline_id':'S1.1','title':'企业竞争格局','writing_focus':'2024—2026年产品与订单'}]}]


def model(**kwargs):
    info=kwargs.get('extra_log_info','')
    if 'agentic_planner' in info:
        payload={'industry':'embodied','sub_queries':[
            {'question':'企业产品','strategy':'hybrid','evidence_requirements':['产品原文'],'reason':'查产品'},
            {'question':'产业链位置','strategy':'graph_hybrid','evidence_requirements':['关系原文'],'reason':'定位企业'}]}
    elif info == 'report_generation.task_coordination':
        payload={'changes':[]}
    else:
        payload=fallback_decision({'title':'企业竞争格局'})
    return LLMQueryResult(content=json.dumps(payload,ensure_ascii=False),finish_reason='stop')


def run_flow(stream=False):
    queries=[]
    def rag(query, *, industry, top_k):
        queries.append((query,industry))
        return {'status':'success','retrieval_version':'hybrid_v2','evidence_blocks':[
            {'library':'embodied_news','material_id':'m1','vector_id':'v1','chunk_id':'v1',
             'title':'企业产品公告','text':'企业提供减速器产品','source_address':'https://source.example/a'}], 'warnings':[]}
    graph={'status':'success','industry':'embodied','graph_context_text':'产业链线索','evidence_blocks':[]}
    kwargs=dict(user_prompt='比较2024—2026年企业产品和订单',report_title='具身智能竞争报告',outline=OUTLINE,industry='embodied')
    with patch.object(coordinator.llm,'query_result',side_effect=model), \
         patch.object(coordinator,'retrieve_external_rag',side_effect=rag), \
         patch.object(coordinator,'retrieve_industry_graph',return_value=graph) as graph_call, \
         patch.object(coordinator,'retrieve_graph_keyword_candidates',return_value={'status':'success','terms':[],'candidates':[],'warnings':[]}):
        if stream:
            events=list(coordinator.stream_writing_tasks(**kwargs))
            result=next(event for event in events if event['event']=='completed')
            completed=next(event for event in events if event['event']=='task_completed')
            assert completed['agentic_retrieval']['plan']['status']=='planned'
        else:
            result=coordinator.generate_writing_tasks(**kwargs)
        assert graph_call.call_count == 1
    return result,queries


def test_sync_and_stream_share_planned_execution_and_reference_registration():
    for stream in (False,True):
        result, queries=run_flow(stream)
        task=result['writing_tasks'][0]
        assert len(queries)==2  # No hidden low-source retry per subquery.
        assert all(industry=='embodied' for _,industry in queries)
        assert all('2024—2026' in query for query,_ in queries)
        assert task['agentic_retrieval']['plan']['status']=='planned'
        assert len(task['agentic_retrieval']['steps'])==2
        blocks=task['external_rag_retrieval']['evidence_blocks']
        assert len(blocks)==1
        assert blocks[0]['citation_id']=='C1'
        assert blocks[0]['agentic_query_ids']==['q1','q2']
        assert result['references'][0]['vector_ids']==['v1']
        assert '[C1]' in task['external_rag_retrieval']['rag_context_text']


def test_planner_failure_keeps_fixed_query_and_visible_reason():
    with patch.object(coordinator.llm,'query_result',return_value=LLMQueryResult(error_message='planner unavailable')), \
         patch.object(coordinator,'retrieve_external_rag',return_value={'status':'error','message':'index unavailable','evidence_blocks':[]}) as rag:
        row,warnings=coordinator._retrieve_candidates_for_subsection(
            subsection=coordinator._flatten_body_subsections(OUTLINE)[0],
            user_prompt='比较企业',report_title='报告',industry='embodied',top_k=10,use_graph=False)
    assert row['agentic_retrieval']['plan']['status']=='fallback'
    assert rag.call_args_list[0].args[0]==row['section_retrieval_query']
    assert row['external_rag_retrieval']['status']=='error'
    assert row['agentic_retrieval']['status']=='error'
    assert any('planner unavailable' in w['message'] for w in warnings)


def test_actual_subquery_survives_ai_report_query_focusing():
    from report_generation.external_rag.report_adapter import build_report_query
    _,queries=run_flow()
    assert '企业产品' in build_report_query(queries[0][0]).semantic_query
    assert '产业链位置' in build_report_query(queries[1][0]).semantic_query


def test_writing_decision_failure_does_not_discard_retrieval_trace():
    for streaming in (False,True):
        with patch.object(coordinator.llm,'query_result',side_effect=model), \
             patch.object(coordinator,'retrieve_external_rag',return_value={'status':'success','evidence_blocks':[]}), \
             patch.object(coordinator,'request_decision',side_effect=RuntimeError('decision unavailable')):
            kwargs=dict(user_prompt='企业对比',report_title='报告',outline=OUTLINE,industry='embodied',use_graph=False)
            if streaming:
                events=list(coordinator.stream_writing_tasks(**kwargs))
                result=next(e for e in events if e['event']=='completed')
            else:
                result=coordinator.generate_writing_tasks(**kwargs)
        assert result['writing_tasks'][0]['agentic_retrieval']['plan']['outline_id']=='S1.1'


def test_outline_only_time_requirement_reaches_actual_and_fallback_queries():
    from report_generation.external_rag.report_adapter import build_report_query
    outline=json.loads(json.dumps(OUTLINE))
    outline[0]['time_requirement']='仅限2025年'
    outline[0]['subsections'][0]['writing_focus']='比较产品'
    for valid in (True,False):
        def ask(**kwargs):
            if not valid:
                return LLMQueryResult(error_message='planner failed')
            return LLMQueryResult(content=json.dumps({'industry':'embodied','sub_queries':[
                {'question':'代表企业有哪些产品','strategy':'hybrid','evidence_requirements':['产品原文'],'reason':'查产品'}]},ensure_ascii=False),finish_reason='stop')
        queries=[]
        def rag(query,**kwargs):
            queries.append(query)
            return {'status':'success','evidence_blocks':[]}
        with patch.object(coordinator.llm,'query_result',side_effect=ask), \
             patch.object(coordinator,'retrieve_external_rag',side_effect=rag):
            row,_=coordinator._retrieve_candidates_for_subsection(
                subsection=coordinator._flatten_body_subsections(outline)[0],
                user_prompt='比较企业产品',report_title='产品报告',industry='embodied',top_k=10,use_graph=False)
        assert all('仅限2025年' in q for q in queries)
        assert '2025' in build_report_query(queries[0]).semantic_query

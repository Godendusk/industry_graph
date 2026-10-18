import json
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation import coordinator_agent as ca, body_agent
from report_generation.writing_decisions import fallback_decision

OUTLINE=[{'section_type':'body','level1_id':'S1','level1_title':'竞争格局','content_requirements':['企业产品','订单依据'],
          'subsections':[{'outline_id':'S1.1','title':'企业布局','writing_focus':'产品与订单','time_requirement':'2025年'}]}]


def test_both_entries_assess_followup_allocate_and_bind_support_quotes():
    for streaming in (False,True):
        queries=[]
        def model(**kw):
            info=kw.get('extra_log_info',''); data=json.loads(kw['user_prompt']) if 'agentic_' in info else {}
            if 'agentic_planner' in info:
                payload={'industry':'embodied','sub_queries':[
                    {'question':'2025年企业产品','strategy':'hybrid','evidence_requirements':['企业产品'],'reason':'查产品'},
                    {'question':'2025年订单','strategy':'hybrid','evidence_requirements':['订单依据'],'reason':'查订单'}]}
            elif 'agentic_assessment' in info:
                rows=[]
                for r in data['requirements']:
                    target='甲企业生产减速器。' if r['requirement']=='企业产品' else '甲企业2025年已交付订单。'
                    found=next((b for b in data['evidence'] if target in b['text']),None)
                    rows.append({'id':r['id'],'status':'supported' if found else 'insufficient',
                                 'reason':'原文支持' if found else '缺少实际订单',
                                 'support':[{'evidence_id':found['evidence_id'],'quote':target}] if found else [],
                                 'follow_up_query':'' if found else '甲企业2025年实际订单交付', 'strategy':'hybrid'})
                payload={'requirements':rows}
            elif info=='report_generation.task_coordination':payload={'changes':[]}
            else:payload=fallback_decision({'title':'企业布局'})
            return LLMQueryResult(content=json.dumps(payload,ensure_ascii=False),finish_reason='stop')
        def retrieve(query,**kw):
            queries.append(query); order='实际订单交付' in query
            return {'status':'success','retrieval_version':'hybrid_v2','evidence_blocks':[
                {'industry':'embodied','library':'news','material_id':'m2' if order else 'm1',
                 'vector_id':'v2' if order else 'v1','text':'甲企业2025年已交付订单。' if order else '甲企业生产减速器。'}]}
        with patch.object(ca.llm,'query_result',side_effect=model),patch.object(ca,'retrieve_external_rag',side_effect=retrieve):
            args=dict(user_prompt='比较2025年企业',report_title='报告',outline=OUTLINE,industry='embodied',use_graph=False,top_k=2)
            if streaming:result=next(e for e in ca.stream_writing_tasks(**args) if e['event']=='completed')
            else:result=ca.generate_writing_tasks(**args)
        task=result['writing_tasks'][0];pack=task['evidence_pack']
        assert len(queries)==3 and all('2025年' in q for q in queries)
        assert all(r['status']=='supported' for r in pack['requirements'])
        assert len(result['references'])==2
        assert task['agentic_retrieval']['follow_up']['rounds']==1
        assert task['agentic_retrieval']['follow_up']['new_evidence_count']==1
        assert all(s['citation_id'] in ('C1','C2') for r in pack['requirements'] for s in r['support'])
        captured=[]
        def write(**kw):captured.append(kw['user_prompt']);return LLMQueryResult(content='甲企业提供减速器[C1]。',finish_reason='stop')
        with patch.object(body_agent.llm,'query_result',side_effect=write):
            body=body_agent.generate_body_section(task,'企业对比','报告')
        assert body['status']=='success'
        assert '章节证据要求与写作边界' in captured[0]
        assert '甲企业2025年已交付订单。' in captured[0]


def test_merged_section_retains_missing_ranking_constraint_in_body_prompt():
    from report_generation.outline_adjustments import apply_outline_adjustments
    from report_generation.agentic_rag.assessment import assess_evidence
    from types import SimpleNamespace
    p={'outline_id':'S1.2','industry':'embodied','input':{'content_requirements':['市场排名'],'use_external_rag':True},'sub_queries':[]}
    pack=assess_evidence(p,[{'library':'news','material_id':'m1','vector_id':'v1','text':'企业有产品'}],
        retrieval_status='success',query_model=lambda **kw:SimpleNamespace(content=json.dumps({'requirements':[
            {'id':'r1','status':'insufficient','reason':'没有可比份额数据','support':[]}]},ensure_ascii=False),finish_reason='stop',error_message=''))
    tasks=[{'outline_id':'S1.1','title':'企业布局','external_rag_retrieval':{'evidence_blocks':[]}},
           {'outline_id':'S1.2','title':'竞争排名','external_rag_retrieval':{'evidence_blocks':[]},'evidence_pack':pack}]
    outline=[{'section_type':'body','level1_id':'S1','subsections':[{'outline_id':'S1.1'},{'outline_id':'S1.2'}]}]
    _,merged,notes,warnings=apply_outline_adjustments(outline,tasks,[{'kind':'merge','source_ids':['S1.2'],'target_id':'S1.1','reason':'合并分析'}])
    assert warnings==[]
    assert merged[0]['merged_evidence_packs'][0]['outline_id']=='S1.2'
    prompt=body_agent._build_body_user_prompt(merged[0],'企业报告','报告')
    assert '市场排名' in prompt and '不生成确定排名' in prompt
    assert notes[0]['evidence_packs'][0]['requirements'][0]['status']=='insufficient'

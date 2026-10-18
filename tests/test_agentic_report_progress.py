from report_generation.agentic_rag.chapter import retrieve_chapter


def test_progress_emits_actual_retrieval_assessment_and_one_followup_in_order():
    p={'outline_id':'S1.1','industry':'embodied','status':'planned','input':{'use_graph':False,'use_external_rag':True},
       'sub_queries':[{'id':'q1','question':'企业产品','strategy':'hybrid','evidence_requirements':['产品'],'reason':'需要'}]}
    events=[]
    def retrieve(question,strategy):
        assert events[-1]['phase'] in ('retrieving','follow_up')
        return {'graph_retrieval':{'status':'skipped'},'external_rag_retrieval':{'status':'success','evidence_blocks':[
            {'industry':'embodied','library':'news','material_id':question,'vector_id':question,'text':question}]}},[]
    def assess(*a,**kw):
        assert events[-1]['phase']=='assessing'
        return {'status':'assessed','warnings':[],'model_calls':1,'uncovered_requirements':['r1'],'requirements':[
          {'id':'r1','requirement':'订单','status':'insufficient','reason':'缺口','follow_up_query':'实际订单','strategy':'hybrid'}]}
    result,_=retrieve_chapter(p,retrieve=retrieve,assessor=assess,on_event=events.append)
    assert [e['phase'] for e in events]==['retrieving','assessing','follow_up','assessing','retrieval_completed']
    assert events[-1]['status']==result['agentic_retrieval']['status']

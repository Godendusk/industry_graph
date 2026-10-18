from report_generation.agentic_rag.chapter import retrieve_chapter


def plan():
    return {'outline_id':'S1.1','industry':'embodied','status':'planned','elapsed_seconds':0,'fallback_reason':'',
            'input':{'use_graph':False,'use_external_rag':True,'content_requirements':['企业产品','市场排名']},
            'sub_queries':[{'id':f'q{i}','question':f'初查{i}','strategy':'hybrid','evidence_requirements':['原文'],'reason':'需要'} for i in range(1,4)]}


def block(id):return {'library':'news','material_id':id,'vector_id':id,'text':id+'原文'}


def result(id):return {'external_rag_retrieval':{'status':'success','evidence_blocks':[block(id)],'retrieval_version':'hybrid_v2'},'graph_retrieval':{'status':'skipped'}}


def pack(queries):
    return {'status':'assessed','model_calls':1,'warnings':[], 'requirements':[
        {'id':f'r{i}', 'requirement':q,'status':'insufficient','follow_up_query':q,'strategy':'hybrid','support':[],'reason':'缺口'} for i,q in enumerate(queries)],
        'writing_constraints':['不写无依据排名'],'uncovered_requirements':[]}


def test_one_followup_round_with_at_most_two_queries_and_no_hidden_source_retry():
    calls=[];assessments=[]
    def retrieve(q,s):
        calls.append(q);return result(q),[]
    def assess(*a,**kw):
        assessments.append(1);return pack(['补查1','补查2','补查3'])
    r,_=retrieve_chapter(plan(),retrieve=retrieve,assessor=assess)
    assert calls==['初查1','初查2','初查3','补查1','补查2']
    assert len(assessments)==2
    assert r['agentic_retrieval']['follow_up']['rounds']==1
    assert r['agentic_retrieval']['follow_up']['new_evidence_count']==2
    assert len(r['agentic_retrieval']['steps'])==5


def test_duplicate_query_and_no_new_evidence_stop_without_third_assessment():
    p=plan();p['sub_queries']=p['sub_queries'][:1]
    calls=[];checks=[]
    def retrieve(q,s):calls.append(q);return result('same'),[]
    def assess(*a,**kw):checks.append(1);return pack(['初查1','新问法'])
    r,_=retrieve_chapter(p,retrieve=retrieve,assessor=assess)
    assert calls==['初查1','新问法'] and len(checks)==1
    assert r['agentic_retrieval']['follow_up']['stop_reason']=='no_new_evidence'


def test_assessment_failure_does_not_start_more_queries():
    calls=[]
    def retrieve(q,*args):calls.append(q);return result(q),[]
    failed=pack(['补查']);failed['status']='failed'
    r,_=retrieve_chapter(plan(),retrieve=retrieve,assessor=lambda *a,**kw:failed)
    assert len(calls)==3
    assert r['agentic_retrieval']['follow_up']['stop_reason']=='assessment_failed'


def test_followup_failure_keeps_initial_evidence_and_marks_trace_partial():
    def retrieve(q,*args):
        if q=='补查':raise RuntimeError('offline')
        return result(q),[]
    r,warnings=retrieve_chapter(plan(),retrieve=retrieve,assessor=lambda *a,**kw:pack(['补查']))
    assert len(r['external_rag_retrieval']['evidence_blocks'])==3
    assert r['agentic_retrieval']['status']=='partial'
    assert any('offline' in w['message'] for w in warnings)

import copy
import json
from unittest.mock import patch
from llm_client import LLMQueryResult
from report_generation import coordinator_agent as ca, body_agent

OUTLINE=[{'section_type':'body','level1_id':'S3','level1_title':'布局',
          'subsections':[{'outline_id':'S3.1','title':'布局现状'}, {'outline_id':'S3.2','title':'资源禀赋'}]}]

def decision(question='组织资源如何转化？'):
    return {'section_question':question,'evidence_uses':[],
            'content_scope':{'full_exposition':['中国移动具身智能产业联盟'],'carry_over':[]},
            'judgment_limits':['成立不证明实施成效']}

def retrieval(**kwargs):
    return ({'graph_retrieval':{'status':'skipped','graph_context_text':''},
             'external_rag_retrieval':{'status':'success','evidence_blocks':[
                 {'citation_id':'旧ID','library':'n','material_id':'m','vector_id':'v',
                  'text':'中国移动具身智能产业联盟成立','title':'联盟消息'}]}}, [])

def test_both_entries_pass_prior_decisions_then_coordinate_before_completion():
    finals=[]
    for streaming in (False,True):
        previous=[]
        def request(task, user_prompt, report_title, outline_context, previous_tasks, outline_ids):
            previous.append(copy.deepcopy(previous_tasks))
            assert task['external_rag_retrieval']['evidence_blocks'][0]['citation_id']=='C1'
            return {'decision':decision(), 'status':'generated','warnings':[]}
        def coordinate(tasks):
            tasks=copy.deepcopy(tasks)
            tasks[1]['writing_decision']=decision('协调后的资源转化问题')
            tasks[1]['writing_system_prompt']='协调后的指令'
            return tasks, {'status':'completed','changed_outline_ids':['S3.2'],'rejected_outline_ids':[], 'input_chars':500,'elapsed_seconds':0}, []
        with patch.object(ca,'_retrieve_candidates_for_subsection',side_effect=retrieval), \
             patch.object(ca,'request_decision',side_effect=request,create=True) as call, \
             patch.object(ca,'coordinate_writing_tasks',side_effect=coordinate,create=True) as review, \
             patch.object(ca.llm,'query_result',return_value=LLMQueryResult(content='{}',finish_reason='stop')):
            kwargs=dict(user_prompt='报告',report_title='测试',outline=OUTLINE,industry='embodied')
            if streaming:
                events=list(ca.stream_writing_tasks(**kwargs));result=events[-1]
                names=[e['event'] for e in events]
                assert names.index('coordination_started') < names.index('coordination_completed') < names.index('completed')
            else:
                result=ca.generate_writing_tasks(**kwargs)
        assert call.call_count==2 and review.call_count==1
        assert previous[0]==[] and previous[1][0]['outline_id']=='S3.1'
        assert result['writing_tasks'][1]['writing_system_prompt']=='协调后的指令'
        assert result['coordination']['status']=='completed'
        finals.append(result['writing_tasks'])
    assert finals[0]==finals[1]

def test_body_uses_final_decision_instead_of_stale_prompt_and_preserves_raw_material():
    task={'outline_id':'S3.2','title':'资源禀赋','writing_system_prompt':'旧安排：重新介绍联盟成员',
          'writing_decision':decision(),'graph_retrieval':{'status':'skipped'},
          'external_rag_retrieval':{'rag_context_text':'[C14] 原始材料全文','evidence_blocks':[{'citation_id':'C14'}]}}
    with patch.object(body_agent.llm,'query_result',return_value=LLMQueryResult(content='分析[C14]。',finish_reason='stop')) as call:
        result=body_agent.generate_body_section(task,'需求','标题')
    assert result['status']=='success'
    assert '旧安排' not in call.call_args.kwargs['system_prompt']
    assert '组织资源如何转化' in call.call_args.kwargs['system_prompt']
    assert '[C14] 原始材料全文' in call.call_args.kwargs['user_prompt']

def test_damaged_new_decision_does_not_fall_back_to_stale_prompt():
    task={'title':'资源','writing_system_prompt':'旧安排','writing_decision':{}}
    with patch.object(body_agent.llm,'query_result') as call:
        result=body_agent.generate_body_section(task,'需求','标题')
    assert result['status']=='error' and not call.called
    assert any(w['stage']=='writing_decision_validation' for w in result['warnings'])


def test_nineteen_decisions_and_one_coordination_without_extra_calls():
    from report_generation.writing_decisions import compact_json, fallback_decision
    outline=[{'section_type':'body','level1_id':'S1','level1_title':'产业',
              'subsections':[{'outline_id':f'S1.{i}', 'title':f'问题{i}'} for i in range(1,20)]}]
    def model(**kwargs):
        if kwargs['extra_log_info']=='report_generation.task_coordination':
            return LLMQueryResult(content='{"changes":[]}',finish_reason='stop')
        return LLMQueryResult(content=compact_json(fallback_decision({'title':'问题'})),finish_reason='stop')
    with patch.object(ca,'_retrieve_candidates_for_subsection',side_effect=retrieval), \
         patch.object(ca.llm,'query_result',side_effect=model) as call:
        result=ca.generate_writing_tasks('报告','测试',outline,'embodied')
    contexts=[c.kwargs['extra_log_info'] for c in call.call_args_list]
    assert len(contexts)==20
    assert all(c.startswith('report_generation.writing_decisions outline=') for c in contexts[:19])
    assert contexts[-1]=='report_generation.task_coordination'
    assert len(result['writing_tasks'])==19
    assert result['fallback_count']==0 and result['coordination']['status']=='completed'
    assert all(t['external_rag_retrieval']['evidence_blocks'][0]['citation_id']=='C1' for t in result['writing_tasks'])

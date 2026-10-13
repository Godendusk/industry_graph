from report_generation.coordinator_agent import finalize_coordination_outline


def test_finalization_merges_task_and_keeps_source_evidence():
    outline = [{'section_type':'body','level1_id':'S1','level1_title':'现状','subsections':[
        {'outline_id':'S1.1','title':'布局'}, {'outline_id':'S1.2','title':'资源'},
        {'outline_id':'S1.3','title':'实践'}]}]
    tasks = [{'outline_id':sid,'parent_level1_id':'S1','title':title,
              'external_rag_retrieval':{'status':'success','evidence_blocks':[{'citation_id':cid,'text':text}]}}
             for sid,title,cid,text in [('S1.1','布局','C1','布局事实'),
                                         ('S1.2','资源','C2','资源事实'),
                                         ('S1.3','实践','C3','实践事实')]]
    coord = {'status':'completed','outline_operations':[
        {'kind':'merge','source_ids':['S1.2'],'target_id':'S1.1','reason':'重复背景'}]}
    final_outline, final_tasks, notes, warnings = finalize_coordination_outline(outline,tasks,coord,'产业研究')
    assert not warnings
    assert [x['outline_id'] for x in final_tasks] == ['S1.1','S1.3']
    assert [x['citation_id'] for x in final_tasks[0]['external_rag_retrieval']['evidence_blocks']] == ['C1','C2']
    assert notes[0]['kind'] == 'outline_merge'
    assert len(final_outline[0]['subsections']) == 2

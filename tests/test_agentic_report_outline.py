from report_generation.outline_adjustments import apply_outline_adjustments


def tasks():
    return [{'outline_id':id,'agentic_retrieval':{'plan':{'outline_id':id},'steps':[{'query':id+' query'}]},
             'external_rag_retrieval':{'evidence_blocks':[
                 {'citation_id':'C1','vector_id':'v1','text':'同一片段',
                  'agentic_query_refs':[{'outline_id':id,'query_id':'q1'}]}]}}
            for id in ('S1.1','S1.2')]


def test_merge_preserves_source_trace_and_scoped_chunk_query_refs():
    outline=[{'section_type':'body','level1_id':'S1','subsections':[{'outline_id':'S1.1'},{'outline_id':'S1.2'}]}]
    op=[{'kind':'merge','source_ids':['S1.2'],'target_id':'S1.1','reason':'内容重合'}]
    _,result,notes,warnings=apply_outline_adjustments(outline,tasks(),op)
    assert warnings==[] and len(result)==1
    target=result[0]
    assert target['merged_agentic_retrievals'][0]['plan']['outline_id']=='S1.2'
    assert target['agentic_retrieval']['plan']['outline_id']=='S1.1'
    assert target['external_rag_retrieval']['evidence_blocks'][0]['agentic_query_refs']==[
        {'outline_id':'S1.1','query_id':'q1'},{'outline_id':'S1.2','query_id':'q1'}]
    assert notes[0]['agentic_retrievals'][0]['plan']['outline_id']=='S1.2'


def test_deleted_section_keeps_trace_in_adjustment_note():
    outline=[{'section_type':'body','level1_id':'S1','subsections':[{'outline_id':'S1.1'},{'outline_id':'S1.2'}]}]
    op=[{'kind':'delete','source_ids':['S1.2'],'target_id':None,'reason':'无独立内容'}]
    _,_,notes,warnings=apply_outline_adjustments(outline,tasks(),op)
    assert warnings==[]
    assert notes[0]['agentic_retrievals'][0]['plan']['outline_id']=='S1.2'

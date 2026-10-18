from report_generation.agentic_rag.chapter import retrieve_chapter


def test_shared_support_prevents_supplement_without_repeating_initial_search():
    plan = {'status': 'planned', 'industry': 'embodied', 'outline_id': 'S1.1',
            'input': {'use_external_rag': True, 'use_graph': False},
            'sub_queries': [{'id': 'q1', 'question': '收入', 'strategy': 'hybrid'}]}
    calls = []
    def retrieve(question, strategy):
        calls.append(question)
        return {'external_rag_retrieval': {'status': 'success', 'evidence_blocks': []},
                'graph_retrieval': {'status': 'skipped'}}, []
    def assess(*args, **kwargs):
        return {'status': 'assessed', 'requirements': [
            {'id': 'r1', 'requirement': '收入', 'status': 'insufficient',
             'follow_up_query': '甲公司收入', 'reason': '缺少收入'}]}
    initial, _ = retrieve_chapter(plan, retrieve=retrieve, assessor=assess, defer_followup=True)
    assert calls == ['收入']
    initial['evidence_pack']['requirements'][0]['status'] = 'supported'
    final, _ = retrieve_chapter(plan, retrieve=retrieve, assessor=assess, initial_result=initial)
    assert calls == ['收入']
    assert final['agentic_retrieval']['follow_up']['query_count'] == 0

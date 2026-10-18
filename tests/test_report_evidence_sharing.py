import json
from unittest.mock import patch

from llm_client import LLMQueryResult
from report_generation import material_allocator as ma


def fixture():
    sections = [{'outline_id': 'S1.1', 'title': '估值'}, {'outline_id': 'S2.1', 'title': '经营'}]
    rows = [{'external_rag_retrieval': {'status': 'success', 'evidence_blocks': [
                {'library': 'base', 'material_id': 'finance', 'vector_id': 'v1', 'text': '2025年总收入100亿元，项目计划2027年投产。'}]},
             'evidence_pack': {'requirements': []}},
            {'external_rag_retrieval': {'status': 'success', 'evidence_blocks': []},
             'evidence_pack': {'status': 'assessed', 'requirements': [
                 {'id': 'r1', 'requirement': '2025年总收入', 'status': 'unknown', 'support': []},
                 {'id': 'r2', 'requirement': '五年收入增长', 'status': 'unknown', 'support': []}]}}]
    return sections, rows


def response(status='supported', quote='2025年总收入100亿元'):
    return LLMQueryResult(content=json.dumps({'allocations': [
        {'section_id': 'S2.1', 'requirement_id': 'r1', 'status': status,
         'reason': '单年总收入可供经营比较', 'support': [{'evidence_id': 'e1', 'quote': quote}]}]}, ensure_ascii=False), finish_reason='stop')


def test_share_maps_existing_financial_evidence_to_target_requirement_only():
    sections, rows = fixture()
    with patch.object(ma.llm, 'query_result', return_value=response()) as call:
        final = ma.share_evidence_candidates(sections, rows)
    assert call.call_count == 1
    block = final[1]['external_rag_retrieval']['evidence_blocks'][0]
    assert block['text'].endswith('项目计划2027年投产。')
    assert block['material_id'] == 'finance'
    requirement = final[1]['evidence_pack']['requirements'][0]
    assert requirement['status'] == 'supported' and requirement['support'][0]['evidence_key']['vector_id'] == 'v1'
    assert final[1]['evidence_pack']['requirements'][1]['status'] == 'unknown'
    assert rows[1]['external_rag_retrieval']['evidence_blocks'] == []


def test_share_rejects_invented_quote_without_copying_any_source():
    sections, rows = fixture()
    with patch.object(ma.llm, 'query_result', return_value=response(quote='五年增长100%')):
        final = ma.share_evidence_candidates(sections, rows)
    assert final[1]['external_rag_retrieval']['evidence_blocks'] == []
    assert final[1]['evidence_pack']['requirements'][0]['status'] == 'unknown'
    assert final[1]['evidence_sharing']['status'] == 'failed'


def test_long_report_sharing_compacts_evidence_instead_of_skipping_all():
    sections, rows = fixture()
    for i in range(60):
        rows[0]['external_rag_retrieval']['evidence_blocks'].append(
            {'library': 'base', 'material_id': f'm{i}', 'vector_id': f'v{i+2}',
             'text': '项目计划投产，不能当作已完成。' * 100})
    with patch.object(ma.llm, 'query_result', return_value=response()) as call:
        final = ma.share_evidence_candidates(sections, rows)
    assert call.call_count == 1
    assert final[1]['evidence_pack']['requirements'][0]['status'] == 'supported'


def test_partial_shared_support_keeps_remaining_gap_query():
    sections, rows = fixture()
    rows[1]['evidence_pack']['requirements'][0]['follow_up_query'] = '核对完整收入'
    with patch.object(ma.llm, 'query_result', return_value=response(status='insufficient')):
        final = ma.share_evidence_candidates(sections, rows)
    assert final[1]['evidence_pack']['requirements'][0]['follow_up_query'] == '核对完整收入'

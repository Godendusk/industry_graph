import copy
from unittest.mock import patch

from report_generation import coordinator_agent as coordinator


def scope_fixture():
    outline = [{'section_type': 'body', 'level1_id': 'S1', 'level1_title': '比较', 'subsections': [
        {'outline_id': 'S1.1', 'title': '比较'}, {'outline_id': 'S1.2', 'title': '重复背景'}]}]
    tasks = [{'outline_id': 'S1.1', 'external_rag_retrieval': {'status': 'success', 'evidence_blocks': [{'citation_id': 'C1', 'text': '甲公司收入10亿元。'}]}},
             {'outline_id': 'S1.2', 'external_rag_retrieval': {'status': 'success', 'evidence_blocks': [{'citation_id': 'C2', 'text': '乙公司收入5亿元。'}]}}]
    meta = {'section_answers': [{'outline_id': 'S1.1', 'answer': '比较甲乙收入规模，不能推出业务成熟度。', 'citation_ids': ['C1', 'C2']}], 'status': 'completed', 'report_scope': {'effective_title': '企业比较', 'core_question': '比较企业',
        'deliverable_type': 'report', 'boundary': {'subjects': ['甲公司', '乙公司'], 'period': '', 'classification': ''},
        'coverage': [{'requirement': '企业比较', 'status': 'partial', 'reason': '有两家收入', 'section_ids': ['S1.1']}],
        'adjustments': ['合并背景'], 'remaining_gaps': []}, 'effective_outline': outline,
        'outline_operations': [{'kind': 'merge', 'source_ids': ['S1.2'], 'target_id': 'S1.1', 'reason': '重复背景'}]}
    return outline,tasks,meta



def test_explicit_merge_is_the_single_structure_source_and_preserves_materials():
    from report_generation.report_scope import apply_report_scope
    outline,tasks,meta = scope_fixture()
    result = apply_report_scope(outline,tasks,meta,'比较企业','报告')
    assert result[2]['status'] == 'completed'
    assert len(result[1]) == 1
    assert {e['citation_id'] for e in result[1][0]['external_rag_retrieval']['evidence_blocks']} == {'C1', 'C2'}


def test_section_disappearing_without_explicit_operation_remains_incomplete():
    from report_generation.report_scope import apply_report_scope
    outline,tasks,meta = scope_fixture()
    meta['outline_operations'] = []
    meta['effective_outline'] = copy.deepcopy(outline)
    meta['effective_outline'][0]['subsections'] = meta['effective_outline'][0]['subsections'][:1]
    result = apply_report_scope(outline,tasks,meta,'比较企业','报告')
    assert result[2]['status'] == 'incomplete'
    assert len(result[1]) == 2

import copy

import pytest

from report_generation.outline_adjustments import apply_outline_adjustments, reduction_limit


def fixture():
    outline = [{'section_type': 'body', 'level1_id': 'S1', 'level1_title': '现状',
                'subsections': [{'outline_id': 'S1.1', 'title': '布局'},
                                {'outline_id': 'S1.2', 'title': '资源'},
                                {'outline_id': 'S1.3', 'title': '实践'}]}]
    tasks = [{'outline_id': 'S1.1', 'parent_level1_id': 'S1', 'title': '布局',
              'external_rag_retrieval': {'evidence_blocks': [{'citation_id': 'C1', 'text': '甲'}]}},
             {'outline_id': 'S1.2', 'parent_level1_id': 'S1', 'title': '资源',
              'external_rag_retrieval': {'evidence_blocks': [{'citation_id': 'C2', 'text': '乙'}]}},
             {'outline_id': 'S1.3', 'parent_level1_id': 'S1', 'title': '实践',
              'external_rag_retrieval': {'evidence_blocks': [{'citation_id': 'C3', 'text': '丙'}]}}]
    return outline, tasks


@pytest.mark.parametrize('count,expected', [(0,0),(1,1),(8,1),(10,1),(19,2),(30,2)])
def test_reduction_limit(count, expected):
    assert reduction_limit(count) == expected


def test_merge_retains_source_evidence_and_does_not_mutate_inputs():
    outline, tasks = fixture()
    before = copy.deepcopy((outline, tasks))
    final, final_tasks, notes, warnings = apply_outline_adjustments(
        outline, tasks, [{'kind':'merge', 'source_ids':['S1.2'], 'target_id':'S1.1', 'reason':'内容重复'}], set())
    assert [x['outline_id'] for x in final[0]['subsections']] == ['S1.1','S1.3']
    assert [x['citation_id'] for x in final_tasks[0]['external_rag_retrieval']['evidence_blocks']] == ['C1','C2']
    assert notes[0]['kind'] == 'outline_merge'
    assert not warnings
    assert (outline, tasks) == before


def test_two_removals_over_budget_leave_outline_intact():
    outline, tasks = fixture()
    operations = [{'kind':'delete','source_ids':[sid], 'target_id':None, 'reason':'缺少独立内容'}
                  for sid in ('S1.2','S1.3')]
    final, final_tasks, notes, warnings = apply_outline_adjustments(outline, tasks, operations, set())
    assert final == outline and final_tasks == tasks
    assert not notes and warnings


def test_protected_section_cannot_be_removed():
    outline, tasks = fixture()
    final, _, notes, warnings = apply_outline_adjustments(outline, tasks,
        [{'kind':'delete','source_ids':['S1.2'], 'target_id':None, 'reason':'缺少独立内容'}], {'S1.2'})
    assert final == outline and not notes and warnings


def test_merge_preserves_source_decision_use_or_rejects_merge():
    outline, tasks = fixture()
    for task in tasks:
        task['writing_decision'] = {'section_question': '回答本节问题',
            'evidence_uses': [{'topic': task['title'], 'basis': 'external',
                               'citation_ids': [task['external_rag_retrieval']['evidence_blocks'][0]['citation_id']],
                               'use': '说明本节事实', 'support_limit': ''}],
            'content_scope': {'full_exposition': [task['title']], 'carry_over': []},
            'judgment_limits': []}
    _, final_tasks, notes, warnings = apply_outline_adjustments(outline, tasks,
        [{'kind':'merge','source_ids':['S1.2'],'target_id':'S1.1','reason':'内容重复'}], set())
    assert not warnings and notes
    assert {use['topic'] for use in final_tasks[0]['writing_decision']['evidence_uses']} == {'布局','资源'}
    assert '资源' in final_tasks[0]['writing_decision']['content_scope']['full_exposition']

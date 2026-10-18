import copy

from report_generation.report_scope import apply_report_scope


def fixture():
    outline = [{'section_type': 'body', 'level1_id': 'S1', 'level1_title': '前十排名',
                'subsections': [{'outline_id': 'S1.1', 'title': '企业比较'},
                                {'outline_id': 'S1.2', 'title': '背景'}]}]
    tasks = [{'outline_id': 'S1.1', 'title': '企业比较', 'parent_level1_id': 'S1',
              'external_rag_retrieval': {'status': 'success', 'evidence_blocks': [{'citation_id': 'C1', 'text': '甲乙公司收入'}]}},
             {'outline_id': 'S1.2', 'title': '背景', 'parent_level1_id': 'S1',
              'external_rag_retrieval': {'status': 'success', 'evidence_blocks': []}}]
    scope = {'effective_title': '代表企业经营比较', 'deliverable_type': 'brief',
             'core_question': '企业经营表现如何比较？',
             'boundary': {'subjects': ['甲公司', '乙公司'], 'period': '2025', 'classification': '公司总收入'},
             'coverage': [{'requirement': '企业经营比较', 'status': 'partial', 'section_ids': ['S1.1'], 'reason': '仅两家有可比收入'}],
             'adjustments': ['取消无依据前十排名，保留比较'], 'remaining_gaps': ['缺少完整前十名单']}
    effective = copy.deepcopy(outline)
    effective[0]['level1_title'] = '代表企业经营'
    effective[0]['subsections'] = effective[0]['subsections'][:1]
    return outline, tasks, {'report_scope': scope, 'effective_outline': effective,
                            'section_answers': [{'outline_id': 'S1.1', 'answer': '比较同年度公司收入规模。', 'citation_ids': ['C1']},
                                                {'outline_id': 'S1.2', 'answer': '说明比较边界，不作业务收入排名。', 'citation_ids': []}],
                            'outline_operations': [{'kind': 'delete', 'source_ids': ['S1.2'], 'target_id': None, 'reason': '无独立内容'}]}


def test_scope_adopts_title_and_outline_and_attaches_same_definition():
    outline, tasks, review = fixture()
    final, final_tasks, scope, notes, warnings = apply_report_scope(outline, tasks, review, '比较企业经营表现', '前十企业排名')
    assert not warnings and notes and scope['status'] == 'completed'
    assert scope['original_title'] == '前十企业排名'
    assert scope['effective_title'] == '代表企业经营比较'
    assert final[0]['level1_title'] == '代表企业经营'
    assert final_tasks[0]['parent_level1_title'] == '代表企业经营'
    assert final_tasks[0]['report_scope'] == scope
    assert len(final_tasks) == 1 and len(tasks) == 2


def test_invalid_scope_rolls_back_title_and_outline_with_incomplete_status():
    outline, tasks, review = fixture()
    review['report_scope']['coverage'][0]['section_ids'] = ['S99']
    final, final_tasks, scope, notes, warnings = apply_report_scope(outline, tasks, review, '比较企业经营表现', '前十企业排名')
    assert final == outline and scope['effective_title'] == '前十企业排名'
    assert scope['status'] == 'incomplete' and warnings and not notes
    assert len(final_tasks) == 2


def test_unavailable_retrieval_cannot_be_interpreted_as_absent_industry_evidence():
    outline, tasks, review = fixture()
    tasks[1]['external_rag_retrieval']['status'] = 'error'
    tasks[1]['evidence_pack'] = {'status': 'unavailable', 'requirements': []}
    _, _, scope, _, warnings = apply_report_scope(outline, tasks, review, '比较企业经营表现', '前十企业排名')
    assert scope['status'] == 'incomplete' and warnings


def test_background_only_cannot_claim_substantive_brief_without_covered_evidence():
    outline, tasks, review = fixture()
    review['report_scope']['coverage'][0]['status'] = 'insufficient'
    _, _, scope, _, warnings = apply_report_scope(outline, tasks, review, '比较企业经营表现', '前十企业排名')
    assert scope['status'] == 'incomplete' and warnings


def test_scope_rejects_added_or_implicitly_removed_ids():
    outline, tasks, review = fixture()
    review['outline_operations'] = []
    _, _, scope, _, warnings = apply_report_scope(outline, tasks, review, '比较企业经营表现', '前十企业排名')
    assert scope['status'] == 'incomplete' and warnings


def test_final_task_order_matches_adopted_outline():
    outline, tasks, review = fixture()
    review['outline_operations'] = []
    review['effective_outline'] = copy.deepcopy(outline)
    review['effective_outline'][0]['subsections'].reverse()
    _, ordered, scope, _, warnings = apply_report_scope(outline, tasks, review, '比较企业经营表现', '前十排名')
    assert not warnings
    assert [t['outline_id'] for t in ordered] == ['S1.2', 'S1.1']


def test_merged_graph_clues_reach_effective_writer_context():
    from report_generation.body_agent import _build_body_user_prompt
    outline, tasks, review = fixture()
    tasks[1]['graph_retrieval'] = {'status': 'success', 'graph_context_text': '来源小节独有线索',
                                   'evidence_blocks': [{'segment': {'name': '线索'}}]}
    review['outline_operations'][0].update(kind='merge', target_id='S1.1')
    _, final, _, _, warnings = apply_report_scope(outline, tasks, review, '企业比较', '报告')
    assert not warnings
    assert '来源小节独有线索' in _build_body_user_prompt(final[0], '企业比较', '报告')


def test_coverage_uses_explicit_merge_mapping_before_validating_final_ids():
    outline, tasks, review = fixture()
    review['outline_operations'][0].update(kind='merge', target_id='S1.1')
    review['report_scope']['coverage'][0]['section_ids'] = ['S1.1', 'S1.2']
    _, final, scope, _, warnings = apply_report_scope(outline, tasks, review, '企业比较', '报告')
    assert not warnings and len(final) == 1
    assert scope['coverage'][0]['section_ids'] == ['S1.1']


def test_deleted_coverage_is_retained_as_an_explicit_uncovered_requirement():
    outline, tasks, review = fixture()
    review['report_scope']['coverage'].append({'requirement': '背景专题', 'status': 'insufficient',
        'section_ids': ['S1.2'], 'reason': '无独立材料，合并说明缺口'})
    _, _, scope, _, warnings = apply_report_scope(outline, tasks, review, '企业比较', '报告')
    assert not warnings
    assert scope['coverage'][1]['section_ids'] == []


def test_supported_coverage_cannot_silently_drop_deleted_support_section():
    outline, tasks, review = fixture()
    review['report_scope']['coverage'][0].update(status='supported', section_ids=['S1.1', 'S1.2'])
    _, _, scope, _, warnings = apply_report_scope(outline, tasks, review, '企业比较', '报告')
    assert scope['status'] == 'incomplete'
    assert warnings

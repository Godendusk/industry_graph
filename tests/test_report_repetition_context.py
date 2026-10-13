from report_generation import repetition_context as rc


def section(text, blocks=None, **kwargs):
    return dict(outline_id='S1.1', title='布局', status='success', body_text=text,
                external_evidence_blocks=blocks or [], **kwargs)


def task(blocks, terms=None):
    return {'title': '建议', 'repetition_focus_terms': terms or [],
            'external_rag_retrieval': {'evidence_blocks': blocks}}


def test_records_keep_late_fact_post_sentence_citations_and_unterminated_edits():
    rows = rc.build_fact_records([section('背景。政策[C1]。成本[C2]。融资80%[C4]。末句。[C5]\n编辑[C6]'),
                                 dict(status='error', body_text='失败[C9]。')])
    assert [r['citation_ids'] for r in rows] == [['C1'], ['C2'], ['C4'], ['C5'], ['C6']]
    assert rows[-2]['sentence'] == '末句。[C5]'
    assert rows[-1]['sentence'] == '编辑[C6]'


def test_cross_source_specific_object_and_generic_filter():
    prior = [section('首句。中国移动牵头成立具身智能产业联盟[C14]。')]
    current = task([{'citation_id': 'C17', 'text': '中国移动牵头成立具身智能产业联盟。'}],
                   ['中国移动', '具身智能产业联盟', '产业协同', '500个'])
    assert rc.focus_terms_for_task(current) == ['中国移动', '具身智能产业联盟']
    context = rc.build_prior_context(prior, current)
    assert '中国移动牵头成立具身智能产业联盟[C14]' in context['text']
    assert context['matched_fact_count'] == 1
    assert rc.build_prior_context(prior, task([{'text': '产业协同'}], ['产业协同']))['matched_fact_count'] == 0


def test_focus_grounding_and_fallback_quotes():
    grounding = '500个人工智能应用场景，中国移动，《具体产业研究报告》'
    assert rc.normalize_focus_terms(['500个', '500个人工智能应用场景', '虚构政策名称', '中国移动'], grounding) == ['500个人工智能应用场景', '中国移动']
    assert rc.focus_terms_for_task(task([{'text': grounding}])) == ['具体产业研究报告']


def test_same_material_different_id_and_full_late_sentence():
    prior = [section('首句。第一条[C1]。第二条[C2]。后文融资80%[C4]。',
                     [{'citation_id': 'C4', 'library': 'n', 'material_id': 'm'}])]
    current = task([{'citation_id': 'C8', 'library': 'n', 'material_id': 'm'}])
    context = rc.build_prior_context(prior, current)
    assert '后文融资80%[C4]。' in context['text']
    assert context['matched_fact_count'] == 1


def test_budget_round_robin_omissions_and_all_topic_titles():
    prior = [section('甲一[C1]。甲二[C1]。乙一[C2]。')]
    current = task([{'citation_id': 'C1'}, {'citation_id': 'C2'}])
    context = rc.build_prior_context(prior, current, fact_budget=45, topic_budget=1)
    assert '甲一[C1]' in context['text'] and '乙一[C2]' in context['text']
    assert '甲二[C1]' not in context['text']
    assert context['omitted_fact_count'] == 1
    assert 'S1.1' in context['text'].split('【前文主题】')[1]


def test_exact_repeat_dedup_and_oversize_sentence_is_not_cut():
    prior = [section('同事实[C1]。同事实[C2]。' + '长' * 200 + '[C1]。')]
    context = rc.build_prior_context(prior, task([{'citation_id': 'C1'}, {'citation_id': 'C2'}]), fact_budget=100)
    assert context['text'].split('【前文主题】')[0].count('同事实') == 1
    assert context['omitted_fact_count'] == 1
    assert '长' not in context['text'].split('【前文主题】')[0]


def test_semicolon_keeps_fact_with_its_sentence_end_citation():
    records=rc.build_fact_records([section('中国融资约80%；美国依赖VC/PE[C4]。')])
    assert records[0]['sentence']=='中国融资约80%；美国依赖VC/PE[C4]。'

import copy
from report_generation.report_facts import fact_sources, validate_facts, attach_facts


def tasks():
    return [{'outline_id': 'S1.1', 'title': '产品进展', 'writing_decision': {'section_question': '甲公司产品A状态'},
             'external_rag_retrieval': {'evidence_blocks': [{'citation_id': 'C1', 'vector_id': 'v1',
                 'text': '甲公司产品A于2025年3月取得型号合格证。产品B计划2026年申请。', 'publish_date': '2025-04-01'}]}},
            {'outline_id': 'S2.1', 'title': '甲公司产品A运营', 'external_rag_retrieval': {'evidence_blocks': []}}]


def fact(source, **kw):
    return {'subject': '甲公司产品A', 'attribute': '型号合格证', 'value': '已取得', 'event_time': '2025年3月',
            'published_at': '2025-04-01', 'modality': 'actual', 'applicability': '仅产品A，不推及产品B',
            'supports': [{'evidence_id': source['evidence_id'], 'citation_id': 'C1', 'quote': '甲公司产品A于2025年3月取得型号合格证。'}], **kw}


def test_facts_preserve_product_time_and_modality_without_latest_date_override():
    sources = fact_sources(tasks())
    actual = fact(sources[0]); plan = fact(sources[0], subject='甲公司产品B', value='计划申请',
        event_time='2026年', modality='planned', applicability='仅产品B', supports=[{
        'evidence_id': sources[0]['evidence_id'], 'citation_id': 'C1', 'quote': '产品B计划2026年申请。'}])
    valid, warnings = validate_facts([actual, plan], sources)
    assert not warnings
    assert len(valid) == 2
    assert valid[0]['event_time'] != valid[0]['published_at']
    assert valid[1]['modality'] == 'planned'
    assert valid[0]['subject'] != valid[1]['subject']


def test_fact_cannot_bind_forged_quote_or_wrong_citation():
    sources = fact_sources(tasks()); f = fact(sources[0])
    f['supports'][0]['citation_id'] = 'C999'
    assert not validate_facts([f], sources)[0]
    f = fact(sources[0]); f['supports'][0]['quote'] = '产品B已投产。'
    assert not validate_facts([f], sources)[0]


def test_shared_fact_attaches_original_source_to_related_task_without_mutation():
    original = tasks(); saved = copy.deepcopy(original); sources = fact_sources(original)
    valid, _ = validate_facts([fact(sources[0])], sources)
    result = attach_facts(original, valid, sources)
    assert original == saved
    assert result[1]['report_facts'][0]['subject'] == '甲公司产品A'
    assert result[1]['external_rag_retrieval']['evidence_blocks'][0]['citation_id'] == 'C1'
    assert '[C1]' in result[1]['external_rag_retrieval']['rag_context_text']
    assert result[1]['external_rag_retrieval']['evidence_blocks'][0]['text'] == original[0]['external_rag_retrieval']['evidence_blocks'][0]['text']


def test_key_fact_cannot_add_a_plan_year_absent_from_its_bound_quote():
    sources = fact_sources(tasks()); f = fact(sources[0])
    f['value'] = '已取证，预计2026年量产'
    assert not validate_facts([f], sources)[0]


def test_key_fact_publication_date_must_match_source_metadata():
    sources = fact_sources(tasks()); f = fact(sources[0], published_at='2026-12-01')
    assert not validate_facts([f], sources)[0]


def test_fact_source_budget_covers_late_sections_before_early_second_sources():
    data = []
    for i in range(15):
        data.append({'outline_id': f'S{i+1}.1', 'external_rag_retrieval': {'evidence_blocks': [
            {'citation_id': f'C{i*2+1}', 'text': f'企业{i}计划交付。' + '背景资料。' * 600},
            {'citation_id': f'C{i*2+2}', 'text': f'企业{i}收入披露。' + '重复背景。' * 600}]}})
    sources = fact_sources(data)
    assert 'C29' in {s['citation_id'] for s in sources}
    assert sum(len(s['text']) for s in sources) <= 12000


def test_answer_plan_can_request_a_shared_fact_with_its_original_block():
    original = tasks()
    original[1]['title'] = '跨场景比较'
    original[1]['section_answer'] = {'outline_id': 'S2.1', 'answer': '区分取证与商业运营状态。', 'citation_ids': ['C1']}
    sources = fact_sources(original)
    valid, _ = validate_facts([fact(sources[0])], sources)
    adopted = attach_facts(original, valid, sources)
    assert adopted[1]['external_rag_retrieval']['evidence_blocks'][0]['citation_id'] == 'C1'


def test_key_fact_does_not_duplicate_source_already_present_with_other_ranking():
    original=tasks();sources=fact_sources(original)
    block=copy.deepcopy(original[0]['external_rag_retrieval']['evidence_blocks'][0])
    block['rerank_score']=0.98
    original[1]['external_rag_retrieval']['evidence_blocks']=[block]
    valid,_=validate_facts([fact(sources[0])],sources)
    adopted=attach_facts(original,valid,sources)
    assert len(adopted[1]['external_rag_retrieval']['evidence_blocks'])==1

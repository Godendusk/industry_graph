import json
from types import SimpleNamespace

import pytest

from report_generation.agentic_rag.planner import plan_chapter


def context(**overrides):
    return dict(outline_id='S1.1', industry='embodied', report_title='产业报告',
                user_prompt='分析2024—2026年企业竞争格局', chapter_title='竞争格局',
                chapter_goal='比较产品与订单', content_requirements=['产品', '订单'],
                writing_focus='区分计划与落地', suggested_query='',
                time_requirement='2024—2026年', use_graph=True,
                use_external_rag=True, fallback_query='固定章节查询', **overrides)


def model_payload(queries=None, **overrides):
    return dict(industry='embodied', sub_queries=queries or [dict(
        question='2024—2026年代表企业产品', strategy='hybrid',
        evidence_requirements=['企业产品原文'], reason='需要原文支持产品布局')], **overrides)


def answer(payload):
    return lambda **kwargs: SimpleNamespace(content=json.dumps(payload, ensure_ascii=False),
                                             finish_reason='stop', error_message='')


def test_simple_and_complex_plans_preserve_context_and_have_one_to_three_queries():
    ctx = context()
    captured = []
    def ask(**kwargs):
        captured.append(json.loads(kwargs['user_prompt']))
        return answer(model_payload())()
    simple = plan_chapter(ctx, query_model=ask)
    assert simple['status'] == 'planned'
    assert len(simple['sub_queries']) == 1
    assert captured[0]['time_requirement'] == '2024—2026年'
    assert captured[0]['writing_focus'] == ctx['writing_focus']
    queries = [dict(question=q, strategy=s, evidence_requirements=['原文'], reason='章节需要')
               for q, s in [('企业产品', 'hybrid'), ('产业环节', 'graph_hybrid'), ('企业订单', 'hybrid')]]
    complex_plan = plan_chapter(ctx, query_model=answer(model_payload(queries)))
    assert len(complex_plan['sub_queries']) == 3
    assert complex_plan['industry'] == 'embodied'


@pytest.mark.parametrize('payload', [
    {**model_payload(), 'industry': 'ai'},
    model_payload([dict(question='', strategy='hybrid', evidence_requirements=['原文'], reason='需要')]),
    model_payload([dict(question='产品', strategy='shell', evidence_requirements=['原文'], reason='需要')]),
    model_payload([dict(question='产品', strategy='hybrid', evidence_requirements=[], reason='需要')]),
    model_payload([dict(question=f'q{i}', strategy='hybrid', evidence_requirements=['原文'], reason='需要') for i in range(4)]),
])
def test_invalid_plan_falls_back_to_exact_existing_query(payload):
    plan = plan_chapter(context(), query_model=answer(payload))
    assert plan['status'] == 'fallback'
    assert plan['sub_queries'][0]['question'] == '固定章节查询'
    assert plan['industry'] == 'embodied'
    assert plan['fallback_reason']


def test_disabled_graph_cannot_be_reenabled_by_plan():
    ctx = context(); ctx['use_graph'] = False
    query = dict(question='关系', strategy='graph_hybrid', evidence_requirements=['关系原文'], reason='需要')
    assert plan_chapter(ctx, query_model=answer(model_payload([query])))['status'] == 'fallback'


def test_failed_or_truncated_model_records_reason_and_no_retry():
    calls = []
    def broken(**kwargs):
        calls.append(kwargs)
        raise TimeoutError('planner timeout')
    assert 'planner timeout' in plan_chapter(context(), query_model=broken)['fallback_reason']
    assert len(calls) == 1
    truncated = lambda **kwargs: SimpleNamespace(content=json.dumps(model_payload()), finish_reason='length', error_message='')
    assert plan_chapter(context(), query_model=truncated)['status'] == 'fallback'


def test_both_sources_disabled_skips_model_and_retrieval_plan():
    ctx = context(); ctx.update(use_graph=False, use_external_rag=False)
    def forbidden(**kwargs):
        raise AssertionError('must not call model')
    plan = plan_chapter(ctx, query_model=forbidden)
    assert plan['status'] == 'skipped'
    assert plan['sub_queries'] == []


def test_duplicate_queries_are_not_executed_twice():
    query = model_payload()['sub_queries'][0]
    plan = plan_chapter(context(), query_model=answer(model_payload([query, query])))
    assert len(plan['sub_queries']) == 1

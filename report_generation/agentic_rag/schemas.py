"""Validation for the small, JSON-safe chapter retrieval plan."""

from report_generation.structured_output import clean_text_list

MAX_SUB_QUERIES = 3
STRATEGIES = {'hybrid', 'graph_hybrid', 'graph'}


def validate_queries(payload, context):
    if payload.get('industry') != context['industry']:
        raise ValueError('检索计划不能改变报告行业')
    queries = payload.get('sub_queries')
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_SUB_QUERIES:
        raise ValueError('计划必须包含1至3个子问题')
    result, seen = [], set()
    for query in queries:
        if not isinstance(query, dict):
            raise ValueError('子问题必须是对象')
        question, reason = query.get('question'), query.get('reason')
        strategy = query.get('strategy')
        requirements = clean_text_list(query.get('evidence_requirements'))
        if not isinstance(question, str) or not question.strip():
            raise ValueError('子问题不能为空')
        if not isinstance(reason, str) or not reason.strip() or not requirements:
            raise ValueError('子问题需要检索原因和证据要求')
        if not isinstance(strategy, str) or strategy not in STRATEGIES:
            raise ValueError('计划包含未实现的检索策略')
        if strategy in ('graph', 'graph_hybrid') and not context['use_graph']:
            raise ValueError('当前任务未启用图谱')
        if strategy in ('hybrid', 'graph_hybrid') and not context['use_external_rag']:
            raise ValueError('当前任务未启用外部资料')
        # When documents are enabled, graph navigation must still fetch original evidence.
        if strategy == 'graph' and context['use_external_rag']:
            raise ValueError('启用外部资料时图谱关系应使用graph_hybrid查找原文')
        key = ' '.join(question.split())
        if key in seen:
            continue
        seen.add(key)
        result.append({'id': f'q{len(result)+1}', 'question': question.strip(),
                       'strategy': strategy, 'evidence_requirements': requirements,
                       'reason': reason.strip()})
    return result

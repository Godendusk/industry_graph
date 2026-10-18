"""One model call to plan chapter retrieval, with an exact fixed-query fallback."""

import copy
import json
import time

from llm_client import llm
from report_generation.structured_output import parse_json_object
from .schemas import validate_queries

SYSTEM_PROMPT = '''你是产业报告章节检索规划器，只规划当前小节，不生成报告正文。
根据输入章节目标、写作重点、内容要求及用户需求生成1至3个具体子问题；简单章节只需1个。
保留需求中的时间、研究对象与事实状态限定，不扩大产业范围，不凭空指定企业或预定排名。
仅返回JSON：{"industry":"输入行业", "sub_queries":[{"question":"检索问题", "strategy":"hybrid或graph_hybrid或graph", "evidence_requirements":["需要原文回答的具体问题"], "reason":"选择此路径的简短原因"}]}。
industry必须逐字复制输入industry字段的行业代码（如embodied、biology），不能改为中文行业名或“输入行业”字样。
hybrid检索政策、产品、订单等原文；graph_hybrid先用图谱定位产业环节和企业，再联合原文检索。
graph仅在外部资料关闭、图谱开启时可用；不得重新开启被关闭的数据源。
图谱线索不等于事实证明。无需固定拆成3问，不重复查询，不返回参数、代码、文件路径或正文。'''


def plan_chapter(context, *, query_model=None):
    started = time.monotonic()
    plan = {'version': 'chapter_plan_v1', 'outline_id': context['outline_id'],
            'industry': context['industry'], 'input': copy.deepcopy(context),
            'status': 'skipped', 'sub_queries': [], 'fallback_reason': ''}
    if not context['use_graph'] and not context['use_external_rag']:
        plan['elapsed_seconds'] = time.monotonic() - started
        return plan
    try:
        result = (query_model or llm.query_result)(
            user_prompt=json.dumps(context, ensure_ascii=False), system_prompt=SYSTEM_PROMPT,
            temperature=0, max_tokens=1800, reasoning_effort='low',
            extra_body={'thinking': {'type': 'disabled'}},
            extra_log_info=f"report_generation.agentic_planner outline={context['outline_id']}",
        )
        if result.error_message:
            raise ValueError(result.error_message)
        if result.finish_reason == 'length':
            raise ValueError('检索计划输出被截断')
        plan['sub_queries'] = validate_queries(parse_json_object(result.content), context)
        plan['status'] = 'planned'
    except Exception as exc:
        strategy = ('graph_hybrid' if context['use_graph'] else 'hybrid') if context['use_external_rag'] else 'graph'
        plan.update(status='fallback', fallback_reason=str(exc), sub_queries=[{
            'id': 'q1', 'question': context['fallback_query'], 'strategy': strategy,
            'evidence_requirements': context['content_requirements'] or [context['chapter_title']],
            'reason': '规划未完成，沿用固定章节查询',
        }])
    plan['elapsed_seconds'] = time.monotonic() - started
    return plan

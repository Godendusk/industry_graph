"""Evidence requirements, bounded semantic assessment and post-allocation binding."""

import copy
import json
import time

from llm_client import llm
from report_generation.structured_output import parse_json_object

MAX_EVIDENCE_CHARS = 20000
MAX_CHUNK_CHARS = 2000
STATUSES = {'supported', 'insufficient', 'conflicting', 'unknown'}
SYSTEM_PROMPT = '''你是产业报告章节证据评估器，只判断输入原文对每项需求的支持情况，不写正文。
逐项返回全部requirements，id不可新增或省略，只返回JSON：
{"requirements":[{"id":"r1","status":"supported/insufficient/conflicting/unknown", "reason":"具体判断原因", "support":[{"evidence_id":"e1","quote":"逐字原文"}], "follow_up_query":"针对该缺口的新查询，可为空", "strategy":"hybrid或graph_hybrid"}]}。
supported必须有确实回答该需求的原文及逐字quote，仅提到企业不能证明排名或订单。
需求含比较、情景或建议时，分别核对形成分析所需的事实前提与范围；不同片段分别支持两类对象的事实即可用于对照，不要求某一篇文章已经直接给出本报告的比较结论或建议。reason说明哪些事实足以支撑何种有限分析、哪些具体事实仍缺失，不能仅以缺少“对照性原文”判定无法分析。
conflicting需要至少两个原文片段，先区分对象、日期、单位及统计口径；不同口径不直接算矛盾。
insufficient表示现有完整片段不足；截断、遗漏、日期未知或判断不明确应返回unknown。
严格区分资料发布日期与事件时间、预测/计划与已实现、工业机器人与人形机器人。
原文缺日期不能自动证明指定年份。背景资料可以较早，但不能充当指定年份动态。
遵守review_note、evidence_scope、review_method；图谱绑定只是线索，仍须由原文支持具体关系。
不能从融资、产品发布或榜单名次推断市场份额；分析推断要区别于事实。
项目申报指南、单个示范项目或单个样本只能支持对应项目/样本的要求和状态，不能直接作为整个技术路线普遍的工程门槛、成本优势或准入条件。reason说明适用对象与能够回答的有限问题，后续写作即使加“仅供参考”也不能保留越界结论。
补查只针对未解决需求，不重复初查，不凭空指定企业；关闭图谱时不能使用graph_hybrid。
证据充分不要求多来源凑数，也不提供置信评分。'''


def evidence_key(block):
    return {'library': str(block.get('library') or ''),
            'material_id': str(block.get('material_id') or block.get('document_id') or ''),
            'vector_id': str(block.get('chunk_id') or block.get('vector_id') or '')}


def _key(value):
    return tuple(value.get(k, '') for k in ('library', 'material_id', 'vector_id'))


def _requirements(plan):
    values = list(plan.get('input', {}).get('content_requirements') or [])
    values.extend(r for query in plan.get('sub_queries', []) for r in query.get('evidence_requirements', []))
    if not values:
        values = [plan.get('input', {}).get('chapter_title') or '当前章节目标']
    return [{'id': f'r{i+1}', 'requirement': text, 'status': 'unknown',
             'support': [], 'reason': '', 'follow_up_query': '', 'strategy': 'hybrid'}
            for i, text in enumerate(dict.fromkeys(values))]


def _refresh(pack):
    pack['uncovered_requirements'] = [r['id'] for r in pack['requirements'] if r['status'] != 'supported']
    pack['conflicts'] = [copy.deepcopy(r) for r in pack['requirements'] if r['status'] == 'conflicting']
    constraints = ['项目要求、单个示范或样本只在对应对象内使用；不得用项目申报指南推导整条产业路线的普遍工程、成本或准入条件。',
                   '区分原文事实和分析推断；未绑定原文的图谱关系仅用于定位，不作为事实证明。',
                   '比较、情景或建议属于本报告的分析任务；可综合不同片段已支持的事实提出有限比较，写明假设与边界，不要求资料直接给出同一结论。需求未充分支持时不得补造缺失事实，也不应仅因缺少现成对照结论而放弃有事实基础的分析。']
    for row in pack['requirements']:
        text = row['requirement']
        if row['status'] == 'conflicting':
            constraints.append(f'{text}存在资料差异：{row["reason"]}。保留不同来源及时间口径，不能擅自选择一个数字。')
        elif row['status'] != 'supported':
            if any(term in text for term in ('排名', '份额', '出货', '产能', '规模', '预测')):
                action = '缺少可比依据时仅比较公开产品或动态，不生成确定排名、数值或已兑现产能。'
            elif any(term in text for term in ('政策', '条款', '发布日期')):
                action = '未确认的政策名称、日期与条款不写成已核实事实，保留待确认项。'
            else:
                action = '只写实际原文支持的范围，明确必要的缺口，不生成该项确定性结论。'
            constraints.append(f'尚未充分支持：{text}（{row["reason"]}）。{action}')
    pack['writing_constraints'] = constraints
    return pack


def assess_evidence(plan, blocks, *, retrieval_status, query_model=None):
    started = time.monotonic()
    pack = {'outline_id': plan['outline_id'], 'industry': plan['industry'], 'status': 'assessed',
            'requirements': _requirements(plan), 'warnings': [], 'model_calls': 0,
            'input_diagnostics': {'omitted_count': 0, 'truncated_count': 0}}

    def finish():
        pack['elapsed_seconds'] = time.monotonic() - started
        return _refresh(pack)

    if not plan.get('input', {}).get('use_external_rag', True):
        pack['status'] = 'skipped'
        for row in pack['requirements']:
            row['reason'] = '未启用外部原文检索；图谱线索不能替代原文'
        return finish()
    if retrieval_status == 'error' and not blocks:
        pack['status'] = 'unavailable'
        for row in pack['requirements']:
            row['reason'] = '原文检索服务失败，无法判断资料是否存在'
        return finish()
    if not blocks:
        for row in pack['requirements']:
            row.update(status='insufficient', reason='本次查询未召回可用原文',
                       follow_up_query=' '.join(filter(None, (plan.get('input', {}).get('chapter_title', ''), row['requirement'], plan.get('input', {}).get('time_requirement', '')))))
        return finish()
    evidence, lookup, budget = [], {}, MAX_EVIDENCE_CHARS
    for block in blocks:
        if block.get('industry', plan['industry']) != plan['industry'] or not block.get('text'):
            continue
        raw = str(block['text'])
        if budget <= 0:
            pack['input_diagnostics']['omitted_count'] += 1
            continue
        text = raw[:min(MAX_CHUNK_CHARS, budget)]
        budget -= len(text)
        id = f'e{len(evidence)+1}'
        item = {field: block.get(field, '') for field in (
            'title', 'publish_date', 'source_address', 'evidence_scope', 'review_note', 'review_method')}
        item.update(evidence_id=id, text=text, truncated=len(text) < len(raw))
        pack['input_diagnostics']['truncated_count'] += int(item['truncated'])
        evidence.append(item); lookup[id] = (block, text)
    if not evidence:
        for row in pack['requirements']:
            row['reason'] = '候选没有同产业可用正文片段'
        return finish()
    payload = {'context': plan.get('input', {}), 'requirements': pack['requirements'],
               'initial_queries': [q['question'] for q in plan.get('sub_queries', [])],
               'evidence': evidence, 'input_diagnostics': pack['input_diagnostics']}
    try:
        pack['model_calls'] = 1
        result = (query_model or llm.query_result)(user_prompt=json.dumps(payload, ensure_ascii=False),
            system_prompt=SYSTEM_PROMPT, temperature=0, max_tokens=4000, reasoning_effort='low',
            extra_body={'thinking': {'type': 'disabled'}},
            extra_log_info=f"report_generation.agentic_assessment outline={plan['outline_id']}")
        if result.error_message or result.finish_reason == 'length':
            raise ValueError(result.error_message or '证据评估输出被截断')
        rows = parse_json_object(result.content).get('requirements')
        if not isinstance(rows, list):
            raise ValueError('证据评估缺少requirements数组')
        by_id = {r.get('id'): r for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)}
        if len(by_id) != len(rows) or set(by_id) != {r['id'] for r in pack['requirements']}:
            raise ValueError('证据评估需求编号缺失、重复或新增')
        for requirement in pack['requirements']:
            row = by_id[requirement['id']]
            try:
                if row.get('status') not in STATUSES or not isinstance(row.get('reason'), str) or not row['reason'].strip():
                    raise ValueError('评估状态或判断原因无效')
                support = []
                for ref in row.get('support', []):
                    id, quote = ref.get('evidence_id'), ref.get('quote')
                    if not isinstance(id, str) or id not in lookup or not isinstance(quote, str) or not quote.strip() or quote not in lookup[id][1]:
                        raise ValueError('支持依据不是输入片段的逐字原文')
                    bound = {'evidence_key': evidence_key(lookup[id][0]), 'quote': quote}
                    if bound not in support:
                        support.append(bound)
                if row['status'] == 'supported' and not support:
                    raise ValueError('有支持必须绑定原文')
                if row['status'] == 'conflicting' and len({_key(s['evidence_key']) for s in support}) < 2:
                    raise ValueError('冲突必须保留至少两段原文')
                status = row['status']
                if status == 'insufficient' and any(pack['input_diagnostics'].values()):
                    status = 'unknown'
                follow_up = row.get('follow_up_query', '')
                strategy = row.get('strategy', 'hybrid')
                if not isinstance(follow_up, str):
                    follow_up = ''
                if strategy not in ('hybrid', 'graph_hybrid') or (strategy == 'graph_hybrid' and not plan.get('input', {}).get('use_graph', False)):
                    follow_up = ''; strategy = 'hybrid'
                requirement.update(status=status, support=support, reason=row['reason'].strip(),
                    follow_up_query=follow_up.strip() if status != 'supported' else '', strategy=strategy)
            except (ValueError, TypeError, AttributeError) as exc:
                requirement.update(status='unknown', support=[], reason=str(exc), follow_up_query='')
                pack['warnings'].append({'stage': 'agentic_assessment', 'requirement_id': requirement['id'], 'message': str(exc)})
    except Exception as exc:
        pack['status'] = 'failed'
        for row in pack['requirements']:
            row.update(status='unknown', support=[], reason=f'评估未完成：{exc}', follow_up_query='')
        pack['warnings'].append({'stage': 'agentic_assessment', 'message': str(exc)})
    return finish()


def reconcile_allocation(pack, selected, candidates, limit):
    """Restore all support chunks that fit; downgrade any unsupported binding."""
    pack = copy.deepcopy(pack)
    by_key = {_key(evidence_key(b)): b for b in candidates}
    selected = copy.deepcopy(selected[:limit])
    protected = set()
    for requirement in sorted(pack['requirements'], key=lambda r: r['status'] == 'insufficient'):
        if requirement['status'] not in ('supported', 'conflicting', 'insufficient'):
            continue
        required = {_key(s['evidence_key']) for s in requirement['support']}
        if not required.issubset(by_key) or len(protected | required) > limit:
            requirement.update(status='unknown', support=[], follow_up_query='', reason='资料分配容量不足或支持片段缺失，不能保留完整依据')
            continue
        protected.update(required)
    preserved = [copy.deepcopy(by_key[k]) for k in by_key if k in protected]
    seen = set(protected)
    for block in selected:
        key = _key(evidence_key(block))
        if len(preserved) < limit and key not in seen:
            preserved.append(block); seen.add(key)
    pack['allocation_status'] = 'checked'
    return preserved, _refresh(pack)


def bind_citations(pack, blocks):
    pack = copy.deepcopy(pack)
    by_key = {_key(evidence_key(b)): b for b in blocks}
    for requirement in pack['requirements']:
        for support in requirement['support']:
            block = by_key.get(_key(support['evidence_key']))
            if block and support['quote'] in str(block.get('text', '')) and block.get('citation_id'):
                support['citation_id'] = block['citation_id']
            else:
                requirement.update(status='unknown', reason='分配后的原文或引用绑定不可用', follow_up_query='')
    return _refresh(pack)


def render_evidence_pack(pack):
    if not pack:
        return ''
    lines = [f"章节证据评估：{pack.get('outline_id', '')} / {pack['status']}"]
    for row in pack['requirements']:
        lines.append(f"{row['requirement']}：{row['status']}；{row['reason']}")
        for support in row['support']:
            if support.get('citation_id'):
                lines.append(f"[{support['citation_id']}] {support['quote'][:400]}")
    lines.extend(pack['writing_constraints'])
    return '\n'.join(lines)

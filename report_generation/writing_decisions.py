"""Compact section decisions, source eligibility, and sequential arrangements."""

from __future__ import annotations

import json

from llm_client import llm

from .structured_output import parse_json_object


MAX_PRIOR_LEDGER_CHARS = 8000

COMMON_DECISION_RULES = '''围绕本节问题作答，自行组织自然段，不预设必须得出的结论。
已展开背景通常短句承接，同一资料允许支持不同分析用途。
无新增分析或证据不足时允许缩短，必要时说明现有公开材料不足以判断。
原始材料是事实依据；任务书和前节分工记录不是事实证据。
只能使用当前材料真实的[C数字]；未列为重点的当前证据也可用于符合本节问题的新分析。
区分事实、分析和待验证条件，不把建议反推为现实问题，不把行业短板套到央企群体。
图谱只证明记录的产业关系，不证明技术水平、经营状况或实施成效。'''

PRIOR_LEDGER_PREFIX = (
    '此前写作安排，不是事实证据；以全篇大纲选择最适合的小节，'
    '允许把完整展开留给后节；冲突交最终协调。\n'
)


def compact_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f'{label}必须是包含规定字段的对象')


def _text(value, maximum, label, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f'{label}必须是字符串')
    value = value.strip()
    if (not value and not allow_empty) or len(value) > maximum:
        raise ValueError(f'{label}为空或超过{maximum}字符')
    return value


def _list(value, maximum, label):
    if not isinstance(value, list) or (maximum is not None and len(value) > maximum):
        raise ValueError(f'{label}必须是列表且条数在限制内')
    return value


def _unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def validate_decision_shape(value) -> dict:
    """Normalize a fresh copy without repeating source or outline validation."""
    _object(value, ('section_question', 'evidence_uses', 'content_scope', 'judgment_limits'), '决策')
    question = _text(value['section_question'], 100, 'section_question')
    uses = []
    for item in _list(value['evidence_uses'], 4, 'evidence_uses'):
        _object(item, ('topic', 'basis', 'citation_ids', 'use', 'support_limit'), '证据用途')
        basis = _text(item['basis'], 8, 'basis')
        if basis not in ('external', 'graph'):
            raise ValueError('basis必须是external或graph')
        ids = _unique([_text(cid, 60, 'citation_id')
                       for cid in _list(item['citation_ids'], None, 'citation_ids')])
        if basis == 'external' and not ids:
            raise ValueError('external用途必须提供当前引用编号')
        uses.append({'topic': _text(item['topic'], 60, 'topic'), 'basis': basis,
                     'citation_ids': ids, 'use': _text(item['use'], 120, 'use'),
                     'support_limit': _text(item['support_limit'], 120, 'support_limit', True)})
    scope = value['content_scope']
    _object(scope, ('full_exposition', 'carry_over'), 'content_scope')
    full = _unique([_text(topic, 60, 'full_exposition.topic')
                    for topic in _list(scope['full_exposition'], 3, 'full_exposition')])
    carry = []
    for item in _list(scope['carry_over'], 3, 'carry_over'):
        _object(item, ('topic', 'section_id', 'use'), '承接安排')
        carry.append({'topic': _text(item['topic'], 60, 'carry_over.topic'),
                      'section_id': _text(item['section_id'], 60, 'section_id'),
                      'use': _text(item['use'], 120, 'carry_over.use')})
    limits = _unique([_text(item, 120, 'judgment_limit')
                      for item in _list(value['judgment_limits'], 3, 'judgment_limits')])
    normalized = {'section_question': question, 'evidence_uses': _unique(uses),
                  'content_scope': {'full_exposition': full, 'carry_over': _unique(carry)},
                  'judgment_limits': limits}
    return normalized


def validate_decision(value, task, outline_ids) -> dict:
    normalized = validate_decision_shape(value)
    allowed_ids = {block.get('citation_id') for block in
                   (task.get('external_rag_retrieval') or {}).get('evidence_blocks', [])}
    for item in normalized['evidence_uses']:
        if any(cid not in allowed_ids for cid in item['citation_ids']):
            raise ValueError('证据用途包含不属于当前材料的引用编号')
        if item['basis'] == 'graph' and (task.get('graph_retrieval') or {}).get('status') != 'success':
            raise ValueError('graph用途需要当前图谱检索成功')
    for item in normalized['content_scope']['carry_over']:
        if item['section_id'] == task.get('outline_id') or item['section_id'] not in outline_ids:
            raise ValueError('承接小节不存在或指向自身')
    return normalized


def fallback_decision(task) -> dict:
    question = f"围绕“{task.get('title', '')}”回答本节问题。"
    if len(question) > 100:
        question = '回答当前二级标题的问题'
    return {'section_question': question, 'evidence_uses': [],
            'content_scope': {'full_exposition': [], 'carry_over': []},
            'judgment_limits': ['仅据当前材料判断；证据不足则说明，不预设排名、成功成效或群体能力结论。']}


def render_decision_prompt(decision) -> str:
    decision = validate_decision_shape(decision)
    lines = [COMMON_DECISION_RULES, '\n本节问题：', decision['section_question'], '\n证据用途：']
    for item in decision['evidence_uses']:
        ids = ','.join(item['citation_ids'])
        lines.append(f"- {item['topic']}（{item['basis']} {ids}）：{item['use']}")
        if item['support_limit']:
            lines.append(f"  支持边界：{item['support_limit']}")
    lines.append('\n展开与承接：')
    for topic in decision['content_scope']['full_exposition']:
        lines.append(f'- 完整展开：{topic}')
    for item in decision['content_scope']['carry_over']:
        lines.append(f"- 承接{item['section_id']}的{item['topic']}：{item['use']}")
    lines.append('\n判断边界：')
    lines.extend(f'- {limit}' for limit in decision['judgment_limits'])
    return '\n'.join(lines)


def decision_topics(decision) -> list:
    """Candidates for existing evidence grounding; these are not trusted facts."""
    normalized = validate_decision_shape(decision)
    return _unique([item['topic'] for item in normalized['evidence_uses']]
                   + normalized['content_scope']['full_exposition']
                   + [item['topic'] for item in normalized['content_scope']['carry_over']])


def build_prior_ledger(tasks) -> str:
    rows = []
    for task in tasks:
        decision = task['writing_decision']
        rows.append({'outline_id': task['outline_id'], 'section_question': decision['section_question'],
                     'full_exposition': decision['content_scope']['full_exposition'],
                     'evidence_uses': [{'topic': item['topic'], 'use': item['use']}
                                       for item in decision['evidence_uses']]})
    ledger = PRIOR_LEDGER_PREFIX + compact_json(rows)
    if len(ledger) > MAX_PRIOR_LEDGER_CHARS:
        raise ValueError(f'此前分工记录超过{MAX_PRIOR_LEDGER_CHARS}字符')
    return ledger


def request_decision(task, user_prompt, report_title, outline_context, previous_tasks, outline_ids) -> dict:
    def fallback(reason):
        messages = {'prior_budget': '此前分工记录超预算，使用备用决策。',
                    'model_error': '写作决策模型请求失败，使用备用决策。',
                    'empty': '写作决策为空，使用备用决策。',
                    'length': '写作决策输出被截断，使用备用决策。',
                    'invalid_decision': '写作决策结构或来源无效，使用备用决策。'}
        return {'decision': fallback_decision(task), 'status': 'fallback', 'warnings': [
            {'stage': 'writing_prompt_generation', 'outline_id': task['outline_id'],
             'reason': reason, 'message': messages[reason]}]}

    try:
        ledger = build_prior_ledger(previous_tasks)
    except ValueError:
        return fallback('prior_budget')
    contract = {
        'section_question': '一个本节问题',
        'evidence_uses': [{'topic': '具体对象', 'basis': 'external', 'citation_ids': ['当前C编号'],
                           'use': '事实或分析用途', 'support_limit': '必要时的支持边界，可为空'}],
        'content_scope': {'full_exposition': ['具体对象'], 'carry_over': [
            {'topic': '具体对象', 'section_id': '其他有效小节编号', 'use': '短句承接用途'}]},
        'judgment_limits': ['材料相关的判断边界']}
    prompt = (
        f'报告需求：{user_prompt}\n报告标题：{report_title}\n全篇大纲：\n{outline_context}\n'
        f"当前小节：{task['outline_id']} {task['title']}\n"
        f"当前图谱状态：{(task.get('graph_retrieval') or {}).get('status', 'skipped')}\n"
        f"当前图谱材料：\n{(task.get('graph_retrieval') or {}).get('graph_context_text', '')}\n"
        f"当前外部材料：\n{(task.get('external_rag_retrieval') or {}).get('rag_context_text', '')}\n"
        f'{ledger}\n{COMMON_DECISION_RULES}\n'
        '只返回四字段简洁JSON决策，不返回正文或长任务书。'
        '不重复两份材料清单，不预设央企弱、机制未打通、成功案例等结论。'
        '最多4条证据用途、3个完整展开对象、3个承接对象、3条判断边界；列表可为空。'
        '问题不超过100字符；对象不超过60字符；用途、支持边界及单条判断边界不超过120字符。'
        'external的引用编号非空且只能来自当前材料；graph仅在当前图谱成功时使用，引用可为空。'
        '承接小节可为后节，不可指向自身或不存在的小节。\n'
        f'JSON合同：{compact_json(contract)}'
    )
    try:
        result = llm.query_result(
            user_prompt=prompt, system_prompt='你是产业报告小节写作决策生成器。只返回规定JSON，不写正文。',
            max_tokens=3000, reasoning_effort=None, extra_body={'thinking': {'type': 'disabled'}},
            extra_log_info=f"report_generation.writing_decisions outline={task['outline_id']}")
    except Exception:
        return fallback('model_error')
    if result.error_message:
        return fallback('model_error')
    if result.finish_reason == 'length':
        return fallback('length')
    if not (result.content or '').strip():
        return fallback('empty')
    try:
        decision = validate_decision(parse_json_object(result.content), task, outline_ids)
    except (ValueError, TypeError):
        return fallback('invalid_decision')
    return {'decision': decision, 'status': 'generated', 'warnings': []}

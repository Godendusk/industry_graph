"""One bounded report-wide review of section writing decisions."""

import copy
import time
from collections import Counter

from llm_client import llm
from report_generation.repetition_context import focus_terms_for_task
from report_generation.structured_output import parse_json_object
from report_generation.writing_decisions import compact_json, render_decision_prompt, validate_decision


MAX_COORDINATION_INPUT_CHARS = 24000

SYSTEM_PROMPT = '''你是产业报告全篇写作分工协调器。根据大纲和已有决策选择最适合完整介绍对象的小节，
其余小节短句承接或分析不同用途。取消缺证据的预定结论，允许缩短，不强制每节提出新观点。
不得修改大纲、材料或引用编号；这不是原文事实核验，写作安排不是事实证据。
只返回JSON对象，顶层changes和outline_operations数组；无需调整时两个数组均为空。
一级章节不变；二级小节确实没有独立内容时才可提议少量合并/删除，最多减少原数10%向上取整且不超过2。
outline_operations每项仅kind（merge或delete）、source_ids、target_id、reason；merge限同一一级章节内。
缺证据若由检索失败造成，不得据此删除。用户明确要求的内容不得丢失。
每项只能有outline_id、reason、set。set仅包含需要改动的决策字段，不重复输出未修改字段。
reason非空且不超过160字符。可改字段为：
section_question（<=100字符），evidence_uses（最多4项，每项topic、basis、citation_ids、use、support_limit），
content_scope（full_exposition字符串数组最多3项，carry_over最多3项，每项topic、section_id、use），
judgment_limits（字符串数组最多3项）。topic和完整展开对象<=60字符，use、support_limit及判断边界<=120字符，
external引用必须来自本节allowed_citation_ids且非空；graph只支持记录关系。
承接可指向后节，不能指向自身或不存在小节。不得增加其他字段或输出正文。'''


def _allowed_citation_ids(task):
    retrieval = task.get('external_rag_retrieval') or {}
    blocks = retrieval.get('evidence_blocks') or task.get('external_evidence_blocks') or []
    return list(dict.fromkeys(block['citation_id'] for block in blocks if block.get('citation_id')))


def build_coordination_payload(tasks):
    """Keep review input free of documents, graph entities and old prompts."""
    return {
        'outline': [{'outline_id': task['outline_id'],
                     'parent_title': task.get('parent_level1_title', ''),
                     'title': task.get('title', '')} for task in tasks],
        'sections': [{'outline_id': task['outline_id'],
                      'decision': copy.deepcopy(task['writing_decision']),
                      'allowed_citation_ids': _allowed_citation_ids(task)} for task in tasks],
    }


def _warning(reason, message, outline_id=None):
    warning = {'stage': 'task_coordination', 'reason': reason, 'message': message}
    if outline_id is not None:
        warning['outline_id'] = outline_id
    return warning


def apply_coordination_changes(tasks, changes, outline_ids):
    """Apply qualified changes independently, without touching selected materials."""
    if not isinstance(changes, list):
        raise ValueError('changes必须是数组')
    final = copy.deepcopy(tasks)
    by_id = {task['outline_id']: task for task in final}
    for task in final:
        task['decision_review_status'] = 'unchanged'
    counts = Counter(item.get('outline_id') for item in changes
                     if isinstance(item, dict) and isinstance(item.get('outline_id'), str))
    changed, rejected, warnings = [], [], []
    for item in changes:
        outline_id = item.get('outline_id') if isinstance(item, dict) else None
        if not isinstance(outline_id, str):
            outline_id = None
        try:
            if not isinstance(item, dict) or set(item) != {'outline_id', 'reason', 'set'}:
                raise ValueError('调整项必须仅含outline_id、reason、set')
            if outline_id is None or outline_id not in by_id:
                raise ValueError('调整小节编号不存在')
            if counts[outline_id] > 1:
                raise ValueError('重复调整同一小节，全部拒绝')
            reason = item['reason']
            if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 160:
                raise ValueError('reason必须非空且不超过160字符')
            task = by_id[outline_id]
            updates = item['set']
            if not isinstance(updates, dict) or not updates or not set(updates) <= {
                    'section_question', 'evidence_uses', 'content_scope', 'judgment_limits'}:
                raise ValueError('set必须只包含需要更新的决策字段')
            candidate = copy.deepcopy(task['writing_decision'])
            candidate.update(copy.deepcopy(updates))
            decision = validate_decision(candidate, task, outline_ids)
            if decision == task['writing_decision']:
                continue
            task['writing_decision'] = decision
            task['writing_system_prompt'] = render_decision_prompt(decision)
            task['repetition_focus_terms'] = (
                [use['topic'] for use in decision['evidence_uses']]
                + decision['content_scope']['full_exposition']
                + [scope['topic'] for scope in decision['content_scope']['carry_over']])
            task['repetition_focus_terms'] = focus_terms_for_task(task)
            task['decision_review_status'] = 'adjusted'
            changed.append(outline_id)
        except ValueError as exc:
            if outline_id is not None and outline_id not in rejected:
                rejected.append(outline_id)
            warnings.append(_warning('invalid_change', str(exc), outline_id))
    return final, changed, rejected, warnings


def coordinate_writing_tasks(tasks):
    """Return final tasks, review diagnostics and warnings after at most one call."""
    started = time.monotonic()
    payload_text = compact_json(build_coordination_payload(tasks))
    meta = {'status': 'failed', 'input_chars': len(payload_text),
            'elapsed_seconds': 0.0, 'changed_outline_ids': [], 'rejected_outline_ids': []}

    def finish(final, warnings):
        meta['elapsed_seconds'] = time.monotonic() - started
        return final, meta, warnings

    duplicate_ids = [outline_id for outline_id, count in
                     Counter(task['outline_id'] for task in tasks).items() if count > 1]
    if duplicate_ids:
        meta['rejected_outline_ids'] = duplicate_ids
        return finish(copy.deepcopy(tasks), [_warning(
            'duplicate_outline_id', '小节编号重复，无法确定调整对象；保留逐节决策')])
    if len(payload_text) > MAX_COORDINATION_INPUT_CHARS:
        meta['status'] = 'skipped_budget'
        return finish(copy.deepcopy(tasks), [_warning('input_budget', '全报告协调输入超过字符预算，保留逐节决策')])
    try:
        result = llm.query_result(user_prompt=payload_text, system_prompt=SYSTEM_PROMPT,
                                  max_tokens=5000, reasoning_effort=None,
                                  extra_body={'thinking': {'type': 'disabled'}},
                                  extra_log_info='report_generation.task_coordination')
    except Exception:
        return finish(copy.deepcopy(tasks), [_warning('model_error', '全报告协调模型调用失败，保留逐节决策')])
    if result.error_message:
        return finish(copy.deepcopy(tasks), [_warning('model_error', '全报告协调模型调用失败，保留逐节决策')])
    if result.finish_reason == 'length':
        return finish(copy.deepcopy(tasks), [_warning('length', '全报告协调输出被截断，保留逐节决策')])
    if not result.content or not result.content.strip():
        return finish(copy.deepcopy(tasks), [_warning('empty', '全报告协调输出为空，保留逐节决策')])
    try:
        response = parse_json_object(result.content)
        if not set(response) <= {'changes', 'outline_operations'} or 'changes' not in response or not isinstance(response['changes'], list):
            raise ValueError('协调顶层必须包含changes数组，可包含outline_operations数组')
        outline_operations = response.get('outline_operations', [])
        if not isinstance(outline_operations, list):
            raise ValueError('outline_operations必须是数组')
        final, changed, rejected, warnings = apply_coordination_changes(
            tasks, response['changes'], {task['outline_id'] for task in tasks})
    except ValueError as exc:
        return finish(copy.deepcopy(tasks), [_warning('invalid_response', str(exc))])
    meta.update(status='partial' if warnings else 'completed',
                changed_outline_ids=changed, rejected_outline_ids=rejected,
                outline_operations=outline_operations)
    return finish(final, warnings)

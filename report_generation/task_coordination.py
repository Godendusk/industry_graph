"""One bounded report-wide review of section writing decisions."""

import copy
import time
from collections import Counter

from llm_client import llm
from report_generation.repetition_context import focus_terms_for_task
from report_generation.structured_output import parse_json_object
from report_generation.report_facts import fact_sources, validate_facts
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


def build_coordination_payload(tasks, user_prompt=None, report_title=None, outline=None):
    """Keep review input free of documents, graph entities and old prompts."""
    payload = {
        'outline': [{'outline_id': task['outline_id'],
                     'parent_title': task.get('parent_level1_title', ''),
                     'title': task.get('title', '')} for task in tasks],
        'sections': [{'outline_id': task['outline_id'],
                      'decision': copy.deepcopy(task['writing_decision']),
                      'allowed_citation_ids': _allowed_citation_ids(task)} for task in tasks],
    }
    if user_prompt is not None:
        payload['fact_sources'] = [{k: v for k, v in source.items() if k != '_block'} for source in fact_sources(tasks)]
        payload.update(user_prompt=user_prompt, report_title=report_title or '',
                       full_outline=[{'section_type': c.get('section_type'), 'level1_id': c.get('level1_id'), 'level1_title': c.get('level1_title'), 'subsections': [{'outline_id': sub.get('outline_id'), 'title': sub.get('title')} for sub in c.get('subsections', [])]} for c in (outline or [])])
        for section, task in zip(payload['sections'], tasks):
            pack = task.get('evidence_pack') or {}
            retrieval = task.get('external_rag_retrieval') or {}
            section['evidence'] = {
                'retrieval_status': retrieval.get('status', 'unknown'),
                'assessment_status': pack.get('status', 'unknown'),
                'requirements': [
                    {'id': row.get('id'), 'requirement': str(row.get('requirement') or '')[:180],
                     'status': row.get('status'), 'reason': str(row.get('reason') or '')[:140],
                     'support': [{'citation_id': ref.get('citation_id'),
                                  'quote': str(ref.get('quote') or '')[:160]}
                                 for ref in row.get('support', [])[:2]]}
                    for row in pack.get('requirements', [])],
                'snippets': [{'citation_id': b.get('citation_id'),
                              'library': b.get('library'), 'material_id': b.get('material_id'),
                              'vector_id': b.get('chunk_id') or b.get('vector_id'),
                              'title': b.get('title', ''), 'publish_date': b.get('publish_date', ''),
                              'text': str(b.get('text', ''))[:240]}
                             for b in retrieval.get('evidence_blocks', [])[:3]],
                'graph_status': (task.get('graph_retrieval') or {}).get('status', 'skipped'),
            }
    return payload


SCOPE_PROMPT = '''
本次必须在原用户核心问题、研究对象和时间要求内，根据真实需求支持状态统一研究范围。
检索服务失败是unavailable，不代表行业无资料；不足以回答核心问题时明确范围未完成，不能改成行业科普冒充研究。
有四家可比较企业时保留企业比较；历史序列不足但节点可靠时保留节点分析；不得捏造前十排名或五年增长。
允许修改报告标题、一级和二级标题，跨一级合并、删除无独立内容章节；无固定章数、最低字数、最多两节限制。
除changes与outline_operations外必须返回report_scope和effective_outline。
effective_outline只返回section_type、level1_id、level1_title、subsections中outline_id和title，省略任务要求和原文；它是full_outline形状的完整最终大纲，保留现有level1_id和outline_id；章节增删并以outline_operations为唯一结构依据，effective_outline提供保留章节的标题和顺序，不能生成新编号。被移除小节必须显式merge/delete映射；不要在effective_outline中重复列出已合并的源小节。
report_scope字段：effective_title、deliverable_type(report/brief)、core_question、
boundary{subjects:字符串数组,period:字符串,classification:字符串}、
coverage[{requirement:具体核心要求,status:supported/partial/insufficient/unknown/unavailable,section_ids:有效小节编号数组,reason:真实依据或缺口}]、
adjustments:简洁原因字符串数组、remaining_gaps:剩余缺口字符串数组。
coverage需覆盖用户所有明确要求；supported/partial必须对应实质相关证据，来源数量不等于支持程度。
允许以事实为依据、明确假设与边界的原创条件分析；不得以未检索到推出没有业务或尚未商业化。
无需修改时仍返回完整有效范围与大纲。范围不是事实证据。'''

SCOPE_PROMPT += '''
先输出report_scope，再输出effective_outline、outline_operations、section_answers，最后输出changes，确保核心范围先完整表达。
这是一次紧凑的整篇决策，不是逐节重写。coverage按用户核心比较维度合并，通常4—8项，不逐条复制所有章节需求；core_question不超过180字，coverage的requirement不超过80字、reason不超过100字。boundary、adjustments和remaining_gaps只列必要信息，单项不超过100字。
changes只保留最多4项最关键的分工冲突，每项set只修改必要字段，不输出逐节完整决策；其余小节沿用已生成决策。effective_outline的标题用短标题，不复制检索问题。所有删并都保留显式映射，不为压缩输出丢失有效小节或用户要求。'''

SCOPE_PROMPT += '''
最后返回report_facts数组，仅整理会决定报告结论、需要跨节一致的证照/投产/交付/收入归属/项目要求等关键事实，最多8项，不能照抄全部资料。字段subject（具体企业及型号或项目）、attribute、value、event_time、published_at、modality(actual/planned/forecast/requirement/unknown)、applicability（适用对象和不可推广范围）、supports[{evidence_id,citation_id,quote}]。supports必须绑定fact_sources中逐字原文，quote只摘必要短句；未知日期留空。区分来源发布日期与事件日期、同企业不同型号、计划和已实现；最新发布日期不自动覆盖旧事件。申报指南只证明该项目要求，不证明全行业门槛。没有可核实事实返回空数组，不捏造。各事实总输出保持紧凑，优先完成范围与大纲。\n每节应有实质回答或不同分析用途；若只是重复方法、资料局限或其他节已有结论则合并，重要缺口集中说明。同一事实服务不同分析可保留，不按引用复用次数删节。不能只加限定语便把项目要求当作行业普遍条件。'''


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


def coordinate_writing_tasks(tasks, user_prompt=None, report_title=None, outline=None):
    """Return final tasks, review diagnostics and warnings after at most one call."""
    started = time.monotonic()
    payload = build_coordination_payload(tasks, user_prompt, report_title, outline)
    payload_text = compact_json(payload)
    if user_prompt is not None and len(payload_text) > 60000:
        for section in payload['sections']:
            decision = section['decision']
            section['decision'] = {'section_question': decision['section_question'],
                                   'content_scope': decision['content_scope']}
            section['evidence']['snippets'] = section['evidence']['snippets'][:1]
            for requirement in section['evidence']['requirements']:
                requirement['reason'] = requirement['reason'][:80]
                requirement['support'] = requirement['support'][:1]
                for ref in requirement['support']:
                    ref['quote'] = ref['quote'][:80]
        payload_text = compact_json(payload)
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
    if len(payload_text) > (86000 if user_prompt is not None else MAX_COORDINATION_INPUT_CHARS):
        meta['status'] = 'skipped_budget'
        return finish(copy.deepcopy(tasks), [_warning('input_budget', '全报告协调输入超过字符预算，保留逐节决策')])
    try:
        result = llm.query_result(user_prompt=payload_text, system_prompt=(SYSTEM_PROMPT if user_prompt is None else SYSTEM_PROMPT.replace('不得修改大纲、材料或引用编号', '不得修改材料或引用编号').replace('一级章节不变；二级小节确实没有独立内容时才可提议少量合并/删除，最多减少原数10%向上取整且不超过2。', '').replace('merge限同一一级章节内。', '') + SCOPE_PROMPT),
                                  max_tokens=7000 if user_prompt is not None else 5000, reasoning_effort=None,
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
        if not set(response) <= ({'changes', 'outline_operations'} if user_prompt is None else {'changes', 'outline_operations', 'report_scope', 'effective_outline', 'report_facts', 'section_answers'}) or 'changes' not in response or not isinstance(response['changes'], list):
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
    if user_prompt is not None:
        facts, fact_warnings = validate_facts(response.get('report_facts', []), fact_sources(tasks))
        warnings.extend(fact_warnings)
        meta.update(report_scope=response.get('report_scope'), effective_outline=response.get('effective_outline'), report_facts=facts, section_answers=response.get('section_answers'))
        if not isinstance(meta['report_scope'], dict) or not isinstance(meta['effective_outline'], list):
            meta['status'] = 'incomplete'
            warnings.append(_warning('incomplete_scope', '范围决策或有效大纲缺失，范围校验未完成'))
    return finish(final, warnings)



SCOPE_PROMPT += """
还必须返回section_answers数组，为每个最终保留小节给出{outline_id,answer,citation_ids}，不输出已删并的源小节。answer用不超过100字说明已有材料实际能得到的具体回答或条件分析，不能只写“分析现状、讨论挑战、资料不足、提出建议”等任务名称。citation_ids列出支撑本节回答的原始材料编号，可来自全篇各节已给出的现有材料；程序会把所选真实原文共享到目标小节；基于图谱关系或纯条件推导时可为空，但不能借此编造实际成效。拟回答仍须正文生成与事实核验，不是已经核实的事实。
先比较这些实质回答：若两节只能重复同一回答或研究方法、资料缺口，应合并内容或集中限制说明；若基于相同事实回答不同问题则保留。核心比较不能仅因来源没有直接写出比较结论而删除。项目申报条件只能回答该项目允许什么对象申报，不能用来回答整条路线的运行稳定性、经济性或实际准入情况。无实质证据且无法完成条件分析的小节不得靠重复缺口保留。
"""

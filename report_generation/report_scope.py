"""Validate and atomically adopt one report-wide research scope and outline."""
from __future__ import annotations

import copy

from .outline_adjustments import apply_outline_adjustments
from .report_facts import attach_facts, fact_sources, source_identity

STATUSES = {'supported', 'partial', 'insufficient', 'unknown', 'unavailable'}


def _text(value, field, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f'{field}必须是有效字符串')
    return value.strip()


def _sections(outline):
    sections = {}
    chapter_ids = set()
    if not isinstance(outline, list):
        raise ValueError('effective_outline必须为完整大纲数组')
    for chapter in outline:
        if not isinstance(chapter, dict):
            raise ValueError('一级章节格式无效')
        if chapter.get('section_type') != 'body':
            continue
        chapter_id = _text(chapter.get('level1_id'), 'level1_id')
        if chapter_id in chapter_ids:
            raise ValueError('一级章节编号重复')
        chapter_ids.add(chapter_id)
        _text(chapter.get('level1_title'), 'level1_title')
        if not isinstance(chapter.get('subsections'), list) or not chapter['subsections']:
            raise ValueError('正文一级章节必须有有效小节')
        for sub in chapter['subsections']:
            section_id = _text(sub.get('outline_id'), 'outline_id')
            _text(sub.get('title'), 'title')
            if section_id in sections:
                raise ValueError('小节编号重复')
            sections[section_id] = (chapter, sub)
    if not sections:
        raise ValueError('有效大纲没有实质研究小节')
    return sections


def _unavailable(task):
    return ((task.get('evidence_pack') or {}).get('status') == 'unavailable'
            or (task.get('external_rag_retrieval') or {}).get('status') == 'error')


def apply_report_scope(outline, tasks, coordination, user_prompt, report_title):
    """Return final_outline, final_tasks, scope, notes, warnings without mutating inputs.

    Scope failures retain all retrieved materials and explicitly prevent completion.
    Removed stable IDs require explicit merge/delete operations. Merge can cross L1.
    """
    fallback = {'original_title': report_title, 'effective_title': report_title,
                'deliverable_type': 'report', 'core_question': user_prompt,
                'boundary': {'subjects': [], 'period': '', 'classification': ''},
                'coverage': [], 'adjustments': [], 'remaining_gaps': [], 'status': 'incomplete'}
    try:
        raw = coordination.get('report_scope')
        if not isinstance(raw, dict):
            raise ValueError('全篇范围决策缺失，尚未完成研究范围校验')
        scope = copy.deepcopy(raw)
        for key in ('effective_title', 'core_question'):
            scope[key] = _text(scope.get(key), key)
        if scope.get('deliverable_type') not in ('report', 'brief'):
            raise ValueError('deliverable_type必须是report或brief')
        boundary = scope.get('boundary')
        if not isinstance(boundary, dict) or set(boundary) != {'subjects', 'period', 'classification'}:
            raise ValueError('boundary必须给出subjects、period、classification')
        if not isinstance(boundary['subjects'], list) or not boundary['subjects']:
            raise ValueError('必须保留明确的研究对象')
        boundary['subjects'] = [_text(v, 'subjects') for v in boundary['subjects']]
        for key in ('period', 'classification'):
            boundary[key] = _text(boundary[key], key, empty=True)
        for key in ('adjustments', 'remaining_gaps'):
            if not isinstance(scope.get(key), list):
                raise ValueError(f'{key}必须是数组')
            scope[key] = [_text(v, key) for v in scope[key]]
        effective = copy.deepcopy(coordination.get('effective_outline'))
        original_sections = _sections(outline)
        raw_sections = _sections(effective)
        operations = coordination.get('outline_operations', [])
        # Operations carry the structural decision. The outline carries surviving
        # headings/order and may repeat an explicitly merged/deleted source ID.
        declared_removed = {sid for op in operations if isinstance(op, dict) and op.get('kind') in ('merge', 'delete')
                            for sid in op.get('source_ids', [])}
        if not set(raw_sections) <= set(original_sections):
            raise ValueError('调整后不得生成无材料的新小节编号')
        for chapter in effective:
            if chapter.get('section_type') == 'body':
                chapter['subsections'] = [sub for sub in chapter['subsections'] if sub['outline_id'] not in declared_removed]
        effective = [chapter for chapter in effective if chapter.get('section_type') != 'body' or chapter['subsections']]
        final_sections = _sections(effective)
        if not set(final_sections) <= set(original_sections):
            raise ValueError('调整后不得生成无材料的新小节编号')
        old_chapters = {v[0]['level1_id'] for v in original_sections.values()}
        if any(v[0]['level1_id'] not in old_chapters for v in final_sections.values()):
            raise ValueError('一级章节须保留稳定编号')
        operations = coordination.get('outline_operations', [])
        removed_ids = set(original_sections) - set(final_sections)
        merged_ids = {sid for op in operations if isinstance(op, dict) and op.get('kind') == 'merge'
                      for sid in op.get('source_ids', [])}
        by_id = {task['outline_id']: task for task in tasks}
        if any(_unavailable(by_id[sid]) for sid in removed_ids - merged_ids):
            raise ValueError('不能因检索服务故障删除研究内容；资料是否存在仍未知')
        adjusted, final_tasks, notes, warnings = apply_outline_adjustments(
            outline, tasks, operations, scope_rewrite=True)
        if warnings:
            raise ValueError(warnings[0]['message'])
        if set(_sections(adjusted)) != set(final_sections):
            raise ValueError('有效大纲与显式合并/删除映射不一致')
        coverage = scope.get('coverage')
        if not isinstance(coverage, list) or not coverage:
            raise ValueError('coverage必须逐项说明核心要求的覆盖')
        final_by_id = {task['outline_id']: task for task in final_tasks}
        mapped_ids = {sid: op.get('target_id') if op.get('kind') == 'merge' else None
                      for op in operations for sid in op.get('source_ids', [])}
        substantive = False
        for item in coverage:
            if not isinstance(item, dict) or item.get('status') not in STATUSES:
                raise ValueError('覆盖状态无效')
            _text(item.get('requirement'), 'coverage.requirement')
            _text(item.get('reason'), 'coverage.reason')
            ids = item.get('section_ids')
            if not isinstance(ids, list) or any(sid not in original_sections for sid in ids):
                raise ValueError('覆盖关系引用不存在的小节')
            if item['status'] in ('supported', 'partial') and any(
                    sid in mapped_ids and mapped_ids[sid] is None for sid in ids):
                raise ValueError('已覆盖要求引用了被删除且未合并的小节，需要重新判断覆盖或明确缺口')
            # Coverage may still name a source section from the same, explicitly
            # mapped merge. Adopt the mapping together with the outline/tasks.
            ids = list(dict.fromkeys(mapped_ids.get(sid, sid) for sid in ids))
            ids = [sid for sid in ids if sid is not None]
            if any(sid not in final_sections for sid in ids):
                raise ValueError('覆盖关系的合并目标不在有效大纲中')
            item['section_ids'] = ids
            if item['status'] in ('supported', 'partial'):
                if not ids:
                    raise ValueError('已覆盖要求必须对应有证据的小节')
                supported = any((final_by_id[sid].get('external_rag_retrieval') or {}).get('evidence_blocks')
                                or (final_by_id[sid].get('graph_retrieval') or {}).get('status') == 'success'
                                for sid in ids)
                if not supported:
                    raise ValueError('已覆盖核心要求没有任何现有证据')
                substantive = True
            if any(_unavailable(final_by_id[sid]) for sid in ids) and item['status'] == 'insufficient':
                raise ValueError('服务不可用必须标为unavailable或unknown，不能判断资料不足')
        if not substantive:
            raise ValueError('仅有背景或未覆盖要求，不能交付为已完成研究简报')
        scope.update(original_title=report_title, status='completed')
        final_tasks = [final_by_id[sid] for sid in final_sections]
        answers = coordination.get('section_answers')
        if not isinstance(answers, list):
            raise ValueError('最终小节的实质回答安排缺失')
        answers_by_id = {}
        for row in answers:
            if not isinstance(row, dict) or set(row) != {'outline_id', 'answer', 'citation_ids'}:
                raise ValueError('小节实质回答格式无效')
            sid = row['outline_id']
            if not isinstance(sid, str) or sid not in original_sections:
                raise ValueError('小节实质回答引用不存在编号')
            if sid in removed_ids:
                continue
            if sid in answers_by_id:
                raise ValueError('小节实质回答重复')
            answer = _text(row['answer'], 'section_answer.answer')
            ids = row['citation_ids']
            if not isinstance(ids, list) or any(not isinstance(cid, str) for cid in ids):
                raise ValueError('小节实质回答引用格式无效')
            answers_by_id[sid] = {'outline_id': sid, 'answer': answer, 'citation_ids': list(dict.fromkeys(ids))}
        if set(answers_by_id) != set(final_sections):
            raise ValueError('并非每个保留小节都有实质回答安排')
        from .external_rag.report_adapter import build_rag_context_text
        report_blocks = [block for source_task in tasks
                         for block in ((source_task.get('external_rag_retrieval') or {}).get('evidence_blocks')
                                       or source_task.get('external_evidence_blocks') or [])]
        for task in final_tasks:
            row = answers_by_id[task['outline_id']]
            task['section_answer'] = copy.deepcopy(row)
            retrieval = task.setdefault('external_rag_retrieval', {})
            blocks = retrieval.setdefault('evidence_blocks', copy.deepcopy(task.get('external_evidence_blocks') or []))
            added = False
            seen = {source_identity(block) for block in blocks}
            for block in report_blocks:
                identity = source_identity(block)
                if block.get('citation_id') in row['citation_ids'] and identity not in seen:
                    blocks.append(copy.deepcopy(block))
                    seen.add(identity)
                    added = True
            if added:
                retrieval['rag_context_text'] = build_rag_context_text(blocks)
        final_tasks = attach_facts(final_tasks, coordination.get('report_facts', []), fact_sources(tasks))
        for task in final_tasks:
            row = answers_by_id[task['outline_id']]
            blocks = (task.get('external_rag_retrieval') or {}).get('evidence_blocks') or task.get('external_evidence_blocks') or []
            allowed = {block.get('citation_id') for block in blocks}
            if not set(row['citation_ids']) <= allowed:
                raise ValueError('小节实质回答引用了该节无法使用的资料')
            task['section_answer'] = copy.deepcopy(row)
        for task in final_tasks:
            chapter, sub = final_sections[task['outline_id']]
            task.update(title=sub['title'], parent_level1_id=chapter['level1_id'],
                        parent_level1_title=chapter['level1_title'], report_scope=copy.deepcopy(scope))
        if effective != outline or scope['effective_title'] != report_title:
            notes.append({'kind': 'report_scope', 'reason': '；'.join(scope['adjustments']) or '根据实际证据统一研究范围',
                          'original_title': report_title, 'effective_title': scope['effective_title']})
        return effective, final_tasks, scope, notes, []
    except (ValueError, TypeError, KeyError) as exc:
        fallback['remaining_gaps'] = [str(exc)]
        final_tasks = copy.deepcopy(tasks)
        for task in final_tasks:
            task['report_scope'] = copy.deepcopy(fallback)
        return copy.deepcopy(outline), final_tasks, fallback, [], [
            {'stage': 'report_scope', 'reason': 'incomplete_scope', 'message': str(exc)}]

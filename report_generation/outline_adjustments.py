"""Apply a small number of report outline reductions without losing merged evidence."""

from __future__ import annotations

import copy

from .writing_decisions import render_decision_prompt, validate_decision


def reduction_limit(original_count: int) -> int:
    return min(2, (original_count + 9) // 10)


def apply_outline_adjustments(outline, tasks, operations, protected_outline_ids=None):
    """Return new outline/tasks, applied notes and warnings; reject invalid batches atomically."""
    original_outline = copy.deepcopy(outline)
    original_tasks = copy.deepcopy(tasks)
    if not operations:
        return original_outline, original_tasks, [], []
    protected = set(protected_outline_ids or [])
    sections = {sub.get('outline_id'): (chapter, sub)
                for chapter in original_outline if isinstance(chapter, dict)
                and chapter.get('section_type') == 'body'
                for sub in chapter.get('subsections', []) if isinstance(sub, dict)}
    tasks_by_id = {task.get('outline_id'): task for task in original_tasks if isinstance(task, dict)}
    original_count = len(sections)
    removed = []
    try:
        if not isinstance(operations, list):
            raise ValueError('操作必须为列表')
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {'kind', 'source_ids', 'target_id', 'reason'}:
                raise ValueError('大纲操作字段无效')
            kind, source_ids, target_id = operation['kind'], operation['source_ids'], operation['target_id']
            if kind not in ('merge', 'delete') or not isinstance(source_ids, list) or not source_ids:
                raise ValueError('大纲操作类型或来源无效')
            if not isinstance(operation['reason'], str) or not operation['reason'].strip():
                raise ValueError('大纲调整缺少原因')
            if any(source_id not in sections or source_id not in tasks_by_id or source_id in protected
                   for source_id in source_ids):
                raise ValueError('来源小节不存在或包含受保护内容')
            if kind == 'delete' and target_id is not None:
                raise ValueError('删除操作不能指定目标')
            if kind == 'merge':
                if target_id not in sections or target_id not in tasks_by_id or target_id in source_ids:
                    raise ValueError('合并目标无效')
                if any(sections[source_id][0] is not sections[target_id][0] for source_id in source_ids):
                    raise ValueError('仅允许同一一级标题内合并')
            removed.extend(source_ids)
        if len(set(removed)) != len(removed):
            raise ValueError('同一小节只能被调整一次')
        if any(operation['kind'] == 'merge' and operation['target_id'] in removed for operation in operations):
            raise ValueError('合并目标不能同时被移除')
        if len(removed) > reduction_limit(original_count):
            raise ValueError('大纲减少小节超过上限')
        for chapter in original_outline:
            if chapter.get('section_type') == 'body' and chapter.get('subsections'):
                remaining = [sub for sub in chapter['subsections'] if sub.get('outline_id') not in removed]
                if not remaining:
                    raise ValueError('不能删除一级章节的最后一个小节')
    except ValueError as exc:
        return copy.deepcopy(outline), copy.deepcopy(tasks), [], [
            {'stage': 'outline_adjustment', 'message': str(exc)}]

    notes = []
    for operation in operations:
        if operation['kind'] == 'merge':
            target = tasks_by_id[operation['target_id']]
            target_rag = target.setdefault('external_rag_retrieval', {})
            target_blocks = target_rag.setdefault('evidence_blocks', [])
            existing = {(row.get('citation_id'), row.get('vector_id'), row.get('text')) for row in target_blocks}
            for source_id in operation['source_ids']:
                source = tasks_by_id[source_id]
                if 'writing_decision' in target and 'writing_decision' in source:
                    target_decision = target['writing_decision']
                    source_decision = source['writing_decision']
                    for field in ('evidence_uses', 'judgment_limits'):
                        for item in source_decision[field]:
                            if item not in target_decision[field]:
                                target_decision[field].append(copy.deepcopy(item))
                    target_full = target_decision['content_scope']['full_exposition']
                    for topic in source_decision['content_scope']['full_exposition']:
                        if topic not in target_full:
                            target_full.append(topic)
                for block in source.get('external_rag_retrieval', {}).get('evidence_blocks', []):
                    key = (block.get('citation_id'), block.get('vector_id'), block.get('text'))
                    if key not in existing:
                        target_blocks.append(copy.deepcopy(block))
                        existing.add(key)
                if source.get('graph_retrieval', {}).get('status') == 'success':
                    target.setdefault('merged_graph_retrieval', []).append(copy.deepcopy(source['graph_retrieval']))
            target_rag['rag_context_text'] = '\n'.join(
                f"[{row['citation_id']}] {row.get('text','')}" for row in target_blocks if row.get('citation_id'))
        notes.append({'kind': 'outline_merge' if operation['kind'] == 'merge' else 'outline_delete',
                      'outline_ids': operation['source_ids'], 'target_id': operation['target_id'],
                      'reason': operation['reason']})
    for chapter in original_outline:
        if isinstance(chapter, dict) and chapter.get('section_type') == 'body':
            chapter['subsections'] = [sub for sub in chapter.get('subsections', [])
                                      if sub.get('outline_id') not in removed]
    original_tasks = [task for task in original_tasks if task.get('outline_id') not in removed]
    try:
        remaining_ids = {task.get('outline_id') for task in original_tasks}
        merger_targets = {source_id: operation['target_id'] for operation in operations
                          if operation['kind'] == 'merge' for source_id in operation['source_ids']}
        for task in original_tasks:
            decision = task.get('writing_decision')
            if not isinstance(decision, dict):
                continue
            carry = decision['content_scope']['carry_over']
            remapped = []
            for item in carry:
                next_item = copy.deepcopy(item)
                next_item['section_id'] = merger_targets.get(next_item['section_id'], next_item['section_id'])
                if next_item['section_id'] in remaining_ids and next_item['section_id'] != task['outline_id']:
                    remapped.append(next_item)
            decision['content_scope']['carry_over'] = remapped
            task['writing_decision'] = validate_decision(decision, task, remaining_ids)
            task['writing_system_prompt'] = render_decision_prompt(task['writing_decision'])
    except (KeyError, TypeError, ValueError) as exc:
        return copy.deepcopy(outline), copy.deepcopy(tasks), [], [
            {'stage': 'outline_adjustment', 'message': f'合并后无法保留有效分工：{exc}'}]
    return original_outline, original_tasks, notes, []

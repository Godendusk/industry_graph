"""Source-bound key facts for one report; no retrieval or persistent knowledge store."""
import copy
import json
import re

_KEY = re.compile(r'取得|获批|投产|交付|运营|营收|收入|申报|指南|计划|预计|合格证|产能')


def source_identity(block):
    return (block.get('citation_id'), block.get('library'),
            block.get('material_id') or block.get('document_id'),
            block.get('chunk_id') or block.get('vector_id'), block.get('text'))


def fact_sources(tasks, budget=12000):
    sources, seen = [], set()
    groups = [((task.get('external_rag_retrieval') or {}).get('evidence_blocks') or task.get('external_evidence_blocks', [])) for task in tasks]
    window = min(1400, max(1, budget // max(1, len(groups))))
    # Visit each chapter before a second fragment from an early chapter.
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index >= len(group):
                continue
            block = group[index]
            cid, text = block.get('citation_id'), str(block.get('text') or '')
            key = (cid, block.get('chunk_id') or block.get('vector_id'), text)
            if not cid or not text or key in seen or not _KEY.search(text):
                continue
            seen.add(key)
            if budget <= 0:
                break
            hit = _KEY.search(text)
            start = max(0, hit.start() - 200)
            snippet = text[start:start + min(window, budget)]
            sources.append({'evidence_id': f'F{len(sources) + 1}', 'citation_id': cid,
                            'title': block.get('title', ''), 'published_at': block.get('publish_date', ''),
                            'text': snippet, 'truncated': start > 0 or len(snippet) < len(text),
                            '_block': copy.deepcopy(block)})
            budget -= len(snippet)
    return sources


def validate_facts(facts, sources):
    lookup = {s['evidence_id']: s for s in sources}
    valid, warnings = [], []
    if not isinstance(facts, list):
        return [], [{'stage': 'report_facts', 'reason': 'invalid_facts', 'message': '关键事实必须为数组'}]
    for index, raw in enumerate(facts):
        try:
            fields = ('subject', 'attribute', 'value', 'event_time', 'published_at', 'modality', 'applicability')
            if not isinstance(raw, dict) or any(not isinstance(raw.get(k), str) for k in fields):
                raise ValueError('关键事实字段缺失')
            if any(not raw[k].strip() for k in ('subject', 'attribute', 'value', 'applicability')):
                raise ValueError('关键事实对象或适用范围为空')
            if raw['modality'] not in ('actual', 'planned', 'forecast', 'requirement', 'unknown'):
                raise ValueError('关键事实状态无效')
            if not isinstance(raw.get('supports'), list) or not raw['supports']:
                raise ValueError('关键事实缺少原文依据')
            supports = []
            for support in raw['supports']:
                source = lookup.get(support.get('evidence_id')) if isinstance(support, dict) else None
                quote = support.get('quote') if isinstance(support, dict) else None
                if (not source or support.get('citation_id') != source['citation_id']
                        or not isinstance(quote, str) or not quote.strip() or quote not in source['text']):
                    raise ValueError('关键事实引文未绑定输入原文')
                supports.append({k: support[k] for k in ('evidence_id', 'citation_id', 'quote')})
            quoted_numbers = set(re.findall(r'\d+(?:\.\d+)?', ' '.join(s['quote'] for s in supports)))
            fact_numbers = set(re.findall(r'\d+(?:\.\d+)?', raw['value'] + ' ' + raw['event_time']))
            if not fact_numbers <= quoted_numbers:
                raise ValueError('关键事实数字或事件年份未包含在绑定引文中')
            if raw['published_at']:
                date_parts = lambda text: [int(n) for n in re.findall(r'\d+', text)[:3]]
                actual_dates = [lookup[s['evidence_id']]['published_at'] for s in supports]
                if not any(date_parts(date) == date_parts(raw['published_at']) and date for date in actual_dates):
                    raise ValueError('关键事实发布日期与来源元数据不一致')
            valid.append({**{k: raw[k] for k in fields}, 'supports': supports})
        except ValueError as exc:
            warnings.append({'stage': 'report_facts', 'reason': 'invalid_fact', 'fact_index': index, 'message': str(exc)})
    return valid, warnings


def attach_facts(tasks, facts, sources):
    """Attach related facts and their real source blocks, preserving citation identity."""
    from .external_rag.report_adapter import build_rag_context_text
    result = copy.deepcopy(tasks)
    lookup = {s['evidence_id']: s['_block'] for s in sources}
    for task in result:
        blocks = (task.get('external_rag_retrieval') or {}).get('evidence_blocks') or task.get('external_evidence_blocks', [])
        cids = {b.get('citation_id') for b in blocks} | set((task.get('section_answer') or {}).get('citation_ids', []))
        context = json.dumps({k: task.get(k) for k in ('title', 'writing_decision', 'evidence_pack', 'section_answer')}, ensure_ascii=False)
        selected = [f for f in facts if f['subject'] in context or any(s['citation_id'] in cids for s in f['supports'])]
        task['report_facts'] = copy.deepcopy(selected)
        if not selected:
            continue
        retrieval = task.setdefault('external_rag_retrieval', {})
        adopted = retrieval.setdefault('evidence_blocks', copy.deepcopy(blocks))
        added = False
        seen = {source_identity(block) for block in adopted}
        for fact in selected:
            for support in fact['supports']:
                block = lookup[support['evidence_id']]
                if source_identity(block) not in seen:
                    adopted.append(copy.deepcopy(block))
                    seen.add(source_identity(block))
                    added = True
        if added:
            retrieval['rag_context_text'] = build_rag_context_text(adopted)
    return result

"""Pure allocation of evidence candidates across report sections."""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any


def _material_key(block: Any) -> str:
    """Return a stable library/material identity, falling back to vector id."""
    if not isinstance(block, dict):
        return ""
    library = str(block.get("library") or "").strip()
    material_id = str(block.get("material_id") or "").strip()
    vector_id = str(block.get("vector_id") or "").strip()
    identity = material_id or vector_id
    return f"{library}:{identity}" if identity else ""


def allocate_evidence_blocks(section_candidates: list[dict[str, Any]], target_per_section: int) -> list[dict[str, Any]]:
    """Allocate at most ``target_per_section`` evidence blocks for each section.

    Candidates are consumed in section order. One candidate per material is selected
    first, preferring materials used in fewer preceding sections; a section's first
    valid candidate is always retained. Remaining slots may contain a second chunk
    from a selected material. Inputs and selected blocks are deep copied.
    """
    try:
        target = max(0, int(target_per_section))
    except (TypeError, ValueError):
        target = 0

    prior_usage: defaultdict[str, int] = defaultdict(int)
    allocated: list[dict[str, Any]] = []

    for section in section_candidates or []:
        section_copy = copy.deepcopy(section)
        candidates = section.get("candidates", []) if isinstance(section, dict) else []
        if not isinstance(candidates, list):
            candidates = []

        valid: list[tuple[int, dict[str, Any], str]] = []
        for index, candidate in enumerate(candidates):
            key = _material_key(candidate)
            if key and isinstance(candidate, dict):
                valid.append((index, candidate, key))

        selected: list[tuple[int, dict[str, Any], str]] = []
        selected_keys: set[str] = set()
        first = valid[0] if valid else None
        seen_vectors = set()
        if target and first is not None:
            selected.append(first)
            selected_keys.add(first[2])
            seen_vectors.add((first[1].get("library"), first[1].get("vector_id")))
            for pool in ([r for r in valid if r[0] < 10],
                         [r for r in valid if r[0] >= 10]):
                for row in sorted(pool, key=lambda r: (prior_usage[r[2]], r[0])):
                    if len(selected) >= target:
                        break
                    vector = (row[1].get("library"), row[1].get("vector_id"))
                    if row[2] in selected_keys or (vector[1] and vector in seen_vectors):
                        continue
                    selected.append(row)
                    selected_keys.add(row[2])
                    if vector[1]:
                        seen_vectors.add(vector)
            selected.sort(key=lambda r: (r[0] >= 10, prior_usage[r[2]], r[0]))
            per_material = defaultdict(int)
            for row in selected:
                per_material[row[2]] += 1
            for row in valid:
                if len(selected) >= target:
                    break
                vector = (row[1].get("library"), row[1].get("vector_id"))
                if row[2] not in selected_keys or per_material[row[2]] >= 2:
                    continue
                if not vector[1] or vector in seen_vectors:
                    continue
                selected.append(row)
                per_material[row[2]] += 1
                seen_vectors.add(vector)

        blocks = [copy.deepcopy(candidate) for _, candidate, _ in selected]
        selected_materials = {key for _, _, key in selected}
        reused = sorted(key for key in selected_materials if prior_usage[key] > 0)
        section_copy["evidence_blocks"] = blocks
        section_copy["diagnostics"] = {
            "candidate_count": len(candidates),
            "distinct_material_count": len(selected_materials),
            "reused_material_ids": reused,
        }
        allocated.append(section_copy)

        for key in selected_materials:
            prior_usage[key] += 1

    return allocated


# One bounded semantic pass shares existing snippets before normal allocation.
from llm_client import llm
from .structured_output import parse_json_object
from .writing_decisions import compact_json
from .agentic_rag.assessment import evidence_key, _refresh

MAX_SHARING_INPUT_CHARS = 86000
SHARING_PROMPT = '''你是整篇报告已有证据的需求分配器。只把输入中相关原文分配到确实需要的目标需求，不检索、不生成来源。
仅返回{"allocations":[{"section_id":"S1.1","requirement_id":"r1","status":"supported/insufficient/unknown/conflicting","reason":"目标需求支持判断","support":[{"evidence_id":"e1","quote":"逐字原文"}]}]}。
没有跨节用途则返回空数组；同一section_id+requirement_id最多一项。不得把整池材料复制给每节。
依据目标需求重新判断，不能复制来源章节的supported；必须保留对象、时期、总收入/业务收入、计划/实绩等限定。
单年收入不支持五年增长；资料只提及公司不支持排名。supported必须由逐字原文实质回答目标需求。
insufficient仍可分配有用的部分依据，但不能把目标需求改为supported；截断或日期不明应为unknown。
conflicting必须绑定两个不同的现有片段。只传片段索引和原文quote，不输出改写的材料。
只返回带来新增跨节依据的分配，不重复目标小节已持有的片段，不逐项复述所有需求状态。
最多返回12项关键分配，每项最多2个支持片段，quote只摘取足以支持判断的原文且不超过120字，reason不超过80字；优先核心比较缺口，无新增可返回空数组。'''


def share_evidence_candidates(subsections, rows):
    """Return copied retrieval rows with only semantically mapped existing evidence.

    Uses one bounded model call, no new retrieval. Target requirement assessment is
    rebound to original chunk identity so existing allocation/citation binding works.
    Failure retains all original candidates and exposes evidence_sharing diagnostics.
    """
    original = copy.deepcopy(rows)
    if len(subsections) != len(rows):
        return original
    sections, pool, lookup, identities = [], [], {}, {}
    for section, row in zip(subsections, rows):
        if not isinstance(row, dict):
            continue
        requirements = (row.get('evidence_pack') or {}).get('requirements') or []
        if requirements:
            sections.append({'section_id': section['outline_id'], 'title': section.get('title', ''),
                             'requirements': [{k: copy.deepcopy(r.get(k)) for k in
                                               ('id', 'requirement', 'status', 'reason')} for r in requirements
                                              if r.get('status') != 'supported']})
        for block in (row.get('external_rag_retrieval') or {}).get('evidence_blocks', []):
            key = tuple(evidence_key(block).values())
            if not any(key) or not block.get('text'):
                continue
            if key not in identities:
                id = f'e{len(pool)+1}'
                identities[key] = id
                text = str(block['text'])[:1000]
                lookup[id] = (block, text, section['outline_id'])
                pool.append({'evidence_id': id, 'source_section_id': section['outline_id'],
                             'identity': evidence_key(block), 'text': text,
                             **{k: block.get(k, '') for k in ('title', 'publish_date', 'evidence_scope', 'review_note')}})
    if len(rows) < 2 or not sections or not pool:
        return original
    # Keep all document identities; shorten preview text rather than dropping
    # later sections. Known assessed quotes preserve useful non-leading facts.
    for preview_limit in (1000, 300, 120, 80):
        for item in pool:
            block, _, source_id = lookup[item['evidence_id']]
            raw = str(block['text'])
            assessed_quotes = [ref.get('quote', '') for row in rows
                               for req in (row.get('evidence_pack') or {}).get('requirements', [])
                               for ref in req.get('support', [])
                               if ref.get('evidence_key') == evidence_key(block)
                               and ref.get('quote') in raw]
            excerpt = raw[:preview_limit]
            for quote in assessed_quotes[:2]:
                if quote and quote not in excerpt:
                    excerpt += '\n' + quote[:240]
            item['text'] = excerpt
            item['truncated'] = excerpt != raw
            lookup[item['evidence_id']] = (block, excerpt, source_id)
        wire = ([{k: item[k] for k in ('evidence_id', 'text')} for item in pool]
                if preview_limit == 80 else
                [{k: item[k] for k in ('evidence_id', 'text', 'truncated')}
                 | {'title': str(item.get('title') or '')[:70],
                    'publish_date': str(item.get('publish_date') or '')[:20]}
                 for item in pool])
        payload = compact_json({'sections': sections, 'evidence': wire})
        if len(payload) <= MAX_SHARING_INPUT_CHARS:
            break

    def failure(reason, status='failed'):
        for row in original:
            if isinstance(row, dict):
                row['evidence_sharing'] = {'status': status, 'reason': reason}
        return original

    if len(payload) > MAX_SHARING_INPUT_CHARS:
        return failure('已有证据共享输入超过预算，保留逐节候选', 'skipped_budget')
    try:
        result = llm.query_result(user_prompt=payload, system_prompt=SHARING_PROMPT,
                                  max_tokens=6000, reasoning_effort=None,
                                  extra_body={'thinking': {'type': 'disabled'}},
                                  extra_log_info='report_generation.evidence_sharing')
        if result.error_message or result.finish_reason == 'length':
            raise ValueError('证据共享调用失败或输出截断')
        allocations = parse_json_object(result.content).get('allocations')
        if not isinstance(allocations, list):
            raise ValueError('证据共享缺少allocations数组')
        by_id = {section['outline_id']: row for section, row in zip(subsections, original)}
        seen = set()
        validated = []
        for item in allocations:
            sid, rid = item.get('section_id'), item.get('requirement_id')
            if sid not in by_id or (sid, rid) in seen:
                raise ValueError('目标小节不存在或需求重复分配')
            seen.add((sid, rid))
            pack = by_id[sid].get('evidence_pack') or {}
            requirement = next((r for r in pack.get('requirements', []) if r.get('id') == rid), None)
            if requirement is None or item.get('status') not in {'supported', 'insufficient', 'unknown', 'conflicting'}:
                raise ValueError('目标需求或支持状态无效')
            if not isinstance(item.get('reason'), str) or not item['reason'].strip():
                raise ValueError('目标需求缺少支持判断原因')
            refs = item.get('support')
            if not isinstance(refs, list) or not refs:
                raise ValueError('共享需求必须绑定有用的现有片段')
            support, blocks = [], []
            for ref in refs:
                id, quote = ref.get('evidence_id'), ref.get('quote')
                if id not in lookup or not isinstance(quote, str) or not quote.strip() or quote not in lookup[id][1]:
                    raise ValueError('证据共享引用或逐字原文无效')
                block, _, source_id = lookup[id]
                support.append({'evidence_key': evidence_key(block), 'quote': quote})
                blocks.append((block, source_id))
            if item['status'] == 'conflicting' and len({tuple(s['evidence_key'].values()) for s in support}) < 2:
                raise ValueError('冲突需求必须绑定两个不同片段')
            validated.append((sid, requirement, item, support, blocks))
        for sid, requirement, item, support, blocks in validated:
            row = by_id[sid]
            retrieval = row.setdefault('external_rag_retrieval', {})
            candidates = retrieval.setdefault('evidence_blocks', [])
            existing = {tuple(evidence_key(b).values()) for b in candidates}
            for block, source_id in blocks:
                key = tuple(evidence_key(block).values())
                if key not in existing:
                    shared = copy.deepcopy(block)
                    shared['shared_from_outline_id'] = source_id
                    candidates.append(shared)
                    existing.add(key)
            requirement.update(status=item['status'], reason=item['reason'], support=support)
            if item['status'] == 'supported':
                requirement['follow_up_query'] = ''
            pack = row['evidence_pack']
            # A successful target assessment of shared snippets supersedes local retrieval failure.
            if item['status'] in ('supported', 'conflicting'):
                pack['status'] = 'assessed'
            _refresh(pack)
        for row in original:
            if isinstance(row, dict):
                row['evidence_sharing'] = {'status': 'completed', 'mapped_requirement_count': len(validated)}
        return original
    except Exception as exc:
        return failure(str(exc) or '已有证据共享失败')

"""Bounded, independent review requests retaining every claim and section."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import copy
import json
import re

from .runtime_budget import BudgetExceeded, call_remaining, submit_with_context
from .agentic_rag.verification import validate_checks

MAX_SECTIONS = 3
MAX_CLAIMS_PER_SECTION = 8
MAX_INPUT_CHARS = 86000
_INDEX_PROMPT = '''为长报告定位需要比较的跨节重复。section_index包含全部小节的段落摘要，摘要不是可编辑原文。
只返回JSON：{"related_section_groups":[["S1.1","S20.1"]]}。列出可能重复介绍同一事实、数字、案例、分类或结论的小节组，每组2到3节；相关分析用途不同也可列出，后续将核对原文。覆盖后部小节，不默认保留最早位置。不输出引文、修改或claim_checks。'''


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def claim_batches(prepared_sections, originals=None):
    """Round-robin overflow into later batches; identities/offsets never change."""
    originals_by_id = None if originals is None else {s['outline_id']: s for s in originals}
    slices = []
    for section in prepared_sections:
        if not section['claims']:
            slices.append(section)
        for start in range(0, len(section['claims']), MAX_CLAIMS_PER_SECTION):
            claims = section['claims'][start:start + MAX_CLAIMS_PER_SECTION]
            used = {cid for c in claims for cid in c['citation_ids'] + c.get('context_citation_ids', []) + c.get('section_citation_ids', [])}
            evidence, remaining, incomplete = [], 8000, section['incomplete_evidence']
            for source in section['evidence']:
                if source['citation_id'] not in used:
                    continue
                if remaining <= 0:
                    incomplete = True
                    continue
                e = copy.deepcopy(source)
                if len(e['text']) > remaining:
                    e['text'] = e['text'][:remaining]
                    e['truncated'] = True
                    incomplete = True
                remaining -= len(e['text'])
                evidence.append(e)
            unavailable = set(section.get('unavailable_citation_ids', []))
            unavailable.update(used - {e['citation_id'] for e in evidence})
            unavailable.update(e['citation_id'] for e in evidence if e.get('truncated'))
            slices.append({**section, 'claims': claims, 'evidence': evidence, 'unavailable_citation_ids': sorted(unavailable),
                           'incomplete_evidence': incomplete, 'omitted_claim_count': 0})
    batches, batch = [], []
    for section in slices:
        # A section appears at most once per call, even when it has overflow.
        if (len(batch) >= MAX_SECTIONS or any(s['outline_id'] == section['outline_id'] for s in batch)
                or len(_json(_claim_payload(batch + [section], originals_by_id))) > MAX_INPUT_CHARS):
            if batch:
                batches.append(batch)
            batch = []
        batch.append(section)
    if batch:
        batches.append(batch)
    return batches


def _claim_wire(section, include_body=False):
    # Initial checks retain paragraph context for pronouns; preservation checks
    # already carry the whole body. Context is writer text, never source evidence.
    wire = {k: v for k, v in section.items() if include_body or k != 'body_text'}
    if include_body:
        return wire
    body = section.get('body_text', '')
    claims = section.get('claims', [])
    context, number = [], 0
    for line in re.finditer(r'[^\n]+', body):
        if not line.group().strip():
            continue
        number += 1
        pid = f"{section['outline_id']}:P{number}"
        selected = [claim for claim in claims if claim['paragraph_id'] == pid]
        if not selected:
            continue
        if len(line.group()) <= 1600:
            ranges = [(line.start(), line.end())]
        else:
            ranges = [(line.start(), line.start() + 400)]
            for claim in selected:
                ranges.extend([(max(line.start(), claim['start'] - 240), claim['start']),
                               (claim['end'], min(line.end(), claim['end'] + 240))])
        merged = []
        for start, end in sorted(ranges):
            if end <= start:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        context.extend({'paragraph_id': pid, 'start': start, 'end': end,
                        'text': body[start:end], 'truncated': start != line.start() or end != line.end()}
                       for start, end in merged)
    wire['paragraph_context'] = context
    return wire


def _claim_payload(batch, originals_by_id=None):
    payload = {'claim_verification': [_claim_wire(s, include_body=originals_by_id is not None) for s in batch]}
    if originals_by_id is not None:
        payload['original_sections'] = [originals_by_id[oid] for oid in dict.fromkeys(s['outline_id'] for s in batch)
                                        if oid in originals_by_id]
    return payload


def _split_batch(batch):
    if len(batch) > 1:
        mid = (len(batch) + 1) // 2
        return [batch[:mid], batch[mid:]]
    section = batch[0]
    if len(section['claims']) <= 1:
        return []
    mid = (len(section['claims']) + 1) // 2
    return [[{**section, 'claims': section['claims'][:mid]}],
            [{**section, 'claims': section['claims'][mid:]}]]


def _run_independent(jobs, worker):
    """Two in-flight calls, deadline-aware collection including already done work."""
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='report-review')
    waiting = iter(enumerate(jobs))
    active, results = {}, {}
    exhausted = False
    try:
        while active or not exhausted:
            while len(active) < 2 and not exhausted:
                try:
                    index, job = next(waiting)
                except StopIteration:
                    exhausted = True
                    break
                try:
                    call_remaining()
                except BudgetExceeded as exc:
                    results[index] = (None, str(exc))
                    for remaining_index, _ in waiting:
                        results[remaining_index] = (None, str(exc))
                    exhausted = True
                    break
                active[submit_with_context(executor, worker, job)] = index
            if not active:
                continue
            # Drain completed calls before testing a now-expired deadline.
            done = {future for future in active if future.done()}
            if not done:
                try:
                    timeout = call_remaining()
                except BudgetExceeded:
                    timeout = 0
                done, _ = wait(active, timeout=timeout, return_when=FIRST_COMPLETED)
            if not done:
                for future, index in active.items():
                    if future.done():
                        done.add(future)
                    else:
                        future.cancel()
                        results[index] = (None, '审查阶段时间预算已耗尽')
                for index, _ in waiting:
                    results[index] = (None, '审查阶段时间预算已耗尽')
                exhausted = True
                for future in list(active):
                    if future not in done:
                        del active[future]
            for future in done:
                index = active.pop(future)
                try:
                    results[index] = (future.result(), '')
                except Exception as exc:
                    results[index] = (None, str(exc) or type(exc).__name__)
        return [results[index] for index in range(len(jobs))]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def check_claim_batches(prepared_sections, query, prompt, originals=None):
    """Return per-section rows and explicit per-claim failure reasons."""
    batches = claim_batches(prepared_sections, originals=originals)
    originals_by_id = None if originals is None else {s['outline_id']: s for s in originals}

    def request(batch):
        text = _json(_claim_payload(batch, originals_by_id))
        if len(text) > MAX_INPUT_CHARS:
            raise ValueError('claim_batch_input_budget')
        return query(text, prompt, 6000)

    def worker(batch):
        try:
            answer = request(batch)
        except Exception as exc:
            # All failures share one retry opportunity; split only truncated calls.
            if str(exc) == 'model_output_truncated':
                smaller = _split_batch(batch)
            elif isinstance(exc, ValueError) and str(exc) not in ('model_output_unavailable', 'claim_batch_input_budget'):
                smaller = [batch]
            else:
                smaller = []
            if not smaller:
                return [(batch, None, str(exc) or type(exc).__name__)]
            result = []
            for small in smaller:
                try:
                    call_remaining()
                    result.append((small, request(small), ''))
                except Exception as retry_exc:
                    result.append((small, None, str(retry_exc) or type(retry_exc).__name__))
            return result
        rows = answer.get('claim_checks', []) if isinstance(answer, dict) else []
        rows = rows if isinstance(rows, list) else []
        pending, valid_ids = [], set()
        for prepared in batch:
            checked = validate_checks(prepared, rows)
            missing = {c['claim_id'] for c in checked['claims'] if c.get('validation_error')}
            valid_ids.update(c['claim_id'] for c in checked['claims'] if not c.get('validation_error'))
            if missing:
                pending.append({**prepared, 'claims': [c for c in prepared['claims'] if c['claim_id'] in missing]})
        if not pending:
            return [(batch, answer, '')]
        # Keep all valid semantic judgments, including honest unknowns. Retry only
        # protocol omissions/invalid bindings, never a second full-report check.
        combined = dict(answer) if isinstance(answer, dict) else {}
        combined['claim_checks'] = [r for r in rows if isinstance(r, dict) and r.get('claim_id') in valid_ids]
        try:
            call_remaining()
            retry = request(pending)
            if isinstance(retry, dict):
                retry_ids = {c['claim_id'] for p in pending for c in p['claims']}
                combined['claim_checks'].extend(r for r in retry.get('claim_checks', [])
                    if isinstance(r, dict) and r.get('claim_id') in retry_ids)
                # First-call preservation rows cover the complete section, not just
                # retry claims. Use retry rows only if a section was never returned.
                old_losses = combined.get('information_loss', [])
                old_ids = {r.get('outline_id') for r in old_losses if isinstance(r, dict)}
                combined['information_loss'] = old_losses + [r for r in retry.get('information_loss', [])
                    if isinstance(r, dict) and r.get('outline_id') not in old_ids]
            return [(batch, combined, '')]
        except Exception as exc:
            return [(batch, combined, str(exc) or type(exc).__name__)]

    rows, failures, losses = {}, {}, {}
    for batch, (results, error) in zip(batches, _run_independent(batches, worker)):
        for subbatch, answer, reason in results or [(batch, None, error)]:
            valid_rows = answer.get('claim_checks') if isinstance(answer, dict) else None
            valid_rows = valid_rows if isinstance(valid_rows, list) else []
            for prepared in subbatch:
                oid = prepared['outline_id']
                ids = {c['claim_id'] for c in prepared['claims']}
                scoped_rows = [r for r in valid_rows if isinstance(r, dict) and r.get('claim_id') in ids]
                validated = validate_checks(prepared, scoped_rows, failure_reason='声明核对批次未覆盖：' + (reason or '未返回该声明的有效核对结果'))
                rows.setdefault(oid, []).extend(validated['claims'])
                returned = {r['claim_id'] for r in validated['claims'] if not r.get('validation_error')}
                for cid in ids - returned:
                    failures[cid] = '声明核对批次未覆盖：' + (reason or '未返回该声明的有效核对结果')
                loss_rows = answer.get('information_loss', []) if isinstance(answer, dict) else []
                losses.setdefault(oid, []).extend(r for r in loss_rows if isinstance(r, dict) and r.get('outline_id') == oid)
    return rows, failures, losses


def repetition_responses(payload, query, prompt):
    """Whole small reports; index and bounded raw groups for long reports."""
    sections = payload['sections']
    input_size = getattr(query, 'input_size', lambda value: len(_json(value)))
    if len(sections) <= 8 and input_size(payload) <= MAX_INPUT_CHARS:
        try:
            return [(query(_json(payload), prompt, 16000), '')]
        except Exception as exc:
            return [(None, str(exc) or type(exc).__name__)]
    index = [{'outline_id': s['outline_id'], 'title': s['title'],
              'paragraphs': [{'id': p['id'], 'summary': p['text'][:240]} for p in s['paragraphs']]}
             for s in sections]
    groups, index_failure = [], ''
    try:
        located = query(_json({'report_title': payload['report_title'], 'section_index': index}), _INDEX_PROMPT, 4000)
        groups = located.get('related_section_groups', [])
        if not isinstance(groups, list):
            raise ValueError('invalid_repetition_index')
    except Exception as exc:
        index_failure = str(exc) or type(exc).__name__
    by_id = {s['outline_id']: s for s in sections}
    ids = list(by_id)
    # Every section receives a raw-text local pass, including all late sections.
    requested = [ids[start:start + MAX_SECTIONS] for start in range(0, len(ids), MAX_SECTIONS)]
    for group in groups:
        if not isinstance(group, list) or any(not isinstance(oid, str) or oid not in by_id for oid in group):
            continue
        related = list(dict.fromkeys(group))
        if len(related) >= 2:
            requested.extend([related[0]] + related[start:start + 2] for start in range(1, len(related), 2))
    jobs, seen = [], set()
    for group in requested:
        key = tuple(sorted(group))
        if key in seen:
            continue
        seen.add(key)
        # Split oversized groups at paragraph boundaries, never truncate a section.
        def job_for(chunk):
            selected = []
            for owner in group:
                ps = [p for oid, p in chunk if oid == owner]
                if ps:
                    selected.append({**by_id[owner], 'paragraphs': ps})
            return {**payload, 'sections': selected}

        chunks, chunk = [], []
        for oid in group:
            section = by_id[oid]
            for paragraph in section['paragraphs']:
                raw = paragraph['text']
                for start in range(0, len(raw), 15744):
                    end = min(start + 16000, len(raw))
                    window = {**paragraph, 'text': raw[start:end], 'start': start, 'end': end}
                    candidate = chunk + [(oid, window)]
                    if chunk and input_size(job_for(candidate)) > MAX_INPUT_CHARS:
                        chunks.append(chunk)
                        chunk = []
                    chunk.append((oid, window))
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            jobs.append(job_for(chunk))
    results = _run_independent(jobs, lambda job: query(_json(job), prompt, 8000))
    if index_failure:
        results.append((None, '跨节索引未完成：' + index_failure))
    return results

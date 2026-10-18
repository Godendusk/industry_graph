"""Execute chapter subqueries sequentially and retain provenance on merged chunks."""

import copy
import time
from report_generation.runtime_budget import call_remaining, BudgetExceeded
from itertools import zip_longest

from report_generation.external_rag.report_adapter import build_rag_context_text
from report_generation.graph_evidence import merge_curation_fields


def _merge_blocks(groups, *, graph=False):
    output, by_key = [], {}
    # Round-robin preserves a place for each question before section allocation.
    for entries in zip_longest(*groups):
        for entry in entries:
            if entry is None:
                continue
            block, query_id = entry
            block = copy.deepcopy(block)
            if graph:
                key = (block.get('segment') or {}).get('id')
            else:
                chunk = block.get('chunk_id') or block.get('vector_id')
                key = (block.get('industry'), block.get('library'), chunk) if chunk else None
            if key is None:
                output.append(block)
                block['agentic_query_ids'] = block.get('agentic_query_ids') or ([query_id] if query_id else [])
                continue
            if key in by_key:
                previous = by_key[key]
                for id in (block.get('agentic_query_ids') or ([query_id] if query_id else [])):
                    if id not in previous['agentic_query_ids']:
                        previous['agentic_query_ids'].append(id)
                previous.update(merge_curation_fields(previous, block))
                previous['graph_linked'] = bool(previous.get('graph_linked') or block.get('graph_linked'))
                for field in ('graph_matches', 'graph_evidence_refs', 'agentic_query_refs'):
                    if field in block:
                        target = previous.setdefault(field, [])
                        for value in block[field]:
                            if value not in target:
                                target.append(copy.deepcopy(value))
            else:
                block['agentic_query_ids'] = block.get('agentic_query_ids') or ([query_id] if query_id else [])
                by_key[key] = block
                output.append(block)
    return output


def _merge_retrievals(rows, field, *, graph=False):
    values = [row[field] for row in rows if isinstance(row.get(field), dict)]
    successes = [value for value in values if value.get('status') == 'success']
    merged = copy.deepcopy((successes or values or [{}])[0])
    merged['status'] = 'success' if successes else ('error' if any(v.get('status') == 'error' for v in values) else 'skipped')
    merged['evidence_blocks'] = _merge_blocks([
        [(block, row['_query_id']) for block in row.get(field, {}).get('evidence_blocks', [])]
        for row in rows
    ], graph=graph)
    if merged['evidence_blocks'] and not graph:
        merged['status'] = 'success'
    merged['warnings'] = [copy.deepcopy(w) for value in values for w in value.get('warnings', [])]
    if graph:
        merged['graph_context_text'] = '\n\n'.join(dict.fromkeys(v.get('graph_context_text', '') for v in successes if v.get('graph_context_text')))
        segments = []
        for value in successes:
            for segment in value.get('matched_segments', []):
                if segment not in segments:
                    segments.append(copy.deepcopy(segment))
        merged['matched_segments'] = segments
    else:
        merged['rag_context_text'] = build_rag_context_text(merged['evidence_blocks'])
        merged['diagnostics'] = {'sub_queries': [copy.deepcopy(v.get('diagnostics', {})) for v in values]}
        if any(v.get('retrieval_degraded') or v.get('status') == 'error' for v in values):
            merged['retrieval_degraded'] = True
    return merged


def execute_plan(plan, *, retrieve):
    started = time.monotonic()
    rows, steps, warnings = [], [], []
    if plan['status'] == 'fallback':
        warnings.append({'stage': 'agentic_planning', 'outline_id': plan['outline_id'],
                         'message': plan['fallback_reason']})
    for query in plan['sub_queries']:
        call_remaining()
        step_start = time.monotonic()
        try:
            row, query_warnings = retrieve(query['question'], query['strategy'])
            row = copy.deepcopy(row)
            warnings.extend(query_warnings)
            statuses = [row.get(key, {}).get('status', 'skipped') for key in ('graph_retrieval', 'external_rag_retrieval')]
            status = 'partial' if 'error' in statuses and 'success' in statuses else ('error' if 'error' in statuses else 'skipped' if all(s == 'skipped' for s in statuses) else 'success')
            step = {'id': query['id'], 'query': row.get('section_retrieval_query', query['question']),
                    'question': query['question'], 'strategy': query['strategy'],
                    'status': status, 'graph_status': statuses[0], 'external_status': statuses[1],
                    'candidate_count': len(row.get('external_rag_retrieval', {}).get('evidence_blocks', [])),
                    'diagnostics': copy.deepcopy(row.get('external_rag_retrieval', {}).get('diagnostics', {})),
                    'graph_evidence_diagnostics': copy.deepcopy(row.get('external_rag_retrieval', {}).get('graph_diagnostics', {})),
                    'graph_keyword_terms': copy.deepcopy(row.get('external_rag_retrieval', {}).get('graph_keyword_terms', [])),
                    'graph_keyword_diagnostics': copy.deepcopy(row.get('external_rag_retrieval', {}).get('graph_keyword_diagnostics', {})),
                    'graph_selection_diagnostics': copy.deepcopy(row.get('graph_retrieval', {}).get('selection_diagnostics', {})),
                    'tool_calls': copy.deepcopy(row.get('tool_calls', [])),
                    'warnings': copy.deepcopy(query_warnings)}
        except BudgetExceeded:
            raise
        except Exception as exc:
            row = {'graph_retrieval': {'status': 'error', 'evidence_blocks': []},
                   'external_rag_retrieval': {'status': 'error', 'evidence_blocks': []}}
            warning = {'stage': 'agentic_retrieval', 'outline_id': plan['outline_id'], 'query_id': query['id'], 'message': str(exc)}
            warnings.append(warning)
            step = {'id': query['id'], 'query': row.get('section_retrieval_query', query['question']),
                    'question': query['question'], 'strategy': query['strategy'],
                    'status': 'error', 'message': str(exc)}
        step['elapsed_seconds'] = time.monotonic() - step_start
        for field in ('graph_retrieval', 'external_rag_retrieval'):
            for block in row.get(field, {}).get('evidence_blocks', []):
                block['agentic_query_refs'] = [{'outline_id': plan['outline_id'], 'query_id': query['id']}]
        row['_query_id'] = query['id']
        rows.append(row)
        steps.append(step)
    state = 'skipped' if not steps or all(s['status'] == 'skipped' for s in steps) else ('error' if all(s['status'] == 'error' for s in steps) else
                                        'partial' if any(s['status'] in ('error', 'partial') for s in steps) else 'success')
    result = {'graph_retrieval': _merge_retrievals(rows, 'graph_retrieval', graph=True),
              'external_rag_retrieval': _merge_retrievals(rows, 'external_rag_retrieval'),
              'agentic_retrieval': {'status': state, 'plan': copy.deepcopy(plan), 'steps': steps,
                                   'elapsed_seconds': time.monotonic() - started}}
    return result, warnings

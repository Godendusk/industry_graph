"""One initial retrieval and at most one gap-driven follow-up round."""

import copy
import time

from .assessment import assess_evidence, evidence_key
from .executor import execute_plan, _merge_retrievals
from .schemas import validate_queries

MAX_FOLLOW_UP_QUERIES = 2


def _identities(blocks):
    return {tuple(evidence_key(block).values()) for block in blocks}


def retrieve_chapter(plan, *, retrieve, assessor=None, on_event=None, defer_followup=False, initial_result=None):
    started = time.monotonic()
    assess = assessor or assess_evidence
    def emit(phase, **details):
        if callable(on_event):
            on_event({'phase': phase, **details})
    if initial_result is None:
        emit('retrieving')
        initial, warnings = execute_plan(plan, retrieve=retrieve)
        external = initial['external_rag_retrieval']
        emit('assessing')
        pack = assess(plan, external.get('evidence_blocks', []), retrieval_status=external['status'])
        warnings.extend(pack.get('warnings', []))
        trace = initial['agentic_retrieval']
        for step in trace['steps']:
            step['round'] = 0
        trace['assessments'] = [copy.deepcopy(pack)]
        trace['follow_up'] = {'rounds': 0, 'query_count': 0, 'new_evidence_count': 0, 'stop_reason': ''}
    else:
        initial = copy.deepcopy(initial_result)
        warnings = []
        external = initial['external_rag_retrieval']
        pack = initial['evidence_pack']
        trace = initial['agentic_retrieval']
    if defer_followup:
        trace['follow_up']['stop_reason'] = 'awaiting_shared_evidence'
        initial['evidence_pack'] = pack
        trace['elapsed_seconds'] = time.monotonic() - started
        return initial, warnings
    followup = trace['follow_up']
    seen = {' '.join(q['question'].split()) for q in plan['sub_queries']}
    queries = []
    if pack['status'] == 'assessed':
        context = {**plan.get('input', {}), 'industry': plan['industry']}
        context.setdefault('use_graph', False); context.setdefault('use_external_rag', True)
        for requirement in pack['requirements']:
            question = requirement.get('follow_up_query', '').strip()
            if requirement['status'] == 'supported' or not question or ' '.join(question.split()) in seen:
                continue
            payload = {'industry': plan['industry'], 'sub_queries': [{
                'question': question, 'strategy': requirement.get('strategy', 'hybrid'),
                'evidence_requirements': [requirement['requirement']], 'reason': requirement['reason']}]}
            try:
                query = validate_queries(payload, context)[0]
            except (ValueError, TypeError):
                continue
            query['id'] = f'f{len(queries)+1}'
            query['requirement_ids'] = [requirement['id']]
            queries.append(query); seen.add(' '.join(question.split()))
            if len(queries) == MAX_FOLLOW_UP_QUERIES:
                break
    if queries:
        followup.update(rounds=1, query_count=len(queries))
        follow_plan = {**copy.deepcopy(plan), 'status': 'planned', 'sub_queries': queries, 'fallback_reason': ''}
        emit('follow_up', query_count=len(queries))
        supplemental, more_warnings = execute_plan(follow_plan, retrieve=retrieve)
        warnings.extend(more_warnings)
        for step in supplemental['agentic_retrieval']['steps']:
            step['round'] = 1
        trace['follow_up_plan'] = follow_plan
        trace['steps'].extend(supplemental['agentic_retrieval']['steps'])
        old = _identities(external.get('evidence_blocks', []))
        new = _identities(supplemental['external_rag_retrieval'].get('evidence_blocks', [])) - old
        followup['new_evidence_count'] = len(new)
        rows = [{**initial, '_query_id': ''}, {**supplemental, '_query_id': ''}]
        initial['external_rag_retrieval'] = _merge_retrievals(rows, 'external_rag_retrieval')
        initial['graph_retrieval'] = _merge_retrievals(rows, 'graph_retrieval', graph=True)
        states = [s['status'] for s in trace['steps']]
        trace['status'] = 'error' if all(s == 'error' for s in states) else ('partial' if any(s in ('error','partial') for s in states) else 'success')
        if new:
            external = initial['external_rag_retrieval']
            emit('assessing')
            pack = assess(plan, external['evidence_blocks'], retrieval_status=external['status'])
            trace['assessments'].append(copy.deepcopy(pack)); warnings.extend(pack.get('warnings', []))
            followup['stop_reason'] = 'round_limit' if pack.get('uncovered_requirements') else 'requirements_supported'
        else:
            followup['stop_reason'] = 'retrieval_failed' if supplemental['agentic_retrieval']['status'] == 'error' else 'no_new_evidence'
    else:
        followup['stop_reason'] = 'assessment_' + pack['status'] if pack['status'] != 'assessed' else 'no_new_query'
    trace['elapsed_seconds'] = time.monotonic() - started
    trace['assessment_model_calls'] = sum(p.get('model_calls', 0) for p in trace['assessments'])
    emit('retrieval_completed', status=trace['status'])
    initial['evidence_pack'] = pack
    return initial, warnings

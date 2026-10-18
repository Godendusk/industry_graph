"""Offline comparison of fixed Hybrid v2 + GraphRAG queries and Agentic retrieval.

Both arms use production writing, repetition review, claim verification and summary.
Only the baseline's chapter retrieval function is replaced inside this process.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
from threading import Lock
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
CASE_PATH = CODE_ROOT / 'evaluation/agentic_report/cases.json'


def save(root, name, value):
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def load_cases():
    return json.loads(CASE_PATH.read_text(encoding='utf8'))


class CallBudgetExceeded(RuntimeError):
    pass


class CallRecorder:
    """Count application query_result calls; optional local traces retain report prompts and responses."""
    def __init__(self, client, max_calls=120, trace_dir=None):
        self.client, self.max_calls = client, max_calls
        self.trace_dir = Path(trace_dir) if trace_dir is not None else None
        self.records = []
        self.stage = 'initialization'
        self.exhausted = False
        self.lock = Lock()

    def __enter__(self):
        self.original = self.client.query_result
        self.patcher = patch.object(self.client, 'query_result', self.query)
        self.patcher.start()
        return self

    def __exit__(self, *exc):
        self.patcher.stop()

    def query(self, *args, **kwargs):
        with self.lock:
            if self.max_calls is not None and len(self.records) >= self.max_calls:
                self.exhausted = True
                raise CallBudgetExceeded(f'application LLM call budget exhausted ({self.max_calls})')
            row = {'call_id': len(self.records) + 1, 'stage': self.stage, 'model': self.client.model, 'status': 'started'}
            self.records.append(row)
        start = perf_counter()
        trace = None
        if self.trace_dir is not None:
            request = {k: kwargs[k] for k in ('user_prompt', 'system_prompt', 'max_tokens', 'temperature', 'reasoning_effort') if k in kwargs}
            for key, value in zip(('user_prompt', 'system_prompt'), args):
                request[key] = value
            trace = {'request': request}
        try:
            result = self.original(*args, **kwargs)
            row.update(status='failed' if result.error_message else 'completed',
                       prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
                       finish_reason=result.finish_reason)
            if trace is not None:
                trace['response'] = {k: getattr(result, k, None) for k in
                    ('content', 'error_message', 'finish_reason', 'prompt_tokens', 'completion_tokens')}
            return result
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__)
            raise
        finally:
            row['elapsed_seconds'] = round(perf_counter() - start, 3)
            if trace is not None:
                name = f'call-{row["call_id"]:04d}.json'
                row['trace_file'] = name
                save(self.trace_dir, name, {**row, **trace})

    def summary(self):
        return {'calls': len(self.records), 'budget_exhausted': self.exhausted,
                'prompt_tokens': sum(r.get('prompt_tokens') or 0 for r in self.records),
                'completion_tokens': sum(r.get('completion_tokens') or 0 for r in self.records),
                'usage_missing_calls': sum(r.get('prompt_tokens') is None or r.get('completion_tokens') is None
                                           for r in self.records), 'records': self.records}


def source_snapshot(project_root, industries):
    """Metadata only: graph/sidecar, all vector files, and lexical-index files."""
    files = {}
    for industry in industries:
        locations = [project_root / 'static/data' / industry,
                     project_root / 'report_generation/vector_db' / industry,
                     project_root / 'RAG/indexes/report_v2_news' / industry]
        for location in locations:
            for path in sorted(location.rglob('*')) if location.exists() else []:
                if path.is_file():
                    stat = path.stat()
                    files[str(path.relative_to(project_root))] = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    return {'industries': sorted(industries), 'files': files}


def fixed_query_baseline(coordinator):
    """Adapt only the production progress callback to the existing fixed query API."""
    def retrieve(subsection, user_prompt, report_title, top_k, industry='ai',
                 use_graph=True, use_external_rag=True, on_event=None):
        return coordinator._retrieve_candidates_once(
            subsection=subsection, user_prompt=user_prompt, report_title=report_title,
            top_k=top_k, industry=industry, use_graph=use_graph,
            use_external_rag=use_external_rag)
    return retrieve


def run_pipeline(case, output, api, *, max_workers=1, top_k=5, recorder=None, resume=False):
    """Save every stage before checking status; summary/export use reviewed bodies."""
    started = perf_counter()
    timing = {}
    stage = 'coordination'
    reuse_checkpoints = resume
    failure_path = output / 'failure.json'
    failed_stage = (json.loads(failure_path.read_text(encoding='utf8')).get('failed_stage')
                    if resume and failure_path.exists() else None)
    def step(name, invoke):
        nonlocal stage, reuse_checkpoints
        stage = name
        if recorder:
            recorder.stage = name
            if recorder.exhausted:
                raise CallBudgetExceeded('application LLM call budget exhausted')
        checkpoint = output / (name + '.json')
        if name == failed_stage:
            reuse_checkpoints = False
        if reuse_checkpoints and checkpoint.exists():
            cached = json.loads(checkpoint.read_text(encoding='utf8'))
            if cached.get('status') == 'success':
                timing[name] = {'resumed': True}
                return cached
        reuse_checkpoints = False
        start = perf_counter()
        result = invoke()
        timing[name] = {'elapsed_seconds': round(perf_counter() - start, 3)}
        save(output, name + '.json', result)
        if recorder:
            save(output, 'calls.json', recorder.summary())
            if recorder.exhausted:
                raise CallBudgetExceeded('application LLM call budget exhausted')
        if result.get('status') != 'success':
            raise RuntimeError(result.get('message') or f'{name}: {result.get("status")}')
        return result
    save(output, 'request.json', case)
    try:
        common = {'report_title': case['title'], 'industry': case['industry']}
        coordinated = step('coordination', lambda: api.coordinate(
            **common, user_prompt=case['prompt'], outline=case['outline'], top_k=top_k,
            use_graph=True, use_external_rag=True, max_workers=max_workers))
        warnings = list(coordinated.get('warnings', []))
        for task in coordinated['writing_tasks']:
            warnings.extend(task.get('warnings', []))
        task_failures = [w for w in warnings if (
            w.get('stage') == 'coordinator_task_generation'
            or w.get('code') == 'coordinator_task_failure'
            or w.get('reason') == 'coordinator_task_failure')]
        if task_failures:
            raise RuntimeError('coordinator task failed: ' + '; '.join(
                w.get('message', 'worker failure') for w in task_failures))
        failed_retrieval = [t['outline_id'] for t in coordinated['writing_tasks']
                            if (t.get('external_rag_retrieval') or {}).get('status') == 'error']
        if failed_retrieval:
            raise RuntimeError('document retrieval failed: ' + ', '.join(failed_retrieval))
        bodies = step('body', lambda: api.body(
            **common, user_prompt=case['prompt'], writing_tasks=coordinated['writing_tasks'],
            references=coordinated.get('references', []), max_workers=max_workers))
        # Carry retrieval restrictions to the existing exporter; no extra API is needed.
        tasks = {t['outline_id']: t for t in coordinated['writing_tasks']}
        for section in bodies['body_sections']:
            task = tasks.get(section.get('outline_id'), {})
            for field in ('evidence_pack', 'merged_evidence_packs'):
                if field in task:
                    section[field] = copy.deepcopy(task[field])
        save(output, 'body.json', bodies)
        summary = step('summary', lambda: api.summary(
            **common, outline=coordinated.get('final_outline') or case['outline'],
            body_sections=bodies['body_sections']))
        step('export', lambda: api.export(
            **common, abstract_text=summary['abstract_text'], body_sections=bodies['body_sections'],
            references=bodies.get('references', []), adjustment_notes=bodies.get('adjustment_notes', []),
            output_dir=str(output.resolve())))
        result = {'status': 'generated_pending_human_review'}
        if failure_path.exists():
            failure_path.unlink()
    except Exception as exc:
        result = {'status': 'failed', 'failed_stage': stage, 'error': str(exc)}
        save(output, 'failure.json', result)
    result.update(elapsed_seconds=round(perf_counter() - started, 3), stages=timing)
    save(output, 'result.json', result)
    return result


_CHROMA_CLIENTS_BY_DATA_ROOT = {}


def clone_selected_data(source_root, data_root, industries):
    """Clone only selected existing retrieval data, preserving index file mtimes."""
    source_root, data_root = source_root.resolve(), data_root.resolve()
    if data_root.exists():
        raise FileExistsError(f'data copy already exists: {data_root}')
    locations = []
    for industry in industries:
        locations.extend([
            Path('static/data') / industry / 'graph_data.json',
            Path('static/data') / industry / 'graph_evidence_links.json',
            Path('report_generation/vector_db') / industry,
            Path('RAG/indexes/report_v2_news') / industry,
        ])
    existing = [relative for relative in locations if (source_root / relative).exists()]
    mechanism = 'apfs_clone_cp_cR' if sys.platform == 'darwin' else 'ordinary_copy'
    print(f'Data copy: {mechanism}; {source_root} -> {data_root}', flush=True)
    data_root.mkdir(parents=True)
    for relative in existing:
        source, target = source_root / relative, data_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'darwin':
            # -p is needed: the lexical READY marker contains file mtime metadata.
            subprocess.run(['cp', '-cRp', str(source), str(target)], check=True)
        elif source.is_dir():
            shutil.copytree(source, target, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, target)
    relocated = []
    for industry in industries:
        ready = data_root / 'RAG/indexes/report_v2_news' / industry / 'READY'
        if ready.exists():
            marker = json.loads(ready.read_text(encoding='utf8'))
            original_db = source_root / 'report_generation/vector_db' / industry / 'chroma.sqlite3'
            if marker.get('source') != str(original_db.resolve()):
                raise ValueError(f'lexical READY source differs from copied database: {industry}')
            marker['source'] = str((data_root / 'report_generation/vector_db' / industry / 'chroma.sqlite3').resolve())
            ready.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
            relocated.append(str(ready.relative_to(data_root)))
    return {'source_root': str(source_root), 'data_root': str(data_root),
            'industries': sorted(industries), 'mechanism': mechanism,
            'command': 'cp -cRp' if sys.platform == 'darwin' else 'shutil.copytree/copy2',
            'copied_paths': [str(path) for path in existing], 'relocated_ready_markers': relocated}


def configure_data_paths(project_root, data_root, *, industry_config, news_index,
                         news_retrieval, vector_store, summary_agent):
    """Separate per-arm data paths from shared model/template configuration."""
    industry_config.PROJECT_ROOT = data_root
    for industry, row in industry_config.INDUSTRY_CONFIG.items():
        row['graph_path'] = data_root / 'static/data' / industry / 'graph_data.json'
        row['vector_db_path'] = data_root / 'report_generation/vector_db' / industry
    news_index.PROJECT_ROOT = data_root
    news_index.INDEX_ROOT = data_root / 'RAG/indexes/report_v2_news'
    news_retrieval.PROJECT_ROOT = project_root
    # Existing production cache keys are industries. Select a separate cache for
    # each resolved data root so the same industry cannot reuse another arm's DB.
    vector_store._chroma_clients = _CHROMA_CLIENTS_BY_DATA_ROOT.setdefault(str(data_root.resolve()), {})
    summary_agent.DEFAULT_TEMPLATE_PATH = project_root / '产业链报告模板.docx'


def configure_runtime(project_root, data_root):
    """Use worktree code, isolated data, original .env, model files and template."""
    from dotenv import load_dotenv
    load_dotenv(project_root / '.env', override=True)
    from report_generation import industry_config, coordinator_agent, body_agent, summary_agent, word_export_agent
    from report_generation.external_rag import news_index, news_retrieval, vector_store
    configure_data_paths(project_root, data_root, industry_config=industry_config,
                         news_index=news_index, news_retrieval=news_retrieval,
                         vector_store=vector_store, summary_agent=summary_agent)
    from llm_client import llm
    return SimpleNamespace(coordinate=coordinator_agent.generate_writing_tasks,
                           body=body_agent.generate_report_bodies,
                           summary=summary_agent.generate_report_summary,
                           export=word_export_agent.export_report_docx), llm, coordinator_agent


def select_cases(industries, requested):
    selected = []
    for case in load_cases():
        if case['industry'] not in industries:
            continue
        if not requested or case['id'] in requested:
            selected.append(case)
        for subsection in case['outline'][0]['subsections']:
            case_id = case['industry'] + '-' + subsection['scenario']
            if case_id in requested:
                small = copy.deepcopy(case)
                small['id'] = case_id
                small['outline'][0]['subsections'] = [copy.deepcopy(subsection)]
                selected.append(small)
    unknown = set(requested) - {c['id'] for c in selected}
    if unknown:
        raise ValueError('unknown/unselected cases: ' + ', '.join(sorted(unknown)))
    if not selected:
        raise ValueError('no cases selected')
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--industries', nargs='+', choices=['embodied', 'biology'], default=['embodied', 'biology'])
    parser.add_argument('--cases', nargs='+', default=[])
    parser.add_argument('--max-workers', type=int, default=1)
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--max-calls', type=int, default=120, help='per arm/case; application calls, not HTTP retries')
    parser.add_argument('--resume', action='store_true', help='reuse successful stage checkpoints with identical request/config')
    args = parser.parse_args(argv)
    if min(args.max_calls, args.max_workers, args.top_k) < 1:
        parser.error('budgets and worker count must be positive')
    cases = select_cases(args.industries, args.cases)
    root, output = args.project_root.resolve(), args.output_dir.resolve()
    for industry in {c['industry'] for c in cases}:
        if not (root / 'report_generation/vector_db' / industry / 'chroma.sqlite3').is_file():
            parser.error(f'existing {industry} database missing under --project-root')
    from dotenv import load_dotenv
    load_dotenv(root / '.env', override=True)
    from llm_client import llm
    industries = sorted({c['industry'] for c in cases})
    snapshot = source_snapshot(root, industries)
    config = {'project_root': str(root), 'code_root': str(CODE_ROOT), 'model': llm.model,
              'top_k': args.top_k, 'max_workers': args.max_workers, 'max_calls': args.max_calls,
              'embedding_model': str(root / 'RAG/model_store/bge-base-zh-v1.5'),
              'reranker_model': str(root / 'RAG/model_store/bge-reranker-base'),
              'cases': cases, 'comparison': 'fixed chapter query vs Agentic retrieval; identical writing and all reviews'}
    manifest_path = output / 'manifest.json'
    manifest = {'configuration': config, 'snapshot_before': snapshot}
    if args.resume:
        previous = json.loads(manifest_path.read_text(encoding='utf8'))
        if 'data_copy' not in previous or 'fixed_data_metadata' not in previous:
            parser.error('run has no fixed data copy; use a new output directory')
        if previous['configuration'] != config or previous['snapshot_before'] != snapshot:
            parser.error('resume requires identical case/configuration and unchanged source snapshot')
        manifest = previous
        fixed_data_root = Path(manifest['data_copy']['data_root'])
        if source_snapshot(fixed_data_root, industries) != manifest['fixed_data_metadata']:
            parser.error('fixed data copy changed; use a new output directory')
    elif manifest_path.exists():
        parser.error('output already contains a run; use --resume or a new --output-dir')
    else:
        fixed_data_root = output / 'fixed_data'
        manifest['data_copy'] = clone_selected_data(root, fixed_data_root, industries)
        manifest['fixed_data_metadata'] = source_snapshot(fixed_data_root, industries)
        save(output, 'manifest.json', manifest)
    if source_snapshot(root, industries) != snapshot:
        parser.error('source metadata changed while cloning; use a new output directory')
    outcomes = []
    stable = True
    for case in cases:
        for arm in ('baseline', 'agentic'):
            arm_root = output / case['id'] / arm
            arm_data_root = arm_root / 'data'
            copy_record = arm_root / 'data_copy.json'
            if args.resume and copy_record.exists():
                arm_data_root = Path(json.loads(copy_record.read_text(encoding='utf8'))['data_root'])
            else:
                save(arm_root, 'data_copy.json', clone_selected_data(fixed_data_root, arm_data_root, industries))
            api, llm, coordinator = configure_runtime(root, arm_data_root)
            print(f'{case["id"]}: {arm}', flush=True)
            retrieval_calls = []
            original_retrieve = coordinator._retrieve_candidates_once
            def observed_retrieve(*a, **kw):
                start = perf_counter()
                row = {'outline_id': kw.get('subsection', {}).get('outline_id')}
                retrieval_calls.append(row)
                try:
                    result, warnings = original_retrieve(*a, **kw)
                    row.update(query=result.get('section_retrieval_query'),
                               tool_calls=result.get('tool_calls', []))
                    return result, warnings
                except Exception as exc:
                    row['error_type'] = type(exc).__name__
                    raise
                finally:
                    row['elapsed_seconds'] = round(perf_counter() - start, 3)
            with ExitStack() as stack:
                stack.enter_context(patch.object(coordinator, '_retrieve_candidates_once', observed_retrieve))
                if arm == 'baseline':
                    stack.enter_context(patch.object(coordinator, '_retrieve_candidates_for_subsection',
                                                    fixed_query_baseline(coordinator)))
                recorder = stack.enter_context(CallRecorder(llm, args.max_calls))
                result = run_pipeline(case, arm_root, api, max_workers=args.max_workers,
                                      top_k=args.top_k, recorder=recorder, resume=args.resume)
                # Persist each invocation separately so resumed costs are not overwritten.
                attempts = len(list(arm_root.glob('calls_attempt_*.json'))) + 1
                save(arm_root, f'calls_attempt_{attempts}.json', recorder.summary())
                save(arm_root, f'retrieval_attempt_{attempts}.json', {
                    'chapter_query_calls': len(retrieval_calls),
                    'tool_calls': sum(len(r.get('tool_calls', [])) for r in retrieval_calls),
                    'records': retrieval_calls})
            after = source_snapshot(root, industries)
            stable = after == snapshot
            save(arm_root, 'snapshot_after.json', after)
            outcomes.append({'case': case['id'], 'arm': arm, 'snapshot_unchanged': stable, **result})
            save(output, 'outcomes.json', outcomes)
            if not stable:
                print('Source metadata changed; stop comparison and inspect snapshot_after.json.', flush=True)
                break
        if not stable:
            break
    save(output, 'snapshot_after.json', source_snapshot(root, industries))
    return 0 if stable and all(r['status'] == 'generated_pending_human_review' for r in outcomes) else 1


if __name__ == '__main__':
    raise SystemExit(main())

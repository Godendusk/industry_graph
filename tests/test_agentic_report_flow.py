"""Offline acceptance harness behavior; no model or source database is needed."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/evaluate_agentic_report.py'


def harness():
    assert SCRIPT.exists(), 'offline evaluation harness is missing'
    spec = importlib.util.spec_from_file_location('agentic_evaluation', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cases_cover_two_industries_and_five_fixed_scenarios():
    m = harness()
    cases = m.load_cases()
    assert {c['industry'] for c in cases} == {'embodied', 'biology'}
    for case in cases:
        assert case['outline_source'] == 'fixed_acceptance_input'
        assert {s['scenario'] for s in case['outline'][0]['subsections']} == {
            'overview', 'chain', 'policy', 'competition', 'insufficient'}


def test_call_budget_stops_before_extra_call_and_preserves_usage():
    m = harness()
    calls = []
    client = SimpleNamespace(model='same-model', query_result=lambda **kw: (
        calls.append(kw) or SimpleNamespace(prompt_tokens=10, completion_tokens=4,
                                          error_message='', finish_reason='stop')))
    recorder = m.CallRecorder(client, max_calls=1)
    with recorder:
        client.query_result(user_prompt='first')
        with pytest.raises(m.CallBudgetExceeded):
            client.query_result(user_prompt='second')
    assert len(calls) == 1
    assert recorder.summary()['prompt_tokens'] == 10
    assert recorder.summary()['completion_tokens'] == 4
    assert recorder.summary()['calls'] == 1


def test_failed_stage_retains_result_and_does_not_summarize(tmp_path):
    m = harness()
    summary_calls = []
    api = SimpleNamespace(
        coordinate=lambda **kw: {'status': 'success', 'writing_tasks': [], 'references': []},
        body=lambda **kw: {'status': 'partial_success', 'body_sections': [{'status': 'error'}]},
        summary=lambda **kw: summary_calls.append(kw), export=lambda **kw: None)
    result = m.run_pipeline(m.load_cases()[0], tmp_path, api)
    assert result['status'] == 'failed'
    assert result['failed_stage'] == 'body'
    assert (tmp_path / 'coordination.json').exists()
    assert (tmp_path / 'body.json').exists()
    assert not summary_calls


def test_summary_and_export_receive_final_body_and_pending_notes(tmp_path):
    m = harness()
    captured = {}
    final = [{'outline_id': 'S1.1', 'status': 'success', 'body_text': '审阅后的正文',
              'claim_verification': {'status': 'needs_confirmation'}}]
    notes = [{'kind': 'review_warning', 'reason': '关键事实待确认'}]
    def summary(**kwargs):
        captured['summary'] = kwargs
        return {'status': 'success', 'abstract_text': '摘要'}
    def export(**kwargs):
        captured['export'] = kwargs
        return {'status': 'success'}
    api = SimpleNamespace(
        coordinate=lambda **kw: {'status': 'success', 'writing_tasks': [], 'references': [],
                                 'final_outline': [{'reviewed': True}]},
        body=lambda **kw: {'status': 'success', 'body_sections': final, 'adjustment_notes': notes,
                           'references': []}, summary=summary, export=export)
    result = m.run_pipeline(m.load_cases()[0], tmp_path, api)
    assert result['status'] == 'generated_pending_human_review'
    assert captured['summary']['body_sections'] == final
    assert captured['summary']['outline'] == [{'reviewed': True}]
    assert captured['export']['body_sections'] == final
    assert captured['export']['adjustment_notes'] == notes
    assert (tmp_path / 'export.json').exists()


def test_exception_is_checkpointed_and_existing_stages_retained(tmp_path):
    m = harness()
    def failed(**kwargs):
        raise RuntimeError('model unavailable')
    api = SimpleNamespace(
        coordinate=lambda **kw: {'status': 'success', 'writing_tasks': [], 'references': []},
        body=failed)
    result = m.run_pipeline(m.load_cases()[0], tmp_path, api)
    assert result['failed_stage'] == 'body'
    assert 'model unavailable' in result['error']
    assert (tmp_path / 'failure.json').exists()


def test_snapshot_detects_file_changes_without_reading_content(tmp_path):
    m = harness()
    path = tmp_path / 'report_generation/vector_db/embodied/chroma.sqlite3'
    path.parent.mkdir(parents=True)
    path.write_text('initial')
    before = m.source_snapshot(tmp_path, ['embodied'])
    path.write_text('changed contents')
    after = m.source_snapshot(tmp_path, ['embodied'])
    assert before != after
    row = before['files'][str(path.relative_to(tmp_path))]
    assert set(row) == {'size', 'mtime_ns'}


def test_retrieval_failure_is_not_treated_as_empty_success(tmp_path):
    m = harness()
    api = SimpleNamespace(coordinate=lambda **kw: {
        'status': 'success', 'writing_tasks': [{'outline_id': 'S1.1',
            'external_rag_retrieval': {'status': 'error', 'evidence_blocks': []},
            'graph_retrieval': {'status': 'success'}}]})
    result = m.run_pipeline(m.load_cases()[0], tmp_path, api)
    assert result['status'] == 'failed'
    assert result['failed_stage'] == 'coordination'
    assert 'retrieval failed' in result['error']


def test_retrieval_pack_is_carried_to_export(tmp_path):
    m = harness()
    captured = {}
    pack = {'status': 'insufficient', 'requirements': []}
    def export(**kwargs):
        captured.update(kwargs)
        return {'status': 'success'}
    api = SimpleNamespace(
        coordinate=lambda **kw: {'status': 'success', 'writing_tasks': [
            {'outline_id': 'S1.1', 'evidence_pack': pack}], 'references': []},
        body=lambda **kw: {'status': 'success', 'body_sections': [
            {'outline_id': 'S1.1', 'body_text': '最终正文', 'status': 'success'}]},
        summary=lambda **kw: {'status': 'success', 'abstract_text': '摘要'}, export=export)
    m.run_pipeline(m.load_cases()[0], tmp_path, api)
    assert captured['body_sections'][0]['evidence_pack'] == pack


def test_resume_does_not_reuse_downstream_after_rerunning_failed_stage(tmp_path):
    m = harness()
    m.save(tmp_path, 'coordination.json', {'status': 'error'})
    m.save(tmp_path, 'body.json', {'status': 'success', 'body_sections': [{'body_text': '过期正文'}]})
    captured = []
    api = SimpleNamespace(
        coordinate=lambda **kw: {'status': 'success', 'writing_tasks': [], 'references': []},
        body=lambda **kw: captured.append('regenerated') or {'status': 'error'})
    m.run_pipeline(m.load_cases()[0], tmp_path, api, resume=True)
    assert captured == ['regenerated']


def test_resume_retries_failed_stage_even_when_agent_returned_success(tmp_path):
    m = harness()
    m.save(tmp_path, 'coordination.json', {'status': 'success', 'writing_tasks': [], 'references': []})
    m.save(tmp_path, 'failure.json', {'failed_stage': 'coordination', 'error': 'call budget exhausted'})
    calls = []
    api = SimpleNamespace(coordinate=lambda **kw: calls.append('retry') or {'status': 'error'})
    m.run_pipeline(m.load_cases()[0], tmp_path, api, resume=True)
    assert calls == ['retry']


def test_fixed_baseline_accepts_progress_callback_without_forwarding_it():
    m = harness()
    calls = []
    def retrieve_once(subsection, user_prompt, report_title, top_k, industry='ai',
                      use_graph=True, use_external_rag=True):
        calls.append((subsection, user_prompt, report_title, top_k, industry, use_graph, use_external_rag))
        return {'fixed': True}, []
    coordinator = SimpleNamespace(_retrieve_candidates_once=retrieve_once)
    baseline = m.fixed_query_baseline(coordinator)
    result = baseline(subsection={'outline_id': 'S1.1'}, user_prompt='需求',
                      report_title='报告', top_k=5, industry='embodied',
                      use_graph=True, use_external_rag=True,
                      on_event=lambda event: pytest.fail('fixed query baseline must ignore callback'))
    assert result == ({'fixed': True}, [])
    assert calls == [({'outline_id': 'S1.1'}, '需求', '报告', 5, 'embodied', True, True)]


@pytest.mark.parametrize('warning', [
    {'stage': 'coordinator_task_generation', 'message': 'unexpected on_event'},
    {'code': 'coordinator_task_failure', 'message': 'worker crashed'},
    {'reason': 'coordinator_task_failure', 'message': 'worker crashed'},
])
@pytest.mark.parametrize('at_task', [False, True])
def test_internal_coordinator_failure_cannot_pass_comparison(tmp_path, warning, at_task):
    m = harness()
    task = {'outline_id': 'S1.1', 'external_rag_retrieval': {'status': 'success'}}
    coordination = {'status': 'success', 'writing_tasks': [task], 'references': []}
    (task if at_task else coordination)['warnings'] = [warning]
    body_calls = []
    api = SimpleNamespace(coordinate=lambda **kw: coordination,
                          body=lambda **kw: body_calls.append(kw))
    result = m.run_pipeline(m.load_cases()[0], tmp_path, api)
    assert result['status'] == 'failed'
    assert result['failed_stage'] == 'coordination'
    assert 'coordinator task failed' in result['error']
    assert body_calls == []
    assert (tmp_path / 'coordination.json').exists()


def test_clone_selected_data_copies_only_selected_sources_and_is_independent(tmp_path):
    m = harness()
    source = tmp_path / 'source'
    for relative in ('static/data/embodied/graph_data.json',
                     'static/data/embodied/graph_evidence_links.json',
                     'report_generation/vector_db/embodied/chroma.sqlite3',
                     'RAG/indexes/report_v2_news/embodied/lexical.sqlite3',
                     'report_generation/vector_db/biology/chroma.sqlite3', '.env'):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    import json
    ready = source / 'RAG/indexes/report_v2_news/embodied/READY'
    ready.write_text(json.dumps({'source': str((source / 'report_generation/vector_db/embodied/chroma.sqlite3').resolve())}))
    frozen = tmp_path / 'frozen'
    record = m.clone_selected_data(source, frozen, ['embodied'])
    left, right = tmp_path / 'left', tmp_path / 'right'
    m.clone_selected_data(frozen, left, ['embodied'])
    m.clone_selected_data(frozen, right, ['embodied'])
    relative = 'report_generation/vector_db/embodied/chroma.sqlite3'
    (left / relative).write_text('Chroma startup mutation')
    assert (right / relative).read_text() == relative
    assert (source / relative).read_text() == relative
    assert not (frozen / '.env').exists()
    assert not (frozen / 'report_generation/vector_db/biology').exists()
    assert json.loads((left / 'RAG/indexes/report_v2_news/embodied/READY').read_text())['source'] == str((left / relative).resolve())
    assert json.loads(ready.read_text())['source'] == str((source / relative).resolve())
    assert record['mechanism'] in {'apfs_clone_cp_cR', 'ordinary_copy'}
    assert record['source_root'] == str(source.resolve())
    assert record['data_root'] == str(frozen.resolve())


def test_data_paths_use_arm_copy_while_model_and_template_stay_in_project_root(tmp_path):
    m = harness()
    original, arm = tmp_path / 'source', tmp_path / 'arm'
    config = SimpleNamespace(PROJECT_ROOT=original, INDUSTRY_CONFIG={
        'embodied': {}, 'biology': {}})
    news_index, news_retrieval = SimpleNamespace(), SimpleNamespace()
    vector_store = SimpleNamespace(_chroma_clients={})
    summary = SimpleNamespace()
    kwargs = dict(industry_config=config, news_index=news_index,
                  news_retrieval=news_retrieval, vector_store=vector_store, summary_agent=summary)
    m.configure_data_paths(original, arm, **kwargs)
    assert config.INDUSTRY_CONFIG['embodied']['vector_db_path'] == arm / 'report_generation/vector_db/embodied'
    assert config.INDUSTRY_CONFIG['biology']['graph_path'] == arm / 'static/data/biology/graph_data.json'
    assert news_index.INDEX_ROOT == arm / 'RAG/indexes/report_v2_news'
    assert news_retrieval.PROJECT_ROOT == original
    assert summary.DEFAULT_TEMPLATE_PATH == original / '产业链报告模板.docx'
    vector_store._chroma_clients['embodied'] = 'left-client'
    m.configure_data_paths(original, tmp_path / 'other-arm', **kwargs)
    assert vector_store._chroma_clients == {}
    vector_store._chroma_clients['embodied'] = 'right-client'
    m.configure_data_paths(original, arm, **kwargs)
    assert vector_store._chroma_clients['embodied'] == 'left-client'


def test_main_uses_independent_arm_copies_and_resume_reads_fixed_copy_config(tmp_path, monkeypatch):
    import json
    import sys
    m = harness()
    source = tmp_path / 'original'
    for relative in ('static/data/embodied/graph_data.json',
                     'report_generation/vector_db/embodied/chroma.sqlite3',
                     'RAG/indexes/report_v2_news/embodied/lexical.sqlite3'):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture')
    output = tmp_path / 'run'
    client = SimpleNamespace(model='same-model', query_result=lambda **kw: None)
    monkeypatch.setitem(sys.modules, 'llm_client', SimpleNamespace(llm=client))
    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(load_dotenv=lambda *a, **kw: None))
    coordinator = SimpleNamespace(_retrieve_candidates_once=lambda **kw: ({}, []),
                                  _retrieve_candidates_for_subsection=lambda **kw: ({}, []))
    paths = []
    api = SimpleNamespace(
        coordinate=lambda **kw: {'status': 'success', 'writing_tasks': [], 'references': []},
        body=lambda **kw: {'status': 'success', 'body_sections': [
            {'outline_id': 'S1.1', 'body_text': '最终正文', 'status': 'success'}]},
        summary=lambda **kw: {'status': 'success', 'abstract_text': '摘要'},
        export=lambda **kw: {'status': 'success'})
    def runtime(project_root, data_root):
        paths.append((project_root, data_root))
        return api, client, coordinator
    monkeypatch.setattr(m, 'configure_runtime', runtime)
    original = m.source_snapshot(source, ['embodied'])
    args = ['--project-root', str(source), '--output-dir', str(output),
            '--cases', 'embodied-overview', '--industries', 'embodied']
    assert m.main(args) == 0
    assert m.source_snapshot(source, ['embodied']) == original
    assert [p[1] for p in paths] == [output / 'embodied-overview/baseline/data',
                                    output / 'embodied-overview/agentic/data']
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['data_copy']['data_root'] == str(output / 'fixed_data')
    def must_not_copy(*args, **kwargs):
        pytest.fail('resume must read recorded fixed and arm copies')
    monkeypatch.setattr(m, 'clone_selected_data', must_not_copy)
    old_manifest = dict(manifest)
    old_manifest.pop('data_copy')
    m.save(output, 'manifest.json', old_manifest)
    with pytest.raises(SystemExit):
        m.main(args + ['--resume'])
    m.save(output, 'manifest.json', manifest)
    assert m.main(args + ['--resume']) == 0
    assert m.source_snapshot(source, ['embodied']) == original

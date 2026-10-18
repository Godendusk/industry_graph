"""Run reproducible retrieval comparisons and a report through production agents."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import subprocess
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from report_generation.graph_retriever import retrieve_industry_graph
from report_generation.external_rag.retriever import retrieve_external_rag
from report_generation.external_rag.graph_evidence_retrieval import augment_with_graph_evidence
from report_generation.external_rag.graph_query_expansion import retrieve_graph_keyword_candidates

QUESTIONS = [
    '人形机器人伺服电机和无框力矩电机有哪些企业参与？请给出产品证据。',
    '人形机器人控制器与驱动器有哪些企业，分别提供什么产品？',
    '触觉传感器与六维力传感器环节有哪些企业及其产品或检测服务？',
    '人形机器人动力电池的配套企业有哪些？',
    '人形机器人整机有哪些企业及应用案例？',
]


def validate_report_acceptance_result(result, sidecar_links):
    """Check actual retrieval state and selected graph evidence's review limits.

    ``sidecar_links`` is the official sidecar's ``links`` list. Only approved
    links matching each evidence block's graph_matches participate in curation checks.
    Ref notes take precedence over link notes; historical links with neither
    are skipped. ``curation_note_count`` counts distinct selected chunk/note
    pairs, so the same limit shared by graph elements is counted once.
    Counts describe diagnostics; they are not relevance or report-quality scores.
    This function performs no I/O and does not mutate either input.
    """
    version = result.get('retrieval_version')
    fallback = result.get('retrieval_fallback')
    hybrid_error = result.get('hybrid_error')
    identity_warning_count = sum(
        warning.get('code') == 'graph_ref_identity_mismatch'
        for warning in result.get('warnings', [])
    )
    failures = []
    if result.get('status') != 'success':
        failures.append('retrieval_not_successful')
    if version != 'hybrid_v2':
        failures.append('unexpected_retrieval_version')
    if fallback == 'legacy_news':
        failures.append('legacy_news_fallback')
    if hybrid_error:
        failures.append('hybrid_error')
    if identity_warning_count:
        failures.append('graph_identity_warning')

    selected = {
        block.get('chunk_id') or block.get('vector_id'): block
        for block in result.get('evidence_blocks', [])
    }
    selected_elements = {}
    for chunk_id, block in selected.items():
        elements = set()
        for match in block.get('graph_matches', []):
            if match.get('kind') == 'entity_mention':
                elements.add(('node', match.get('node_id')))
            elif match.get('kind') == 'relationship_support':
                elements.add(('relationship', match.get('source'), match.get('target'),
                              str(match.get('type') or '')))
        selected_elements[chunk_id] = elements
    expected_notes = set()
    for link in sidecar_links:
        if link.get('verification_status', 'approved') != 'approved':
            continue
        element_type = str(link.get('element_type') or '').strip().lower()
        if element_type == 'node':
            identity = ('node', link.get('id'))
        elif element_type == 'relationship':
            identity = ('relationship', link.get('source'), link.get('target'),
                        str(link.get('type') or ''))
        else:
            continue
        for ref in link.get('evidence_refs', []):
            chunk_id = ref.get('chunk_id')
            if (ref.get('verification_status', 'approved') != 'approved'
                    or identity not in selected_elements.get(chunk_id, ())):
                continue
            note = (ref.get('review_note') or link.get('review_note') or '').strip()
            if note:
                expected_notes.add((chunk_id, note))
    for chunk_id, note in sorted(expected_notes):
        if note not in (selected[chunk_id].get('review_note') or ''):
            failures.append('missing_evidence_curation_note')
        if note not in (result.get('rag_context_text') or ''):
            failures.append('missing_context_curation_note')

    failures = list(dict.fromkeys(failures))
    return {
        'retrieval_ok': not failures,
        'version': version,
        'fallback': fallback,
        'hybrid_error': hybrid_error,
        'identity_warning_count': identity_warning_count,
        'curation_note_count': len(expected_notes),
        'failure_reasons': failures,
    }


def save(root,name,value):
    (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def serialize_keyword_result(result):
    payload = dict(result)
    payload['candidates'] = []
    for row in result.get('candidates', []):
        payload['candidates'].append({
            'chunk_id': row.chunk_id,
            'document_id': row.document_id,
            'text': row.text,
            'metadata': dict(row.metadata),
            'diagnostics': dict(row.diagnostics),
            'bm25_rank': row.bm25_rank,
            'bm25_score': row.bm25_score,
        })
    return payload



def rerank_control(query, baseline):
    from retrieval_core.schemas import RetrievalCandidate
    from retrieval_core.reranker import rerank_candidates
    from report_generation.external_rag.news_retrieval import local_models
    rows=[RetrievalCandidate(chunk_id=b['vector_id'],document_id=b.get('material_id') or b['vector_id'],text=b['text'],metadata=b) for b in baseline.get('evidence_blocks',[])]
    ranked=rerank_candidates(query,rows,scorer=lambda pairs:local_models().rerank_pairs(query,[pair[1] for pair in pairs]),final_limit=10)
    return [{'chunk_id':r.chunk_id,'rerank_score':r.rerank_score,'fallback':bool(r.diagnostics.get('reranker_fallback'))} for r in ranked]


def compare(root):
    outcomes=[]
    for i,query in enumerate(QUESTIONS,1):
        started=perf_counter()
        baseline=retrieve_external_rag(query,top_k=10,industry='embodied')
        baseline_ms=round((perf_counter()-started)*1000,1)
        started=perf_counter()
        graph=retrieve_industry_graph(query,industry='embodied')
        enriched=augment_with_graph_evidence(query,graph,baseline,'embodied',10)
        enrichment_ms=round((perf_counter()-started)*1000,1)
        control=rerank_control(query,baseline)
        a={b.get('vector_id') for b in baseline.get('evidence_blocks',[])}
        b={b.get('vector_id') for b in enriched.get('evidence_blocks',[])}
        row={'question':query,'baseline_version':baseline.get('retrieval_version'),
             'fallback':baseline.get('retrieval_fallback'),'hybrid_error':baseline.get('hybrid_error'),
             'graph_status':graph.get('status'),'segments':[s['name'] for s in graph.get('matched_segments',[])],
             'baseline_ms':baseline_ms,'enrichment_ms':enrichment_ms,
             'added_retained_chunk_ids':sorted(b-a),'removed_baseline_chunk_ids':sorted(a-b),
             'reranked_baseline_control':control,'graph_diagnostics':enriched.get('graph_diagnostics',{}),'warnings':enriched.get('warnings',[])}
        outcomes.append(row)
        save(root,f'comparison_{i}.json',{'summary':row,'baseline':baseline,'graph':graph,'enriched':enriched})
        print(json.dumps(row,ensure_ascii=False),flush=True)
    save(root,'comparison_summary.json',outcomes)
    lines=['# 图谱证据检索对比','', '同一原始问题、相同候选上限，记录原有链路实际版本以及图谱新增候选。没有人工相关性标注，不能把新增数量等同于质量提升。','']
    for i,row in enumerate(outcomes,1):
        lines.extend([f'## {i} {row["question"]}','',f'实际基线：{row["baseline_version"]}；回退：{row["fallback"] or "无"}。',
                      f'图谱环节：{"、".join(row["segments"])}；保留新增片段：{len(row["added_retained_chunk_ids"])}；被替换的基线片段：{len(row["removed_baseline_chunk_ids"])}。',
                      f'基线耗时 {row["baseline_ms"]} ms；图谱选择、取回及重排耗时 {row["enrichment_ms"]} ms。',''])
    (root/'comparison_summary.md').write_text('\n'.join(lines))


def compare_three_way(root):
    outcomes=[]
    for i,query in enumerate(QUESTIONS,1):
        baseline=retrieve_external_rag(query,top_k=10,industry='embodied')
        graph=retrieve_industry_graph(query,industry='embodied')
        evidence=augment_with_graph_evidence(query,graph,baseline,'embodied',10)
        keyword=retrieve_graph_keyword_candidates(query,graph,'embodied',20)
        expanded=augment_with_graph_evidence(query,graph,baseline,'embodied',10,
                                              keyword_candidates=keyword.get('candidates',[]))
        row={'question':query,'baseline_version':baseline.get('retrieval_version'),
             'fallback':baseline.get('retrieval_fallback'),'hybrid_error':baseline.get('hybrid_error'),
             'keyword_status':keyword.get('status'),'keyword_terms':keyword.get('terms',[]),
             'keyword_candidate_count':len(keyword.get('candidates',[])),
             'evidence_selected_chunk_ids':[b.get('vector_id') for b in evidence.get('evidence_blocks',[])],
             'expanded_selected_chunk_ids':[b.get('vector_id') for b in expanded.get('evidence_blocks',[])],
             'expanded_sources':[{'chunk_id':b.get('vector_id'),'source':b.get('retrieval_source')} for b in expanded.get('evidence_blocks',[])],
             'graph_diagnostics':expanded.get('graph_diagnostics',{}),'warnings':expanded.get('warnings',[])}
        outcomes.append(row)
        save(root,f'three_way_{i}.json',{'summary':row,'baseline':baseline,'graph':graph,'evidence':evidence,'keyword':serialize_keyword_result(keyword),'expanded':expanded})
        print(json.dumps(row,ensure_ascii=False),flush=True)
    save(root,'three_way_summary.json',outcomes)
    lines=['# 具身智能三路 GraphRAG 对比','','纯 Hybrid、Hybrid + 图谱证据、Hybrid + 图谱证据 + 图谱关键词候选的真实对比。新增数量不单独代表质量提升。','']
    for i,row in enumerate(outcomes,1):
        lines.extend([f'## {i} {row["question"]}','',
                      f'基线：{row["baseline_version"]}；回退：{row["fallback"] or "无"}；Hybrid 错误：{row["hybrid_error"] or "无"}。',
                      f'关键词状态：{row["keyword_status"]}；关键词数：{len(row["keyword_terms"])}；关键词候选：{row["keyword_candidate_count"]}。',
                      f'图谱证据结果数：{len(row["evidence_selected_chunk_ids"])}；三路扩展结果数：{len(row["expanded_selected_chunk_ids"])}。',''])
    (root/'three_way_summary.md').write_text('\n'.join(lines),encoding='utf8')


def report(root, artifact_python=None):
    from report_generation.coordinator_agent import generate_writing_tasks
    from report_generation.body_agent import generate_report_bodies
    from report_generation.summary_agent import generate_report_summary
    from report_generation.outline_agent import generate_report_outline
    title = '具身智能产业发展报告'
    prompt = '生成一份具身智能产业发展报告，重点分析人形机器人技术进展、产业链结构、政策环境、主要企业、典型应用、商业化趋势及风险挑战，并尽量引用近期可靠资讯。篇幅控制为3个一级章节，每章2个二级章节，每节约400到600字。所有事实以实际资料为准；保留报道的日期及主体限定，区分展示、测试、小批量订单、计划产能与已部署、量产、交付，不能由产业环节参与推断具体供应合作关系。'
    save(root, 'report_request.json', {'title': title, 'industry': 'embodied', 'prompt': prompt})
    save(root, 'run_manifest.json', {
        'title': title, 'industry': 'embodied', 'collection': 'embodied_news',
        'entrypoint': str(Path(__file__).resolve()), 'stage': 'report',
        'output_dir': str(root.resolve()), 'top_k': 5, 'max_workers': 1,
        'artifact_python': artifact_python,
        'pipeline': ['outline', 'coordinator', 'body', 'summary', 'Word export'],
        'source_review_required': True,
        'note': '生成结果仍需来源审阅；模型输出不保证逐字复现历史报告。',
    })
    print('REPORT outline started', flush=True)
    generated_outline = generate_report_outline(
        title, prompt, industry='embodied', industry_confirmed=True,
        outline_template={'level1_titles': ['技术进展与产业链结构', '政策环境与典型应用', '商业化趋势与风险挑战']},
    )
    save(root, 'report_outline.json', generated_outline)
    if generated_outline.get('status') != 'success':
        raise RuntimeError(generated_outline.get('message', 'Outline generation failed'))
    outline = generated_outline['outline']
    print('REPORT coordinator started',flush=True)
    tasks=generate_writing_tasks(prompt,title,outline,industry='embodied',top_k=5,use_graph=True,use_external_rag=True,max_workers=1)
    save(root,'report_tasks.json',tasks)
    if tasks['status']!='success': raise RuntimeError(tasks.get('message',tasks['status']))
    print('REPORT bodies started',flush=True)
    bodies=generate_report_bodies(prompt,title,tasks['writing_tasks'],industry='embodied',max_workers=1,references=tasks['references'])
    save(root,'report_bodies.json',bodies)
    if bodies['status']!='success': raise RuntimeError('Body generation: '+bodies['status'])
    print('REPORT summary started',flush=True)
    summary=generate_report_summary(title,tasks.get('final_outline') or outline,bodies['body_sections'],industry='embodied')
    save(root,'report_summary.json',summary)
    if summary['status']!='success': raise RuntimeError(summary.get('message',summary['status']))
    _export_report_artifacts(root, title, bodies, summary, artifact_python)


def export_saved_report(root, artifact_python=None):
    """Export reviewed checkpoints without invoking generation models."""
    request = json.loads((root / 'report_request.json').read_text(encoding='utf8'))
    bodies = json.loads((root / 'report_bodies.json').read_text(encoding='utf8'))
    summary = json.loads((root / 'report_summary.json').read_text(encoding='utf8'))
    if bodies.get('status') != 'success' or summary.get('status') != 'success':
        raise RuntimeError('Successful body and summary checkpoints are required')
    _export_report_artifacts(root, request['title'], bodies, summary, artifact_python)


def _export_report_artifacts(root, title, bodies, summary, artifact_python):
    from report_generation.word_export_agent import export_report_docx
    if artifact_python:
        code = '''import json,sys
from pathlib import Path
from report_generation.word_export_agent import export_report_docx
root=Path(sys.argv[1]);b=json.loads((root/'report_bodies.json').read_text());s=json.loads((root/'report_summary.json').read_text())
r=export_report_docx(sys.argv[2],s['abstract_text'],b['body_sections'],industry='embodied',output_dir=str(root.resolve()),references=b['references'],adjustment_notes=b.get('adjustment_notes'))
(root/'report_export.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
'''
        subprocess.run([artifact_python, '-c', code, str(root), title],check=True)
        docx=json.loads((root/'report_export.json').read_text())
    else:
        docx=export_report_docx(title,summary['abstract_text'],bodies['body_sections'],industry='embodied',output_dir=str(root.resolve()),references=bodies['references'],adjustment_notes=bodies.get('adjustment_notes'))
    if docx.get('docx_path'):
        docx['docx_path'] = str(Path(docx['docx_path']).resolve())
    save(root,'report_export.json',docx)
    if docx.get('status') != 'success':
        raise RuntimeError(docx.get('message', 'Word export failed'))
    markdown=['# '+title,'',summary['abstract_text'],'']
    trace=[]
    for section in bodies['body_sections']:
        markdown.extend(['## '+section['title'],'',section['body_text'],''])
        used=set(section.get('citation_ids',[]))
        for block in section.get('external_evidence_blocks',[]):
            if block.get('graph_linked'):
                trace.append({'outline_id':section['outline_id'],'title':section['title'],
                    'citation_id':block['citation_id'],'source_cited_in_body':block['citation_id'] in used,
                    'chunk_id':block.get('chunk_id') or block['vector_id'], 'graph_matches':block.get('graph_matches',[]),
                    'text':block['text'],'source_address':block.get('source_address')})
    markdown.extend(['## 参考资料',''])
    for ref in bodies['references']:
        markdown.extend([f"[{ref['citation_id']}] {ref.get('title','')} {ref.get('publish_date','')} {ref.get('source_address','')}",''])
    (root/'report.md').write_text('\n'.join(markdown))
    save(root,'citation_trace.json',trace)
    summary_check={'status':'generated_pending_source_review','body_status':bodies['status'],'export_status':docx['status'],'sections':len(bodies['body_sections']),
        'used_references':len(bodies['references']),'graph_linked_candidates':len(trace),
        'graph_linked_candidates_with_cited_source':sum(x['source_cited_in_body'] for x in trace), 'docx_path':docx.get('docx_path'),
        'warnings':bodies.get('warnings',[])}
    save(root,'report_acceptance.json',summary_check)
    print(json.dumps(summary_check,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--stage',choices=['compare','compare-three-way','report','export-report'],required=True)
    p.add_argument('--artifact-python',help='Bundled artifact runtime for the project Word exporter')
    args=p.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.stage=='compare': compare(args.output_dir)
    elif args.stage=='compare-three-way': compare_three_way(args.output_dir)
    elif args.stage=='report': report(args.output_dir,args.artifact_python)
    else: export_saved_report(args.output_dir,args.artifact_python)

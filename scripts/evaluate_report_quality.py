"""Run new report topics through production scope, writing, review and delivery."""
from pathlib import Path
import argparse
import json
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_agentic_report import (clone_selected_data, configure_runtime,
                                            CallRecorder, save)

CASES = {
    'low_altitude': ('低空经济代表企业业务与商业化条件比较',
        '比较低空经济中有公开业务材料的代表企业，重点回答业务位置、产品与交付状态、经营披露和商业化约束有哪些差异。'
        '不要求完整企业名单或市场份额排名，不能把公司总营收当作低空业务收入。优先形成具体企业对照和有条件的分析，避免行业背景重复。'),
    'sea': ('海洋经济产业结构与区域变化研究',
        '研究2020—2025年海洋经济产业结构与区域变化，比较传统与新兴产业、区域优势和产业链案例。'
        '区分长期变化和近年变化，资料不足时按实际证据收窄。先提出17至20个小节作为研究候选，正式协调时可依据证据合并和调整，不能靠背景填充。'),
    'biology': ('生物制造食品配料与材料路线比较',
        '比较生物制造在食品配料与材料领域的技术路线和商业化条件，区分已有产品、中试与计划项目，'
        '解释不同路线的适用条件和主要限制，不要求市场份额排名。'),
}

HOLDOUT = json.loads((ROOT / 'evaluation/report_quality/round2/cases.json').read_text())['holdout_round2']
CASES['holdout_round2'] = (HOLDOUT['title'], HOLDOUT['prompt'])
FINAL_HOLDOUT = json.loads((ROOT / 'evaluation/report_quality/round2/cases.json').read_text())['holdout_round2_final']
CASES['holdout_round2_final'] = (FINAL_HOLDOUT['title'], FINAL_HOLDOUT['prompt'])


def run_case(industry, source, output, *, prepare_only=False, reuse_outline=False):
    title, prompt = CASES[industry]
    industry = {'holdout_round2': HOLDOUT['industry'], 'holdout_round2_final': FINAL_HOLDOUT['industry']}.get(industry, industry)
    data_root = output / 'data'
    if not data_root.exists():
        save(output, 'data_copy.json', clone_selected_data(source, data_root, [industry]))
    api, llm, _ = configure_runtime(source, data_root)
    from report_generation.task_card_agent import generate_writing_task_card
    from report_generation.outline_agent import generate_report_outline
    from report_generation.runtime_budget import RuntimeBudget
    started = perf_counter()
    with CallRecorder(llm, max_calls=None, trace_dir=output / 'call_traces') as recorder:
        recorder.stage = 'task_card'
        card_path = output / 'task_card.json'
        card = json.loads(card_path.read_text()) if card_path.exists() else generate_writing_task_card(title, prompt, industry)
        save(output, 'task_card.json', card)
        if card.get('status') != 'success':
            return {'status': 'failed', 'stage': 'task_card', 'message': card.get('message')}
        task = card['task_card']
        requirement = task.get('report_requirement') or prompt
        recorder.stage = 'outline'
        outline_path = output / 'outline.json'
        outlined = (json.loads(outline_path.read_text()) if reuse_outline and outline_path.exists()
                    else generate_report_outline(title=title, user_requirement=requirement,
                                                 industry=industry, industry_confirmed=True))
        save(output, 'outline.json', outlined)
        if outlined.get('status') != 'success':
            return {'status': 'failed', 'stage': 'outline', 'message': outlined.get('message')}
        if prepare_only:
            return {'status': 'prepared', 'input_sections': sum(len(c.get('subsections', [])) for c in outlined['outline'])}
        budget = RuntimeBudget()
        print('PRODUCTION_START', industry, len(outlined['outline']), budget.snapshot(), flush=True)
        production_started = perf_counter()
        recorder.stage = 'coordination'
        coordinated = api.coordinate(user_prompt=requirement, report_title=title,
                                     outline=outlined['outline'], industry=industry,
                                     top_k=6, max_workers=3, runtime_budget=budget)
        print('COORDINATION_END', industry, coordinated.get('status'), budget.snapshot(), flush=True)
        save(output, 'coordination.json', coordinated)
        if coordinated.get('status') != 'success':
            save(output, 'calls.json', recorder.summary())
            return {'status': 'failed', 'stage': 'coordination', 'message': coordinated.get('message'),
                    'runtime_budget': budget.snapshot()}
        scope = coordinated.get('report_scope')
        final_title = coordinated.get('report_title', title)
        recorder.stage = 'body_review'
        bodies = api.body(user_prompt=requirement, report_title=final_title,
                          writing_tasks=coordinated['writing_tasks'], industry=industry,
                          references=coordinated['references'], runtime_budget=budget)
        print('BODY_END', industry, bodies.get('status'), budget.snapshot(), flush=True)
        save(output, 'body.json', bodies)
        successful = [s for s in bodies.get('body_sections', []) if s.get('status') == 'success']
        if not successful:
            save(output, 'calls.json', recorder.summary())
            return {'status': 'failed', 'stage': 'body', 'message': bodies.get('message'),
                    'runtime_budget': budget.snapshot()}
        recorder.stage = 'summary'
        summary = api.summary(report_title=final_title, outline=coordinated['final_outline'],
                              body_sections=successful, industry=industry,
                              report_scope=scope, runtime_budget=budget)
        save(output, 'summary.json', summary)
        exported = {}
        if summary.get('status') == 'success':
            recorder.stage = 'export'
            exported = api.export(report_title=final_title, abstract_text=summary['abstract_text'],
                                  body_sections=successful, industry=industry,
                                  references=bodies.get('references', []),
                                  adjustment_notes=coordinated.get('adjustment_notes', []) + bodies.get('adjustment_notes', []),
                                  report_scope=scope, review=bodies.get('review'),
                                  summary_review=summary.get('summary_review'),
                                  output_dir=str(output.resolve()), runtime_budget=budget)
            save(output, 'export.json', exported)
        save(output, 'calls.json', recorder.summary())
        text = '\n\n'.join(s['title'] + '\n' + s['body_text'] for s in successful)
        (output / 'report.md').write_text('# ' + final_title + '\n\n' + summary.get('abstract_text', '') + '\n\n' + text)
        return {'status': exported.get('delivery_status', 'incomplete'),
                'scope_status': (scope or {}).get('status'),
                'deliverable_type': (scope or {}).get('deliverable_type'),
                'input_sections': sum(len(c.get('subsections', [])) for c in outlined['outline']),
                'final_sections': len(coordinated['writing_tasks']), 'generated_sections': len(successful),
                'production_seconds': round(perf_counter() - production_started, 2),
                'including_interactive_preparation_seconds': round(perf_counter() - started, 2),
                'runtime_budget': budget.snapshot(), 'review_status': (bodies.get('review') or {}).get('status'),
                'summary_status': summary.get('status'), 'export_status': exported.get('status'),
                'docx_path': exported.get('docx_path'), 'calls': recorder.summary()['calls']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=list(CASES) + ['all'], required=True)
    parser.add_argument('--source', type=Path, default=Path('/Users/livictor/Desktop/industry/industry_graph'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--reuse-outline', action='store_true', help='Reuse this case\'s previously generated normal outline for an affected-case rerun')
    args = parser.parse_args()
    selected = list(CASES) if args.case == 'all' else [args.case]
    outcomes = []
    for industry in selected:
        output = args.output / industry if args.case == 'all' else args.output
        try:
            result = run_case(industry, args.source, output, prepare_only=args.prepare_only, reuse_outline=args.reuse_outline)
        except Exception as exc:
            result = {'status': 'failed', 'error': str(exc), 'exception_type': type(exc).__name__}
        save(output, 'result.json', result)
        outcomes.append({'case': industry, **result})
        save(args.output, 'outcomes.json', outcomes)
        print(json.dumps(outcomes[-1], ensure_ascii=False), flush=True)



if __name__ == '__main__':
    main()

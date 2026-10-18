"""Replay saved real coordination after a deterministic scope fix, then use production agents.

Usage: python scripts/replay_report_quality_coordination.py INPUT_DIR OUTPUT_DIR
Timing is cumulative execution from the saved coordination, not a fresh continuous run.
"""
import json,sys
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path.cwd()))
from scripts.evaluate_agentic_report import configure_runtime,save,CallRecorder
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
api,llm,_=configure_runtime(Path('/Users/livictor/Desktop/industry/industry_graph'),root/'data')
from report_generation.report_scope import apply_report_scope
from report_generation.runtime_budget import RuntimeBudget
c=json.loads((root/'coordination.json').read_text());o=json.loads((root/'outline.json').read_text())
outline,tasks,scope,notes,warnings=apply_report_scope(o['outline'],c['writing_tasks'],c['coordination'],c['user_prompt'],c['report_title'])
if scope['status']!='completed':raise ValueError(str(warnings))
consumed=c['runtime_budget']['consumed_seconds'];budget=RuntimeBudget(consumed_seconds=consumed);start=perf_counter()
c.update(final_outline=outline,writing_tasks=tasks,report_scope=scope,report_title=scope['effective_title'],adjustment_notes=notes)
save(out,'coordination.json',c)
with CallRecorder(llm,max_calls=None,trace_dir=out/'call_traces') as recorder:
 recorder.stage='body_review'
 b=api.body(user_prompt=c['user_prompt'],report_title=c['report_title'],writing_tasks=tasks,industry=c['industry'],references=c['references'],runtime_budget=budget)
 save(out,'body.json',b);print('BODY_END',b.get('status'),budget.snapshot(),flush=True)
 successful=[s for s in b.get('body_sections',[]) if s.get('status')=='success']
 recorder.stage='summary'
 s=api.summary(report_title=c['report_title'],outline=outline,body_sections=successful,industry=c['industry'],report_scope=scope,runtime_budget=budget)
 save(out,'summary.json',s);e={}
 if s.get('status')=='success':
  recorder.stage='export'
  e=api.export(report_title=c['report_title'],abstract_text=s['abstract_text'],body_sections=successful,industry=c['industry'],references=b.get('references',[]),adjustment_notes=notes+b.get('adjustment_notes',[]),report_scope=scope,review=b.get('review'),summary_review=s.get('summary_review'),output_dir=str(out.resolve()),runtime_budget=budget)
  save(out,'export.json',e)
 save(out,'calls.json',recorder.summary())
 (out/'report.md').write_text('# '+c['report_title']+'\n\n'+s.get('abstract_text','')+'\n\n'+'\n\n'.join(x['title']+'\n'+x['body_text'] for x in successful))
 result={'status':e.get('delivery_status','incomplete'),'validation_mode':'replayed saved real coordination after deterministic ID mapping fix; no reretrieval', 'input_sections':sum(len(x.get('subsections',[])) for x in o['outline']),'final_sections':len(tasks),'generated_sections':len(successful),'original_coordination_seconds':consumed,'replay_seconds':perf_counter()-start,'cumulative_execution_seconds':consumed+perf_counter()-start,'review_status':b.get('review',{}).get('status'),'runtime_budget':budget.snapshot(),'docx_path':e.get('docx_path')}
 save(out,'result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)

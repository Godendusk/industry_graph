"""Recheck newly generated content through the production reviewer; no manual body edits."""
import json,sys
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path.cwd()))
from scripts.evaluate_agentic_report import configure_runtime,save,CallRecorder
root=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
api,llm,_=configure_runtime(Path('/Users/livictor/Desktop/industry/industry_graph'),root/'data')
from report_generation.review_agent import review_report_bodies
from report_generation.runtime_budget import RuntimeBudget
c=json.loads((root/'coordination.json').read_text());old=json.loads((root/'body.json').read_text())
consumed=old['runtime_budget']['consumed_seconds'];budget=RuntimeBudget(consumed_seconds=consumed);start=perf_counter()
with CallRecorder(llm,max_calls=500,trace_dir=out/'call_traces') as recorder:
 recorder.stage='review_replay'
 review=review_report_bodies(body_sections=old['body_sections'],writing_tasks=c['writing_tasks'],report_title=c['report_title'],user_prompt=c['user_prompt'],references=old['references'],runtime_budget=budget)
 b={**old,**review};save(out,'body.json',b)
 successful=[s for s in b.get('body_sections',[]) if s.get('status')=='success']
 recorder.stage='summary'
 s=api.summary(report_title=c['report_title'],outline=c['final_outline'],body_sections=successful,industry=c['industry'],report_scope=c['report_scope'],runtime_budget=budget)
 save(out,'summary.json',s);e={}
 if s.get('status')=='success':
  recorder.stage='export'
  e=api.export(report_title=c['report_title'],abstract_text=s['abstract_text'],body_sections=successful,industry=c['industry'],references=b.get('references',[]),adjustment_notes=c.get('adjustment_notes',[])+b.get('adjustment_notes',[]),report_scope=c['report_scope'],review=b.get('review'),summary_review=s.get('summary_review'),output_dir=str(out.resolve()),runtime_budget=budget)
  save(out,'export.json',e)
 save(out,'calls.json',recorder.summary());save(out,'coordination.json',c)
 (out/'report.md').write_text('# '+c['report_title']+'\n\n'+s.get('abstract_text','')+'\n\n'+'\n\n'.join(x['title']+'\n'+x['body_text'] for x in successful))
 result={'status':e.get('delivery_status','incomplete'),'validation_mode':'replayed production review against new report after consistency repair fix', 'input_sections':len(c['writing_tasks']),'final_sections':len(c['writing_tasks']),'generated_sections':len(successful),'original_body_seconds':consumed,'replay_seconds':perf_counter()-start,'cumulative_execution_seconds':consumed+perf_counter()-start,'review_status':b.get('review',{}).get('status'),'runtime_budget':budget.snapshot(),'docx_path':e.get('docx_path')}
 save(out,'result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)

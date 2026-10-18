const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
function load() {
 const c={console,URLSearchParams,setTimeout,clearTimeout,window:{currentIndustry:'ai',location:{origin:'http://localhost',pathname:'/'},addEventListener(){}},document:{getElementById(){return null},querySelectorAll(){return []},addEventListener(){}}};
 vm.createContext(c);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../static/js/modules/industry_report.js'),'utf8'),c);
 for (const fn of ['renderIndustryReportPreview','renderIndustryReportProgress','renderIndustryReportFlowSteps','renderIndustryReportOutline','setIndustryReportStatus','setIndustryReportStage','closeIndustryReportRewriteModal']) c[fn]=()=>{};
 c.saveIndustryReportHistory=async()=>{};
 return c;
}
const section={outline_id:'S1.1',title:'竞争格局',status:'success',body_text:'甲公司2025年计划扩产。[C1]',citation_ids:['C1'],external_evidence_blocks:[{citation_id:'C1'}],claim_verification:{status:'needs_confirmation',body_text:'甲公司2025年计划扩产。[C1]',claims:[{quote:'甲公司2025年计划扩产。[C1]',status:'unknown',reason:'缺日期',supports:[]}]}};
const task={outline_id:'S1.1',title:'竞争格局',agentic_retrieval:{plan:{sub_queries:[{id:'q1',question:'查询甲公司产品',reason:'定位产品'}]},steps:[{id:'q1',status:'success'}],follow_up:{rounds:1,query_count:1,new_evidence_count:2,stop_reason:'round_limit'}},evidence_pack:{requirements:[{requirement:'2025年市场份额',status:'insufficient',reason:'没有统计口径'}],writing_constraints:['不能写市场第一']}};
function set(c,s=section,t=task){c.inputSection=s;c.inputTask=t;vm.runInContext('industryReportWorkspace.bodySections=[inputSection]; industryReportWorkspace.writingTasks=[inputTask];',c);}
test('chapter shows expandable plan, evidence gaps and claim reason with escaped content',()=>{
 const c=load();set(c);const html=c.renderIndustryReportAgenticDetails(section);
 for(const text of ['待确认','查询甲公司产品','2025年市场份额','没有统计口径','不能写市场第一','缺日期','<details']) assert.ok(html.includes(text),text);
 const bad=JSON.parse(JSON.stringify(section));bad.claim_verification.claims[0].reason='<script>alert(1)</script>';
 assert.ok(!c.renderIndustryReportAgenticDetails(bad).includes('<script>'));
});
test('manual edit invalidates verification and summary; repeated DOM sync preserves invalidation',()=>{
 const c=load();set(c);vm.runInContext("industryReportWorkspace.abstractText='旧摘要'",c);
 c.updateIndustryReportBodyText('S1.1','甲公司已经投产。[C1]');
 let record=c.buildIndustryReportHistoryRecord();assert.equal(record.bodySections[0].claim_verification.invalidated,true);assert.equal(record.abstractText,'');
 assert.equal(record.bodySections[0].claim_verification.claims.length,0);
 c.updateIndustryReportBodyText('S1.1','甲公司已经投产。[C1]');assert.equal(c.buildIndustryReportHistoryRecord().bodySections[0].claim_verification.invalidated,true);
});
test('rewrite installs fresh verification and discards original evidence assessment',()=>{
 const c=load();set(c);const fresh={status:'completed',body_text:'甲公司计划扩产。[C1]',claims:[]};
 c.applyIndustryReportRewrite({body_text:fresh.body_text,claim_verification:fresh,citation_ids:['C1'],selected_external_evidence_blocks:[{citation_id:'C1'}]},'S1.1');
 const current=c.buildIndustryReportHistoryRecord().bodySections[0];assert.equal(current.claim_verification.status,'completed');assert.equal(current.evidence_pack,null);
 assert.ok(!c.renderIndustryReportAgenticDetails(current).includes('2025年市场份额'));
});
test('history roundtrip retains plans, evidence packs and fresh or stale claim records', async()=>{
 const c=load();set(c);const saved=JSON.parse(JSON.stringify(c.buildIndustryReportHistoryRecord()));
 c.document.getElementById=id=>id==='industry-report-history-select'?{value:'saved'}:null;
 c.industryReportApi=async()=>({report:{...saved,id:'saved'}});c.renderIndustryReportTaskCard=()=>{};c.syncIndustryReportHeader=()=>{};c.renderIndustryReportHistorySelect=()=>{};
 await c.loadSelectedIndustryReportHistory();
 const restored=c.buildIndustryReportHistoryRecord();assert.equal(restored.writingTasks[0].agentic_retrieval.follow_up.query_count,1);assert.equal(restored.bodySections[0].claim_verification.claims[0].reason,'缺日期');
});
test('progress displays actual planning and followup phases',()=>{
 const c=load();let message='';c.setIndustryReportStage=(stage,text)=>message=text;
 c.handleIndustryReportCoordinatorStreamEvent({event:'retrieval_progress',outline_id:'S1.1',title:'竞争格局',phase:'follow_up'});
 assert.match(message,/补查/);
 c.handleIndustryReportBodyStreamEvent({event:'review_started'});assert.match(message,/事实/);
});
test('export sections include assessment and current verification; pending notes stay on page',()=>{
 const c=load();set(c);const rows=c.buildIndustryReportExportSections();assert.equal(rows[0].evidence_pack.requirements[0].status,'insufficient');
 const notes=c.buildIndustryReportAgenticNotes();assert.ok(notes.some(n=>n.reason.includes('没有统计口径')));assert.ok(notes.some(n=>n.reason.includes('缺日期')));
 assert.doesNotMatch(c.buildIndustryReportMarkdown(),/没有统计口径/);
 assert.match(c.renderIndustryReportAdjustmentNotes(),/没有统计口径/);
});
test('editing body clears visible old summary so DOM sync cannot resurrect it',()=>{
 const c=load();set(c);const abstract={innerHTML:'旧摘要'};c.document.getElementById=id=>id==='industry-report-abstract-editor'?abstract:null;
 c.updateIndustryReportBodyText('S1.1','修改后的2025年正文。[C1]');assert.equal(abstract.innerHTML,'');
});
test('display whitespace normalization never invalidates matching server verification or offsets',()=>{
 const c=load();const raw='  甲公司2025年发布产品。[C1]\n\n乙公司计划扩产。[C2]  ';
 const checked={...section,body_text:raw,claim_verification:{status:'completed',body_text:raw,claims:[{start:2,end:8,quote:'甲公司'}]}};
 const normalized=c.normalizeIndustryReportBodySections([checked])[0];assert.equal(normalized.claim_verification.status,'completed');assert.equal(normalized.body_text,raw);
 set(c,normalized);vm.runInContext("industryReportWorkspace.abstractText='已核对摘要'",c);
 c.updateIndustryReportBodyText('S1.1','甲公司2025年发布产品。[C1]\n乙公司计划扩产。[C2]');
 const record=c.buildIndustryReportHistoryRecord();assert.equal(record.bodySections[0].claim_verification.status,'completed');assert.equal(record.bodySections[0].body_text,raw);assert.equal(record.bodySections[0].claim_verification.claims[0].start,2);assert.equal(record.abstractText,'已核对摘要');
});

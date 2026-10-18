const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function load() {
 const c={console,URLSearchParams,setTimeout,clearTimeout,window:{currentIndustry:'ai',location:{origin:'http://localhost',pathname:'/'},addEventListener(){}},document:{getElementById(){return null},querySelectorAll(){return []},addEventListener(){}}};
 vm.createContext(c);vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../static/js/modules/industry_report.js'),'utf8'),c);
 return c;
}
test('runtime and effective scope survive history save',()=>{
 const c=load();
 c.acceptIndustryReportRunResult({runtime_budget:{consumed_seconds:202},report_scope:{effective_title:'实际比较',status:'completed'},delivery_status:'incomplete'});
 const record=c.buildIndustryReportHistoryRecord();
 assert.equal(record.runtimeBudget.consumed_seconds,202);
 assert.equal(record.title,'实际比较');
 assert.equal(record.deliveryStatus,'incomplete');
});
test('production requests carry the same accumulated budget and scope',()=>{
 const c=load();c.acceptIndustryReportRunResult({runtime_budget:{consumed_seconds:305},report_scope:{effective_title:'有效题目'}});
 const payload=c.withIndustryReportRuntime({report_title:'旧题目'});
 assert.equal(payload.runtime_budget.consumed_seconds,305);
 assert.equal(payload.report_scope.effective_title,'有效题目');
});
test('prepared Word download never calls generation again',async()=>{
 const c=load();let downloads=0;
 vm.runInContext("industryReportWorkspace.preparedDocxPath='/report.docx'",c);
 c.downloadIndustryReportWord=async()=>downloads++;
 c.setIndustryReportStatus=()=>{};
 c.industryReportApi=async()=>{throw new Error('should not generate');};
 await c.exportIndustryReportWord();assert.equal(downloads,1);
});
test('editing abstract invalidates prepared file and checked status',()=>{
 const c=load();
 vm.runInContext("industryReportWorkspace.preparedDocxPath='/old.docx';industryReportWorkspace.summaryReview={status:'completed'};industryReportWorkspace.deliveryStatus='completed'",c);
 c.updateIndustryReportAbstractText({innerText:'新摘要',textContent:'新摘要'});
 const record=c.buildIndustryReportHistoryRecord();
 assert.equal(record.preparedDocxPath,'');
 assert.equal(record.deliveryStatus,'incomplete');
 assert.equal(record.summaryReview,null);
});
test('confirmed outline can run production stages continuously',async()=>{
 const c=load();const stages=[];
 c.prepareIndustryReportTasks=async()=>{stages.push('coordinator');return {status:'success'};};
 c.startIndustryReportGeneration=async()=>stages.push('body');
 await c.startIndustryReportRun();
 assert.deepEqual(stages,['coordinator','body']);
});

test('export diagnostics survive history and stay in delivery details outside report',()=>{
 const c=load();
 c.acceptIndustryReportRunResult({docx_path:'/report.docx',delivery_status:'incomplete',delivery_reasons:['关键事实仍有待确认项'],
  adjustment_notes:[{kind:'review_warning',reason:'一项摘录未通过校验'}]});
 vm.runInContext(`industryReportWorkspace.bodySections=[{outline_id:'S1.1',parent_level1_title:'现状',title:'运营',status:'success',body_text:'满载条件下的测算值。',citation_ids:[]}];industryReportWorkspace.abstractText='摘要';industryReportWorkspace.reportScope={status:'completed',boundary:{subjects:['国内物流'],period:'2024—2026年'}}`,c);
 const record=c.buildIndustryReportHistoryRecord();
 assert.equal(record.deliveryReasons[0],'关键事实仍有待确认项');
 assert.equal(record.adjustmentNotes[0].reason,'一项摘录未通过校验');
 const details=c.renderIndustryReportAdjustmentNotes();
 assert.match(details,/生成与交付核对/);
 assert.match(details,/关键事实仍有待确认项/);
 assert.match(details,/一项摘录未通过校验/);
 const md=c.buildIndustryReportMarkdown();
 assert.doesNotMatch(md,/未完成稿|报告调整说明|一项摘录未通过校验|关键事实仍有待确认项/);
 assert.match(md,/资料与方法说明/);
 assert.match(md,/国内物流/);
 assert.match(md,/满载条件下的测算值/);
});

test('editing a checked abstract refreshes the visible delivery state',()=>{
 const c=load(),details={innerHTML:''};
 c.document.getElementById=id=>id==='industry-report-delivery-details'?details:null;
 vm.runInContext(`industryReportWorkspace.deliveryStatus='completed';industryReportWorkspace.deliveryReasons=['旧状态原因'];industryReportWorkspace.bodySections=[{outline_id:'S1.1',title:'现状',body_text:'正文。'}]`,c);
 c.renderIndustryReportDeliveryDetails();
 assert.match(details.innerHTML,/本次生成与核对已完成/);
 c.updateIndustryReportAbstractText({innerText:'新摘要',textContent:'新摘要'});
 assert.match(details.innerHTML,/核对尚未全部完成/);
 assert.doesNotMatch(details.innerHTML,/旧状态原因/);
});

test('editing checked body refreshes the delivery state and invalidated claim details',()=>{
 const c=load(),details={innerHTML:''};
 c.document.getElementById=id=>id==='industry-report-delivery-details'?details:null;
 vm.runInContext(`industryReportWorkspace.deliveryStatus='completed';industryReportWorkspace.deliveryReasons=['旧状态原因'];industryReportWorkspace.bodySections=[{outline_id:'S1.1',title:'现状',body_text:'旧正文。',claim_verification:{status:'completed',body_text:'旧正文。',claims:[]}}]`,c);
 c.renderIndustryReportDeliveryDetails();
 c.updateIndustryReportBodyText('S1.1','新正文。');
 assert.equal(c.buildIndustryReportHistoryRecord().deliveryStatus,'incomplete');
 assert.match(details.innerHTML,/核对尚未全部完成/);
 assert.match(details.innerHTML,/原事实核对结果失效/);
 assert.doesNotMatch(details.innerHTML,/旧状态原因/);
});

test('export citation warnings reach delivery details and history',()=>{
 const c=load();
 c.acceptIndustryReportRunResult({docx_path:'/report.docx',delivery_status:'incomplete',
  warnings:[{stage:'word_export_citation_validation',message:'引用 C999 未绑定有效来源',invalid_citation_ids:['C999']}]});
 const record=c.buildIndustryReportHistoryRecord();
 assert.equal(record.warnings[0].invalid_citation_ids[0],'C999');
 assert.match(c.renderIndustryReportAdjustmentNotes(),/引用 C999 未绑定有效来源/);
});

test('preview keeps delivery diagnostics outside report body even when viewing abstract',()=>{
 const c=load(),preview={innerHTML:''},details={innerHTML:''};
 c.document.getElementById=id=>id==='industry-report-preview'?preview:id==='industry-report-delivery-details'?details:null;
 c.acceptIndustryReportRunResult({delivery_status:'incomplete',delivery_reasons:['关键事实仍有待确认项']});
 vm.runInContext(`industryReportWorkspace.bodySections=[{outline_id:'S1.1',parent_level1_title:'现状',title:'布局',body_text:'正文。'}];industryReportWorkspace.abstractText='摘要';industryReportWorkspace.previewTarget={type:'abstract'}`,c);
 c.renderIndustryReportPreview();
 assert.match(details.innerHTML,/关键事实仍有待确认项/);
 assert.doesNotMatch(preview.innerHTML,/生成与交付核对|关键事实仍有待确认项/);
});

test('historical report restores delivery reasons without reclassifying pending as passed',async()=>{
 const c=load();
 c.document.getElementById=id=>id==='industry-report-history-select'?{value:'r1'}:null;
 const record={id:'r1',title:'报告',deliveryStatus:'incomplete',deliveryReasons:['跨节重复仍有未解决项'],
  bodySections:[{outline_id:'S1.1',title:'现状',body_text:'正文。'}],adjustmentNotes:[],outline:[]};
 c.industryReportApi=async()=>({report:record});
 for (const key of ['renderIndustryReportPreview','renderIndustryReportFlowSteps','renderIndustryReportOutline','renderIndustryReportProgress','renderIndustryReportHistorySelect','syncIndustryReportHeader','syncIndustryReportGenerateButton','setIndustryReportStatus','setIndustryReportStage','setIndustryReportRequirementSubmittedStatus']) c[key]=()=>{};
 await c.loadSelectedIndustryReportHistory();
 const saved=c.buildIndustryReportHistoryRecord();
 assert.equal(saved.deliveryStatus,'incomplete');
 assert.equal(saved.deliveryReasons[0],'跨节重复仍有未解决项');
});

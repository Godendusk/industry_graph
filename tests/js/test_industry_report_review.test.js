const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function load() {
  const script = fs.readFileSync(path.resolve(__dirname, '../../static/js/modules/industry_report.js'), 'utf8');
  const context = {console, URLSearchParams, setTimeout, clearTimeout,
    window: {currentIndustry: 'ai', location: {origin:'https://example.test', pathname:'/'}, addEventListener(){}},
    document: {getElementById(){return null}, querySelectorAll(){return []}, addEventListener(){}}};
  vm.createContext(context);
  vm.runInContext(script, context);
  context.setIndustryReportStatus = () => {};
  return context;
}

test('completed body event keeps review result and adjustment notes for history', () => {
  const context = load();
  context.renderIndustryReportProgress = () => {};
  context.renderIndustryReportPreview = () => {};
  context.setIndustryReportStage = () => {};
  const event = {event:'completed', status:'success', success_count:1, total:1,
    body_sections:[{outline_id:'S1.1', title:'布局', status:'success', body_text:'审查后正文。', citation_ids:[]}],
    review:{status:'completed', changed_outline_ids:['S1.1']},
    adjustment_notes:[{kind:'body_edit', outline_ids:['S1.1'], reason:'压缩重复背景'}]};
  context.handleIndustryReportBodyStreamEvent(event);
  const record = context.buildIndustryReportHistoryRecord();
  assert.equal(record.review.status, 'completed');
  assert.equal(record.adjustmentNotes[0].reason, '压缩重复背景');
  assert.equal(record.bodySections[0].body_text, '审查后正文。');
});

test('coordinator completion uses the reduced final outline', () => {
  const context = load();
  context.renderIndustryReportOutline = () => {};
  context.renderIndustryReportFlowSteps = () => {};
  context.setIndustryReportStage = () => {};
  const finalOutline = [{section_type:'body', level1_id:'S1', level1_title:'现状',
    subsections:[{outline_id:'S1.1', title:'布局'}]}];
  context.handleIndustryReportCoordinatorStreamEvent({event:'completed',
    writing_tasks:[{outline_id:'S1.1', title:'布局'}], final_outline:finalOutline,
    adjustment_notes:[{kind:'outline_merge', reason:'合并重复小节'}], references:[], warnings:[]});
  const record = context.buildIndustryReportHistoryRecord();
  assert.equal(record.outline[0].subsections.length, 1);
  assert.equal(record.adjustmentNotes[0].kind, 'outline_merge');
});

test('rewrite applies directly to its explicit target and invalidates the abstract', () => {
  const context = load();
  context.renderIndustryReportPreview = () => {};
  context.saveIndustryReportHistory = async () => {};
  context.closeIndustryReportRewriteModal = () => {};
  vm.runInContext(`
    industryReportWorkspace.activeSectionId = 'S2.1';
    industryReportWorkspace.abstractText = '旧摘要';
    industryReportWorkspace.bodySections = [
      {outline_id:'S1.1', body_text:'原文', title:'目标'},
      {outline_id:'S2.1', body_text:'其他节原文', title:'其他'}];
  `, context);
  context.applyIndustryReportRewrite({body_text:'最终重写正文',
    adjustment_notes:[{kind:'body_edit', outline_ids:['S1.1'], reason:'压缩重复'}]}, 'S1.1');
  const record = context.buildIndustryReportHistoryRecord();
  assert.equal(record.bodySections[0].body_text, '最终重写正文');
  assert.equal(record.bodySections[1].body_text, '其他节原文');
  assert.equal(record.abstractText, '');
  assert.equal(record.adjustmentNotes[0].reason, '压缩重复');
  assert.equal(context.renderIndustryReportRewritePreview, undefined);
  assert.equal(context.updateIndustryReportPendingRewriteText, undefined);
  assert.equal(vm.runInContext("'pendingRewrite' in industryReportWorkspace", context), false);
});

test('failed rewrite keeps body and abstract intact', async () => {
  const context = load();
  const preview = {innerHTML:''};
  context.document.getElementById = id => id === 'industry-report-rewrite-prompt'
    ? {value:'压缩背景'} : id === 'industry-report-rewrite-preview' ? preview : null;
  context.industryReportApi = async () => {throw new Error('模型失败');};
  vm.runInContext(`
    industryReportWorkspace.activeSectionId='S1.1';
    industryReportWorkspace.abstractText='现有摘要';
    industryReportWorkspace.bodySections=[{outline_id:'S1.1', body_text:'现有正文'}];
    industryReportWorkspace.rewriteMaterials={external_rag_retrieval:{evidence_blocks:[]}};
  `, context);
  await context.rewriteIndustryReportSection();
  const record = context.buildIndustryReportHistoryRecord();
  assert.equal(record.bodySections[0].body_text, '现有正文');
  assert.equal(record.abstractText, '现有摘要');
  assert.match(preview.innerHTML, /重写失败/);
});

test('summary review notes replace prior summary notes and persist for export and history', async () => {
  const context = load();
  vm.runInContext(`industryReportWorkspace.adjustmentNotes = [
    {kind:'body_edit', reason:'正文已压缩'},
    {kind:'summary_review', reason:'旧摘要提示'}];`, context);
  context.industryReportApi = async () => ({abstract_text:'修正摘要',
    adjustment_notes:[{kind:'summary_review', outline_ids:[], reason:'摘要已修正'}]});
  const text = await context.generateIndustryReportSummaryForWord('报告', []);
  assert.equal(text, '修正摘要');
  const record = context.buildIndustryReportHistoryRecord();
  assert.equal(record.adjustmentNotes.length, 2);
  assert.equal(record.adjustmentNotes[1].reason, '摘要已修正');
});

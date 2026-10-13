const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(
    path.resolve(__dirname, "../../static/js/modules/industry_report.js"),
    "utf8",
);

function load() {
    const context = {
        console,
        URLSearchParams,
        clearTimeout,
        setTimeout,
        window: {
            currentIndustry: "ai",
            location: { origin: "https://example.test", pathname: "/" },
            addEventListener() {},
        },
        document: {
            getElementById() { return null; },
            querySelectorAll() { return []; },
            addEventListener() {},
        },
    };
    vm.createContext(context);
    vm.runInContext(script, context);
    context.setIndustryReportStatus = () => {};
    return context;
}

test("citation marker links to its report reference", () => {
    const context = load();
    const html = context.renderIndustryReportParagraphs(
        "规划已经发布[C2]。",
        [{ citation_id: "C2" }],
    );
    assert.match(html, /href="#report-reference-C2"/);
    assert.match(html, />\[C2\]<\/a>/);
});

test("history and markdown keep only actually used references", () => {
    const context = load();
    vm.runInContext(`
        industryReportWorkspace.references = [
            { citation_id: "C1", title: "政策甲", source_address: "https://example.test/a" },
            { citation_id: "C2", title: "案例乙", source_address: "https://example.test/b" },
        ];
        industryReportWorkspace.bodySections = [
            { parent_level1_title: "现状", title: "政策", body_text: "正文[C2]。", citation_ids: ["C2"] },
        ];
    `, context);
    const markdown = context.buildIndustryReportMarkdown();
    assert.match(markdown, /\[C2\] 案例乙/);
    assert.doesNotMatch(markdown, /\[C1\] 政策甲/);
});

test("invalid citation warning is available for visible status", () => {
    const context = load();
    assert.equal(
        context.getIndustryReportCitationValidationWarning([
            { stage: "citation_validation", invalid_citation_ids: ["C9"] },
        ]).invalid_citation_ids[0],
        "C9",
    );
    assert.equal(context.getIndustryReportCitationValidationWarning([]), undefined);
});

test("body and rewrite results keep candidate citation ids stable", () => {
    const context = load();
    const merged = context.mergeIndustryReportReferences(
        [{ citation_id: "C1", title: "政策甲" }, { citation_id: "C2", title: "候选乙" }],
        [{ citation_id: "C1", evidence_excerpt: "正文片段" }],
    );
    assert.deepEqual(Array.from(merged, item => item.citation_id), ["C1", "C2"]);
    assert.equal(merged[0].evidence_excerpt, "正文片段");
});

test("manual edits only keep citations allowed by the current section", () => {
    const context = load();
    vm.runInContext(`
        industryReportWorkspace.references = [
            { citation_id: "C1", title: "本节资料" },
            { citation_id: "C5", title: "其他章节资料" },
        ];
        industryReportWorkspace.bodySections = [{
            outline_id: "S1.1",
            external_evidence_blocks: [{ citation_id: "C1" }],
            citation_ids: ["C1"],
        }];
    `, context);
    const ids = context.extractIndustryReportCitationIds(
        "本节说明[C1]，误插入[C5]。",
        [{ citation_id: "C1" }],
    );
    assert.deepEqual(Array.from(ids), ["C1"]);
});

test("rewrite request sends prior body sections without the active section", async () => {
    const context = load();
    context.API_BASE = "";
    const requests = [];
    const elements = {
        "industry-report-rewrite-prompt": { value: "补充最新材料" },
        "industry-report-rewrite-preview": { innerHTML: "" },
    };
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async (url, options) => {
        requests.push({ url, options });
        return {
            ok: true,
            status: 200,
            async json() {
                return { status: "success", body_text: "重写正文。", citation_ids: [] };
            },
        };
    };
    vm.runInContext(`
        industryReportWorkspace.reportTitle = "测试报告";
        industryReportWorkspace.activeSectionId = "S1.1";
        industryReportWorkspace.bodySections = [
            { outline_id: "S1.1", title: "当前", body_text: "当前正文" },
            { outline_id: "S1.2", title: "前文", body_text: "前文正文" },
        ];
        industryReportWorkspace.rewriteMaterials = {
            graph_retrieval: {},
            external_rag_retrieval: { evidence_blocks: [] },
        };
    `, context);

    await context.rewriteIndustryReportSection();

    assert.equal(requests.filter(item => item.url.endsWith("/api/report/rewrite")).length, 1);
    assert.equal(context.buildIndustryReportHistoryRecord().bodySections[0].body_text, "重写正文。");
    const payload = JSON.parse(requests[0].options.body);
    assert.deepEqual(
        payload.previous_body_sections.map(item => item.outline_id),
        ["S1.2"],
    );
});

test("malformed markers are removed from normalized history with a visible warning", () => {
    const context = load();
    const rows = context.normalizeIndustryReportBodySections([{outline_id:"S1.1", body_text:"事实[citation:4]。另一事实[C4]。"}]);
    assert.equal(rows[0].body_text, "事实。另一事实[C4]。");
    assert.equal(context.getIndustryReportCitationValidationWarning(rows[0].warnings).malformed_citation_markers[0], "[citation:4]");
    let message;
    context.setIndustryReportStatus = text => message = text;
    context.showIndustryReportCitationValidationWarning(rows[0].warnings);
    assert.match(message, /核对.*证据/);
});

test("manual body edits remove malformed markers and keep warnings", () => {
    const context = load();
    vm.runInContext(`industryReportWorkspace.bodySections=[{outline_id:"S1.1", external_evidence_blocks:[{citation_id:"C4"}]}];`, context);
    context.updateIndustryReportBodyText("S1.1", "事实[citation:4]。保留[C4]。");
    const data = vm.runInContext("({body:industryReportWorkspace.bodySections[0],warnings:industryReportWorkspace.warnings})", context);
    assert.equal(data.body.body_text, "事实。保留[C4]。");
    assert.equal(data.body.warnings[0].malformed_citation_markers[0], "[citation:4]");
    assert.ok(data.warnings.length);
});

test("directly applied rewrite retains new focus terms in history", () => {
    const context = load();
    context.renderIndustryReportPreview = () => {};
    context.saveIndustryReportHistory = async () => {};
    context.closeIndustryReportRewriteModal = () => {};
    vm.runInContext(`industryReportWorkspace.activeSectionId="S1.1";
        industryReportWorkspace.bodySections=[{outline_id:"S1.1",title:"当前",repetition_focus_terms:["旧名称"]}];`,context);
    context.applyIndustryReportRewrite({body_text:"新文。",repetition_focus_terms:["中国移动"]}, "S1.1");
    const record = context.buildIndustryReportHistoryRecord();
    assert.deepEqual(Array.from(record.bodySections[0].repetition_focus_terms), ["中国移动"]);
});

test("loading history surfaces the malformed citation cleanup warning", async () => {
    const context = load();
    let message;
    context.setIndustryReportStatus = text => message = text;
    context.document.getElementById = id => id === "industry-report-history-select" ? {value:"saved"} : null;
    context.API_BASE = "";
    context.fetch = async () => ({ok:true, json:async () => ({status:"success", report:{id:"saved", bodySections:[{outline_id:"S1.1", body_text:"事实[citation:4]。"}]}})});
    for (const name of ["renderIndustryReportTaskCard", "renderIndustryReportOutline", "renderIndustryReportProgress", "renderIndustryReportPreview", "syncIndustryReportHeader", "renderIndustryReportHistorySelect", "setIndustryReportStage"]) context[name] = () => {};
    await context.loadSelectedIndustryReportHistory();
    assert.match(message, /异常引用标记.*核对.*证据/);
});

function stubReportRendering(context) {
    for (const name of ["renderIndustryReportTaskCard", "renderIndustryReportOutline", "renderIndustryReportProgress", "renderIndustryReportPreview", "syncIndustryReportHeader", "renderIndustryReportHistorySelect", "renderIndustryReportFlowSteps", "closeIndustryReportRewriteModal"]) context[name] = () => {};
}

test("coordinator waits for final completion and saves final decisions with diagnostics", async () => {
    const context = load();
    stubReportRendering(context);
    const stages = [];
    context.setIndustryReportStage = (stage, detail) => stages.push({stage, detail});
    context.updateIndustryReportCoordinatorProgress = () => {};
    vm.runInContext("industryReportWorkspace.busy = true", context);
    const draft = {event:"task_completed", index:0, outline_id:"S1.1", writing_decision:{section_question:"初稿"}};
    const finalTask = {outline_id:"S1.1", writing_decision:{section_question:"最终问题"}, decision_review_status:"adjusted"};
    const coordination = {status:"partial", changed_outline_ids:["S1.1"], rejected_outline_ids:["S1.2"]};
    context.readIndustryReportSseStream = async (url, payload, callback) => {
        callback(draft);
        assert.match(stages.at(-1).detail, /初稿任务已生成/);
        callback({event:"coordination_started"});
        assert.equal(stages.at(-1).stage, "coordinator");
        assert.match(stages.at(-1).detail, /正在协调全报告/);
        assert.equal(vm.runInContext("industryReportWorkspace.bodySections.length", context), 0);
        assert.equal(vm.runInContext("industryReportWorkspace.busy", context), true);
        assert.equal(vm.runInContext("industryReportWorkspace.completedSteps.includes('coordinator')", context), false);
        callback({event:"coordination_completed", coordination, warnings:[{stage:"task_coordination", reason:"invalid_decision"}]});
        assert.match(stages.at(-1).detail, /部分完成.*调整1节.*保留1节/);
        callback({event:"completed", writing_tasks:[finalTask], coordination, success_count:1, total:1, fallback_count:1});
    };
    await context.streamIndustryReportCoordinator({});
    assert.match(stages.at(-1).detail, /部分完成.*备用任务书/);
    const record = context.buildIndustryReportHistoryRecord();
    assert.equal(record.writingTasks[0].writing_decision.section_question, "最终问题");
    assert.equal(record.coordination, coordination);
    assert.equal(record.warnings[0].reason, "invalid_decision");
});

test("coordination completion retains failure and budget reasons", () => {
    const context = load();
    stubReportRendering(context);
    let detail;
    context.setIndustryReportStage = (stage, text) => detail = text;
    const expectations = {completed:/协调完成：调整2节/, partial:/部分完成：调整2节，保留1节原决策/, failed:/协调失败.*保留逐节决策/, skipped_budget:/超预算.*未调用模型.*保留逐节决策/};
    for (const [status, expected] of Object.entries(expectations)) {
        const coordination = {status, changed_outline_ids:["S1.1","S1.2"], rejected_outline_ids:["S1.3"]};
        context.handleIndustryReportCoordinatorStreamEvent({event:"coordination_completed", coordination});
        assert.match(detail, expected);
        context.handleIndustryReportCoordinatorStreamEvent({event:"completed", writing_tasks:[], coordination});
        assert.match(detail, expected);
    }
});

test("history round trip keeps coordination and old histories default to null without calls", async () => {
    const context = load();
    stubReportRendering(context);
    context.setIndustryReportStage = () => {};
    assert.equal(vm.runInContext("industryReportWorkspace.coordination", context), null);
    let calls = 0;
    const coordination = {status:"skipped_budget", input_chars:25000, changed_outline_ids:[], rejected_outline_ids:[]};
    let record = {id:"saved", writingTasks:[{outline_id:"S1.1", writing_decision:{section_question:"最终问题"}}], coordination};
    context.document.getElementById = id => id === "industry-report-history-select" ? {value:"saved"} : null;
    context.industryReportApi = async () => { calls++; return {report:record}; };
    await context.loadSelectedIndustryReportHistory();
    assert.equal(context.buildIndustryReportHistoryRecord().coordination, coordination);
    assert.equal(context.buildIndustryReportHistoryRecord().writingTasks[0].writing_decision.section_question, "最终问题");
    record = {id:"old", writingTasks:[{outline_id:"S1.1", writing_system_prompt:"历史指令"}]};
    await context.loadSelectedIndustryReportHistory();
    assert.equal(context.buildIndustryReportHistoryRecord().coordination, null);
    assert.equal(calls, 2);
    context.resetIndustryReportWorkspace();
    assert.equal(vm.runInContext("industryReportWorkspace.coordination", context), null);
});

test("prepare response preserves coordination reason and fallback completion text", async () => {
    const context = load();
    stubReportRendering(context);
    const stages = [];
    context.setIndustryReportStage = (stage, detail) => stages.push(detail);
    context.setIndustryReportBusy = () => {};
    context.startIndustryReportStepTiming = () => {};
    context.setIndustryReportRequirementSubmittedStatus = () => {};
    context.getIndustryReportFormValues = () => ({title:"测试", prompt:"需求", industry:"ai"});
    context.readIndustryReportOutlineFromDom = () => [{subsections:[{id:"S1.1", title:"本节"}]}];
    const coordination = {status:"failed", changed_outline_ids:[], rejected_outline_ids:[]};
    context.streamIndustryReportCoordinator = async () => ({writing_tasks:[{outline_id:"S1.1", writing_decision:{section_question:"最终"}}], coordination, fallback_count:1});
    await context.prepareIndustryReportTasks();
    assert.match(stages.at(-1), /协调失败.*备用任务书/);
    assert.equal(context.buildIndustryReportHistoryRecord().coordination, coordination);
});

test("busy coordination blocks history drafts while body completion can still save", async () => {
    const context = load();
    stubReportRendering(context);
    const button = {disabled:false, classList:{toggle() {}}};
    context.document.querySelectorAll = selector => selector === 'button[onclick="saveIndustryReportHistory()"]' ? [button] : [];
    const saved = [];
    context.industryReportApi = async (url, options) => {
        const report = JSON.parse(options.body).report;
        saved.push(report);
        return {report};
    };
    vm.runInContext(`industryReportWorkspace.currentStage = "coordinator";
        industryReportWorkspace.outline = [{subsections:[{id:"S1.1"}]}];
        industryReportWorkspace.writingTasks = [{outline_id:"S1.1", writing_decision:{section_question:"初稿"}}];`, context);
    context.setIndustryReportBusy(true);
    assert.equal(button.disabled, true);
    await context.saveIndustryReportHistory();
    await context.saveIndustryReportHistory({silent:true});
    assert.equal(saved.length, 0);
    vm.runInContext(`industryReportWorkspace.currentStage = "body";
        industryReportWorkspace.writingTasks[0].writing_decision.section_question = "最终问题";
        industryReportWorkspace.bodySections = [{outline_id:"S1.1",body_text:"完成正文"}];`, context);
    await context.saveIndustryReportHistory({silent:true});
    assert.equal(saved.length, 1);
    assert.equal(saved[0].writingTasks[0].writing_decision.section_question, "最终问题");
    context.setIndustryReportBusy(false);
    assert.equal(button.disabled, false);
});

test("adding after deleting a middle subsection keeps existing ids unique", () => {
    const context = load();
    stubReportRendering(context);
    context.readIndustryReportOutlineFromDom = () => vm.runInContext("industryReportWorkspace.outline", context);
    vm.runInContext(`industryReportWorkspace.outline = [{level1_id:"S1", subsections:[
        {outline_id:"S1.1"}, {outline_id:"S1.2"}, {outline_id:"S1.3"}
    ]}];`, context);
    context.removeIndustryReportSubsection(0, 1);
    context.addIndustryReportSubsection(0);
    const ids = vm.runInContext("industryReportWorkspace.outline[0].subsections.map(item => item.outline_id)", context);
    assert.deepEqual(Array.from(ids), ["S1.1", "S1.3", "S1.4"]);
});

test("adding after deleting a middle section keeps section and subsection ids unique", () => {
    const context = load();
    stubReportRendering(context);
    context.readIndustryReportOutlineFromDom = () => vm.runInContext("industryReportWorkspace.outline", context);
    vm.runInContext(`industryReportWorkspace.outline = [
        {level1_id:"S1",subsections:[{outline_id:"S1.1"}]},
        {level1_id:"S2",subsections:[{outline_id:"S2.1"}]},
        {level1_id:"S3",subsections:[{outline_id:"S3.1"}]}
    ];`, context);
    context.removeIndustryReportSection(1);
    context.addIndustryReportSection();
    const outline = vm.runInContext("industryReportWorkspace.outline", context);
    assert.deepEqual(Array.from(outline, item => item.level1_id), ["S1", "S3", "S4"]);
    assert.equal(outline[2].subsections[0].outline_id, "S4.1");
});

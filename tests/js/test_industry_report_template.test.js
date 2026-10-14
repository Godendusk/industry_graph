const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.resolve(__dirname, "../../static/js/modules/industry_report.js"), "utf8");

function run(scenario) {
    const elements = new Map();
    const listeners = {};
    function element(id) {
        if (!elements.has(id)) elements.set(id, {
            value: "", hidden: true, disabled: false, textContent: "", innerHTML: "",
            classList: { toggle() {}, add() {}, remove() {} },
            focus() {}, querySelector() { return { focus() {}, inert: false }; },
        });
        return elements.get(id);
    }
    const document = {
        getElementById: element,
        addEventListener(name, handler) { listeners[name] = handler; },
        querySelector() { return { inert: false, focus() {} }; },
        querySelectorAll() { return []; },
        activeElement: { focus() {} }, body: { style: { overflow: "" } },
    };
    return vm.runInNewContext(script + `
        industryReportWorkspace.taskCard = { industry_matches: [{key: 'ai', name: '人工智能'}] };
        document.getElementById('industry-report-selected-industry').value = 'ai';
        ` + scenario, {
        document, window: { currentIndustry: "ai", addEventListener() {}, confirm() { return true; } },
        check(value, message) { assert.equal(Boolean(value), true, message); },
        listeners,
    });
}

test("placeholder completion preserves source and avoids duplicated industry suffix", () => run(`
    const source = ['xxx产业分析', 'XXX趋势', 'ｘｘｘ产业', '{产业}产业链', '{{产业}}市场', '新能源产业', '×××产业链发展总体态势', '央企在×××产业链布局现状分析'];
    const result = completeIndustryReportTemplateTitles(source, '人工智能');
    check(result.join('|') === '人工智能产业分析|人工智能趋势|人工智能产业|人工智能产业链|人工智能市场|新能源产业|人工智能产业链发展总体态势|央企在人工智能产业链布局现状分析', 'all placeholders completed');
    check(source[0] === 'xxx产业分析', 'source unchanged');
    check(completeIndustryReportTemplateTitles(['xxx产业与XXX产业'], '人工智能产业')[0] === '人工智能产业与人工智能产业', 'suffix not duplicated');
    check(completeIndustryReportTemplateTitles(['xxx产业'], '')[0] === 'xxx产业', 'missing industry preserves placeholder');
    check(industryReportTemplateHasPlaceholder('×××产业分析'), 'multiplication sign placeholder detected');
    check(completeIndustryReportTemplateTitles(['×××产业与×××产业'], '人工智能产业')[0] === '人工智能产业与人工智能产业', 'multiplication sign suffix not duplicated');
`));

test("saving source keeps dialog open and requires explicit final confirmation", () => run(`
    openIndustryReportTemplate();
    industryReportTemplateDraft = ['xxx产业分析'];
    saveIndustryReportTemplate();
    check(!document.getElementById('industry-report-template-modal').hidden, 'dialog stays open');
    check(!industryReportWorkspace.outlineTemplate.confirmed, 'source save is not confirmation');
    check(readIndustryReportTaskCardFromDom().outline_template === undefined, 'unconfirmed template not submitted');
    editIndustryReportTemplateRow('final', 0, '人工智能产业趋势');
    confirmIndustryReportTemplate();
    check(industryReportWorkspace.outlineTemplate.confirmed, 'confirmed');
    check(readIndustryReportTaskCardFromDom().outline_template.level1_titles[0] === '人工智能产业趋势', 'confirmed final submitted');
    check(document.getElementById('industry-report-template-modal').hidden, 'dialog closed');
`));

test("closing discards edits while revoking confirmation and preserving saved titles", () => run(`
    openIndustryReportTemplate(); industryReportTemplateDraft = ['范围']; saveIndustryReportTemplate(); confirmIndustryReportTemplate();
    openIndustryReportTemplate(); editIndustryReportTemplateRow('final', 0, '未保存编辑'); closeIndustryReportTemplate();
    check(!industryReportWorkspace.outlineTemplate.confirmed, 'confirmation revoked');
    openIndustryReportTemplate();
    check(industryReportTemplateFinalDraft[0] === '范围', 'unsaved final discarded');
    check(industryReportTemplateDraft[0] === '范围', 'saved source preserved');
`));

test("recompletion asks before replacing manual edits", () => run(`
    openIndustryReportTemplate(); industryReportTemplateDraft = ['xxx产业']; saveIndustryReportTemplate();
    editIndustryReportTemplateRow('final', 0, '手动标题');
    window.confirm = () => false;
    saveIndustryReportTemplate();
    check(industryReportTemplateFinalDraft[0] === '手动标题', 'cancel overwrite preserves final');
    window.confirm = () => true;
    saveIndustryReportTemplate();
    check(industryReportTemplateFinalDraft[0] === '人工智能产业', 'accepted overwrite recompletes');
`));

test("unsaved source and unresolved placeholders cannot be confirmed", () => run(`
    openIndustryReportTemplate(); industryReportTemplateDraft = ['范围']; saveIndustryReportTemplate();
    editIndustryReportTemplateRow('source', 0, '新原始模版'); confirmIndustryReportTemplate();
    check(!industryReportWorkspace.outlineTemplate.confirmed, 'unsaved source blocks confirmation');
    industryReportTemplateDraft = ['×××产业'];
    document.getElementById('industry-report-selected-industry').value = '';
    saveIndustryReportTemplate(); confirmIndustryReportTemplate();
    check(!industryReportWorkspace.outlineTemplate.confirmed, 'missing industry blocks confirmation');
    check(document.getElementById('industry-report-template-confirm').disabled, 'confirm disabled');
`));

test("legacy templates require confirmation and cancellation restores default behavior", () => run(`
    industryReportWorkspace.outlineTemplate = normalizeIndustryReportTemplate({level1_titles: ['旧标题']});
    check(!industryReportWorkspace.outlineTemplate.confirmed, 'legacy unconfirmed');
    check(industryReportWorkspace.outlineTemplate.source_titles[0] === '旧标题', 'legacy source retained');
    openIndustryReportTemplate(); cancelIndustryReportTemplate();
    check(industryReportWorkspace.outlineTemplate === null, 'template removed');
    check(readIndustryReportTaskCardFromDom().outline_template === undefined, 'default request restored');
`));

test("industry changes preserve saved manual titles and require another confirmation", () => run(`
    openIndustryReportTemplate(); industryReportTemplateDraft = ['xxx产业']; saveIndustryReportTemplate();
    editIndustryReportTemplateRow('final', 0, '手动标题'); confirmIndustryReportTemplate();
    resetIndustryReportWorkspace = () => { industryReportWorkspace.outlineTemplate = null; };
    listeners.industryChanged();
    check(industryReportWorkspace.outlineTemplate.level1_titles[0] === '手动标题', 'manual titles retained');
    check(industryReportWorkspace.outlineTemplate.source_titles[0] === 'xxx产业', 'source retained');
    check(!industryReportWorkspace.outlineTemplate.confirmed, 'confirmation revoked');
`));

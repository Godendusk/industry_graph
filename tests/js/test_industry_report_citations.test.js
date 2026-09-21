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

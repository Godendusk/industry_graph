const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const REPORT_SCRIPT_PATH = path.resolve(
    __dirname,
    "../../static/js/modules/industry_report.js",
);
const REPORT_SCRIPT = fs.readFileSync(REPORT_SCRIPT_PATH, "utf8");

function loadReportScript({ withSwitchView = true, withHistory = true } = {}) {
    const calls = {
        industries: [],
        loadedIndustries: [],
        replacedUrls: [],
        views: [],
    };
    const storage = new Map([["token", "authenticated-token"]]);
    const sessionStorage = {
        getItem(key) {
            return storage.has(key) ? storage.get(key) : null;
        },
        setItem(key, value) {
            storage.set(key, String(value));
        },
    };
    const history = withHistory
        ? {
            replaceState(_state, _title, url) {
                calls.replacedUrls.push(String(url));
            },
        }
        : {};
    const window = {
        addEventListener() {},
        currentIndustry: "ai",
        history,
        location: {
            origin: "https://sasac-rc.com",
            pathname: "/indusgraph/",
        },
        sessionStorage,
    };
    const context = {
        URLSearchParams,
        clearTimeout,
        console,
        document: {
            addEventListener() {},
            getElementById() {
                return null;
            },
            querySelectorAll() {
                return [];
            },
        },
        history,
        sessionStorage,
        setTimeout,
        window,
    };
    if (withSwitchView) {
        context.setCurrentIndustryFromRoute = industry => {
            calls.industries.push(industry);
            window.currentIndustry = industry;
        };
        context.loadIndustryData = industry => calls.loadedIndustries.push(industry);
        context.switchView = view => calls.views.push(view);
    }
    vm.createContext(context);
    vm.runInContext(REPORT_SCRIPT, context, { filename: REPORT_SCRIPT_PATH });
    return { calls, context, sessionStorage, window };
}

test("report evidence graph link uses in-page navigation instead of a new tab", () => {
    const { context } = loadReportScript();
    const html = context.renderIndustryReportEvidenceCard(
        { id: "node-7", title: "模型服务" },
        "知识图谱 1",
        "graph",
    );

    assert.doesNotMatch(html, /target=["']_blank["']/);
    assert.match(html, /data-graph-node-id="node-7"/);
    assert.match(html, /onclick="return openIndustryReportGraph\(this\.dataset\.graphNodeId\)"/);
    assert.match(
        html,
        /href="https:\/\/sasac-rc\.com\/indusgraph\/\?view=graph&amp;subview=graph&amp;node=node-7&amp;industry=ai"/,
    );
});

test("rewrite material graph link also uses in-page navigation", () => {
    const { context } = loadReportScript();
    const html = context.renderIndustryReportMaterialRow(
        { id: "node-8", title: "行业应用" },
        0,
        "graph",
        false,
    );

    assert.doesNotMatch(html, /target=["']_blank["']/);
    assert.match(html, /data-graph-node-id="node-8"/);
    assert.match(html, /onclick="return openIndustryReportGraph\(this\.dataset\.graphNodeId\)"/);
});

test("graph node id is HTML-escaped outside the fixed click handler", () => {
    const { context } = loadReportScript();
    const html = context.renderIndustryReportEvidenceCard(
        { id: 'node-7" onmouseover="alert(1)', title: "不可信节点" },
        "知识图谱 1",
        "graph",
    );

    assert.match(html, /data-graph-node-id="node-7&quot; onmouseover=&quot;alert\(1\)"/);
    assert.match(html, /onclick="return openIndustryReportGraph\(this\.dataset\.graphNodeId\)"/);
    assert.doesNotMatch(html, /onclick="[^"]*alert\(1\)/);
});

test("saved report keeps its provenance when the global industry changes", () => {
    const { context } = loadReportScript();
    vm.runInContext(`
        industryReportWorkspace.historyId = "saved-report";
        industryReportWorkspace.industry = "ai";
        window.currentIndustry = "sea";
        syncIndustryReportHeader();
    `, context);

    assert.equal(vm.runInContext("industryReportWorkspace.industry", context), "ai");
});

test("opening a report graph node preserves session and switches the current view", () => {
    const { calls, context, sessionStorage, window } = loadReportScript();
    vm.runInContext("industryReportWorkspace.industry = 'sea'", context);

    const result = context.openIndustryReportGraph(" node-42 ");

    assert.equal(result, false);
    assert.deepEqual(calls.industries, ["sea"]);
    assert.equal(window.pendingGraphSubView, "graph");
    assert.equal(window.pendingGraphFocusNodeId, "node-42");
    assert.deepEqual(calls.views, ["graph"]);
    assert.deepEqual(calls.replacedUrls, [
        "https://sasac-rc.com/indusgraph/?view=graph&subview=graph&node=node-42&industry=sea",
    ]);
    assert.equal(sessionStorage.getItem("token"), "authenticated-token");
});

test("cross-industry graph navigation invokes the existing cache reset pipeline", () => {
    const { calls, context } = loadReportScript();
    vm.runInContext("industryReportWorkspace.industry = 'sea'", context);

    assert.equal(context.openIndustryReportGraph("node-42"), false);
    assert.deepEqual(calls.loadedIndustries, ["sea"]);
});

test("missing app navigation falls back to the normal same-tab link", () => {
    const { calls, context } = loadReportScript({ withSwitchView: false });

    assert.equal(context.openIndustryReportGraph("node-9"), true);
    assert.deepEqual(calls.replacedUrls, []);
    assert.deepEqual(calls.views, []);
});

test("history API absence does not block the in-page graph switch", () => {
    const { calls, context, window } = loadReportScript({ withHistory: false });

    assert.equal(context.openIndustryReportGraph("node-10"), false);
    assert.equal(window.pendingGraphFocusNodeId, "node-10");
    assert.deepEqual(calls.views, ["graph"]);
    assert.deepEqual(calls.replacedUrls, []);
});

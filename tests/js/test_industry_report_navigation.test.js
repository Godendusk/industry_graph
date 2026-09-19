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

function createClassList() {
    const names = new Set();
    return {
        add(...items) {
            items.forEach(item => names.add(item));
        },
        remove(...items) {
            items.forEach(item => names.delete(item));
        },
        toggle(item, force) {
            const enabled = force === undefined ? !names.has(item) : Boolean(force);
            if (enabled) names.add(item);
            else names.delete(item);
            return enabled;
        },
        contains(item) {
            return names.has(item);
        },
    };
}

function loadReportScript({ withSwitchView = true, withHistory = true } = {}) {
    const calls = {
        industries: [],
        loadedIndustries: [],
        replacedUrls: [],
        statuses: [],
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
    context.setIndustryReportStatus = (message, type = "info") => {
        calls.statuses.push({ message, type });
    };
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

test("generated report keeps provenance while its history save is pending", () => {
    const { context } = loadReportScript();
    vm.runInContext(`
        industryReportWorkspace.historyId = "";
        industryReportWorkspace.industry = "ai";
        industryReportWorkspace.outline = [{ level1_id: "S1" }];
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

test("embodied report task-card request reaches the backend with its page industry", async () => {
    const { context, window } = loadReportScript();
    const requests = [];
    const elements = {
        "industry-report-prompt": { value: "分析具身智能产业发展" },
        "industry-report-title": { value: "具身智能产业报告" },
    };
    window.currentIndustry = "embodied";
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async (url, options) => {
        requests.push({ url, options });
        return {
            ok: true,
            async json() {
                return {
                    status: "success",
                    report_title: "具身智能产业报告",
                    outline: [],
                };
            },
        };
    };

    await context.submitIndustryReportRequirement();

    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "/api/report/task-card");
    assert.deepEqual(
        JSON.parse(requests[0].options.body),
        {
            title: "具身智能产业报告",
            user_requirement: "分析具身智能产业发展",
            page_industry: "embodied",
        },
    );
});

test("embodied report coordinator request keeps the selected industry", async () => {
    const { context, window } = loadReportScript();
    const requests = [];
    const elements = {
        "industry-report-prompt": { value: "分析具身智能产业发展" },
        "industry-report-title": { value: "具身智能产业报告" },
    };
    window.currentIndustry = "embodied";
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async (url, options) => {
        requests.push({ url, options });
        return {
            ok: true,
            async json() {
                return { status: "success", writing_tasks: [] };
            },
        };
    };
    vm.runInContext(`
        readIndustryReportOutlineFromDom = () => [{
            level1_id: "S1",
            level1_title: "产业发展",
            subsections: [{ outline_id: "S1.1", title: "技术进展" }],
        }];
    `, context);

    await context.prepareIndustryReportTasks();

    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "/api/report/coordinator");
    assert.equal(JSON.parse(requests[0].options.body).industry, "embodied");
});

test("embodied report header uses the supported-industry style", () => {
    const { context, window } = loadReportScript();
    const pill = { textContent: "", className: "" };
    window.currentIndustry = "embodied";
    context.document.getElementById = id => (
        id === "report-industry-pill" ? pill : null
    );

    context.syncIndustryReportHeader();

    assert.equal(pill.textContent, "具身智能");
    assert.match(pill.className, /bg-blue-50/);
    assert.doesNotMatch(pill.className, /bg-amber-50/);
});

test("task-card fallback remains editable and tells the user to confirm it", async () => {
    const { calls, context } = loadReportScript();
    const warning = {
        stage: "report_requirement",
        code: "report_requirement_fallback",
        reason: "empty_visible_content",
        message: "模型未返回完整报告需求，已生成可编辑基础需求，请确认后继续。",
    };
    const classList = createClassList();
    const elements = {
        "industry-report-prompt": { value: "关注具身智能企业的上市表现" },
        "industry-report-title": { value: "具身智能投资状况" },
        "industry-report-task-card-section": { classList },
        "industry-report-task-requirement": { value: "", disabled: true },
        "report-task-card-confirm-btn": { disabled: true, classList },
    };
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async () => ({
        ok: true,
        async json() {
            return {
                status: "success",
                task_card: {
                    original_title: "具身智能投资状况",
                    selected_title: "具身智能投资状况",
                    report_requirement: "围绕具身智能产业，关注具身智能企业的上市表现。",
                    selected_industry: "embodied",
                },
                warnings: [warning],
            };
        },
    });

    await context.submitIndustryReportRequirement();

    assert.deepEqual(calls.statuses.at(-1), {
        message: warning.message,
        type: "info",
    });
    assert.equal(
        elements["industry-report-task-requirement"].value,
        "围绕具身智能产业，关注具身智能企业的上市表现。",
    );
    assert.equal(elements["industry-report-task-requirement"].disabled, false);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, false);
});

test("industry-change fallback warning is visible", async () => {
    const { calls, context } = loadReportScript();
    const warning = {
        stage: "report_requirement",
        code: "report_requirement_fallback",
        reason: "empty_visible_content",
        message: "模型未返回完整报告需求，已生成可编辑基础需求，请确认后继续。",
    };
    const classList = createClassList();
    const elements = {
        "industry-report-selected-industry": { value: "embodied" },
        "industry-report-task-title": { value: "具身智能投资状况" },
        "industry-report-task-requirement": { value: "原始需求", disabled: false },
        "report-task-card-confirm-btn": { disabled: false, classList },
    };
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async () => ({
        ok: true,
        async json() {
            return {
                status: "success",
                report_requirement: "围绕具身智能产业，关注具身智能企业的上市表现。",
                source: "fallback",
                warnings: [warning],
            };
        },
    });
    vm.runInContext(`
        industryReportWorkspace.taskCard = {
            original_title: "具身智能投资状况",
            selected_title: "具身智能投资状况",
            original_requirement: "关注具身智能企业的上市表现",
            report_requirement: "原始需求",
            industry_matches: [{ key: "embodied", name: "具身智能", graph_available: true }],
        };
    `, context);

    await context.handleIndustryReportSelectedIndustryChange();

    assert.deepEqual(calls.statuses.at(-1), {
        message: warning.message,
        type: "info",
    });
    assert.equal(elements["industry-report-task-requirement"].disabled, false);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, false);
});

test("a stale industry rewrite cannot overwrite a newly submitted task card", async () => {
    const { context } = loadReportScript();
    const classList = createClassList();
    const elements = {
        "industry-report-prompt": { value: "新的用户需求" },
        "industry-report-title": { value: "新任务卡标题" },
        "industry-report-task-card-section": { classList },
        "industry-report-selected-industry": { value: "embodied" },
        "industry-report-task-title": { value: "旧任务卡标题" },
        "industry-report-task-requirement": { value: "旧需求", disabled: false },
        "report-task-card-confirm-btn": { disabled: false, classList },
    };
    let resolveRewrite;
    const rewriteResponse = new Promise(resolve => {
        resolveRewrite = resolve;
    });
    let resolveTaskCard;
    const taskCardResponse = new Promise(resolve => {
        resolveTaskCard = resolve;
    });
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async url => {
        if (url === "/api/report/task-card/rewrite-requirement") return rewriteResponse;
        return taskCardResponse;
    };
    vm.runInContext(`
        industryReportWorkspace.requirementRewriteSeq = 7;
        industryReportWorkspace.taskCard = {
            original_title: "旧任务卡标题",
            selected_title: "旧任务卡标题",
            original_requirement: "旧需求",
            report_requirement: "旧需求",
            industry_matches: [{ key: "embodied", name: "具身智能", graph_available: true }],
        };
    `, context);

    const staleRewrite = context.handleIndustryReportSelectedIndustryChange();
    await Promise.resolve();
    const newSubmission = context.submitIndustryReportRequirement();
    await Promise.resolve();
    assert.equal(elements["industry-report-task-requirement"].disabled, true);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);
    resolveRewrite({
        ok: true,
        async json() {
            return {
                status: "success",
                report_requirement: "旧产业切换请求的需求。",
                warnings: [],
            };
        },
    });
    await staleRewrite;

    assert.equal(
        vm.runInContext("industryReportWorkspace.taskCard.report_requirement", context),
        "旧需求",
    );
    assert.equal(
        elements["industry-report-task-requirement"].value,
        "正在重新生成报告需求...",
    );
    assert.equal(elements["industry-report-task-requirement"].disabled, true);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);

    resolveTaskCard({
        ok: true,
        async json() {
            return {
                status: "success",
                task_card: {
                    original_title: "新任务卡标题",
                    selected_title: "新任务卡标题",
                    report_requirement: "新任务卡需求。",
                    selected_industry: "ai",
                },
                warnings: [],
            };
        },
    });
    await newSubmission;

    assert.equal(
        vm.runInContext("industryReportWorkspace.taskCard.selected_title", context),
        "新任务卡标题",
    );
    assert.equal(
        vm.runInContext("industryReportWorkspace.taskCard.report_requirement", context),
        "新任务卡需求。",
    );
    assert.equal(elements["industry-report-task-requirement"].disabled, false);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, false);
});

test("a reset cannot reuse a rewrite sequence held by a pending industry rewrite", async () => {
    const { context } = loadReportScript();
    const classList = createClassList();
    const elements = {
        "industry-report-prompt": { value: "新的用户需求" },
        "industry-report-title": { value: "新任务卡标题", placeholder: "" },
        "industry-report-task-card-section": { classList },
        "industry-report-selected-industry": { value: "embodied" },
        "industry-report-task-title": { value: "旧任务卡标题" },
        "industry-report-task-requirement": { value: "旧需求", disabled: false },
        "report-task-card-confirm-btn": { disabled: false, classList },
    };
    let resolveRewrite;
    const rewriteResponse = new Promise(resolve => {
        resolveRewrite = resolve;
    });
    let resolveTaskCard;
    const taskCardResponse = new Promise(resolve => {
        resolveTaskCard = resolve;
    });
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async url => {
        if (url === "/api/report/task-card/rewrite-requirement") return rewriteResponse;
        if (url === "/api/report/task-card") return taskCardResponse;
        return {
            ok: true,
            async json() {
                return { status: "success", items: [] };
            },
        };
    };
    vm.runInContext(`
        industryReportWorkspace.taskCard = {
            original_title: "旧任务卡标题",
            selected_title: "旧任务卡标题",
            original_requirement: "旧需求",
            report_requirement: "旧需求",
            industry_matches: [{ key: "embodied", name: "具身智能", graph_available: true }],
        };
    `, context);

    const staleRewrite = context.handleIndustryReportSelectedIndustryChange();
    await Promise.resolve();
    context.resetIndustryReportWorkspace();
    const newSubmission = context.submitIndustryReportRequirement();
    await Promise.resolve();

    assert.equal(elements["industry-report-task-requirement"].disabled, true);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);

    resolveRewrite({
        ok: true,
        async json() {
            return {
                status: "success",
                report_requirement: "旧产业切换请求的需求。",
                warnings: [],
            };
        },
    });
    await staleRewrite;

    assert.equal(vm.runInContext("industryReportWorkspace.taskCard", context), null);
    assert.equal(elements["industry-report-task-requirement"].value, "");
    assert.equal(elements["industry-report-task-requirement"].disabled, true);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);

    resolveTaskCard({
        ok: true,
        async json() {
            return {
                status: "success",
                task_card: {
                    original_title: "新任务卡标题",
                    selected_title: "新任务卡标题",
                    report_requirement: "新任务卡需求。",
                    selected_industry: "ai",
                },
                warnings: [],
            };
        },
    });
    await newSubmission;

    assert.equal(
        vm.runInContext("industryReportWorkspace.taskCard.report_requirement", context),
        "新任务卡需求。",
    );
    assert.equal(elements["industry-report-task-requirement"].disabled, false);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, false);
});

test("a stale task-card success cannot overwrite or unlock a reset workspace", async () => {
    const { calls, context } = loadReportScript();
    const classList = createClassList();
    const elements = {
        "industry-report-prompt": { value: "任务卡 A 的需求" },
        "industry-report-title": { value: "任务卡 A 的标题", placeholder: "" },
        "industry-report-task-card-section": { classList },
        "industry-report-task-requirement": { value: "", disabled: false },
        "report-task-card-confirm-btn": { disabled: false, classList },
        "report-outline-btn": { disabled: false, classList },
    };
    let resolveFirstTaskCard;
    const firstTaskCardResponse = new Promise(resolve => {
        resolveFirstTaskCard = resolve;
    });
    let resolveSecondTaskCard;
    const secondTaskCardResponse = new Promise(resolve => {
        resolveSecondTaskCard = resolve;
    });
    let taskCardRequestCount = 0;
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async url => {
        if (url === "/api/report/task-card") {
            taskCardRequestCount += 1;
            return taskCardRequestCount === 1 ? firstTaskCardResponse : secondTaskCardResponse;
        }
        return {
            ok: true,
            async json() {
                return { status: "success", items: [] };
            },
        };
    };

    const firstSubmission = context.submitIndustryReportRequirement();
    await Promise.resolve();
    context.resetIndustryReportWorkspace();
    elements["industry-report-prompt"].value = "任务卡 B 的需求";
    elements["industry-report-title"].value = "任务卡 B 的标题";
    const secondSubmission = context.submitIndustryReportRequirement();
    await Promise.resolve();
    const statusCountBeforeFirstResponse = calls.statuses.length;

    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);
    assert.equal(elements["report-outline-btn"].disabled, true);

    resolveFirstTaskCard({
        ok: true,
        async json() {
            return {
                status: "success",
                task_card: {
                    selected_title: "任务卡 A 的标题",
                    report_requirement: "任务卡 A 的需求。",
                    selected_industry: "ai",
                },
                warnings: [],
            };
        },
    });
    await firstSubmission;

    assert.equal(vm.runInContext("industryReportWorkspace.taskCard", context), null);
    assert.equal(calls.statuses.length, statusCountBeforeFirstResponse);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);
    assert.equal(elements["report-outline-btn"].disabled, true);

    resolveSecondTaskCard({
        ok: true,
        async json() {
            return {
                status: "success",
                task_card: {
                    selected_title: "任务卡 B 的标题",
                    report_requirement: "任务卡 B 的需求。",
                    selected_industry: "ai",
                },
                warnings: [],
            };
        },
    });
    await secondSubmission;

    assert.equal(
        vm.runInContext("industryReportWorkspace.taskCard.report_requirement", context),
        "任务卡 B 的需求。",
    );
    assert.equal(elements["report-task-card-confirm-btn"].disabled, false);
    assert.equal(elements["report-outline-btn"].disabled, false);
});

test("a stale task-card failure cannot update or unlock a newer submission", async () => {
    const { calls, context } = loadReportScript();
    const classList = createClassList();
    const elements = {
        "industry-report-prompt": { value: "任务卡 A 的需求" },
        "industry-report-title": { value: "任务卡 A 的标题", placeholder: "" },
        "industry-report-task-card-section": { classList },
        "industry-report-task-requirement": { value: "", disabled: false },
        "report-task-card-confirm-btn": { disabled: false, classList },
        "report-outline-btn": { disabled: false, classList },
    };
    let rejectFirstTaskCard;
    const firstTaskCardResponse = new Promise((_resolve, reject) => {
        rejectFirstTaskCard = reject;
    });
    let resolveSecondTaskCard;
    const secondTaskCardResponse = new Promise(resolve => {
        resolveSecondTaskCard = resolve;
    });
    let taskCardRequestCount = 0;
    context.API_BASE = "";
    context.document.getElementById = id => elements[id] || null;
    context.fetch = async url => {
        if (url === "/api/report/task-card") {
            taskCardRequestCount += 1;
            return taskCardRequestCount === 1 ? firstTaskCardResponse : secondTaskCardResponse;
        }
        return {
            ok: true,
            async json() {
                return { status: "success", items: [] };
            },
        };
    };

    const firstSubmission = context.submitIndustryReportRequirement();
    await Promise.resolve();
    context.resetIndustryReportWorkspace();
    elements["industry-report-prompt"].value = "任务卡 B 的需求";
    elements["industry-report-title"].value = "任务卡 B 的标题";
    const secondSubmission = context.submitIndustryReportRequirement();
    await Promise.resolve();
    const statusCountBeforeFirstFailure = calls.statuses.length;

    rejectFirstTaskCard(new Error("任务卡 A 已失败"));
    await firstSubmission;

    assert.equal(vm.runInContext("industryReportWorkspace.taskCard", context), null);
    assert.equal(calls.statuses.length, statusCountBeforeFirstFailure);
    assert.equal(elements["report-task-card-confirm-btn"].disabled, true);
    assert.equal(elements["report-outline-btn"].disabled, true);

    resolveSecondTaskCard({
        ok: true,
        async json() {
            return {
                status: "success",
                task_card: {
                    selected_title: "任务卡 B 的标题",
                    report_requirement: "任务卡 B 的需求。",
                    selected_industry: "ai",
                },
                warnings: [],
            };
        },
    });
    await secondSubmission;

    assert.equal(
        vm.runInContext("industryReportWorkspace.taskCard.report_requirement", context),
        "任务卡 B 的需求。",
    );
    assert.equal(elements["report-task-card-confirm-btn"].disabled, false);
    assert.equal(elements["report-outline-btn"].disabled, false);
});

# Fix Report Graph Login Redirect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every “打开图谱” link in generated reports navigate to and focus the corresponding graph node in the current tab without losing the authenticated session.

**Architecture:** Keep the existing graph route URL and graph initialization pipeline, but intercept report link clicks before full-page navigation. A small report-owned navigation function will synchronize the industry, set the existing pending graph state, replace the address-bar route without reload, and call the existing `switchView('graph')` entry point.

**Tech Stack:** Browser JavaScript, Node.js built-in `node:test`/`vm`, existing Python `unittest` suite in the `kunlun` Conda environment.

---

## File Structure

- Create `tests/js/test_industry_report_navigation.test.js`: execute the real report script in a minimal browser-like VM and verify rendered links plus navigation side effects.
- Modify `static/js/modules/industry_report.js`: add the in-page graph navigator and wire both report graph-link renderers to it.

No backend, authentication, graph rendering, or report generation file changes are required.

### Task 1: Add regression tests that reproduce the new-tab/session-loss path

**Files:**

- Create: `tests/js/test_industry_report_navigation.test.js`
- Test: `tests/js/test_industry_report_navigation.test.js`

- [ ] **Step 1: Write the failing tests**

Create the following test file:

```javascript
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
    assert.match(html, /onclick="return openIndustryReportGraph\('node-7'\)"/);
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
    assert.match(html, /onclick="return openIndustryReportGraph\('node-8'\)"/);
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
```

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
node --test tests/js/test_industry_report_navigation.test.js
```

Expected: FAIL. The first two tests find `target="_blank"`, and the navigation tests report that `openIndustryReportGraph` is undefined. These failures prove the test covers the reported behavior rather than an unrelated setup error.

- [ ] **Step 3: Confirm the production script is unchanged during RED**

Run:

```bash
git diff -- static/js/modules/industry_report.js
```

Expected: no output.

### Task 2: Implement minimal same-page navigation

**Files:**

- Modify: `static/js/modules/industry_report.js:960-990`
- Modify: `static/js/modules/industry_report.js:1065-1084`
- Test: `tests/js/test_industry_report_navigation.test.js`

- [ ] **Step 1: Add the navigation function next to the existing graph-link builder**

Insert after `buildIndustryReportGraphLink(nodeId)`:

```javascript
function openIndustryReportGraph(nodeId) {
    const normalizedNodeId = String(nodeId ?? "").trim();
    if (!normalizedNodeId || typeof switchView !== "function") return true;

    const industry = industryReportWorkspace.industry || getIndustryReportCurrentIndustry();
    if (typeof setCurrentIndustryFromRoute === "function") {
        setCurrentIndustryFromRoute(industry);
    }
    window.pendingGraphSubView = "graph";
    window.pendingGraphFocusNodeId = normalizedNodeId;
    if (window.history && typeof window.history.replaceState === "function") {
        window.history.replaceState({}, "", buildIndustryReportGraphLink(normalizedNodeId));
    }
    switchView("graph");
    return false;
}
```

- [ ] **Step 2: Wire the report evidence link to the navigator**

Replace the graph-link expression in `renderIndustryReportEvidenceCard()` with:

```javascript
${graphLink ? `<a href="${escapeIndustryReportHtml(graphLink)}" onclick="return openIndustryReportGraph('${escapeIndustryReportJs(nodeId)}')" class="text-blue-600 hover:text-blue-700 font-medium">打开图谱</a>` : ""}
```

- [ ] **Step 3: Wire the rewrite-material link to the same navigator**

Replace the graph-link expression in `renderIndustryReportMaterialRow()` with:

```javascript
${graphLink ? `<a href="${escapeIndustryReportHtml(graphLink)}" onclick="return openIndustryReportGraph('${escapeIndustryReportJs(nodeId)}')" class="text-blue-600 hover:text-blue-700">打开图谱</a>` : ""}
```

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run:

```bash
node --test tests/js/test_industry_report_navigation.test.js
```

Expected: `5` tests pass, `0` fail. The output must contain no runtime errors or warnings.

- [ ] **Step 5: Check syntax and diff hygiene**

Run:

```bash
node --check static/js/modules/industry_report.js
git diff --check
```

Expected: both commands exit `0` with no output.

- [ ] **Step 6: Commit the focused implementation**

```bash
git add static/js/modules/industry_report.js tests/js/test_industry_report_navigation.test.js
git commit -m "fix: keep report graph navigation in current session"
```

### Task 3: Run regression verification and document evidence

**Files:**

- Verify: `static/js/modules/industry_report.js`
- Verify: `tests/js/test_industry_report_navigation.test.js`

- [ ] **Step 1: Verify both report links no longer open a new tab**

Run:

```bash
rg -n '打开图谱|target="_blank"|openIndustryReportGraph' static/js/modules/industry_report.js
```

Expected: two “打开图谱” renderers call `openIndustryReportGraph`; no `target="_blank"` appears in this file.

- [ ] **Step 2: Run the complete JavaScript navigation tests again**

Run:

```bash
node --test tests/js/test_industry_report_navigation.test.js
```

Expected: `5` tests pass, `0` fail.

- [ ] **Step 3: Run the existing project regression suite in its required environment**

Run:

```bash
conda run -n kunlun python -m unittest discover -s tests -v
```

Expected: `264` existing Python tests pass with the existing single optional `jieba` skip; no failures or errors.

- [ ] **Step 4: Confirm only planned files changed and commits are clean**

Run:

```bash
git status --short
git log --oneline -4
```

Expected: the worktree is clean. Recent commits contain the design documentation and focused navigation fix only.

## Manual deployment acceptance

After deploying the branch to an authenticated test environment:

1. Open a saved/generated report and expand a section's evidence.
2. Click “打开图谱” and confirm the current tab enters the force graph without visiting the login page.
3. Confirm the report's industry is selected and the referenced node is focused.
4. Return to the report through the sidebar, open the rewrite modal, recommend materials, and repeat with its “打开图谱” link.
5. Confirm the address bar contains only `view`, `subview`, `node`, and `industry`; it must not contain token or user information.

## Rollback

Revert the focused implementation commit. No database, storage, API, or data migration rollback is required.

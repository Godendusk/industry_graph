const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const FIXTURE_PATH = path.resolve(__dirname, "../fixtures/mixed_depth_graph.json");
const GRAPH_HIERARCHY = require("../../static/js/modules/graph_hierarchy.js");
const SCRIPT_PATH = path.resolve(__dirname, "../../static/js/modules/chain_panorama.js");

function loadPanorama() {
    const context = {
        console,
        document: { addEventListener() {}, getElementById() { return null; } },
        window: { currentIndustry: "ai", addEventListener() {}, innerWidth: 1200 },
        localStorage: { getItem() { return null; }, setItem() {} },
        fetch() { return Promise.reject(new Error("not used")); },
        setTimeout,
        clearTimeout,
        GraphHierarchy: GRAPH_HIERARCHY,
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(SCRIPT_PATH, "utf8"), context, { filename: SCRIPT_PATH });
    return context;
}

function makeStructure(context, graph) {
    return context.analyzeGraph(graph.nodes, graph.relationships);
}

test("panorama builds rows for level 3, 4, and 5 terminal paths", () => {
    const context = loadPanorama();
    const graph = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));
    const structure = makeStructure(context, graph);
    const rows = context.buildTerminalRows(structure, 10);

    assert.deepEqual(rows.map(row => row.segmentId), [20, 30, 40]);
    assert.deepEqual(rows[1].pathNames, ["三级分支", "四级叶子"]);
    assert.deepEqual(rows[2].pathNames, ["三级深分支", "四级分支", "五级叶子"]);
    assert.deepEqual(rows.map(row => row.companyCount), [1, 1, 1]);
});

test("panorama statistics include all four level-one branches", () => {
    const context = loadPanorama();
    const graph = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));
    const structure = makeStructure(context, graph);
    const stats = context.calcL1TypeStats(structure);

    assert.equal(stats.length, 4);
    assert.deepEqual(Array.from(stats, item => item.name), ["一级甲", "一级乙", "一级丙", "一级丁"]);
    assert.equal(stats[0].counts.total, 3);
});

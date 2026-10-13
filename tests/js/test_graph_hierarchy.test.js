const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const GraphHierarchy = require("../../static/js/modules/graph_hierarchy.js");
const FIXTURE_PATH = path.resolve(__dirname, "../fixtures/mixed_depth_graph.json");
const graph = JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8"));

test("terminal segments are derived from children across levels 3-5", () => {
    const hierarchy = GraphHierarchy.create(graph);
    assert.deepEqual(hierarchy.terminalSegmentIds(), [20, 30, 40]);
    assert.deepEqual(hierarchy.terminalSegmentIds(0), [20, 30, 40]);
});

test("segment paths contain every ancestor", () => {
    const hierarchy = GraphHierarchy.create(graph);
    assert.deepEqual(hierarchy.segmentPathIds(20), [1, 10, 20]);
    assert.deepEqual(hierarchy.segmentPathIds(30), [1, 10, 21, 30]);
    assert.deepEqual(hierarchy.segmentPathIds(40), [1, 10, 22, 31, 40]);
});

test("descendants and companies are deduplicated", () => {
    const hierarchy = GraphHierarchy.create(graph);
    assert.deepEqual(hierarchy.descendantSegmentIds(10), [20, 21, 22, 30, 31, 40]);
    assert.deepEqual(hierarchy.companyIdsForSegments([20, 30, 40]), [100, 101, 102]);
});

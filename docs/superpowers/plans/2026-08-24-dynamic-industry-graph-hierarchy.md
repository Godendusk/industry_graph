# Dynamic Industry Graph Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every existing graph consumer support a variable segment hierarchy from level 2 through level 5, with companies attached to terminal segment nodes, without replacing production data or adding a new industry.

**Architecture:** Introduce one small, pure hierarchy index in Python and one equivalent browser-side helper. Both derive parent/child relationships from `从属于`, identify terminal segments by topology rather than `level == 3`, and return complete root-to-leaf paths. Report retrieval, risk analysis, import matching, panorama rendering, sunburst, and mind map consume these helpers while keeping their own domain-specific presentation logic.

**Tech Stack:** Python 3.10, Flask application modules, `unittest`, browser JavaScript, Node.js built-in `node:test`/`vm`, ECharts, Markmap.

---

## Scope And Data Contract

This plan implements the following contract:

- The JSON envelope remains `{ "nodes": [...], "relationships": [...] }`.
- Root is the node whose `properties.level` is `0`.
- Segment nodes have label `环节` and numeric levels from 1 through 5.
- A `从属于` relationship points from child to parent.
- A terminal segment is an `环节` node with no child `环节` connected by `从属于`.
- Companies remain graph leaves and connect to terminal segments through `参与环节`.
- `level` is presentation metadata. Terminal status is derived from topology.
- The extra relationship property `seed` is accepted and ignored by existing consumers.

Explicitly out of scope:

- Do not overwrite `static/data/ai/graph_data.json` with the attached new-energy-vehicle sample.
- Do not add a `new_energy_vehicle` industry option, policy workbook, or report configuration.
- Do not introduce feature flags, schema versions, hashes, migration frameworks, or compatibility wrappers.
- Preserve only the narrow read fallback required for already-saved report evidence (`level3`) and panorama settings (`l3`). New writes use the new names.

## File Map

- Create `graph_hierarchy.py`: pure Python hierarchy indexing and traversal.
- Create `static/js/modules/graph_hierarchy.js`: browser and Node-compatible hierarchy indexing and traversal.
- Create `tests/fixtures/mixed_depth_graph.json`: minimal graph containing terminal segments at levels 3, 4, and 5 and four level-1 branches.
- Create `tests/test_graph_hierarchy.py`: Python traversal contract tests.
- Create `tests/test_graph_retriever_dynamic_hierarchy.py`: report retrieval contract tests.
- Create `tests/test_risk_dynamic_hierarchy.py`: risk aggregation tests.
- Create `tests/test_graph_import_dynamic_hierarchy.py`: import dictionary tests.
- Create `tests/js/test_graph_hierarchy.test.js`: browser helper tests.
- Create `tests/js/test_chain_panorama_dynamic_hierarchy.test.js`: panorama flattening and statistics tests.
- Create `tests/js/test_graph_dynamic_legends.test.js`: dynamic legend tests.
- Modify `report_generation/graph_retriever.py`: retrieve terminal segments and arbitrary ancestor paths.
- Modify `report_generation/outline_agent.py`: normalize the new `segment` evidence field.
- Modify `report_generation/coordinator_agent.py`: use `matched_segments`.
- Modify `report_generation/rewrite_agent.py`: use `matched_segments`.
- Modify `static/js/modules/industry_report.js`: render new evidence and read old saved `level3` evidence.
- Modify `risk_inference/risk.py`: recursively aggregate descendant terminal segments and companies.
- Modify `graph_import_script.py`: expose complete terminal paths to the extraction prompt.
- Modify `static/js/modules/chain_panorama.js`: render flattened terminal paths and dynamic level-1 statistics.
- Modify `static/js/modules/graph_sunburt.js`: use dynamic segment-level legend entries and colors.
- Modify `static/js/modules/graph_mindmap.js`: use the shared hierarchy and dynamic level colors.
- Modify `templates/base.html`: load `graph_hierarchy.js` before graph view modules.
- Modify `README.md`, `MODULES.md`, and `产业报告项目交接文档.md`: replace the fixed L1/L2/L3 contract with the terminal-segment contract.

### Task 1: Add The Mixed-Depth Contract Fixture

**Files:**
- Create: `tests/fixtures/mixed_depth_graph.json`
- Create: `tests/test_graph_hierarchy.py`
- Create: `tests/js/test_graph_hierarchy.test.js`

- [ ] **Step 1: Create a minimal fixture that exercises all variable terminal depths**

Use numeric IDs and the production relationship direction. Include:

```json
{
  "nodes": [
    {"id": 0, "labels": ["Root"], "properties": {"name": "测试产业", "level": 0}},
    {"id": 1, "labels": ["环节"], "properties": {"name": "一级甲", "level": 1}},
    {"id": 2, "labels": ["环节"], "properties": {"name": "一级乙", "level": 1}},
    {"id": 3, "labels": ["环节"], "properties": {"name": "一级丙", "level": 1}},
    {"id": 4, "labels": ["环节"], "properties": {"name": "一级丁", "level": 1}},
    {"id": 10, "labels": ["环节"], "properties": {"name": "二级甲", "level": 2}},
    {"id": 20, "labels": ["环节"], "properties": {"name": "三级叶子", "level": 3}},
    {"id": 21, "labels": ["环节"], "properties": {"name": "三级分支", "level": 3}},
    {"id": 22, "labels": ["环节"], "properties": {"name": "三级深分支", "level": 3}},
    {"id": 30, "labels": ["环节"], "properties": {"name": "四级叶子", "level": 4}},
    {"id": 31, "labels": ["环节"], "properties": {"name": "四级分支", "level": 4}},
    {"id": 40, "labels": ["环节"], "properties": {"name": "五级叶子", "level": 5}},
    {"id": 100, "labels": ["公司"], "properties": {"name": "甲公司", "category": "中央企业"}},
    {"id": 101, "labels": ["公司"], "properties": {"name": "乙公司", "category": "民营企业"}},
    {"id": 102, "labels": ["公司"], "properties": {"name": "丙公司", "category": "外资企业"}}
  ],
  "relationships": [
    {"source": 1, "target": 0, "type": "从属于"},
    {"source": 2, "target": 0, "type": "从属于"},
    {"source": 3, "target": 0, "type": "从属于"},
    {"source": 4, "target": 0, "type": "从属于"},
    {"source": 10, "target": 1, "type": "从属于"},
    {"source": 20, "target": 10, "type": "从属于"},
    {"source": 21, "target": 10, "type": "从属于"},
    {"source": 22, "target": 10, "type": "从属于"},
    {"source": 30, "target": 21, "type": "从属于", "seed": true},
    {"source": 31, "target": 22, "type": "从属于"},
    {"source": 40, "target": 31, "type": "从属于"},
    {"source": 100, "target": 20, "type": "参与环节"},
    {"source": 101, "target": 30, "type": "参与环节"},
    {"source": 102, "target": 40, "type": "参与环节"}
  ]
}
```

- [ ] **Step 2: Write failing Python contract tests**

Test the public interface before implementing it:

```python
from graph_hierarchy import GraphHierarchy

class GraphHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.graph = GraphHierarchy.from_path(FIXTURE_PATH)

    def test_terminal_segments_are_derived_from_children(self):
        self.assertEqual(self.graph.terminal_segment_ids(), [20, 30, 40])

    def test_path_supports_mixed_depths(self):
        self.assertEqual(self.graph.segment_path_ids(20), [1, 10, 20])
        self.assertEqual(self.graph.segment_path_ids(30), [1, 10, 21, 30])
        self.assertEqual(self.graph.segment_path_ids(40), [1, 10, 22, 31, 40])

    def test_descendants_include_every_supported_depth(self):
        self.assertEqual(self.graph.descendant_segment_ids(10), [20, 21, 22, 30, 31, 40])

    def test_direct_companies_are_deduplicated(self):
        self.assertEqual(self.graph.company_ids_for_segments([20, 30, 40]), [100, 101, 102])
```

- [ ] **Step 3: Write failing Node contract tests**

Require `static/js/modules/graph_hierarchy.js` and assert the same IDs and paths:

```javascript
const hierarchy = GraphHierarchy.create(graph);
assert.deepEqual(hierarchy.terminalSegmentIds(), [20, 30, 40]);
assert.deepEqual(hierarchy.segmentPathIds(30), [1, 10, 21, 30]);
assert.deepEqual(hierarchy.segmentPathIds(40), [1, 10, 22, 31, 40]);
assert.deepEqual(hierarchy.descendantSegmentIds(10), [20, 21, 22, 30, 31, 40]);
assert.deepEqual(hierarchy.companyIdsForSegments([20, 30, 40]), [100, 101, 102]);
```

- [ ] **Step 4: Run both tests and verify the missing modules fail**

Run:

```bash
python -m unittest tests.test_graph_hierarchy -v
node --test tests/js/test_graph_hierarchy.test.js
```

Expected: both fail because `graph_hierarchy.py` and `graph_hierarchy.js` do not exist.

- [ ] **Step 5: Commit the fixture and failing tests**

```bash
git add tests/fixtures/mixed_depth_graph.json tests/test_graph_hierarchy.py tests/js/test_graph_hierarchy.test.js
git commit -m "test: define dynamic graph hierarchy contract"
```

### Task 2: Implement Shared Hierarchy Indexes

**Files:**
- Create: `graph_hierarchy.py`
- Create: `static/js/modules/graph_hierarchy.js`
- Modify: `templates/base.html:158-165`
- Test: `tests/test_graph_hierarchy.py`
- Test: `tests/js/test_graph_hierarchy.test.js`

- [ ] **Step 1: Implement the Python index**

Expose this focused API:

```python
class GraphHierarchy:
    @classmethod
    def from_path(cls, path: Path) -> "GraphHierarchy": ...
    @classmethod
    def from_data(cls, data: dict) -> "GraphHierarchy": ...
    def terminal_segment_ids(self, under_id=None) -> list: ...
    def segment_path_ids(self, segment_id, include_root=False) -> list: ...
    def descendant_segment_ids(self, segment_id) -> list: ...
    def company_ids_for_segments(self, segment_ids) -> list: ...
    def node_summary(self, node_id) -> dict: ...
```

Build `nodes_by_id`, `segment_children_by_parent`, `segment_parent_by_child`, and `company_ids_by_segment` once in `__init__`. `terminal_segment_ids()` only considers segment nodes with normalized level 2 through 5, so an incomplete level-1 branch is not mistaken for a valid terminal segment. Sort results by numeric ID when possible and otherwise by string ID. Use a visited set in ancestor and descendant traversal so malformed cycles cannot hang a supported operation; do not add a separate validation framework.

- [ ] **Step 2: Implement the browser index with the same semantics**

Use a small UMD-style export so production sees `window.GraphHierarchy` and Node tests can `require()` it:

```javascript
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.GraphHierarchy = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    function create(data) { /* build maps once and return traversal methods */ }
    return { create };
});
```

- [ ] **Step 3: Load the browser helper before all graph views**

Add to `templates/base.html` before `chain_panorama.js`, `graph_sunburt.js`, and `graph_mindmap.js`:

```html
<script src="{{ STATIC_BASE }}js/modules/graph_hierarchy.js"></script>
```

- [ ] **Step 4: Run the focused contract tests**

```bash
python -m unittest tests.test_graph_hierarchy -v
node --test tests/js/test_graph_hierarchy.test.js
```

Expected: all hierarchy tests pass.

- [ ] **Step 5: Commit**

```bash
git add graph_hierarchy.py static/js/modules/graph_hierarchy.js templates/base.html tests/test_graph_hierarchy.py tests/js/test_graph_hierarchy.test.js
git commit -m "feat: add dynamic graph hierarchy indexes"
```

### Task 3: Migrate Report Graph Retrieval To Terminal Segments

**Files:**
- Create: `tests/test_graph_retriever_dynamic_hierarchy.py`
- Modify: `report_generation/graph_retriever.py`
- Modify: `report_generation/outline_agent.py:390-405`
- Modify: `report_generation/coordinator_agent.py:276-291,498-507`
- Modify: `report_generation/rewrite_agent.py:205-218,500-509`
- Modify: `static/js/modules/industry_report.js:985-995,1580-1595`
- Modify: `tests/js/test_industry_report_navigation.test.js`

- [ ] **Step 1: Write failing retrieval tests without calling the LLM**

Instantiate the graph class against the fixture and test:

```python
def test_candidate_rows_include_both_terminal_depths(self):
    graph = _AIGraph(FIXTURE_PATH)
    self.assertEqual(set(graph.terminal_segments), {20, 30, 40})
    self.assertIn("一级甲 > 二级甲 > 三级叶子", graph.terminal_prompt_rows()[0])
    self.assertTrue(any("一级甲 > 二级甲 > 三级分支 > 四级叶子" in row for row in graph.terminal_prompt_rows()))
    self.assertTrue(any("一级甲 > 二级甲 > 三级深分支 > 四级分支 > 五级叶子" in row for row in graph.terminal_prompt_rows()))

def test_terminal_evidence_keeps_complete_path_and_direct_company(self):
    graph = _AIGraph(FIXTURE_PATH)
    self.assertEqual(graph.segment_path(30)[-1]["id"], 30)
    self.assertEqual([item["id"] for item in graph.get_direct_entities(30)], [101])
```

Patch `_select_terminal_segments_with_llm` in one end-to-end test and assert the response writes:

```python
{
    "matched_segments": [{"id": 30, "name": "四级叶子", "level": 4, ...}],
    "evidence_blocks": [{
        "segment": {"id": 30, "name": "四级叶子", "level": 4},
        "segment_path": [...],
        "chain_path": "一级甲 > 二级甲 > 三级分支 > 四级叶子",
        "downward_entities": [{"id": 101, ...}]
    }]
}
```

- [ ] **Step 2: Run the retrieval test and verify it fails on fixed L3 behavior**

```bash
python -m unittest tests.test_graph_retriever_dynamic_hierarchy -v
```

Expected: FAIL because levels 4 and 5 are not candidates and the new keys are absent.

- [ ] **Step 3: Replace fixed-level retrieval with topology-based retrieval**

In `graph_retriever.py`:

- Compose `_AIGraph` with `GraphHierarchy`.
- Rename internal selection methods from `level3` to `terminal_segment`.
- Send terminal segment ID, level, and complete path to the LLM.
- Validate returned IDs against `terminal_segments`.
- Build `segment_path` and `chain_path` for any supported depth.
- Emit only `matched_segments` and `segment` in new responses.
- Change messages from “三级环节” to “末级环节”.

Do not change the public function name `retrieve_ai_graph`; it is an AI-report entry point, not a hierarchy name.

- [ ] **Step 4: Update Python response consumers atomically**

Change coordinator and rewrite normalization/error responses to:

```python
normalized["matched_segments"] = normalized.get("matched_segments") or []
```

Change outline evidence normalization to copy `segment` and `segment_path`, not `level3`.

- [ ] **Step 5: Keep one narrow historical evidence read fallback in the report UI**

New evidence uses `segment`; existing saved reports in `report_generation/history/` may still contain `level3`. Read both without writing both:

```javascript
function getIndustryReportGraphSegment(item) {
    return item?.segment || item?.level3 || null;
}
```

Use this helper for evidence title and graph-node ID. Add a Node test proving both old and new saved evidence links still open the correct node.

- [ ] **Step 6: Run focused Python and JavaScript tests**

```bash
python -m unittest tests.test_graph_retriever_dynamic_hierarchy -v
node --test tests/js/test_industry_report_navigation.test.js
```

Expected: all pass; generated responses contain no `matched_level3` or `level3` fields.

- [ ] **Step 7: Commit**

```bash
git add report_generation/graph_retriever.py report_generation/outline_agent.py report_generation/coordinator_agent.py report_generation/rewrite_agent.py static/js/modules/industry_report.js tests/test_graph_retriever_dynamic_hierarchy.py tests/js/test_industry_report_navigation.test.js
git commit -m "feat: retrieve terminal graph segments in reports"
```

### Task 4: Make Risk Analysis Traverse All Descendant Segments

**Files:**
- Create: `tests/test_risk_dynamic_hierarchy.py`
- Modify: `risk_inference/risk.py:16-174,260-360`

- [ ] **Step 1: Write failing mixed-depth risk tests**

```python
class RiskDynamicHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.engine = SpecializedChainRiskEngine(str(FIXTURE_PATH))

    def test_l2_analysis_counts_all_terminal_segments(self):
        result = self.engine.analyze_internal_composition(10)
        self.assertEqual(result["terminal_segment_count"], 3)
        self.assertEqual(set(result["terminal_segment_details"]), {"三级叶子", "四级叶子", "五级叶子"})

    def test_l2_analysis_counts_companies_below_level_four(self):
        result = self.engine.analyze_internal_composition(10)
        self.assertEqual(result["company_count"], 3)
        self.assertEqual(set(result["company_examples"]), {"甲公司", "乙公司", "丙公司"})
```

- [ ] **Step 2: Run and verify deeper-level companies are missing**

```bash
python -m unittest tests.test_risk_dynamic_hierarchy -v
```

Expected: FAIL because current traversal stops after L3.

- [ ] **Step 3: Replace the L2/L3 branch logic with hierarchy traversal**

Use `GraphHierarchy.descendant_segment_ids(l2_id)` and filter its terminal IDs. Aggregate direct company relationships for every descendant segment and retain existing product handling where product nodes exist. Rename result fields and report labels:

```python
stats = {
    "terminal_segment_count": len(terminal_ids),
    "terminal_segment_details": [...],
    "product_count": ...,
    "company_count": ...,
}
```

Keep `list_level2_nodes()` unchanged because level 2 remains the supported risk-analysis entry point.

- [ ] **Step 4: Run focused tests**

```bash
python -m unittest tests.test_risk_dynamic_hierarchy -v
```

Expected: terminal levels 3, 4, and 5 and all three companies are counted once.

- [ ] **Step 5: Commit**

```bash
git add risk_inference/risk.py tests/test_risk_dynamic_hierarchy.py
git commit -m "feat: traverse dynamic segments in risk analysis"
```

### Task 5: Match Imported Entities To Terminal Segment Paths

**Files:**
- Create: `tests/test_graph_import_dynamic_hierarchy.py`
- Modify: `graph_import_script.py:40-65,190-205,333-384,610-625`

- [ ] **Step 1: Write a failing import-dictionary test**

Extract a pure `build_terminal_segment_paths(graph_data)` function and test it directly, avoiding Excel and LLM initialization. Assert that its prompt context is a flat list of unambiguous terminal paths:

```python
self.assertEqual(
    importer.terminal_segment_paths,
    [
        {"id": 20, "level": 3, "path": "一级甲 > 二级甲 > 三级叶子"},
        {"id": 30, "level": 4, "path": "一级甲 > 二级甲 > 三级分支 > 四级叶子"},
        {"id": 40, "level": 5, "path": "一级甲 > 二级甲 > 三级深分支 > 四级分支 > 五级叶子"},
    ],
)
```

Also assert that internal nodes `21`, `22`, and `31` are not match candidates.

- [ ] **Step 2: Run and verify the current nested L1/L2/L3 map fails**

```bash
python -m unittest tests.test_graph_import_dynamic_hierarchy -v
```

Expected: FAIL because `segment_map` exposes only L3 names and includes the non-terminal L3 branch.

- [ ] **Step 3: Build terminal path context from `GraphHierarchy`**

Replace `_build_segment_skeleton_from_graph()` with `_build_terminal_segment_paths()`. Serialize records containing `id`, `level`, and `path` so duplicate leaf names remain distinguishable by their ancestors.

Change prompt language from:

```text
必须关联到字典中最具体的细分环节（Level 3）
```

to:

```text
必须关联到字典中的末级环节。末级环节可能位于第 2 至第 5 级；只能选择给定完整路径中的真实末级环节。
```

- [ ] **Step 4: Run the focused test**

```bash
python -m unittest tests.test_graph_import_dynamic_hierarchy -v
```

Expected: terminal paths at levels 3, 4, and 5 appear and internal segments 21, 22, and 31 do not.

- [ ] **Step 5: Commit**

```bash
git add graph_import_script.py tests/test_graph_import_dynamic_hierarchy.py
git commit -m "feat: match imports to terminal graph segments"
```

### Task 6: Flatten Terminal Paths In The Chain Panorama

**Files:**
- Create: `tests/js/test_chain_panorama_dynamic_hierarchy.test.js`
- Modify: `static/js/modules/chain_panorama.js:440-543,1680-1900,1958-2155,2180-2460`

- [ ] **Step 1: Expose pure panorama model functions for Node tests**

Export only the model-building functions when `module.exports` exists; do not export DOM rendering internals:

```javascript
if (typeof module === 'object' && module.exports) {
    module.exports = {
        buildChainStructure,
        buildTerminalRows,
        calcL1TypeStats,
        calcNodeCountStats,
    };
}
```

- [ ] **Step 2: Write failing terminal-row and four-branch tests**

Assert:

```javascript
const rows = panorama.buildTerminalRows(structure, 10);
assert.deepEqual(rows.map(row => row.segmentId), [20, 30, 40]);
assert.deepEqual(rows[1].pathNames, ['三级分支', '四级叶子']);
assert.deepEqual(rows[2].pathNames, ['三级深分支', '四级分支', '五级叶子']);
assert.deepEqual(rows.map(row => row.companyCount), [1, 1, 1]);

const stats = panorama.calcL1TypeStats(structure);
assert.equal(stats.length, 4);
assert.deepEqual(stats.map(item => item.name), ['一级甲', '一级乙', '一级丙', '一级丁']);
```

- [ ] **Step 3: Run and verify fixed L3/three-column behavior fails**

```bash
node --test tests/js/test_chain_panorama_dynamic_hierarchy.test.js
```

Expected: FAIL because only direct L3 children and three L1 statistic buckets exist.

- [ ] **Step 4: Build terminal rows under each L2**

Use `GraphHierarchy.terminalSegmentIds(l2Id)` and `segmentPathIds()` to return rows shaped as:

```javascript
{
    segmentId: 30,
    level: 4,
    pathIds: [21, 30],
    pathNames: ['三级分支', '四级叶子'],
    companies: [...]
}
```

Render the current “三级” column as “末级环节”. Display `三级分支 / 四级叶子` for a level-4 leaf and preserve exact-leaf company selection, ordering, and click behavior using `segmentId`.

- [ ] **Step 5: Make L1 statistics array-based**

Replace `{upstream, midstream, downstream}` with:

```javascript
[
    { id: 1, name: '一级甲', companyTypeStats: {...}, levelCounts: {2: 1, 3: 2, 4: 1} },
    ...
]
```

Update statistic-card rendering loops to consume the array. Overall totals must include every L1 branch and every descendant level.

- [ ] **Step 6: Migrate saved panorama settings narrowly**

Read existing `l3` and `l3_ratio` keys when `leaf` and `leaf_ratio` are absent, then write only the new keys. Do not add a version field or migration framework.

- [ ] **Step 7: Run the focused Node test**

```bash
node --test tests/js/test_chain_panorama_dynamic_hierarchy.test.js
```

Expected: three terminal rows render in the model, level-4 and level-5 company counts are present, and four L1 statistic entries are returned.

- [ ] **Step 8: Commit**

```bash
git add static/js/modules/chain_panorama.js tests/js/test_chain_panorama_dynamic_hierarchy.test.js
git commit -m "feat: show terminal paths in chain panorama"
```

### Task 7: Make Sunburst And Mind Map Level Presentation Dynamic

**Files:**
- Create: `tests/js/test_graph_dynamic_legends.test.js`
- Modify: `static/js/modules/graph_sunburt.js:448-735,2490-2585`
- Modify: `static/js/modules/graph_mindmap.js:283-370,508-526`

- [ ] **Step 1: Write failing legend tests**

Load both scripts in a minimal VM and assert the fixture produces counts for levels 1 through 4:

```javascript
assert.deepEqual(countSegmentLevels(graph.nodes), [
    { level: 1, label: '一级环节', count: 4 },
    { level: 2, label: '二级环节', count: 1 },
    { level: 3, label: '三级环节', count: 3 },
    { level: 4, label: '四级环节', count: 2 },
    { level: 5, label: '五级环节', count: 1 },
]);
```

Also assert levels 3, 4, and 5 receive distinct colors.

- [ ] **Step 2: Run and verify levels 4 and 5 are currently grouped into level 3**

```bash
node --test tests/js/test_graph_dynamic_legends.test.js
```

Expected: FAIL because the current legend has only three segment buckets.

- [ ] **Step 3: Add pure dynamic-level presentation helpers**

Use fixed accessible colors for levels 0 through 5 rather than generating viewport-dependent styles:

```javascript
const SEGMENT_LEVEL_COLORS = {
    0: '#364A67',
    1: '#456DA1',
    2: '#6D90BB',
    3: '#8FAACE',
    4: '#AEC4DF',
    5: '#CBD9EA',
};
```

Generate legend rows from levels actually present. Keep company category colors unchanged.

- [ ] **Step 4: Reuse `GraphHierarchy` for parent/child construction**

Replace duplicated relationship indexing where it is only used for segment hierarchy. Keep view-specific company/product rendering local to each module.

- [ ] **Step 5: Run focused tests**

```bash
node --test tests/js/test_graph_dynamic_legends.test.js tests/js/test_graph_hierarchy.test.js
```

Expected: levels 4 and 5 are counted and colored independently; recursive tree rendering remains intact.

- [ ] **Step 6: Commit**

```bash
git add static/js/modules/graph_sunburt.js static/js/modules/graph_mindmap.js tests/js/test_graph_dynamic_legends.test.js
git commit -m "feat: render dynamic graph segment levels"
```

### Task 8: Update Documentation And Run Repository Regression Tests

**Files:**
- Modify: `README.md`
- Modify: `MODULES.md`
- Modify: `产业报告项目交接文档.md`
- Verify: all files modified in Tasks 1-7

- [ ] **Step 1: Update the graph contract documentation**

Replace statements that define the stable skeleton as `level=1/2/3` with:

```text
产业链环节从一级开始，至少包含二级，可按行业数据延伸到三级、四级或五级。
“从属于”关系定义环节父子关系；没有下级环节的节点是末级环节，企业和其他业务实体挂接到末级环节。
```

Update report retrieval, risk, import, and panorama sections to use “末级环节” and “完整路径”. Explicitly state that the current report entry point remains AI-only.

- [ ] **Step 2: Scan for stale fixed-depth logic**

Run:

```bash
rg -n --glob '!*.min.js' "matched_level3|level3_nodes|三级环节清单|最具体的细分环节（Level 3）|i < 3" report_generation risk_inference graph_import_script.py static/js/modules README.md MODULES.md 产业报告项目交接文档.md
```

Expected: no executable fixed-depth matches remain. Historical read fallback `item.level3` and comments explaining saved-data compatibility may remain.

- [ ] **Step 3: Run all focused dynamic-hierarchy tests**

```bash
python -m unittest \
  tests.test_graph_hierarchy \
  tests.test_graph_retriever_dynamic_hierarchy \
  tests.test_risk_dynamic_hierarchy \
  tests.test_graph_import_dynamic_hierarchy -v

node --test \
  tests/js/test_graph_hierarchy.test.js \
  tests/js/test_chain_panorama_dynamic_hierarchy.test.js \
  tests/js/test_graph_dynamic_legends.test.js \
  tests/js/test_industry_report_navigation.test.js
```

Expected: all focused tests pass.

- [ ] **Step 4: Run the existing full test suites**

```bash
python -m unittest discover -s tests -v
node --test tests/js/*.test.js
```

Expected: all existing tests pass. A failure here changes the next action: fix the compatibility regression before using real graph data.

- [ ] **Step 5: Run a read-only acceptance check against the attached sample**

Use the hierarchy helper without copying or modifying the attachment:

```bash
python -c "from pathlib import Path; from graph_hierarchy import GraphHierarchy; p=Path('/Users/livictor/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_x6nq1tyaf8rs22_06d7/temp/RWTemp/2026-08/9e9abba1a90747e062f88534729d5fba/graph_data.json'); g=GraphHierarchy.from_path(p); print(len(g.terminal_segment_ids()), len(g.company_ids_for_segments(g.terminal_segment_ids())))"
```

Expected: `113 399`. A different result means the shared hierarchy semantics still omit or duplicate real sample data and must be fixed before browser testing.

- [ ] **Step 6: Start the app and perform browser acceptance checks**

Start using the project environment:

```bash
python backend_server.py
```

Verify with a test-only data selection or a temporary in-memory fetch stub, without overwriting AI data:

- Knowledge graph, sunburst, and mind map show the complete level-4 path.
- Panorama displays both level-3 and level-4 terminal rows under the same L2.
- Level-4 companies appear in representative-company and company-type totals.
- Four level-1 branches render without dropping the fourth branch.
- Report evidence opens the selected terminal node in the graph view.

- [ ] **Step 7: Commit documentation and final regression adjustments**

```bash
git add README.md MODULES.md 产业报告项目交接文档.md
git commit -m "docs: document dynamic industry graph hierarchy"
```

## Release Gate

The dynamic hierarchy work is complete only when all of these are true:

- The mixed-depth fixture passes Python and JavaScript contract tests.
- The attached sample reports exactly 113 terminal segments and 399 unique companies.
- No report, risk, import, or panorama operation relies on `level == 3` to mean terminal.
- Existing AI graph behavior remains unchanged under the full regression suite.
- Existing saved report evidence using `level3` still opens the correct node.
- Production AI data has not been replaced.

After this plan is complete, onboarding新能源汽车 is a separate, smaller plan covering its data directory, industry selector, data-source mappings, policy availability, and report support decision.

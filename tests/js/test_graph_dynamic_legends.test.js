const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const FIXTURE_PATH = path.resolve(__dirname, '../fixtures/mixed_depth_graph.json');

function loadScript(fileName) {
    const noop = () => {};
    const element = () => ({
        style: {},
        classList: { add: noop, remove: noop, contains: () => false },
        appendChild: noop,
        remove: noop,
        setAttribute: noop,
        addEventListener: noop,
        querySelector: () => null,
        querySelectorAll: () => [],
    });
    const document = {
        addEventListener: noop,
        removeEventListener: noop,
        getElementById: () => null,
        querySelector: () => null,
        querySelectorAll: () => [],
        createElement: element,
        body: element(),
    };
    const context = {
        console,
        document,
        window: { currentIndustry: 'ai', addEventListener: noop, removeEventListener: noop },
        setTimeout,
        clearTimeout,
        URL,
        Math,
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../static/js/modules', fileName), 'utf8'), context, { filename: fileName });
    return context;
}

test('dynamic legend counts include every segment level', () => {
    const graph = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));
    const sunburst = loadScript('graph_sunburt.js');
    const levels = Array.from(sunburst.countSegmentLevels(graph.nodes), item => ({
        level: item.level,
        label: item.label,
        count: item.count,
    }));
    assert.deepEqual(levels, [
        { level: 1, label: '一级环节', count: 4 },
        { level: 2, label: '二级环节', count: 1 },
        { level: 3, label: '三级环节', count: 3 },
        { level: 4, label: '四级环节', count: 2 },
        { level: 5, label: '五级环节', count: 1 },
    ]);
    assert.notEqual(sunburst.segmentLevelColor(3), sunburst.segmentLevelColor(4));
    assert.notEqual(sunburst.segmentLevelColor(4), sunburst.segmentLevelColor(5));
});

test('mind map level colors remain distinct for deeper branches', () => {
    const mindmap = loadScript('graph_mindmap.js');
    assert.notEqual(mindmap.mindmapSegmentLevelColor(3), mindmap.mindmapSegmentLevelColor(4));
    assert.notEqual(mindmap.mindmapSegmentLevelColor(4), mindmap.mindmapSegmentLevelColor(5));
});

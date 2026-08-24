(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.GraphHierarchy = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    const SEGMENT_LABEL = '环节';
    const COMPANY_LABEL = '公司';
    const BELONGS_TO = '从属于';
    const PARTICIPATES_IN = '参与环节';

    function key(value) {
        return String(value);
    }

    function compareIds(left, right) {
        const leftNumber = Number(left);
        const rightNumber = Number(right);
        if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
            return leftNumber - rightNumber;
        }
        return key(left).localeCompare(key(right), 'zh-CN');
    }

    function nodeLevel(node) {
        const value = node && node.properties ? node.properties.level : null;
        const level = Number(value);
        return Number.isFinite(level) ? level : null;
    }

    function nodeName(node) {
        return String((node && node.properties && node.properties.name) || '').trim();
    }

    function create(data) {
        const nodes = Array.isArray(data && data.nodes) ? data.nodes : [];
        const relationships = Array.isArray(data && data.relationships) ? data.relationships : [];
        const nodesByKey = new Map();
        const segmentChildren = new Map();
        const parentBySegment = new Map();
        const companiesBySegment = new Map();

        nodes.forEach(node => {
            if (!node || node.id === undefined || node.id === null) return;
            nodesByKey.set(key(node.id), node);
        });

        function nodeFor(id) {
            return nodesByKey.get(key(id)) || null;
        }

        function isSegment(node) {
            return Boolean(node && Array.isArray(node.labels) && node.labels.includes(SEGMENT_LABEL));
        }

        function isCompany(node) {
            return Boolean(node && Array.isArray(node.labels) && node.labels.includes(COMPANY_LABEL));
        }

        function isRoot(node) {
            return Boolean(node && Array.isArray(node.labels) && node.labels.includes('Root'));
        }

        function push(map, mapKey, value) {
            if (!map.has(mapKey)) map.set(mapKey, []);
            const values = map.get(mapKey);
            if (!values.some(item => key(item) === key(value))) values.push(value);
        }

        relationships.forEach(rel => {
            if (!rel) return;
            const source = rel.source;
            const target = rel.target;
            const sourceNode = nodeFor(source);
            const targetNode = nodeFor(target);
            if (rel.type === BELONGS_TO && isSegment(sourceNode) && (isSegment(targetNode) || isRoot(targetNode))) {
                push(segmentChildren, key(target), source);
                parentBySegment.set(key(source), target);
            }
            if (rel.type === PARTICIPATES_IN && isCompany(sourceNode) && isSegment(targetNode)) {
                push(companiesBySegment, key(target), source);
            }
        });

        function sorted(values) {
            return values.slice().sort(compareIds);
        }

        function segmentIds() {
            return sorted(nodes
                .filter(node => isSegment(node))
                .map(node => node.id));
        }

        function isValidTerminal(node) {
            const level = nodeLevel(node);
            return isSegment(node) && level !== null && level >= 2 && level <= 5
                && !(segmentChildren.get(key(node.id)) || []).length;
        }

        function descendantSegmentIds(segmentId) {
            const result = [];
            const pending = (segmentChildren.get(key(segmentId)) || []).slice();
            const visited = new Set();
            while (pending.length) {
                const current = pending.shift();
                const currentKey = key(current);
                if (visited.has(currentKey)) continue;
                visited.add(currentKey);
                result.push(current);
                (segmentChildren.get(currentKey) || []).forEach(child => pending.push(child));
            }
            return sorted(result);
        }

        function terminalSegmentIds(underId) {
            const candidates = underId === undefined || underId === null
                ? segmentIds()
                : descendantSegmentIds(underId);
            return sorted(candidates.filter(id => isValidTerminal(nodeFor(id))));
        }

        function segmentPathIds(segmentId, includeRoot) {
            const path = [];
            const visited = new Set();
            let current = segmentId;
            while (current !== undefined && current !== null && !visited.has(key(current))) {
                const currentNode = nodeFor(current);
                if (!currentNode || !isSegment(currentNode)) break;
                visited.add(key(current));
                path.unshift(current);
                current = parentBySegment.get(key(current));
            }
            if (!includeRoot && path.length && nodeLevel(nodeFor(path[0])) === 0) path.shift();
            return path;
        }

        function companyIdsForSegments(segmentIdsToRead) {
            const result = [];
            const seen = new Set();
            (segmentIdsToRead || []).forEach(segmentId => {
                (companiesBySegment.get(key(segmentId)) || []).forEach(companyId => {
                    if (!seen.has(key(companyId))) {
                        seen.add(key(companyId));
                        result.push(companyId);
                    }
                });
            });
            return sorted(result);
        }

        return {
            nodeFor,
            segmentNodeIds: segmentIds,
            terminalSegmentIds,
            segmentPathIds,
            descendantSegmentIds,
            companyIdsForSegments,
            nodeSummary(id) {
                const node = nodeFor(id) || {};
                return {
                    id,
                    name: nodeName(node),
                    level: nodeLevel(node),
                    labels: Array.isArray(node.labels) ? node.labels.slice() : [],
                };
            },
        };
    }

    return { create };
});

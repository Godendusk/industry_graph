/**
 * 人工智能产业链技术全景图：从图谱 JSON 聚合上/中/下游二级环节、企业类型占比与代表企业。
 */

/** 列设置缓存（默认全部开启），首次使用前调用 fetchChainColumnSettings() 填充 */
let chainColumnSettings = {
    l2: true,
    l2_ratio: true,
    l3: true,
    l3_ratio: true,
    representative: true
};

/** 代表企业选择缓存（从服务器加载） */
let chainRepPicksCache = {};
/** 代表企业排序缓存（从服务器加载） */
let chainRepSortCache = {};

/** 从后端拉取列设置，失败时保持默认值 */
async function fetchChainColumnSettings() {
    try {
        const base = typeof API_BASE !== 'undefined' ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
        const resp = await fetch(`${base}/api/settings`, { cache: 'no-cache' });
        if (!resp.ok) return;
        const json = await resp.json();
        if (json.status === 'success' && json.data) {
            if (json.data.chain_panorama_column) {
                chainColumnSettings = json.data.chain_panorama_column;
            }
            if (json.data.chain_panorama_rep_picks) {
                chainRepPicksCache = json.data.chain_panorama_rep_picks;
            }
            if (json.data.chain_panorama_rep_sort) {
                chainRepSortCache = json.data.chain_panorama_rep_sort;
            }
        }
    } catch (e) {
        console.warn('获取列设置失败，使用默认值:', e.message);
    }
}

/** 将当前列设置写回后端，成功后刷新全景图 */
async function saveChainColumnSettings(settings) {
    try {
        const base = typeof API_BASE !== 'undefined' ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
        const resp = await fetch(`${base}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chain_panorama_column: settings })
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        chainColumnSettings = settings;
        await reloadChainPanorama();
        return true;
    } catch (e) {
        console.error('保存列设置失败:', e.message);
        alert('保存列设置失败：' + e.message);
        return false;
    }
}

/** 根据当前产业链返回企业类型排序。人工智能：外资优先；其他保持不变。 */
function getChainTypeOrder() {
    const ind = String(window.currentIndustry || 'ai');
    if (ind === 'ai') {
        return ['外资', '央企', '其他国资', '民企'];
    }
    return ['央企', '其他国资', '民企', '外资'];
}
let CHAIN_TYPE_ORDER = getChainTypeOrder();
const CHAIN_TYPE_LABELS = {
    央企: '中央企业',
    其他国资: '其他国资',
    民企: '民营企业',
    外资: '外资企业(含港澳台及国际企业)'
};
const CHAIN_TYPE_COLORS = {
    /** 与知识图谱旭日图 graph_sunburt.js getColor() 一致 */
    // 央企: '#FF0000',
    // // 其他国资: '#FFB3B3',
    // 其他国资: '#F791CE',
    // 民企: '#5470c6',
    // // 外资: '#91cc75'
    // 外资: '#45c348'

    央企: '#F66F6A',
    其他国资: '#FA9841',
    民企: '#5E7CE0',
    外资: '#3AC295'
};
const CHAIN_UNCATEGORIZED_COLOR = '#9ca3af';
const CHAIN_UNCATEGORIZED_LABEL = '未分类';

/** 大屏列数 → 完整 Tailwind 类名（供 JIT 扫描，勿模板拼接） */
function chainPanoramaLgGridColsClass(columnCount) {
    const n = Math.max(1, Math.min(columnCount, 12));
    const map = {
        1: 'lg:grid-cols-1',
        2: 'lg:grid-cols-2',
        3: 'lg:grid-cols-3',
        4: 'lg:grid-cols-4',
        5: 'lg:grid-cols-5',
        6: 'lg:grid-cols-6',
        7: 'lg:grid-cols-7',
        8: 'lg:grid-cols-8',
        9: 'lg:grid-cols-9',
        10: 'lg:grid-cols-10',
        11: 'lg:grid-cols-11',
        12: 'lg:grid-cols-12'
    };
    return map[n] || 'lg:grid-cols-3';
}

/** 表格正文统一 12px */
const CHAIN_TABLE_TEXT = 'text-[12px]';
/** 三级列、代表企业列（含企业名链接）统一文字色 */
const CHAIN_L3_REP_TEXT_CLASS = 'text-[#1E40AF]';

/** 三列表格（上/中/下游列序）统一文字色：紫 / 青绿 / 橙 */
function chainPanoramaTableTextClass(columnIndex) {
    const i = Math.min(Math.max(Number(columnIndex) || 0, 0), 2);
    if (i === 0) return 'text-[#6A4EBA]';
    if (i === 1) return 'text-[#309995]';
    return 'text-[#EF731C]';
}

/** 三列表格（上/中/下游列序）对应颜色值：紫 / 青绿 / 橙，用于图例图标染色 */
function chainPanoramaColumnColor(columnIndex) {
    const i = Math.min(Math.max(Number(columnIndex) || 0, 0), 2);
    if (i === 0) return '#6A4EBA';
    if (i === 1) return '#309995';
    return '#EF731C';
}

/** 代表企业标签浅色边框（与文字同色系，更浅） */
const CHAIN_REP_BORDER_COLORS = {
    央企: '#FFCCCC',
    其他国资: '#FFE0E0',
    民企: '#B3C6ED',
    外资: '#C8E6B3'
};
const CHAIN_REP_BORDER_UNCATEGORIZED = '#D1D5DB';

/** 根据企业类型返回对应图例颜色（用于代表企业标签文字色） */
function chainPanoramaRepTextColor(node) {
    const cat = normalizeCategory(node && node.properties ? node.properties : {});
    if (cat && CHAIN_TYPE_COLORS[cat]) {
        return CHAIN_TYPE_COLORS[cat];
    }
    return CHAIN_UNCATEGORIZED_COLOR;
}

/** 根据企业类型返回对应浅色边框（与文字同色系） */
function chainPanoramaRepBorderColor(node) {
    const cat = normalizeCategory(node && node.properties ? node.properties : {});
    if (cat && CHAIN_REP_BORDER_COLORS[cat]) {
        return CHAIN_REP_BORDER_COLORS[cat];
    }
    return CHAIN_REP_BORDER_UNCATEGORIZED;
}

/** 代表企业列内可点击企业标签（样式不含颜色，颜色由内联 style 动态设置；缩小内边距以便同行容纳更多标签） */
function chainPanoramaRepButtonClasses() {
    return `chain-rep-company inline-flex items-center rounded-sm border px-1 py-0.5 ${CHAIN_TABLE_TEXT} whitespace-nowrap select-none cursor-pointer hover:brightness-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1E40AF]/40`;
}

/** 代表企业容器内联 CSS（flex 布局，允许换行但在标签级别不折行；最小间距以便同行容纳更多标签） */
function chainPanoramaRepContainerStyle() {
    return 'display:flex;flex-wrap:wrap;align-items:center;gap:2px';
}
/** 图例下方「三级环节」详情卡片内环形图边长 */
const CHAIN_DETAIL_DONUT_PX = 112;

let chainPanoramaCharts = [];
let chainRepPickerHost = null;
window.isChainPanoramaFullscreen = false;

/** 全屏产业链时用于随视口变化重算高度（含移动端地址栏） */
function chainPanoramaApplyFullscreenLayout() {
    if (!window.isChainPanoramaFullscreen) return;
    const chainContainer = document.getElementById('chain-panorama-container');
    const mainContent = document.querySelector('main');
    const vv = window.visualViewport;
    const h = vv ? vv.height : window.innerHeight;
    const top = vv ? vv.offsetTop : 0;
    if (chainContainer) {
        chainContainer.style.position = 'fixed';
        chainContainer.style.zIndex = '9999';
        chainContainer.style.background = '#f3f4f6';
        chainContainer.style.display = 'flex';
        chainContainer.style.flexDirection = 'column';
        chainContainer.style.overflow = 'hidden';
        chainContainer.style.boxSizing = 'border-box';
        chainContainer.style.left = '0';
        chainContainer.style.right = '0';
        chainContainer.style.width = '100%';
        chainContainer.style.maxWidth = '100vw';
        chainContainer.style.top = `${top}px`;
        chainContainer.style.height = `${h}px`;
        chainContainer.style.maxHeight = `${h}px`;
    }
    if (mainContent) {
        mainContent.style.height = `${h}px`;
    }
    chainPanoramaCharts.forEach((c) => {
        try {
            c.resize();
        } catch (e) {
            /* ignore */
        }
    });
    if (typeof syncChainPanoramaColumnTableHeights === 'function') {
        syncChainPanoramaColumnTableHeights();
    }
}

function chainPanoramaFullscreenViewportHandler() {
    chainPanoramaApplyFullscreenLayout();
}

function chainDataSourceUrl() {
    if (typeof getIndustryDataSource === 'function') {
        return getIndustryDataSource();
    }
    const ind = window.currentIndustry || 'ai';
    const base = typeof API_BASE !== 'undefined' ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
    if (ind === 'embodied') {
        return `${base}/static/data/embodied/graph_data.json`;
    }
    if (ind === 'low_altitude') {
        return `${base}/static/data/low_altitude/graph_data.json`;
    }
    if (ind === 'sea') {
        return `${base}/static/data/sea/graph_data.json`;
    }
    if (ind === 'quantum') {
        return `${base}/static/data/quantum/graph_data.json`;
    }
    if (ind === 'biology') {
        return `${base}/static/data/biology/graph_data.json`;
    }
    if (ind === 'brain') {
        return `${base}/static/data/brain/graph_data.json`;
    }
    if (ind === 'material') {
        return `${base}/static/data/material/graph_data.json`;
    }
    return `${base}/static/data/ai/graph_data.json`;
}

function isCompanyNode(node) {
    const labels = node.labels || [];
    return labels.includes('公司');
}

function isSegmentNode(node) {
    const labels = node.labels || [];
    return labels.includes('环节');
}

function isProductNode(node) {
    const labels = node.labels || [];
    return labels.includes('产品');
}

function getLevel(node) {
    const lv = node.properties && node.properties.level;
    if (lv === undefined || lv === null) return null;
    const n = Number(lv);
    return Number.isFinite(n) ? n : null;
}

function normalizeCategory(properties) {
    if (!properties) return null;
    const cat = properties.category || '';
    const reason = String(properties.category_reason || '') + String(properties.name || '');
    if (cat === '中央企业') return '央企';
    if (cat === '其他国资') return '其他国资';
    if (cat === '国有企业') return '其他国资';
    if (cat === '民营企业') return '民企';
    if (cat === '外资企业') return '外资';
    if (cat === '央企/国企') {
        if (/国务院国资委|中央企业|央企\b|国资委.*中央|中央直接管理.*骨干|中央直接管理的国有重要骨干企业/.test(reason)) {
            return '央企';
        }
        return '其他国资';
    }
    return null;
}

function buildParentMap(links) {
    const parent = Object.create(null);
    for (let i = 0; i < links.length; i++) {
        const r = links[i];
        if (r && r.type === '从属于') {
            parent[r.source] = r.target;
        }
    }
    return parent;
}

function segmentUnderL2(segmentId, l2Id, parent) {
    let cur = segmentId;
    for (let g = 0; g < 64 && cur !== undefined && cur !== null; g++) {
        if (cur === l2Id) return true;
        cur = parent[cur];
    }
    return false;
}

function findL1ForL2(l2Id, parent, nodeById) {
    let cur = parent[l2Id];
    for (let g = 0; g < 64 && cur !== undefined && cur !== null; g++) {
        const n = nodeById.get(cur);
        if (n && isSegmentNode(n) && getLevel(n) === 1) {
            return cur;
        }
        cur = parent[cur];
    }
    return null;
}

/**
 * 与原型一致：横幅主标题 + 括号副标题（非表格表头）。
 * sectionNum 为 1/2/3（按列顺序）。
 */
function columnMeta(l1Name, sectionNum) {
    if(sectionNum === 1)
        return {
            sectionNum,
            shortTitle: l1Name,
            subtitle: '',
            theme: 'blue'
        };
    if(sectionNum === 2)
        return {
            sectionNum,
            shortTitle: l1Name,
            subtitle: '',
            theme: 'green'
        };
    if(sectionNum === 3)
        return {
            sectionNum,
            shortTitle: l1Name,
            subtitle: '',
            theme: 'orange'
        };
        

    const name = l1Name || '';
    if (/上游|基础/.test(name)) {
        return {
            sectionNum,
            shortTitle: '上游 · 基础设施层',
            subtitle: '底层硬件与基础设施',
            theme: 'blue'
        };
    }
    if (/中游|技术/.test(name)) {
        return {
            sectionNum,
            shortTitle: '中游 · 技术层',
            subtitle: '核心技术与平台',
            theme: 'green'
        };
    }
    if (/下游|应用/.test(name)) {
        return {
            sectionNum,
            shortTitle: '下游 · 应用层',
            subtitle: '行业应用与解决方案',
            theme: 'orange'
        };
    }
    return {
        sectionNum,
        shortTitle: name || '产业链',
        subtitle: '',
        theme: 'gray'
    };
}

function bannerClasses(theme) {
    if (theme === 'blue') return 'bg-[#6A4EBA] text-white';
    if (theme === 'green') return 'bg-[#309995] text-white';
    if (theme === 'orange') return 'bg-[#EF731C] text-white';
    return 'bg-gray-600 text-white';
}

/**
 * 尝试获取二级环节对应的图例图标路径。
 * 图标位于 static/images/industry/，命名格式：
 *   - 人工智能：AI_{二级环节名称}.png
 *   - 低空经济：LOW_ALTITUDE_{二级环节名称}.png
 * 若图标文件不存在（404），mask-image 回退，元素显示为实心彩色方块。
 */
function chainL2IconUrl(l2Name) {
    const ind = String(window.currentIndustry || 'ai');
    let prefix = null;
    if (ind === 'ai') prefix = 'AI';
    else if (ind === 'low_altitude') prefix = 'LOW_ALTITUDE';
    if (!prefix) return null;
    const filename = `${prefix}_${l2Name}.png`;
    // const base = typeof STATIC_BASE !== 'undefined' ? STATIC_BASE : '/static';
    return `static/images/industry/${encodeURIComponent(filename)}`;
}

/** 二级环节：编号与名称；在文字上方加入与列主题色一致的图例图标（透明PNG通过mask-image染色） */
function buildL2CellInnerHtml(columnIndex, l2No, l2Name) {
    const tc = chainPanoramaTableTextClass(columnIndex);
    const colColor = chainPanoramaColumnColor(columnIndex);
    const iconUrl = chainL2IconUrl(l2Name);

    /** 图例图标：使用 CSS mask-image 将透明PNG染色为列主题色 */
    let iconHtml = '';
    if (iconUrl) {
        const iconSize = '24';
        // inline style：以 mask-image 让透明PNG的轮廓显示为列主题色
        // 若PNG不存在，mask-image 回退为空，元素显示为实心彩色方块（作为通用图例标识）
        const iconStyle = `display:inline-block;width:${iconSize}px;height:${iconSize}px;background-color:${colColor};-webkit-mask-image:url('${iconUrl}');mask-image:url('${iconUrl}');-webkit-mask-size:contain;mask-size:contain;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;-webkit-mask-position:center;mask-position:center;flex-shrink:0`;
        iconHtml = `<span style="${iconStyle}" aria-hidden="true"></span>`;
    }

    return `<span class="inline-flex flex-col items-center justify-center gap-1.5 ${tc} mx-auto max-w-[11rem] text-center leading-tight font-bold">
            ${iconHtml}
            <span class="${CHAIN_TABLE_TEXT} font-bold tracking-tight">${escapeHtml(l2No)}</span>
            <span class="${CHAIN_TABLE_TEXT} font-bold">${escapeHtml(l2Name)}</span>
    </span>`;
}

function wrapChartCell(chartDiv) {
    const wrap = document.createElement('div');
    wrap.className = 'flex items-center justify-center';
    wrap.style.maxWidth = '100%';
    wrap.appendChild(chartDiv);
    return wrap;
}

function directSegmentChildren(l2Id, links, nodeById) {
    const ids = [];
    for (let i = 0; i < links.length; i++) {
        const r = links[i];
        if (r && r.type === '从属于' && r.target === l2Id) {
            const n = nodeById.get(r.source);
            if (n && isSegmentNode(n)) {
                ids.push(r.source);
            }
        }
    }
    ids.sort((a, b) => a - b);
    return ids.map((id) => nodeById.get(id)).filter(Boolean);
}

/**
 * 企业 → 环节：支持 (1) 人工智能：`公司 -参与环节-> 环节`；
 * (2) 具身智能/低空经济：`公司 -拥有产品-> 产品 -产品对应环节-> 环节`。
 */
function buildCompanyTargets(links, nodeById) {
    const map = new Map();
    function pushTarget(cid, tgt) {
        if (!map.has(cid)) map.set(cid, []);
        const arr = map.get(cid);
        if (arr.indexOf(tgt) === -1) arr.push(tgt);
    }

    const companyToProducts = new Map();
    const productToSegments = new Map();

    for (let i = 0; i < links.length; i++) {
        const r = links[i];
        if (!r) continue;
        const srcNode = nodeById.get(r.source);
        const tgtNode = nodeById.get(r.target);

        if (r.type === '参与环节' && srcNode && isCompanyNode(srcNode) && tgtNode && isSegmentNode(tgtNode)) {
            pushTarget(r.source, r.target);
            continue;
        }

        if (r.type === '拥有产品' && srcNode && tgtNode) {
            if (isCompanyNode(srcNode) && isProductNode(tgtNode)) {
                if (!companyToProducts.has(r.source)) companyToProducts.set(r.source, []);
                companyToProducts.get(r.source).push(r.target);
            } else if (isProductNode(srcNode) && isCompanyNode(tgtNode)) {
                if (!companyToProducts.has(r.target)) companyToProducts.set(r.target, []);
                companyToProducts.get(r.target).push(r.source);
            }
            continue;
        }

        if (r.type === '产品对应环节' && srcNode && isProductNode(srcNode) && tgtNode && isSegmentNode(tgtNode)) {
            if (!productToSegments.has(r.source)) productToSegments.set(r.source, []);
            productToSegments.get(r.source).push(r.target);
        }
    }

    companyToProducts.forEach((productIds, cid) => {
        for (let p = 0; p < productIds.length; p++) {
            const segs = productToSegments.get(productIds[p]);
            if (!segs) continue;
            for (let s = 0; s < segs.length; s++) {
                pushTarget(cid, segs[s]);
            }
        }
    });

    return map;
}

function companiesForL2(l2Id, parent, companyTargets, nodeById) {
    const out = new Map();
    companyTargets.forEach((targets, cid) => {
        for (let t = 0; t < targets.length; t++) {
            const tid = targets[t];
            if (tid === l2Id || segmentUnderL2(tid, l2Id, parent)) {
                const node = nodeById.get(cid);
                if (node) out.set(cid, node);
                break;
            }
        }
    });
    return Array.from(out.values());
}

/** 仅参与指定环节（通常为三级）的企业，用于与三级环节一一对应 */
function companiesForSegmentExact(segmentId, companyTargets, nodeById) {
    const out = new Map();
    companyTargets.forEach((targets, cid) => {
        if (!targets || targets.length === 0) return;
        let hit = false;
        for (let t = 0; t < targets.length; t++) {
            if (targets[t] === segmentId) {
                hit = true;
                break;
            }
        }
        if (!hit) return;
        const node = nodeById.get(cid);
        if (node && isCompanyNode(node)) out.set(cid, node);
    });
    return Array.from(out.values());
}

/**
 * 按四类统计家数；total 为本环节参与企业总数，uncategorized 为无法归入四类的企业数（用于占比分母与环形图补全）。
 */
function countByType(companies) {
    const c = { 央企: 0, 其他国资: 0, 民企: 0, 外资: 0 };
    for (let i = 0; i < companies.length; i++) {
        const k = normalizeCategory(companies[i].properties || {});
        if (k && c[k] !== undefined) c[k] += 1;
    }
    const sumCategorized = c.央企 + c.其他国资 + c.民企 + c.外资;
    const total = companies.length;
    const uncategorized = Math.max(0, total - sumCategorized);
    return { ...c, total, uncategorized };
}

/**
 * 根据 countByType 的返回值生成企业类型占比条 HTML。
 * 无企业数据时返回空字符串。分母取已分类企业总数，确保色块填满 100%。
 * 色块按固定顺序（央企→其他国资→民企→外资）排列，仅显示百分比，不显示企业类型名。
 */
function formatTypeRatioBar(counts, barHeight) {
    const categorizedTotal = counts.total - (counts.uncategorized || 0);
    if (categorizedTotal <= 0) return '';
    const typeOrder = ['央企', '其他国资', '民企', '外资'];
    const parts = [];
    for (let i = 0; i < typeOrder.length; i++) {
        const k = typeOrder[i];
        const n = counts[k] || 0;
        if (n <= 0) continue;
        const pct = (n / categorizedTotal * 100).toFixed(1);
        const col = CHAIN_TYPE_COLORS[k];
        if (!col) continue;
        const typeLabel = CHAIN_TYPE_LABELS[k] || k;
        var pctNum = parseFloat(pct);
        var displayText = pctNum >= 10 ? pct + '%' : '';
        parts.push(
            '<span class="chain-ratio-segment" style="flex:0 0 ' + pct + '%;background:' + col +
            ';color:#fff;font-size:11px;display:flex;align-items:center;justify-content:center;' +
            'overflow:hidden;white-space:nowrap;cursor:default" ' +
            'data-type-name="' + escapeHtml(typeLabel) + '" ' +
            'data-type-count="' + n + '" ' +
            'data-type-pct="' + pct + '" ' +
            'data-type-total="' + counts.total + '">' + displayText + '</span>'
        );
    }
    if (parts.length === 0) return '';
    var h = barHeight || 22;
    return '<div style="display:flex;height:' + h + 'px;width:100%;overflow:hidden;border-radius:2px;margin-top:4px;">' +
        parts.join('') + '</div>';
}

/**
 * 隐藏三级占比条中所有色块内的文字。占比数值通过 hover 提示框查看。
 * 应在每次 renderColumns 渲染完成后调用。
 */
function hideSmallRatioTexts() {
    const columns = document.getElementById('chain-panorama-columns');
    if (!columns) return;
    const segments = columns.querySelectorAll('.chain-ratio-segment');
    for (let i = 0; i < segments.length; i++) {
        segments[i].textContent = '';
    }
}

/**
 * 按 CHAIN_TYPE_ORDER 各类型优先取 1 家（同类内按 id 升序），不足 4 家则按同顺序循环补位；缺某类则顺延。
 * 返回企业节点数组（最多 4 个），不附带类型标签。
 */
function pickRepresentativeNodes(companies) {
    const by = { 央企: [], 其他国资: [], 民企: [], 外资: [] };
    for (let i = 0; i < companies.length; i++) {
        const c = companies[i];
        const k = normalizeCategory(c.properties || {});
        if (k && by[k]) by[k].push(c);
    }
    CHAIN_TYPE_ORDER.forEach((k) => {
        by[k].sort((a, b) => a.id - b.id);
    });
    const picks = [];
    const used = new Set();
    while (picks.length < 4) {
        let progressed = false;
        for (let o = 0; o < CHAIN_TYPE_ORDER.length; o++) {
            if (picks.length >= 4) break;
            const k = CHAIN_TYPE_ORDER[o];
            const list = by[k];
            const next = list.find((c) => !used.has(c.id));
            if (!next) continue;
            used.add(next.id);
            picks.push(next);
            progressed = true;
        }
        if (!progressed) break;
    }
    return picks;
}

/** 根据自定义拖拽排序对节点列表排序（不改变选中集，只改变顺序） */
function sortNodesByCustomOrder(nodes, segmentId) {
    const customOrder = getRepSortForSegment(segmentId);
    if (!customOrder || customOrder.length === 0) {
        // 没有自定义排序，按默认规则：CHAIN_TYPE_ORDER + id
        const typeIdx = (node) => {
            const k = normalizeCategory(node.properties || {});
            const ix = CHAIN_TYPE_ORDER.indexOf(k);
            return ix >= 0 ? ix : 99;
        };
        return [...nodes].sort((a, b) => {
            const d = typeIdx(a) - typeIdx(b);
            if (d !== 0) return d;
            return Number(a.id) - Number(b.id);
        });
    }
    const posMap = new Map();
    customOrder.forEach((id, idx) => posMap.set(id, idx));
    return [...nodes].sort((a, b) => {
        const pa = posMap.has(a.id) ? posMap.get(a.id) : 99999;
        const pb = posMap.has(b.id) ? posMap.get(b.id) : 99999;
        if (pa !== pb) return pa - pb;
        // 不在自定义列表中的按默认排序
        const typeIdx = (node) => {
            const k = normalizeCategory(node.properties || {});
            const ix = CHAIN_TYPE_ORDER.indexOf(k);
            return ix >= 0 ? ix : 99;
        };
        const d = typeIdx(a) - typeIdx(b);
        if (d !== 0) return d;
        return Number(a.id) - Number(b.id);
    });
}

function formatRepresentativeLine(pickedNodes, totalInSegment, segmentId) {
    if (!pickedNodes || pickedNodes.length === 0) {
        return '<span class="text-gray-400">—</span>';
    }
    // 排序已在 resolveDisplayedRepNodes 中通过 sortNodesByCustomOrder 完成，此处保持传入顺序
    const nodes = pickedNodes;
    const linkCls = chainPanoramaRepButtonClasses();
    const tags = nodes.map((n) => {
        const name = escapeHtml((n.properties && n.properties.name) || String(n.id));
        const idEnc = encodeURIComponent(String(n.id));
        const textColor = chainPanoramaRepTextColor(n);
        const borderColor = chainPanoramaRepBorderColor(n);
        return (
            `<a href="javascript:void(0)" class="${linkCls} chain-rep-drag-item" draggable="true" data-company-id="${idEnc}" data-rep-id="${escapeHtml(String(n.id))}" style="border-color:${borderColor};color:${textColor}">${name}</a>`
        );
    });
    const inner = tags.join('');
    const nameStrs = nodes.map((n) => (n.properties && n.properties.name) || String(n.id));
    const titleAttr = escapeHtml(nameStrs.join('、'));
    const segIdAttr = segmentId != null ? `data-rep-segment-id="${escapeHtml(String(segmentId))}"` : '';
    return `<div class="chain-rep-display chain-rep-drop-zone relative group max-w-full px-1 text-left" ${segIdAttr} style="${chainPanoramaRepContainerStyle()}" title="${titleAttr}">
        ${inner}
        <button type="button" class="chain-rep-picker-btn absolute -right-1 -bottom-1 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-gray-300 bg-white text-[10px] leading-none text-gray-400 opacity-0 pointer-events-none transition-opacity shadow-sm group-hover:pointer-events-auto group-hover:opacity-100 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-600 focus:outline-none focus-visible:pointer-events-auto focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-blue-400/60" aria-label="选择展示的代表企业" title="选择展示的代表企业"><img src="static/images/edit.png" alt="编辑" class="w-3 h-3" /></button>
    </div>`;
}

function disposeChainCharts() {
    for (let i = 0; i < chainPanoramaCharts.length; i++) {
        try {
            chainPanoramaCharts[i].dispose();
        } catch (e) {
            /* ignore */
        }
    }
    chainPanoramaCharts = [];
}

const CHAIN_DONUT_PX = 100;

/** 当前显示的占比条 tooltip DOM 元素引用 */
let chainRatioTooltipEl = null;

/**
 * 在 hover 的色块上方创建悬浮提示框，小三角指向色块中间位置。
 * @param {HTMLElement} segmentEl - 触发的 .chain-ratio-segment 元素
 */
function showRatioTooltip(segmentEl) {
    if (!segmentEl) return;
    const name = segmentEl.getAttribute('data-type-name') || '';
    const count = segmentEl.getAttribute('data-type-count') || '0';
    const pct = segmentEl.getAttribute('data-type-pct') || '0';

    hideRatioTooltip();

    const tooltip = document.createElement('div');
    tooltip.id = 'chain-ratio-tooltip';
    tooltip.style.cssText =
        'position:fixed;z-index:10000;background:#fff;border:1px solid #d1d5db;' +
        'border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.15);' +
        'padding:6px 12px;font-size:12px;line-height:1.5;max-width:180px;pointer-events:none;';

    const arrowId = 'chain-ratio-tooltip-arrow';
    tooltip.innerHTML =
        '<div style="font-weight:600;color:#1f2937;">' + escapeHtml(name) + '</div>' +
        '<div style="color:#6b7280;">' + count + '家（占' + pct + '%）</div>' +
        '<div id="' + arrowId + '" style="position:absolute;bottom:-5px;width:10px;height:10px;' +
        'background:#fff;border-right:1px solid #d1d5db;border-bottom:1px solid #d1d5db;' +
        'transform:rotate(45deg);"></div>';

    document.body.appendChild(tooltip);
    chainRatioTooltipEl = tooltip;

    // 定位：提示框在色块正上方，小三角指向色块中部
    positionRatioTooltip(segmentEl);
}

/**
 * 计算提示框位置：提示框在色块上方居中，小三角指向色块中间位置。
 * @param {HTMLElement} segmentEl - 色块元素
 */
function positionRatioTooltip(segmentEl) {
    if (!chainRatioTooltipEl) return;
    const segRect = segmentEl.getBoundingClientRect();
    const tooltipRect = chainRatioTooltipEl.getBoundingClientRect();

    const gap = 6; // 色块与提示框之间的间距
    const segCenterX = segRect.left + segRect.width / 2;
    const left = segCenterX - tooltipRect.width / 2;
    const top = segRect.top - tooltipRect.height - gap;

    chainRatioTooltipEl.style.left = Math.max(4, left) + 'px';
    chainRatioTooltipEl.style.top = Math.max(4, top) + 'px';

    // 小三角指向色块中心（相对于提示框的水平偏移）
    const arrow = document.getElementById('chain-ratio-tooltip-arrow');
    if (arrow) {
        const arrowCenterX = segCenterX - left;
        arrow.style.left = Math.max(2, Math.min(arrowCenterX - 5, tooltipRect.width - 12)) + 'px';
    }
}

/**
 * 移除占比条 tooltip
 */
function hideRatioTooltip() {
    if (chainRatioTooltipEl && chainRatioTooltipEl.parentNode) {
        chainRatioTooltipEl.parentNode.removeChild(chainRatioTooltipEl);
    }
    chainRatioTooltipEl = null;
}

/**
 * 环形图固定像素，避免表格/flex 下列宽为 0 时 ECharts 画布高度为 0 不绘制。
 * @param {HTMLElement} chartHostEl
 * @param {object} stats
 * @param {number} [piePx] 不传则用 CHAIN_DONUT_PX（表格内小图）
 */
function renderDonut(chartHostEl, stats, piePx) {
    const el = chartHostEl;
    if (!el || !(el instanceof HTMLElement) || typeof echarts === 'undefined') return;
    const total = stats && stats.total != null ? stats.total : 0;
    const w = piePx != null ? piePx : CHAIN_DONUT_PX;
    const h = piePx != null ? piePx : CHAIN_DONUT_PX;
    const data = [];
    for (let i = 0; i < CHAIN_TYPE_ORDER.length; i++) {
        const k = CHAIN_TYPE_ORDER[i];
        const v = stats[k] || 0;
        data.push({
            name: CHAIN_TYPE_LABELS[k],
            value: v,
            itemStyle: { color: CHAIN_TYPE_COLORS[k] }
        });
    }
    if (stats && stats.uncategorized > 0) {
        data.push({
            name: CHAIN_UNCATEGORIZED_LABEL,
            value: stats.uncategorized,
            itemStyle: { color: CHAIN_UNCATEGORIZED_COLOR }
        });
    }
    el.style.width = piePx != null ? `${w}px` : '100%';
    el.style.height = `${h}px`;
    const chart = echarts.init(el, null, {
        width: piePx != null ? w : null,
        height: h,
        renderer: 'canvas'
    });
    chainPanoramaCharts.push(chart);
    if (total < 1) {
        chart.setOption({
            legend: { show: false },
            title: {
                text: '暂无',
                left: 'center',
                top: 'center',
                textStyle: { fontSize: 11, color: '#9ca3af' }
            },
            series: []
        });
        chart.resize();
        requestAnimationFrame(() => {
            try {
                chart.resize();
            } catch (e) {
                /* ignore */
            }
        });
        return;
    }
    const seriesData = data.filter((d) => d.value > 0);
    chart.setOption({
        legend: { show: false },
        tooltip: {
            trigger: 'item',
            appendToBody: true,
            confine: false,
            formatter(params) {
                const pct = total > 0 ? ((params.value / total) * 100).toFixed(1) : '0.0';
                return `${params.name}<br/>${params.value} 家（占 ${pct}%）`;
            }
        },
        series: [
            {
                type: 'pie',
                radius: ['42%', '70%'],
                center: ['50%', '50%'],
                avoidLabelOverlap: true,
                label: { show: false },
                labelLine: { show: false },
                emphasis: {
                    scale: true,
                    scaleSize: 4,
                    itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.12)' }
                },
                data: seriesData
            }
        ]
    });
    chart.resize();
    requestAnimationFrame(() => {
        try {
            chart.resize();
        } catch (e) {
            /* ignore */
        }
    });
}

function populateChartShareCell(tdChart, chartId) {
    tdChart.innerHTML = '';
    const outer = document.createElement('div');
    outer.className = 'flex flex-col items-center justify-center p-0 w-full';
    const chartDiv = document.createElement('div');
    chartDiv.id = chartId;
    chartDiv.className = 'block shrink-0';
    chartDiv.style.width = '100%';
    chartDiv.style.maxWidth = `${CHAIN_DONUT_PX}px`;
    chartDiv.style.height = `${CHAIN_DONUT_PX}px`;
    chartDiv.style.overflow = 'hidden';
    outer.appendChild(chartDiv);
    tdChart.appendChild(outer);
    return chartDiv;
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** localStorage：按产业 → 三级环节 id → 用户勾选的企业 id 列表（仅三级代表列使用） */
const CHAIN_REP_PICKS_KEY = 'chainPanoramaRepPicksByIndustry';

function readRepPicksRoot() {
    // 优先使用服务器缓存
    if (Object.keys(chainRepPicksCache).length > 0) {
        return JSON.parse(JSON.stringify(chainRepPicksCache));
    }
    // 降级：读取 localStorage
    try {
        const raw = localStorage.getItem(CHAIN_REP_PICKS_KEY);
        if (!raw) return {};
        const o = JSON.parse(raw);
        return typeof o === 'object' && o !== null ? o : {};
    } catch (e) {
        return {};
    }
}

/** 防抖定时器：300ms 内多次调用合并为一次保存请求 */
let chainRepSaveTimer = null;

/** 调度代表企业设置保存到服务器（防抖 300ms） */
function scheduleChainRepSave() {
    if (chainRepSaveTimer) clearTimeout(chainRepSaveTimer);
    chainRepSaveTimer = setTimeout(async () => {
        chainRepSaveTimer = null;
        try {
            const base = typeof API_BASE !== 'undefined' ? API_BASE : (window.API_BASE || 'http://127.0.0.1:8000');
            const resp = await fetch(`${base}/api/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    chain_panorama_rep_picks: chainRepPicksCache,
                    chain_panorama_rep_sort: chainRepSortCache
                })
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            // 同步更新 localStorage 作为降级备份
            try {
                localStorage.setItem(CHAIN_REP_PICKS_KEY, JSON.stringify(chainRepPicksCache));
                localStorage.setItem(CHAIN_REP_SORT_KEY, JSON.stringify(chainRepSortCache));
            } catch (e) { /* ignore quota */ }
        } catch (e) {
            console.warn('保存代表企业设置失败，已回退到本地存储:', e.message);
            // 降级：写入 localStorage
            try {
                localStorage.setItem(CHAIN_REP_PICKS_KEY, JSON.stringify(chainRepPicksCache));
                localStorage.setItem(CHAIN_REP_SORT_KEY, JSON.stringify(chainRepSortCache));
            } catch (e2) { /* ignore quota */ }
        }
    }, 300);
}

function writeRepPicksRoot(root) {
    chainRepPicksCache = root;
    scheduleChainRepSave();
}

function currentIndustryStorageKey() {
    return String(window.currentIndustry || 'ai');
}

function getRepPickIdsForSegment(segmentId) {
    const root = readRepPicksRoot();
    const ind = currentIndustryStorageKey();
    const seg = String(segmentId);
    const arr = root[ind] && root[ind][seg];
    if (!Array.isArray(arr) || arr.length === 0) return null;
    return arr.map((x) => Number(x)).filter((n) => Number.isFinite(n));
}

function setRepPickIdsForSegment(segmentId, ids) {
    const ind = currentIndustryStorageKey();
    const seg = String(segmentId);
    const root = readRepPicksRoot();
    if (!root[ind]) root[ind] = {};
    const clean = (ids || []).map((id) => Number(id)).filter((n) => Number.isFinite(n));
    if (clean.length === 0) {
        delete root[ind][seg];
        if (Object.keys(root[ind]).length === 0) delete root[ind];
    } else {
        root[ind][seg] = clean;
    }
    writeRepPicksRoot(root);
}

/** localStorage：按产业 → 三级环节 id → 用户拖拽排序的企业 id 完整顺序 */
const CHAIN_REP_SORT_KEY = 'chainPanoramaRepSortByIndustry';

function readRepSortRoot() {
    // 优先使用服务器缓存
    if (Object.keys(chainRepSortCache).length > 0) {
        return JSON.parse(JSON.stringify(chainRepSortCache));
    }
    // 降级：读取 localStorage
    try {
        const raw = localStorage.getItem(CHAIN_REP_SORT_KEY);
        if (!raw) return {};
        const o = JSON.parse(raw);
        return typeof o === 'object' && o !== null ? o : {};
    } catch (e) {
        return {};
    }
}

function writeRepSortRoot(root) {
    chainRepSortCache = root;
    scheduleChainRepSave();
}

/** 获取指定三级环节下用户自定义的拖拽排序（企业 id 列表），没有则返回 null */
function getRepSortForSegment(segmentId) {
    const root = readRepSortRoot();
    const ind = currentIndustryStorageKey();
    const seg = String(segmentId);
    const arr = root[ind] && root[ind][seg];
    if (!Array.isArray(arr) || arr.length === 0) return null;
    return arr.map((x) => Number(x)).filter((n) => Number.isFinite(n));
}

/** 保存指定三级环节下用户拖拽排序的企业 id 列表 */
function setRepSortForSegment(segmentId, ids) {
    const ind = currentIndustryStorageKey();
    const seg = String(segmentId);
    const root = readRepSortRoot();
    if (!root[ind]) root[ind] = {};
    const clean = (ids || []).map((id) => Number(id)).filter((n) => Number.isFinite(n));
    if (clean.length === 0) {
        delete root[ind][seg];
        if (Object.keys(root[ind]).length === 0) delete root[ind];
    } else {
        root[ind][seg] = clean;
    }
    writeRepSortRoot(root);
}

/** 按自定义拖拽排序重新排列节点列表。已保存顺序的节点排在前面，其余按默认顺序排在后面 */
function applyCustomSortOrder(nodes, segmentId) {
    const saved = getRepSortForSegment(segmentId);
    if (!saved || saved.length === 0) return [...nodes];
    const posMap = new Map();
    saved.forEach((id, idx) => posMap.set(id, idx));
    return [...nodes].sort((a, b) => {
        const pa = posMap.has(a.id) ? posMap.get(a.id) : 99999;
        const pb = posMap.has(b.id) ? posMap.get(b.id) : 99999;
        if (pa !== pb) return pa - pb;
        // 都不在自定义列表中，按默认规则
        return 0;
    });
}

function sortCompaniesForPickerList(companies) {
    const typeIdx = (node) => {
        const k = normalizeCategory(node.properties || {});
        const ix = CHAIN_TYPE_ORDER.indexOf(k);
        return ix >= 0 ? ix : 99;
    };
    return [...companies].sort((a, b) => {
        const d = typeIdx(a) - typeIdx(b);
        if (d !== 0) return d;
        return Number(a.id) - Number(b.id);
    });
}

function nodesFromIdsInOrder(ids, segComps) {
    const map = new Map();
    for (let i = 0; i < segComps.length; i++) {
        const c = segComps[i];
        map.set(c.id, c);
        map.set(Number(c.id), c);
    }
    const out = [];
    const seen = new Set();
    for (let j = 0; j < ids.length; j++) {
        const id = ids[j];
        const n = map.get(id) ?? map.get(Number(id));
        if (n && !seen.has(n.id)) {
            seen.add(n.id);
            out.push(n);
        }
    }
    return out;
}

/** 表格展示用：优先 localStorage 勾选，否则默认四类各 1 的算法，最终按自定义拖拽排序 */
function resolveDisplayedRepNodes(segmentId, segComps) {
    const saved = getRepPickIdsForSegment(segmentId);
    let baseNodes;
    if (saved && saved.length > 0) {
        const mapped = nodesFromIdsInOrder(saved, segComps);
        if (mapped.length > 0) {
            baseNodes = mapped;
        } else {
            baseNodes = pickRepresentativeNodes(segComps);
        }
    } else {
        baseNodes = pickRepresentativeNodes(segComps);
    }
    // 按自定义拖拽排序
    return sortNodesByCustomOrder(baseNodes, segmentId);
}

/** 详情卡片右侧：四类 + 未分类占比（12px，纵向排列） */
function buildL3DetailLegendHtml(stats) {
    const t = stats && stats.total != null ? stats.total : 0;
    if (t < 1) {
        return `<div class="${CHAIN_TABLE_TEXT} text-center text-gray-400">暂无企业数据</div>`;
    }
    const parts = [];
    for (let i = 0; i < CHAIN_TYPE_ORDER.length; i++) {
        const k = CHAIN_TYPE_ORDER[i];
        const v = stats[k] || 0;
        const pct = t > 0 ? ((v / t) * 100).toFixed(0) : '0';
        const name = CHAIN_TYPE_LABELS[k];
        const col = CHAIN_TYPE_COLORS[k];
        parts.push(
            `<div class="flex w-full items-center justify-start gap-1.5 ${CHAIN_TABLE_TEXT} leading-snug">` +
                `<span class="h-2.5 w-2.5 shrink-0 rounded-full" style="background-color:${col}"></span>` +
                `<span class="min-w-0 break-words text-left">${escapeHtml(name)} ${pct}%</span></div>`
        );
    }
    if (stats.uncategorized > 0) {
        const v = stats.uncategorized;
        const pct = t > 0 ? ((v / t) * 100).toFixed(0) : '0';
        parts.push(
            `<div class="flex w-full items-center justify-start gap-1.5 ${CHAIN_TABLE_TEXT} text-gray-600 leading-snug">` +
                `<span class="h-2.5 w-2.5 shrink-0 rounded-full bg-gray-400"></span>` +
                `<span class="min-w-0 break-words text-left">${escapeHtml(CHAIN_UNCATEGORIZED_LABEL)} ${pct}%</span></div>`
        );
    }
    return `<div class="flex w-full min-w-0 flex-col gap-1">${parts.join('')}</div>`;
}

function disposeDetailCardChart(articleEl) {
    if (!articleEl || typeof echarts === 'undefined') return;
    const inner = articleEl.querySelector('.chain-detail-chart-host');
    if (!inner) return;
    const inst = echarts.getInstanceByDom(inner);
    if (!inst) return;
    const ix = chainPanoramaCharts.indexOf(inst);
    if (ix >= 0) chainPanoramaCharts.splice(ix, 1);
    try {
        inst.dispose();
    } catch (e) {
        /* ignore */
    }
}

function appendL3DetailCardForSegment(segmentIdStr) {
    const ctx = window.chainPanoramaContext;
    const host = document.getElementById('chain-panorama-l3-details');
    if (!ctx || !ctx.companyTargets || !ctx.nodeById || !host) return;
    const sid = Number(segmentIdStr);
    if (!Number.isFinite(sid)) return;
    const segNode = ctx.nodeById.get(sid);
    const title = (segNode && segNode.properties && segNode.properties.name) || `环节 ${sid}`;
    const titleKey = title.replace(/\s+/g, ' ').trim();
    const comps = companiesForSegmentExact(sid, ctx.companyTargets, ctx.nodeById);
    const stats = countByType(comps);

    const dupes = host.querySelectorAll('[data-detail-title-key]');
    for (let i = 0; i < dupes.length; i++) {
        if (dupes[i].getAttribute('data-detail-title-key') === titleKey) {
            disposeDetailCardChart(dupes[i]);
            dupes[i].remove();
            break;
        }
    }

    const article = document.createElement('article');
    article.setAttribute('data-detail-title-key', titleKey);
    article.className =
        'group flex max-w-[320px] min-w-[220px] shrink-0 flex-col items-center rounded-lg border border-sky-200 bg-white px-3 py-3 shadow-sm ring-1 ring-black/5';

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className =
        'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-sky-200 bg-white text-base leading-none text-gray-500 opacity-0 shadow-sm pointer-events-none transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 hover:border-red-200 hover:bg-red-50 hover:text-red-600 focus:outline-none focus-visible:pointer-events-auto focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-red-400/60';
    delBtn.setAttribute('aria-label', '删除该环节企业类型占比卡片');
    delBtn.textContent = '\u00d7';
    delBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        disposeDetailCardChart(article);
        article.remove();
    });

    const header = document.createElement('div');
    header.className = 'mb-2 flex w-full min-w-0 items-start justify-between gap-2';

    const h3 = document.createElement('h3');
    h3.className = `${CHAIN_TABLE_TEXT} min-w-0 flex-1 line-clamp-2 text-center font-semibold leading-snug text-blue-700`;
    h3.textContent = title;

    header.appendChild(h3);
    header.appendChild(delBtn);
    article.appendChild(header);

    const row = document.createElement('div');
    row.className =
        'flex w-full max-w-full flex-row flex-nowrap items-center justify-center gap-3 py-0.5';

    const chartWrap = document.createElement('div');
    chartWrap.className = 'flex shrink-0 items-center justify-center';
    const inner = document.createElement('div');
    inner.className = 'chain-detail-chart-host block shrink-0';
    inner.style.width = `${CHAIN_DETAIL_DONUT_PX}px`;
    inner.style.height = `${CHAIN_DETAIL_DONUT_PX}px`;
    chartWrap.appendChild(inner);

    const leg = document.createElement('div');
    leg.className = `flex min-w-[8.5rem] max-w-[12rem] shrink-0 flex-col items-stretch justify-center gap-0.5 ${CHAIN_TABLE_TEXT} text-gray-800`;
    leg.innerHTML = buildL3DetailLegendHtml(stats);

    row.appendChild(chartWrap);
    row.appendChild(leg);
    article.appendChild(row);
    host.prepend(article);
    renderDonut(inner, stats, CHAIN_DETAIL_DONUT_PX);
}

function ensureChainL3ClickDelegation() {
    if (window.chainPanoramaL3ClickBound) return;
    window.chainPanoramaL3ClickBound = true;
    document.addEventListener('click', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        const td = ev.target && ev.target.closest && ev.target.closest('td.chain-l3-cell');
        if (!td) return;
        const sid = td.getAttribute('data-segment-id');
        if (!sid) return;
        appendL3DetailCardForSegment(sid);
    });
}

/** 与旭日图一致：点击代表企业进入企业详情（showCompanyPage） */
function openChainPanoramaCompanyPage(node) {
    if (!node) return;
    if (typeof showCompanyPage === 'function') {
        showCompanyPage(node);
        return;
    }
    const script = document.createElement('script');
    script.src = '/static/js/modules/company.js';
    script.onload = () => {
        if (typeof showCompanyPage === 'function') {
            showCompanyPage(node);
        } else {
            console.error('加载 company.js 后仍找不到 showCompanyPage');
        }
    };
    script.onerror = () => console.error('加载 company.js 失败');
    document.head.appendChild(script);
}

function closeChainRepPickerModal() {
    if (chainRepPickerHost && typeof chainRepPickerHost._repPickerDragCleanup === 'function') {
        try {
            chainRepPickerHost._repPickerDragCleanup();
        } catch (e) {
            /* ignore */
        }
        chainRepPickerHost._repPickerDragCleanup = null;
    }
    if (chainRepPickerHost && chainRepPickerHost.parentNode) {
        chainRepPickerHost.parentNode.removeChild(chainRepPickerHost);
    }
    chainRepPickerHost = null;
    document.removeEventListener('keydown', chainRepPickerOnKeydown);
}

function chainRepPickerOnKeydown(e) {
    if (e.key === 'Escape' || e.key === 'Esc') {
        closeChainRepPickerModal();
    }
}

/** 仅三级行：点击代表企业单元格空白处打开勾选列表（企业名按钮仍进详情） */
function openChainRepPickerModal(td) {
    const segmentIdAttr = td.getAttribute('data-rep-segment-id');
    if (!segmentIdAttr) return;
    const sidNum = Number(segmentIdAttr);
    const segmentId = Number.isFinite(sidNum) ? sidNum : segmentIdAttr;

    const ctx = window.chainPanoramaContext;
    if (!ctx || !ctx.companyTargets || !ctx.nodeById) return;

    const segComps = companiesForSegmentExact(segmentId, ctx.companyTargets, ctx.nodeById);
    const segNode = ctx.nodeById.get(segmentId);
    const segTitle = (segNode && segNode.properties && segNode.properties.name) || `环节 ${segmentId}`;

    closeChainRepPickerModal();

    const root = document.createElement('div');
    root.id = 'chain-rep-picker-modal';
    root.className = 'fixed inset-0 z-[10001] flex items-center justify-center bg-black/40 p-4';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');

    const panel = document.createElement('div');
    panel.className =
        'flex max-h-[68vh] w-full max-w-[22rem] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl';
    panel.addEventListener('click', (e) => e.stopPropagation());

    const head = document.createElement('div');
    head.className =
        'chain-rep-picker-drag-head shrink-0 cursor-grab select-none border-b border-gray-200 px-3 py-2.5 active:cursor-pointer';
    const h2 = document.createElement('h2');
    h2.className = 'text-sm font-semibold leading-snug text-gray-900';
    h2.textContent = `选择代表企业 · ${segTitle}`;
    head.appendChild(h2);

    const search = document.createElement('input');
    search.type = 'search';
    search.className =
        'mx-3 mt-2 rounded-md border border-gray-300 px-2.5 py-1.5 text-sm text-gray-800 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500';
    search.placeholder = '搜索企业名称…';

    const listWrap = document.createElement('div');
    listWrap.className = 'min-h-0 flex-1 overflow-y-auto px-3 py-2';

    const sorted = sortCompaniesForPickerList(segComps);
    const initialNodes = resolveDisplayedRepNodes(segmentId, segComps);
    const initialSet = new Set(initialNodes.map((n) => n.id));

    for (let i = 0; i < sorted.length; i++) {
        const company = sorted[i];
        const row = document.createElement('label');
        row.className =
            'flex cursor-pointer items-start gap-2 rounded-md px-2 py-2 hover:bg-gray-50 chain-rep-picker-row';
        row.setAttribute('data-picker-cid', String(company.id));
        const nm = String((company.properties && company.properties.name) || company.id).toLowerCase();
        row.setAttribute('data-search', nm);

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'chain-rep-picker-cb mt-0.5 h-4 w-4 shrink-0 rounded border-gray-300 text-blue-600 focus:ring-blue-500';
        cb.value = String(company.id);
        cb.checked = initialSet.has(company.id);

        const mid = document.createElement('div');
        mid.className = 'min-w-0 flex-1 text-left';
        const nameEl = document.createElement('div');
        nameEl.className = `${CHAIN_TABLE_TEXT} font-medium text-gray-900`;
        nameEl.textContent = (company.properties && company.properties.name) || String(company.id);
        const cat = normalizeCategory(company.properties || {});
        const tag = document.createElement('div');
        tag.className = `${CHAIN_TABLE_TEXT} mt-0.5 text-gray-500`;
        tag.textContent = cat && CHAIN_TYPE_LABELS[cat] ? CHAIN_TYPE_LABELS[cat] : CHAIN_UNCATEGORIZED_LABEL;

        mid.appendChild(nameEl);
        mid.appendChild(tag);
        row.appendChild(cb);
        row.appendChild(mid);
        listWrap.appendChild(row);
    }

    if (sorted.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'py-8 text-center text-sm text-gray-500';
        empty.textContent = '该环节暂无企业';
        listWrap.appendChild(empty);
    }

    search.addEventListener('input', () => {
        const q = search.value.trim().toLowerCase();
        const rows = listWrap.querySelectorAll('.chain-rep-picker-row');
        for (let r = 0; r < rows.length; r++) {
            const row = rows[r];
            const hay = row.getAttribute('data-search') || '';
            row.style.display = !q || hay.includes(q) ? '' : 'none';
        }
    });

    const foot = document.createElement('div');
    foot.className = 'flex flex-shrink-0 flex-wrap items-center justify-end gap-1.5 border-t border-gray-200 px-3 py-2';

    const mkBtn = (label, primary) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = label;
        if (primary) {
            b.className =
                'rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white shadow hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500';
        } else {
            b.className =
                'rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400';
        }
        return b;
    };

    const btnAll = mkBtn('全选', false);
    const btnClr = mkBtn('清空', false);
    const btnCancel = mkBtn('取消', false);
    const btnOk = mkBtn('确定', true);

    btnAll.addEventListener('click', () => {
        listWrap.querySelectorAll('.chain-rep-picker-cb').forEach((c) => {
            c.checked = true;
        });
    });
    btnClr.addEventListener('click', () => {
        listWrap.querySelectorAll('.chain-rep-picker-cb').forEach((c) => {
            c.checked = false;
        });
    });
    btnCancel.addEventListener('click', () => closeChainRepPickerModal());
    btnOk.addEventListener('click', () => {
        const ids = [];
        const rows = listWrap.querySelectorAll('.chain-rep-picker-row');
        for (let r = 0; r < rows.length; r++) {
            const row = rows[r];
            const c = row.querySelector('.chain-rep-picker-cb');
            if (c && c.checked) ids.push(Number(c.value));
        }
        setRepPickIdsForSegment(segmentId, ids);
        const freshComps = companiesForSegmentExact(segmentId, ctx.companyTargets, ctx.nodeById);
        td.innerHTML = formatRepresentativeLine(
            resolveDisplayedRepNodes(segmentId, freshComps),
            freshComps.length,
            segmentId
        ) + (chainColumnSettings.l3_ratio ? formatTypeRatioBar(countByType(freshComps)) : '');
        requestAnimationFrame(() => hideSmallRatioTexts());
        closeChainRepPickerModal();
    });

    foot.appendChild(btnAll);
    foot.appendChild(btnClr);
    foot.appendChild(btnCancel);
    foot.appendChild(btnOk);

    panel.appendChild(head);
    panel.appendChild(search);
    panel.appendChild(listWrap);
    panel.appendChild(foot);
    root.appendChild(panel);

    root.addEventListener('click', (e) => {
        if (e.target === root) closeChainRepPickerModal();
    });

    document.body.appendChild(root);
    chainRepPickerHost = root;
    document.addEventListener('keydown', chainRepPickerOnKeydown);

    /** 标题栏拖拽移动（viewport 内夹紧） */
    head.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        const rect = panel.getBoundingClientRect();
        panel.style.position = 'fixed';
        panel.style.left = `${rect.left}px`;
        panel.style.top = `${rect.top}px`;
        panel.style.margin = '0';
        panel.style.zIndex = '10002';
        const sx = e.clientX;
        const sy = e.clientY;
        const sl = rect.left;
        const st = rect.top;
        const pad = 8;
        const onMove = (ev) => {
            let nl = sl + (ev.clientX - sx);
            let nt = st + (ev.clientY - sy);
            const pw = panel.offsetWidth;
            const ph = panel.offsetHeight;
            nl = Math.max(pad, Math.min(nl, window.innerWidth - pw - pad));
            nt = Math.max(pad, Math.min(nt, window.innerHeight - ph - pad));
            panel.style.left = `${nl}px`;
            panel.style.top = `${nt}px`;
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            head.classList.remove('cursor-pointer');
            root._repPickerDragCleanup = null;
        };
        root._repPickerDragCleanup = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            head.classList.remove('cursor-pointer');
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        head.classList.add('cursor-pointer');
        e.preventDefault();
    });

    setTimeout(() => search.focus(), 0);
}

function ensureChainRepresentativeClickDelegation() {
    if (window.chainPanoramaRepClickBound) return;
    window.chainPanoramaRepClickBound = true;
    document.addEventListener('click', (ev) => {
        if (window.graphVizSubView !== 'chain') return;

        const btn = ev.target && ev.target.closest && ev.target.closest('a.chain-rep-company');
        if (btn) {
            ev.preventDefault();
            ev.stopPropagation();
            const enc = btn.getAttribute('data-company-id');
            if (!enc) return;
            let rawId;
            try {
                rawId = decodeURIComponent(enc);
            } catch (e) {
                return;
            }
            const ctx = window.chainPanoramaContext;
            if (!ctx || !ctx.nodeById) return;
            const nnum = Number(rawId);
            let node = ctx.nodeById.get(nnum);
            if (!node) node = ctx.nodeById.get(rawId);
            if (!node || !isCompanyNode(node)) return;
            openChainPanoramaCompanyPage(node);
            return;
        }

        const pickerBtn = ev.target && ev.target.closest && ev.target.closest('button.chain-rep-picker-btn');
        if (pickerBtn) {
            ev.preventDefault();
            ev.stopPropagation();
            const repTd = pickerBtn.closest('td.chain-rep-cell');
            if (repTd) openChainRepPickerModal(repTd);
            return;
        }
    });

    /* 占比条色块 hover 提示框 */
    document.addEventListener('mouseover', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        const seg = ev.target && ev.target.closest && ev.target.closest('.chain-ratio-segment');
        if (!seg) return;
        showRatioTooltip(seg);
    });

    document.addEventListener('mouseout', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        const seg = ev.target && ev.target.closest && ev.target.closest('.chain-ratio-segment');
        if (!seg) return;
        // 确认鼠标确实离开了色块（而非进入子元素）
        const related = ev.relatedTarget;
        if (related && seg.contains(related)) return;
        hideRatioTooltip();
    });
}

/** 代表企业标签拖拽排序功能 */
let chainRepDragData = null;

function ensureChainRepDragDelegation() {
    if (window.chainPanoramaRepDragBound) return;
    window.chainPanoramaRepDragBound = true;

    // 注入拖拽样式
    if (!document.getElementById('chain-rep-drag-styles')) {
        const styleEl = document.createElement('style');
        styleEl.id = 'chain-rep-drag-styles';
        styleEl.textContent = `
            a.chain-rep-drag-item { cursor: pointer; user-select: none; transition: opacity 0.15s; }
            body.chain-rep-dragging a.chain-rep-drag-item { cursor: pointer !important; }
            a.chain-rep-drag-item.chain-rep-drag-before { border-left: 3px solid #1E40AF !important; padding-left: 3px !important; }
        `;
        document.head.appendChild(styleEl);
    }

    document.addEventListener('dragstart', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        const dragItem = ev.target && ev.target.closest && ev.target.closest('a.chain-rep-drag-item');
        if (!dragItem) return;
        const repId = dragItem.getAttribute('data-rep-id');
        if (!repId) return;
        const dropZone = dragItem.closest('.chain-rep-drop-zone');
        if (!dropZone) return;

        chainRepDragData = {
            repId: repId,
            sourceZone: dropZone
        };

        dragItem.style.opacity = '0.5';
        document.body.classList.add('chain-rep-dragging');
        ev.dataTransfer.effectAllowed = 'move';
        try {
            ev.dataTransfer.setData('text/plain', repId);
        } catch (e) {
            /* ignore */
        }
    });

    document.addEventListener('dragend', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        const dragItem = ev.target && ev.target.closest && ev.target.closest('a.chain-rep-drag-item');
        if (dragItem) {
            dragItem.style.opacity = '';
        }
        // 移除所有拖拽视觉指示
        document.querySelectorAll('.chain-rep-drag-over').forEach((el) => el.classList.remove('chain-rep-drag-over'));
        document.querySelectorAll('.chain-rep-drag-before').forEach((el) => el.classList.remove('chain-rep-drag-before'));
        document.body.classList.remove('chain-rep-dragging');
        chainRepDragData = null;
    });

    document.addEventListener('dragover', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        // 查找目标位置
        const targetItem = ev.target && ev.target.closest && ev.target.closest('a.chain-rep-drag-item');
        if (targetItem && chainRepDragData && chainRepDragData.sourceZone === targetItem.closest('.chain-rep-drop-zone')) {
            ev.preventDefault();
            ev.dataTransfer.dropEffect = 'move';
            // 移除之前的拖拽指示
            const zone = targetItem.closest('.chain-rep-drop-zone');
            if (zone) {
                zone.querySelectorAll('.chain-rep-drag-before').forEach((el) => el.classList.remove('chain-rep-drag-before'));
            }
            targetItem.classList.add('chain-rep-drag-before');
            return;
        }
        const dropZone = ev.target && ev.target.closest && ev.target.closest('.chain-rep-drop-zone');
        if (dropZone && chainRepDragData && chainRepDragData.sourceZone === dropZone) {
            ev.preventDefault();
            ev.dataTransfer.dropEffect = 'move';
            // 拖到最后
            dropZone.querySelectorAll('.chain-rep-drag-before').forEach((el) => el.classList.remove('chain-rep-drag-before'));
            return;
        }
    });

    document.addEventListener('drop', (ev) => {
        if (window.graphVizSubView !== 'chain') return;
        ev.preventDefault();

        if (!chainRepDragData) return;
        const { repId, sourceZone } = chainRepDragData;
        if (!sourceZone) return;

        const segmentIdAttr = sourceZone.getAttribute('data-rep-segment-id');
        if (!segmentIdAttr) return;
        const segmentId = Number(segmentIdAttr);

        // 获取当前所有代表企业 id（按 DOM 顺序）
        const currentItems = sourceZone.querySelectorAll('a.chain-rep-drag-item');
        const currentIds = [];
        for (let i = 0; i < currentItems.length; i++) {
            currentIds.push(Number(currentItems[i].getAttribute('data-rep-id')));
        }

        // 找到要插入的位置
        let insertBeforeIndex = currentIds.length; // 默认放到最后
        const targetItem = ev.target && ev.target.closest && ev.target.closest('a.chain-rep-drag-item');
        if (targetItem) {
            const targetId = Number(targetItem.getAttribute('data-rep-id'));
            insertBeforeIndex = currentIds.indexOf(targetId);
            if (insertBeforeIndex === -1) insertBeforeIndex = currentIds.length;
        }

        // 从列表中移除被拖拽的 id
        const draggedIdNum = Number(repId);
        const filteredIds = currentIds.filter((id) => id !== draggedIdNum);

        // 在目标位置插入
        // 注意：如果 insertBeforeIndex 在原列表中位于被拖拽元素之后，移除后索引需要调整
        const draggedOrigIndex = currentIds.indexOf(draggedIdNum);
        if (draggedOrigIndex !== -1 && insertBeforeIndex > draggedOrigIndex) {
            insertBeforeIndex = insertBeforeIndex - 1;
        }
        filteredIds.splice(insertBeforeIndex, 0, draggedIdNum);

        // 保存拖拽排序（仅影响当前环节内的企业顺序）
        setRepSortForSegment(segmentId, filteredIds);

        // 刷新该代表企业单元格
        const ctx = window.chainPanoramaContext;
        if (!ctx || !ctx.companyTargets || !ctx.nodeById) return;

        const segComps = companiesForSegmentExact(segmentId, ctx.companyTargets, ctx.nodeById);
        const repTd = sourceZone.closest('td.chain-rep-cell');
        if (repTd) {
            repTd.innerHTML = formatRepresentativeLine(
                resolveDisplayedRepNodes(segmentId, segComps),
                segComps.length,
                segmentId
            ) + (chainColumnSettings.l3_ratio ? formatTypeRatioBar(countByType(segComps)) : '');
            requestAnimationFrame(() => hideSmallRatioTexts());
        }

        chainRepDragData = null;
    });
}

/** 单列：彩色横幅 + 下方表格区块（横幅与表头之间留白） */
function buildChainColumnParts(structure, l1Id, columnIndex, columnSettings) {
    const s = columnSettings || { l2: true, l2_ratio: true, l3: true, l3_ratio: true, representative: true };
    // 代表企业列：只要 l3_ratio 或 representative 任一开启就显示
    const showRepresentativeCol = s.representative || s.l3_ratio;

    const allCols = [
        { key: 'l2', title: '二级', width: 20, visible: s.l2 },
        { key: 'l2_ratio', title: '企业类型占比', width: 20, visible: s.l2_ratio },
        { key: 'l3', title: '三级', width: 20, visible: s.l3 },
        { key: 'representative', title: '代表企业', width: 40, visible: showRepresentativeCol }
    ];
    const visibleCols = allCols.filter(function (c) { return c.visible; });
    const totalWidth = visibleCols.reduce(function (sum, c) { return sum + c.width; }, 0);
    const scaledWidths = visibleCols.map(function (c) {
        return ((c.width / totalWidth) * 100).toFixed(1) + '%';
    });

    const l1Node = structure.nodeById.get(l1Id);
    const l1Name = (l1Node && l1Node.properties && l1Node.properties.name) || `层级 ${l1Id}`;
    const sectionNum = columnIndex + 1;
    const meta = columnMeta(l1Name, sectionNum);
    const bannerCls = bannerClasses(meta.theme);
    const tableTextCls = chainPanoramaTableTextClass(columnIndex);

    const banner = document.createElement('header');
    banner.className = `${bannerCls} w-full shrink-0 rounded-lg px-3 py-4 text-center leading-snug shadow-md ring-1 ring-black/10`;
    const parenPart =
        meta.subtitle && meta.subtitle.trim()
            ? ` <span class="text-sm md:text-base font-normal opacity-95">(${escapeHtml(meta.subtitle)})</span>`
            : '';
    banner.innerHTML = `<span class="text-sm md:text-base font-bold tracking-wide">${escapeHtml(meta.shortTitle)}</span>${parenPart}`;

    const tableWrap = document.createElement('div');
    tableWrap.setAttribute('data-chain-table-wrap', 'true');
    tableWrap.className = 'flex min-h-0 w-full flex-col overflow-x-auto';

    const table = document.createElement('table');
    table.className = `w-full shrink-0 ${CHAIN_TABLE_TEXT} border-collapse table-fixed text-center leading-snug`;

    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    for (let h = 0; h < visibleCols.length; h++) {
        const col = visibleCols[h];
        const th = document.createElement('th');
        th.scope = 'col';
        const isChartCol = col.key === 'l2_ratio';
        const thPad = isChartCol ? 'p-0' : 'px-1.5 py-1.5';
        th.className = `border border-sky-200 ${thPad} ${CHAIN_TABLE_TEXT} font-semibold align-middle leading-tight bg-sky-50 ${tableTextCls} text-center`;
        th.style.width = scaledWidths[h];
        th.textContent = col.title;
        headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    const l2List = structure.l2ByL1.get(l1Id) || [];

    if (l2List.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = visibleCols.length;
        td.className = `border border-gray-300 px-3 py-8 text-center ${tableTextCls}`;
        td.textContent = '暂无二级环节数据';
        tr.appendChild(td);
        tbody.appendChild(tr);
    } else {
        for (let r = 0; r < l2List.length; r++) {
            const l2 = l2List[r];
            const l2Name = (l2.properties && l2.properties.name) || `环节 ${l2.id}`;
            const children = directSegmentChildren(l2.id, structure.links, structure.nodeById);
            const companiesL2 = companiesForL2(
                l2.id,
                structure.parent,
                structure.companyTargets,
                structure.nodeById
            );
            const counts = countByType(companiesL2);
            const chartId = `chain-ec-${l2.id}`;
            const l2Index = r + 1;
            const l2No = `${sectionNum}.${l2Index}`;

            if (children.length === 0) {
                const tr = document.createElement('tr');
                tr.className = 'border-b border-gray-200 hover:bg-gray-50/80';

                let chartElRef = null;
                for (let ci = 0; ci < visibleCols.length; ci++) {
                    switch (visibleCols[ci].key) {
                        case 'l2': {
                            const tdL2 = document.createElement('td');
                            tdL2.className = `border border-gray-300 px-2 py-2 align-middle text-center ${CHAIN_TABLE_TEXT} bg-white`;
                            tdL2.innerHTML = buildL2CellInnerHtml(columnIndex, l2No, l2Name);
                            tr.appendChild(tdL2);
                            break;
                        }
                        case 'l2_ratio': {
                            const tdChart = document.createElement('td');
                            tdChart.className = 'border border-gray-300 p-0 align-middle text-center bg-white';
                            chartElRef = populateChartShareCell(tdChart, chartId);
                            tr.appendChild(tdChart);
                            break;
                        }
                        case 'l3': {
                            const tdL3 = document.createElement('td');
                            tdL3.className = `border border-gray-300 px-1.5 py-2 align-middle text-center ${CHAIN_TABLE_TEXT} ${CHAIN_L3_REP_TEXT_CLASS} bg-white`;
                            tdL3.innerHTML = '<span class="text-gray-400">—</span>';
                            tr.appendChild(tdL3);
                            break;
                        }
                        case 'representative': {
                            const tdRep = document.createElement('td');
                            tdRep.className = `border border-gray-300 px-1 py-2 align-middle text-center ${CHAIN_TABLE_TEXT} ${CHAIN_L3_REP_TEXT_CLASS} leading-tight whitespace-normal bg-white chain-rep-cell`;
                            tdRep.setAttribute('data-rep-segment-id', String(l2.id));
                            const segComps = companiesForSegmentExact(l2.id, structure.companyTargets, structure.nodeById);
                            const picked = pickRepresentativeNodes(segComps);
                            let repHtml = '';
                            if (s.representative) {
                                repHtml += formatRepresentativeLine(picked, segComps.length, l2.id);
                            }
                            if (s.l3_ratio) {
                                repHtml += formatTypeRatioBar(countByType(segComps));
                            }
                            tdRep.innerHTML = repHtml || '<span class="text-gray-400">—</span>';
                            tr.appendChild(tdRep);
                            break;
                        }
                    }
                }
                tbody.appendChild(tr);
                if (chartElRef) {
                    renderDonut(chartElRef, counts);
                }
            } else {
                const n = children.length;
                let chartElRef = null;
                const trRowCls = 'border-b border-gray-200 hover:bg-gray-50/80';
                const tdL3Cls = `chain-l3-cell cursor-pointer border border-gray-300 px-1.5 py-2 align-middle text-center ${CHAIN_TABLE_TEXT} font-medium leading-tight bg-white`;
                const tdRepCls = `border border-gray-300 px-1 py-2 align-middle text-center ${CHAIN_TABLE_TEXT} ${CHAIN_L3_REP_TEXT_CLASS} leading-tight whitespace-normal bg-white`;

                for (let si = 0; si < n; si++) {
                    const tr = document.createElement('tr');
                    tr.className = trRowCls;

                    const isFirstRow = (si === 0);

                    for (let ci = 0; ci < visibleCols.length; ci++) {
                        switch (visibleCols[ci].key) {
                            case 'l2': {
                                if (!isFirstRow) break;
                                const tdL2 = document.createElement('td');
                                tdL2.rowSpan = n;
                                tdL2.className = `border border-gray-300 px-2 py-2 align-middle text-center ${CHAIN_TABLE_TEXT} bg-white`;
                                tdL2.innerHTML = buildL2CellInnerHtml(columnIndex, l2No, l2Name);
                                tr.appendChild(tdL2);
                                break;
                            }
                            case 'l2_ratio': {
                                if (!isFirstRow) break;
                                const tdChart = document.createElement('td');
                                tdChart.rowSpan = n;
                                tdChart.className = 'border border-gray-300 p-0 align-middle text-center bg-white';
                                chartElRef = populateChartShareCell(tdChart, chartId);
                                tr.appendChild(tdChart);
                                break;
                            }
                            case 'l3': {
                                const child = children[si];
                                const childName = (child.properties && child.properties.name) || String(child.id);
                                const l3No = `${sectionNum}.${l2Index}.${si + 1}`;
                                const colColor = chainPanoramaColumnColor(columnIndex);
                                const tdL3 = document.createElement('td');
                                tdL3.className = tdL3Cls;
                                tdL3.setAttribute('data-segment-id', String(child.id));
                                tdL3.innerHTML = `<span class="whitespace-nowrap" style="color:${colColor}">${l3No}</span><br><span style="color:${colColor}">${escapeHtml(childName)}</span>`;
                                tr.appendChild(tdL3);
                                break;
                            }
                            case 'representative': {
                                const child = children[si];
                                const segComps = companiesForSegmentExact(child.id, structure.companyTargets, structure.nodeById);
                                const picked = resolveDisplayedRepNodes(child.id, segComps);
                                const tdRep = document.createElement('td');
                                tdRep.className = `${tdRepCls} chain-rep-cell`;
                                tdRep.setAttribute('data-rep-segment-id', String(child.id));
                                let repHtml = '';
                                if (s.representative) {
                                    repHtml += formatRepresentativeLine(picked, segComps.length, child.id);
                                }
                                if (s.l3_ratio) {
                                    repHtml += formatTypeRatioBar(countByType(segComps));
                                }
                                tdRep.innerHTML = repHtml || '<span class="text-gray-400">—</span>';
                                tr.appendChild(tdRep);
                                break;
                            }
                        }
                    }
                    tbody.appendChild(tr);
                }
                if (chartElRef) {
                    renderDonut(chartElRef, counts);
                }
            }
        }
    }

    table.appendChild(tbody);
    tableWrap.appendChild(table);

    const tableFill = document.createElement('div');
    tableFill.className = 'min-h-0 flex-1 basis-0 bg-white';
    tableFill.setAttribute('aria-hidden', 'true');
    tableWrap.appendChild(tableFill);

    const tableSection = document.createElement('section');
    tableSection.className =
        'flex min-h-0 w-full flex-col overflow-hidden rounded-lg border border-gray-300 bg-white shadow-sm';
    tableSection.setAttribute('aria-label', `${meta.sectionNum}. ${meta.shortTitle} 数据表`);
    tableSection.appendChild(tableWrap);

    return { banner, tableSection };
}

/** 小屏或重置：去掉大屏为对齐表格而写的 tableWrap 高度 */
function clearChainPanoramaTableWrapSizing() {
    document.querySelectorAll('#chain-panorama-columns [data-chain-table-wrap]').forEach((el) => {
        el.style.minHeight = '';
    });
}

/** 大屏：以各列 <table> 实际渲染高度取最大值，仅拉伸 tableWrap，短列留白止于表格外壳（避免整块白底 flex-1 被撑得过高） */
function syncChainPanoramaColumnTableHeights() {
    if (typeof window === 'undefined' || window.innerWidth < 1024) {
        clearChainPanoramaTableWrapSizing();
        return;
    }
    const row = document.querySelector('#chain-panorama-columns [data-chain-columns-row]');
    if (!row) return;
    const wraps = row.querySelectorAll('[data-chain-table-wrap]');
    if (wraps.length < 2) return;

    wraps.forEach((w) => {
        w.style.minHeight = '';
    });
    void row.offsetHeight;

    let maxTable = 0;
    wraps.forEach((w) => {
        const tbl = w.querySelector('table');
        if (tbl) maxTable = Math.max(maxTable, tbl.getBoundingClientRect().height);
    });
    if (maxTable < 1) return;

    const px = `${Math.ceil(maxTable)}px`;
    wraps.forEach((w) => {
        w.style.minHeight = px;
    });
}

function renderColumns(structure) {
    const host = document.getElementById('chain-panorama-columns');
    if (!host) return;
    host.innerHTML = '';
    host.className = 'flex w-full max-w-full min-h-0 flex-col';

    const l1Ids = structure.l1Order;
    const parts = [];
    for (let col = 0; col < l1Ids.length; col++) {
        parts.push(buildChainColumnParts(structure, l1Ids[col], col, chainColumnSettings));
    }

    /** 方案 D：Grid 行高取最高列，子项纵向拉伸，白底卡片底边对齐（flex 行在部分环境下交叉轴拉伸不可靠） */
    const columnsRow = document.createElement('div');
    columnsRow.setAttribute('data-chain-columns-row', 'true');
    const lgCols = chainPanoramaLgGridColsClass(parts.length);
    columnsRow.className = `grid w-full min-h-0 grid-cols-1 items-stretch gap-y-6 gap-x-3 ${lgCols} lg:gap-x-4`;

    for (let i = 0; i < parts.length; i++) {
        const colWrap = document.createElement('div');
        colWrap.setAttribute('data-chain-col-wrap', 'true');
        colWrap.className = 'flex min-h-0 w-full min-w-0 flex-col gap-4';
        colWrap.appendChild(parts[i].banner);
        colWrap.appendChild(parts[i].tableSection);
        columnsRow.appendChild(colWrap);
    }

    host.appendChild(columnsRow);

    /* 动态检测并隐藏小色块文字 */
    requestAnimationFrame(() => {
        hideSmallRatioTexts();
    });

    requestAnimationFrame(() => {
        syncChainPanoramaColumnTableHeights();
        requestAnimationFrame(() => {
            syncChainPanoramaColumnTableHeights();
        });
    });

    window.chainPanoramaContext = {
        companyTargets: structure.companyTargets,
        nodeById: structure.nodeById
    };
    ensureChainL3ClickDelegation();
    ensureChainRepresentativeClickDelegation();
    ensureChainRepDragDelegation();
}

function analyzeGraph(nodes, links) {
    const nodeById = new Map();
    for (let i = 0; i < nodes.length; i++) {
        nodeById.set(nodes[i].id, nodes[i]);
    }
    const parent = buildParentMap(links);
    const companyTargets = buildCompanyTargets(links, nodeById);

    const l1Nodes = [];
    for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        if (isSegmentNode(n) && getLevel(n) === 1) {
            l1Nodes.push(n);
        }
    }
    l1Nodes.sort((a, b) => a.id - b.id);
    const l1Order = l1Nodes.map((n) => n.id);

    const l2ByL1 = new Map();
    for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        if (!isSegmentNode(n) || getLevel(n) !== 2) continue;
        const l1 = findL1ForL2(n.id, parent, nodeById);
        if (l1 == null) continue;
        if (!l2ByL1.has(l1)) l2ByL1.set(l1, []);
        l2ByL1.get(l1).push(n);
    }
    l2ByL1.forEach((list) => {
        list.sort((a, b) => a.id - b.id);
    });

    return { nodeById, parent, companyTargets, links, l1Order, l2ByL1 };
}

/**
 * 计算各一级环节的企业类型占比。
 * 返回 { upstream, midstream, downstream }，每个值为 countByType 返回值。
 */
function calcL1TypeStats(structure) {
    const { nodeById, companyTargets, l2ByL1, l1Order } = structure;
    const result = { upstream: null, midstream: null, downstream: null };
    const keys = ['upstream', 'midstream', 'downstream'];

    // companyTargets 的 key 是公司ID，value 是环节ID数组。
    // 先构建反向映射：环节ID → 公司ID集合，方便后续按环节查企业。
    const segToCompanies = new Map();
    for (const [cid, segIds] of companyTargets) {
        for (let s = 0; s < segIds.length; s++) {
            const sid = segIds[s];
            if (!segToCompanies.has(sid)) segToCompanies.set(sid, new Set());
            segToCompanies.get(sid).add(cid);
        }
    }

    for (let i = 0; i < l1Order.length && i < 3; i++) {
        const l1Id = l1Order[i];
        const l2List = l2ByL1.get(l1Id) || [];
        const seen = new Set();

        for (let j = 0; j < l2List.length; j++) {
            const l2Id = l2List[j].id;
            const segmentIds = [l2Id];
            // 找该二级环节下挂的所有三级环节
            for (const [nid, node] of nodeById) {
                if (isSegmentNode(node) && getLevel(node) === 3) {
                    const parentId = structure.parent[nid];
                    if (parentId === l2Id || segmentUnderL2(nid, l2Id, structure.parent)) {
                        segmentIds.push(nid);
                    }
                }
            }
            // 收集这些环节下的所有企业
            for (let k = 0; k < segmentIds.length; k++) {
                const sid = segmentIds[k];
                const cids = segToCompanies.get(sid);
                if (cids) {
                    for (const cid of cids) {
                        seen.add(cid);
                    }
                }
            }
        }
        // 构建企业节点列表
        const allCompanies = [];
        for (const cid of seen) {
            const cnode = nodeById.get(cid);
            if (cnode && isCompanyNode(cnode)) {
                allCompanies.push(cnode);
            }
        }
        result[keys[i]] = countByType(allCompanies);
    }
    return result;
}

/**
 * 计算全图谱企业类型占比。
 * 聚合所有企业节点（通过 companyTargets 获取所有公司）。
 */
function calcOverallTypeStats(structure) {
    const { nodeById, companyTargets } = structure;
    // companyTargets 的 key 是公司ID，value 是环节ID数组。
    // 直接收集所有公司ID即可。
    const allCompanies = [];
    const seen = new Set();
    for (const [cid, targets] of companyTargets) {
        if (!seen.has(cid)) {
            seen.add(cid);
            const cnode = nodeById.get(cid);
            if (cnode && isCompanyNode(cnode)) {
                allCompanies.push(cnode);
            }
        }
    }
    return countByType(allCompanies);
}

/**
 * 计算节点数量统计：各一级环节下挂的二级/三级环节数。
 * 返回 { upstream: {l2, l3}, midstream: {l2, l3}, downstream: {l2, l3}, total: {l2, l3} }
 */
function calcNodeCountStats(structure) {
    const { l2ByL1, l1Order, nodeById, parent } = structure;
    const keys = ['upstream', 'midstream', 'downstream'];
    const result = { upstream: { l2: 0, l3: 0 }, midstream: { l2: 0, l3: 0 }, downstream: { l2: 0, l3: 0 }, total: { l2: 0, l3: 0 } };

    for (let i = 0; i < l1Order.length && i < 3; i++) {
        const l1Id = l1Order[i];
        const l2List = l2ByL1.get(l1Id) || [];
        const l2Count = l2List.length;
        let l3Count = 0;

        for (let j = 0; j < l2List.length; j++) {
            const l2Id = l2List[j].id;
            for (const [nid, node] of nodeById) {
                if (isSegmentNode(node) && getLevel(node) === 3) {
                    const p = parent[nid];
                    if (p === l2Id) {
                        l3Count++;
                    }
                }
            }
        }
        result[keys[i]] = { l2: l2Count, l3: l3Count };
        result.total.l2 += l2Count;
        result.total.l3 += l3Count;
    }
    return result;
}

/**
 * 渲染进度条模式统计面板（三列布局）。
 * @param {HTMLElement} container - #chain-stats-panel
 * @param {object} statsL1 - { upstream, midstream, downstream } 各为 countByType 返回值
 * @param {object} statsOverall - 全图谱 countByType 返回值
 * @param {object} nodeCounts - calcNodeCountStats 返回值
 */
function renderProgressStats(container, statsL1, statsOverall, nodeCounts) {
    container.innerHTML = '';
    container.classList.remove('hidden');

    const wrap = document.createElement('div');
    wrap.className = 'flex flex-col gap-4';

    const l1Names = ['上游', '中游', '下游'];
    const l1Keys = ['upstream', 'midstream', 'downstream'];
    const l1Colors = [chainPanoramaColumnColor(0), chainPanoramaColumnColor(1), chainPanoramaColumnColor(2)];
    const nodeColors = ['#B39DDB', '#80CBC4', '#FFCC80', '#9FA8DA'];
    const nodeIcons = ['static/images/industry/上游.png', 'static/images/industry/中游.png', 'static/images/industry/下游.png', 'static/images/industry/合计.png'];
    const nodeLabels = ['上游', '中游', '下游', '合计'];
    const nodeTitleColors = [l1Colors[0], l1Colors[1], l1Colors[2], '#3F51B5'];

    const cardsRow = document.createElement('div');
    cardsRow.className = 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4';

    // 左列：一级环节占比
    const leftCard = document.createElement('div');
    leftCard.className = 'bg-white rounded-xl shadow-sm p-5';
    leftCard.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
        '<h3 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0;">企业类型占比（一级环节）</h3>' +
        '<div class="chain-stats-toggle" data-card="l1" style="display:flex;border-radius:6px;overflow:hidden;border:1px solid #e0e0e0;">' +
        '<button class="chain-stats-btn" data-mode="pie" data-card="l1" style="padding:4px 12px;font-size:12px;border:none;background:#e0e0e0;color:#666;cursor:pointer;">饼图</button>' +
        '<button class="chain-stats-btn active" data-mode="progress" data-card="l1" style="padding:4px 12px;font-size:12px;border:none;background:#3F51B5;color:#fff;cursor:pointer;">进度条</button>' +
        '</div></div>';
    const leftContent = document.createElement('div');
    leftContent.className = 'chain-stats-l1-content';
    for (let i = 0; i < 3; i++) {
        const counts = statsL1[l1Keys[i]];
        if (!counts) continue;
        const row = document.createElement('div');
        row.style.cssText = 'margin-bottom:14px;display:flex;align-items:center;gap:8px;';
        const label = document.createElement('span');
        label.style.cssText = 'font-size:13px;color:' + l1Colors[i] + ';font-weight:600;width:36px;';
        label.textContent = l1Names[i];
        row.appendChild(label);
        const barContainer = document.createElement('div');
        barContainer.style.cssText = 'flex:1;overflow:hidden;display:flex;';
        const barHTML = formatTypeRatioBar(counts, 22);
        if (barHTML) {
            barContainer.innerHTML = barHTML;
        } else {
            barContainer.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:#999;font-size:12px;">暂无数据</div>';
        }
        row.appendChild(barContainer);
        leftContent.appendChild(row);
    }
    // 左列图例
    const leftLegend = document.createElement('div');
    leftLegend.style.cssText = 'margin-top:12px;display:flex;flex-direction:column;gap:4px;font-size:11px;color:#666;text-align:left;';
    var legendTypeOrder2 = ['央企', '其他国资', '民企', '外资'];
    var legendFrags2 = [];
    for (var li2 = 0; li2 < legendTypeOrder2.length; li2++) {
        var lk2 = legendTypeOrder2[li2];
        var lv2 = statsOverall[lk2] || 0;
        var lp2 = statsOverall.total > 0 ? ((lv2 / statsOverall.total) * 100).toFixed(1) : '0.0';
        legendFrags2.push('<div style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:10px;height:10px;background:' + CHAIN_TYPE_COLORS[lk2] + ';border-radius:2px;flex-shrink:0;"></span>' + (CHAIN_TYPE_LABELS[lk2] || lk2) + ' ' + lp2 + '%</div>');
    }
    leftLegend.innerHTML = legendFrags2.join('');
    leftContent.appendChild(leftLegend);
    leftCard.appendChild(leftContent);
    cardsRow.appendChild(leftCard);

    // 中列：全图谱占比
    const midCard = document.createElement('div');
    midCard.className = 'bg-white rounded-xl shadow-sm p-5 flex flex-col';
    midCard.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">' +
        '<h3 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0;flex:1;text-align:center;">整体代表企业类型占比（全图谱）</h3>' +
        '<div class="chain-stats-toggle" data-card="overall" style="display:flex;border-radius:6px;overflow:hidden;border:1px solid #e0e0e0;">' +
        '<button class="chain-stats-btn" data-mode="pie" data-card="overall" style="padding:4px 12px;font-size:12px;border:none;background:#e0e0e0;color:#666;cursor:pointer;">饼图</button>' +
        '<button class="chain-stats-btn active" data-mode="progress" data-card="overall" style="padding:4px 12px;font-size:12px;border:none;background:#3F51B5;color:#fff;cursor:pointer;">进度条</button>' +
        '</div></div>';
    const midContent = document.createElement('div');
    midContent.className = 'chain-stats-overall-content';
    midContent.style.cssText = 'flex:1;display:flex;flex-direction:column;';
    // 上部：进度条 + 图例（占满剩余空间，垂直居中）
    const midTop = document.createElement('div');
    midTop.style.cssText = 'flex:1;display:flex;flex-direction:column;justify-content:center;';
    // 进度条
    const barWrap = document.createElement('div');
    barWrap.style.cssText = 'width:100%;overflow:hidden;display:flex;';
    const barHTML2 = formatTypeRatioBar(statsOverall, 33);
    if (barHTML2) {
        barWrap.innerHTML = barHTML2;
    } else {
        barWrap.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:#999;font-size:12px;">暂无数据</div>';
    }
    midTop.appendChild(barWrap);
    // 图例，每行一个类型
    const midLegend = document.createElement('div');
    midLegend.style.cssText = 'margin-top:12px;display:flex;flex-direction:column;gap:4px;font-size:11px;color:#666;text-align:left;';
    var legendTypeOrder3 = ['央企', '其他国资', '民企', '外资'];
    var legendFrags3 = [];
    for (var li3 = 0; li3 < legendTypeOrder3.length; li3++) {
        var lk3 = legendTypeOrder3[li3];
        var lv3 = statsOverall[lk3] || 0;
        var lp3 = statsOverall.total > 0 ? ((lv3 / statsOverall.total) * 100).toFixed(1) : '0.0';
        legendFrags3.push('<div style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:10px;height:10px;background:' + CHAIN_TYPE_COLORS[lk3] + ';border-radius:2px;flex-shrink:0;"></span>' + (CHAIN_TYPE_LABELS[lk3] || lk3) + ' ' + lp3 + '%</div>');
    }
    midLegend.innerHTML = legendFrags3.join('');
    midTop.appendChild(midLegend);
    midContent.appendChild(midTop);
    // 下部：注脚，居左
    const midFootnote = document.createElement('div');
    midFootnote.style.cssText = 'margin-top:12px;font-size:11px;color:#999;text-align:left;';
    midFootnote.textContent = '注：以上占比基于代表企业数据统计';
    midContent.appendChild(midFootnote);
    midCard.appendChild(midContent);
    cardsRow.appendChild(midCard);

    // 右列：节点数量统计
    const rightCard = document.createElement('div');
    rightCard.className = 'bg-white rounded-xl shadow-sm p-5';
    rightCard.innerHTML = '<h3 style="font-size:15px;font-weight:700;color:#1a1a2e;margin:0 0 16px 0;text-align:center;">节点数量统计</h3>';
    const nodeGrid = document.createElement('div');
    nodeGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;height:100%;';
    const nodeData = [nodeCounts.upstream, nodeCounts.midstream, nodeCounts.downstream, nodeCounts.total];
    for (let i = 0; i < 4; i++) {
        const nd = nodeData[i];
        const col = document.createElement('div');
        col.style.cssText = 'text-align:center;display:flex;flex-direction:column;align-items:center;' + (i < 3 ? 'border-right:1px solid #f0f0f0;' : '');
        col.innerHTML = '<div style="width:40px;height:40px;border-radius:50%;background:' + nodeColors[i] + ';display:flex;align-items:center;justify-content:center;margin-bottom:8px;"><img src="' + nodeIcons[i] + '" style="width:20px;height:20px;object-fit:contain;" /></div>' +
            '<span style="font-size:13px;font-weight:700;color:' + nodeTitleColors[i] + ';margin-bottom:12px;">' + nodeLabels[i] + '</span>' +
            '<div style="margin-bottom:8px;"><div style="font-size:28px;font-weight:800;color:#1a1a2e;">' + nd.l3 + '</div><div style="font-size:11px;color:#999;">三级节点</div></div>' +
            '<div><div style="font-size:20px;font-weight:700;color:#666;">' + nd.l2 + '</div><div style="font-size:11px;color:#999;">二级节点</div></div>';
        nodeGrid.appendChild(col);
    }
    rightCard.appendChild(nodeGrid);
    cardsRow.appendChild(rightCard);

    wrap.appendChild(cardsRow);

    container.appendChild(wrap);

    // 绑定 Tab 切换事件（使用闭包引用 statsL1/statsOverall 等变量）
    container.addEventListener('click', function(e) {
        const btn = e.target.closest('.chain-stats-btn');
        if (!btn) return;
        const card = btn.dataset.card;
        const mode = btn.dataset.mode;
        if (btn.classList.contains('active')) return;

        // 更新按钮状态
        const toggle = btn.closest('.chain-stats-toggle');
        toggle.querySelectorAll('.chain-stats-btn').forEach(function(b) {
            b.classList.remove('active');
            b.style.background = '#e0e0e0';
            b.style.color = '#666';
        });
        btn.classList.add('active');
        btn.style.background = '#3F51B5';
        btn.style.color = '#fff';

        if (card === 'l1') {
            var leftContent2 = container.querySelector('.chain-stats-l1-content');
            if (mode === 'pie') {
                var oldCharts2 = leftContent2.querySelectorAll('.chain-stats-pie-host');
                oldCharts2.forEach(function(el2) {
                    var inst2 = echarts.getInstanceByDom(el2);
                    if (inst2) {
                        var ix2 = chainPanoramaCharts.indexOf(inst2);
                        if (ix2 >= 0) chainPanoramaCharts.splice(ix2, 1);
                        inst2.dispose();
                    }
                });
                renderPieL1Chart(leftContent2, statsL1);
            } else {
                var oldCharts3 = leftContent2.querySelectorAll('.chain-stats-pie-host');
                oldCharts3.forEach(function(el3) {
                    var inst3 = echarts.getInstanceByDom(el3);
                    if (inst3) {
                        var ix3 = chainPanoramaCharts.indexOf(inst3);
                        if (ix3 >= 0) chainPanoramaCharts.splice(ix3, 1);
                        inst3.dispose();
                    }
                });
                leftContent2.innerHTML = '';
                for (var i2 = 0; i2 < 3; i2++) {
                    var counts2 = statsL1[l1Keys[i2]];
                    if (!counts2) continue;
                    var row2 = document.createElement('div');
                    row2.style.cssText = 'margin-bottom:14px;display:flex;align-items:center;gap:8px;';
                    var label2 = document.createElement('span');
                    label2.style.cssText = 'font-size:13px;color:' + l1Colors[i2] + ';font-weight:600;width:36px;';
                    label2.textContent = l1Names[i2];
                    row2.appendChild(label2);
                    var barContainer2 = document.createElement('div');
                    barContainer2.style.cssText = 'flex:1;overflow:hidden;display:flex;';
                    var barHTML3 = formatTypeRatioBar(counts2, 22);
                    barContainer2.innerHTML = barHTML3 || '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:#999;font-size:12px;">暂无数据</div>';
                    row2.appendChild(barContainer2);
                    leftContent2.appendChild(row2);
                }
                // 重建图例
                var leftLegend2 = document.createElement('div');
                leftLegend2.style.cssText = 'margin-top:12px;display:flex;flex-direction:column;gap:4px;font-size:11px;color:#666;text-align:left;';
                var lgOrder2 = ['央企', '其他国资', '民企', '外资'];
                var lgFrags = [];
                for (var lgI = 0; lgI < lgOrder2.length; lgI++) {
                    var lgK = lgOrder2[lgI];
                    var lgV = statsOverall[lgK] || 0;
                    var lgP = statsOverall.total > 0 ? ((lgV / statsOverall.total) * 100).toFixed(1) : '0.0';
                    lgFrags.push('<div style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:10px;height:10px;background:' + CHAIN_TYPE_COLORS[lgK] + ';border-radius:2px;flex-shrink:0;"></span>' + (CHAIN_TYPE_LABELS[lgK] || lgK) + ' ' + lgP + '%</div>');
                }
                leftLegend2.innerHTML = lgFrags.join('');
                leftContent2.appendChild(leftLegend2);
            }
        } else if (card === 'overall') {
            var midContent2 = container.querySelector('.chain-stats-overall-content');
            if (mode === 'pie') {
                var oldCharts4 = midContent2.querySelectorAll('.chain-stats-pie-host');
                oldCharts4.forEach(function(el4) {
                    var inst4 = echarts.getInstanceByDom(el4);
                    if (inst4) {
                        var ix4 = chainPanoramaCharts.indexOf(inst4);
                        if (ix4 >= 0) chainPanoramaCharts.splice(ix4, 1);
                        inst4.dispose();
                    }
                });
                renderPieOverallChart(midContent2, statsOverall);
            } else {
                var oldCharts5 = midContent2.querySelectorAll('.chain-stats-pie-host');
                oldCharts5.forEach(function(el5) {
                    var inst5 = echarts.getInstanceByDom(el5);
                    if (inst5) {
                        var ix5 = chainPanoramaCharts.indexOf(inst5);
                        if (ix5 >= 0) chainPanoramaCharts.splice(ix5, 1);
                        inst5.dispose();
                    }
                });
                midContent2.innerHTML = '';
                midContent2.style.cssText = 'flex:1;display:flex;flex-direction:column;';
                var midTop2 = document.createElement('div');
                midTop2.style.cssText = 'flex:1;display:flex;flex-direction:column;justify-content:center;';
                var barWrap2 = document.createElement('div');
                barWrap2.style.cssText = 'width:100%;overflow:hidden;display:flex;';
                var barHTML4 = formatTypeRatioBar(statsOverall, 33);
                barWrap2.innerHTML = barHTML4 || '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:#999;font-size:12px;">暂无数据</div>';
                midTop2.appendChild(barWrap2);
                // 重建图例，每行一个类型
                var midLegend2 = document.createElement('div');
                midLegend2.style.cssText = 'margin-top:12px;display:flex;flex-direction:column;gap:4px;font-size:11px;color:#666;text-align:left;';
                var lgOrderM = ['央企', '其他国资', '民企', '外资'];
                var lgFragsM = [];
                for (var lgIM = 0; lgIM < lgOrderM.length; lgIM++) {
                    var lgKM = lgOrderM[lgIM];
                    var lgVM = statsOverall[lgKM] || 0;
                    var lgPM = statsOverall.total > 0 ? ((lgVM / statsOverall.total) * 100).toFixed(1) : '0.0';
                    lgFragsM.push('<div style="display:flex;align-items:center;gap:3px;"><span style="display:inline-block;width:10px;height:10px;background:' + CHAIN_TYPE_COLORS[lgKM] + ';border-radius:2px;flex-shrink:0;"></span>' + (CHAIN_TYPE_LABELS[lgKM] || lgKM) + ' ' + lgPM + '%</div>');
                }
                midLegend2.innerHTML = lgFragsM.join('');
                midTop2.appendChild(midLegend2);
                midContent2.appendChild(midTop2);
                // 下部：注脚，居左
                var midFootnote2 = document.createElement('div');
                midFootnote2.style.cssText = 'margin-top:12px;font-size:11px;color:#999;text-align:left;';
                midFootnote2.textContent = '注：以上占比基于代表企业数据统计';
                midContent2.appendChild(midFootnote2);
            }
        }
    });
}

/**
 * 渲染饼图模式的一级环节占比（环形图 + 图例纵向排列）。
 * @param {HTMLElement} container - 左列卡片内容容器
 * @param {object} statsL1 - { upstream, midstream, downstream }
 */
function renderPieL1Chart(container, statsL1) {
    container.innerHTML = '';
    var l1NamesP = ['上游', '中游', '下游'];
    var l1KeysP = ['upstream', 'midstream', 'downstream'];
    var l1ColorsP = [chainPanoramaColumnColor(0), chainPanoramaColumnColor(1), chainPanoramaColumnColor(2)];
    var px = 70;

    for (var i = 0; i < 3; i++) {
        var counts = statsL1[l1KeysP[i]];
        if (!counts) continue;
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:6px 0;';

        var label = document.createElement('span');
        label.style.cssText = 'font-size:13px;font-weight:700;color:' + l1ColorsP[i] + ';writing-mode:vertical-lr;letter-spacing:2px;min-width:20px;';
        label.textContent = l1NamesP[i];
        row.appendChild(label);

        var chartHost = document.createElement('div');
        chartHost.className = 'chain-stats-pie-host';
        chartHost.style.cssText = 'width:' + px + 'px;height:' + px + 'px;flex-shrink:0;';
        renderDonut(chartHost, counts, px);
        row.appendChild(chartHost);

        var legend = document.createElement('div');
        legend.style.cssText = 'font-size:11px;color:#666;line-height:1.8;';
        var typeOrderP = ['央企', '其他国资', '民企', '外资'];
        var fragments = [];
        for (var j = 0; j < typeOrderP.length; j++) {
            var k = typeOrderP[j];
            var v = counts[k] || 0;
            var pct = counts.total > 0 ? ((v / counts.total) * 100).toFixed(1) : '0.0';
            var lb = CHAIN_TYPE_LABELS[k] || k;
            fragments.push('<div><span style="display:inline-block;width:10px;height:10px;background:' + CHAIN_TYPE_COLORS[k] + ';border-radius:2px;vertical-align:middle;margin-right:3px;"></span>' + lb + ' ' + pct + '%</div>');
        }
        legend.innerHTML = fragments.join('');
        row.appendChild(legend);

        container.appendChild(row);
        if (i < 2) {
            var hr = document.createElement('hr');
            hr.style.cssText = 'border:none;border-top:1px solid #f0f0f0;margin:0;';
            container.appendChild(hr);
        }
    }
}

/**
 * 渲染饼图模式的全图谱占比（大环形图 + 图例）。
 * @param {HTMLElement} container - 中列卡片内容容器
 * @param {object} statsOverall
 */
function renderPieOverallChart(container, statsOverall) {
    container.innerHTML = '';
    container.style.cssText = 'flex:1;display:flex;flex-direction:column;';

    // 上部：饼图与图例左右分栏（撑满剩余空间，垂直居中）
    var topRow = document.createElement('div');
    topRow.style.cssText = 'flex:1;display:flex;align-items:center;gap:8px;';

    var chartHost = document.createElement('div');
    chartHost.className = 'chain-stats-pie-host';
    var piePx = 140;
    chartHost.style.cssText = 'width:' + piePx + 'px;height:' + piePx + 'px;flex-shrink:0;';
    renderDonut(chartHost, statsOverall, piePx);
    topRow.appendChild(chartHost);

    var legend = document.createElement('div');
    legend.style.cssText = 'flex:1;font-size:11px;color:#666;line-height:1.8;display:flex;flex-direction:column;gap:2px;text-align:left;';
    var typeOrderO = ['央企', '其他国资', '民企', '外资'];
    var fragments = [];
    for (var j = 0; j < typeOrderO.length; j++) {
        var k = typeOrderO[j];
        var v = statsOverall[k] || 0;
        var pct = statsOverall.total > 0 ? ((v / statsOverall.total) * 100).toFixed(1) : '0.0';
        var lb = CHAIN_TYPE_LABELS[k] || k;
        fragments.push('<div><span style="display:inline-block;width:10px;height:10px;background:' + CHAIN_TYPE_COLORS[k] + ';border-radius:2px;vertical-align:middle;margin-right:3px;"></span>' + lb + ' ' + pct + '%</div>');
    }
    legend.innerHTML = fragments.join('');
    topRow.appendChild(legend);

    container.appendChild(topRow);

    // 下部：注脚
    var footnote = document.createElement('div');
    footnote.style.cssText = 'margin-top:12px;font-size:11px;color:#999;text-align:left;';
    footnote.textContent = '注：以上占比基于代表企业数据统计';
    container.appendChild(footnote);
}

async function reloadChainPanorama() {
    closeChainRepPickerModal();
    CHAIN_TYPE_ORDER = getChainTypeOrder();
    const loading = document.getElementById('chain-panorama-loading');
    const errEl = document.getElementById('chain-panorama-error');
    const cols = document.getElementById('chain-panorama-columns');

    if (loading) loading.classList.remove('hidden');
    if (errEl) {
        errEl.classList.add('hidden');
        errEl.textContent = '';
    }
    disposeChainCharts();
    hideRatioTooltip();
    const statsPanel = document.getElementById('chain-stats-panel');
    if (statsPanel) {
        statsPanel.innerHTML = '';
        statsPanel.classList.add('hidden');
    }
    if (cols) cols.innerHTML = '';
    const l3DetailHost = document.getElementById('chain-panorama-l3-details');
    if (l3DetailHost) l3DetailHost.innerHTML = '';

    await fetchChainColumnSettings();

    try {
        let url = chainDataSourceUrl();
        const sep = url.indexOf('?') >= 0 ? '&' : '?';
        url = `${url}${sep}_ts=${Date.now()}`;
        const resp = await fetch(url, { cache: 'no-cache' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const nodes = data.nodes || [];
        const links = data.relationships || data.links || [];
        const structure = analyzeGraph(nodes, links);
        if (!structure.l1Order.length) {
            if (cols) cols.innerHTML = '<p class="text-gray-500 text-center py-8">未识别到一级产业链环节（level=1）。</p>';
            window.chainPanoramaContext = null;
        } else {
            renderColumns(structure);
            const statsL1 = calcL1TypeStats(structure);
            const statsOverall = calcOverallTypeStats(structure);
            const nodeCounts = calcNodeCountStats(structure);
            const statsPanel = document.getElementById('chain-stats-panel');
            if (statsPanel) {
                renderProgressStats(statsPanel, statsL1, statsOverall, nodeCounts);
            }
        }
    } catch (e) {
        console.error('产业链全景图加载失败:', e);
        if (errEl) {
            errEl.textContent = `加载失败：${e.message || e}`;
            errEl.classList.remove('hidden');
        }
    } finally {
        if (loading) loading.classList.add('hidden');
        requestAnimationFrame(() => {
            chainPanoramaCharts.forEach((c) => {
                try {
                    c.resize();
                } catch (ex) {
                    /* ignore */
                }
            });
            syncChainPanoramaColumnTableHeights();
            requestAnimationFrame(() => {
                chainPanoramaCharts.forEach((c) => {
                    try {
                        c.resize();
                    } catch (ex2) {
                        /* ignore */
                    }
                });
            });
        });
    }
}

function handleChainPanoramaFullscreenKeydown(event) {
    if (event.key === 'Escape' || event.key === 'Esc') {
        exitChainPanoramaFullscreen();
    }
}

function createChainPanoramaFullscreenUI() {
    let columnSettingsBtn = document.getElementById('chain-fullscreen-column-settings-btn');
    if (!columnSettingsBtn) {
        columnSettingsBtn = document.createElement('div');
        columnSettingsBtn.id = 'chain-fullscreen-column-settings-btn';
        columnSettingsBtn.className = 'fixed top-4 right-44 z-[10002]';
        columnSettingsBtn.innerHTML =
            '<button type="button" onclick="openChainColumnSettingsDialog()" class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm"><i class="fas fa-columns text-xs"></i><span>列设置</span></button>';
        document.body.appendChild(columnSettingsBtn);
    } else {
        columnSettingsBtn.classList.remove('hidden');
    }

    let downloadBtn = document.getElementById('chain-fullscreen-download-btn');
    if (!downloadBtn) {
        downloadBtn = document.createElement('div');
        downloadBtn.id = 'chain-fullscreen-download-btn';
        downloadBtn.className = 'fixed top-4 right-24 z-[10002]';
        downloadBtn.innerHTML =
            '<button type="button" onclick="captureChainPanoramaScreenshot()" class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm"><i class="fas fa-camera text-xs"></i><span>下载</span></button>';
        document.body.appendChild(downloadBtn);
    } else {
        downloadBtn.classList.remove('hidden');
    }

    let exitBtn = document.getElementById('chain-fullscreen-exit-btn');
    if (!exitBtn) {
        exitBtn = document.createElement('div');
        exitBtn.id = 'chain-fullscreen-exit-btn';
        exitBtn.className = 'fixed top-4 right-4 z-[10002]';
        exitBtn.innerHTML =
            '<button type="button" onclick="exitChainPanoramaFullscreen()" class="bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm"><i class="fas fa-compress text-xs"></i><span>退出</span></button>';
        document.body.appendChild(exitBtn);
    } else {
        exitBtn.classList.remove('hidden');
    }
}

function removeChainPanoramaFullscreenUI() {
    const columnSettingsBtn = document.getElementById('chain-fullscreen-column-settings-btn');
    if (columnSettingsBtn) columnSettingsBtn.remove();
    const downloadBtn = document.getElementById('chain-fullscreen-download-btn');
    if (downloadBtn) downloadBtn.remove();
    const exitBtn = document.getElementById('chain-fullscreen-exit-btn');
    if (exitBtn) exitBtn.remove();
}

function captureChainPanoramaScreenshot() {
    const target = document.getElementById('chain-panorama-scroll') || document.getElementById('chain-panorama-container');
    if (!target) {
        alert('产业链全景未加载');
        return;
    }
    if (typeof htmlToImage === 'undefined') {
        alert('截图功能需要 html-to-image 库支持');
        return;
    }

    const container = document.getElementById('chain-panorama-container');

    let styleEl = document.getElementById('chain-capture-scrollbar-hide');
    if (!styleEl) {
        styleEl = document.createElement('style');
        styleEl.id = 'chain-capture-scrollbar-hide';
        styleEl.textContent = `
#chain-panorama-scroll.chain-capture-hide-scroll::-webkit-scrollbar,
#chain-panorama-scroll.chain-capture-hide-scroll *::-webkit-scrollbar {
  width: 0 !important;
  height: 0 !important;
  display: none !important;
}
#chain-panorama-scroll.chain-capture-hide-scroll,
#chain-panorama-scroll.chain-capture-hide-scroll * {
  scrollbar-width: none !important;
  -ms-overflow-style: none !important;
}`;
        document.head.appendChild(styleEl);
    }

    const l3 = document.getElementById('chain-panorama-l3-details');
    const prevL3Overflow = l3 ? l3.style.overflow : '';
    const prevL3OverflowX = l3 ? l3.style.overflowX : '';
    if (l3) {
        l3.style.overflow = 'visible';
        l3.style.overflowX = 'visible';
    }

    // 修复 chain-stats-toggle 的 overflow:hidden 导致截图时按钮文字被裁剪；
    // 同时显式给按钮设置 white-space/flex-shrink，防止 html-to-image 渲染时被压缩
    const statsToggles = target.querySelectorAll('.chain-stats-toggle');
    const prevStatsToggleOverflows = [];
    const prevBtnStyles = [];
    statsToggles.forEach(function(el) {
        prevStatsToggleOverflows.push({ el: el, overflow: el.style.overflow });
        el.style.overflow = 'visible';
        const btns = el.querySelectorAll('.chain-stats-btn');
        btns.forEach(function(btn) {
            prevBtnStyles.push({
                el: btn,
                whiteSpace: btn.style.whiteSpace,
                flexShrink: btn.style.flexShrink,
                width: btn.style.width
            });
            btn.style.whiteSpace = 'nowrap';
            btn.style.flexShrink = '0';
            btn.style.width = 'auto';
        });
    });

    target.classList.add('chain-capture-hide-scroll');

    const prevTarget = {
        height: target.style.height,
        maxHeight: target.style.maxHeight,
        minHeight: target.style.minHeight,
        flex: target.style.flex,
        flexGrow: target.style.flexGrow,
        flexShrink: target.style.flexShrink,
        overflow: target.style.overflow,
        overflowX: target.style.overflowX,
        overflowY: target.style.overflowY,
        scrollTop: target.scrollTop
    };

    const prevContainer =
        container != null
            ? {
                  overflow: container.style.overflow,
                  minHeight: container.style.minHeight,
                  height: container.style.height,
                  maxHeight: container.style.maxHeight
              }
            : null;

    const restore = () => {
        target.classList.remove('chain-capture-hide-scroll');
        target.style.height = prevTarget.height;
        target.style.maxHeight = prevTarget.maxHeight;
        target.style.minHeight = prevTarget.minHeight;
        target.style.flex = prevTarget.flex;
        target.style.flexGrow = prevTarget.flexGrow;
        target.style.flexShrink = prevTarget.flexShrink;
        target.style.overflow = prevTarget.overflow;
        target.style.overflowX = prevTarget.overflowX;
        target.style.overflowY = prevTarget.overflowY;
        target.scrollTop = prevTarget.scrollTop;

        if (l3) {
            l3.style.overflow = prevL3Overflow;
            l3.style.overflowX = prevL3OverflowX;
        }

        // 恢复 chain-stats-toggle 的 overflow 及按钮样式
        prevStatsToggleOverflows.forEach(function(item) {
            item.el.style.overflow = item.overflow;
        });
        prevBtnStyles.forEach(function(item) {
            item.el.style.whiteSpace = item.whiteSpace;
            item.el.style.flexShrink = item.flexShrink;
            item.el.style.width = item.width;
        });

        if (container && prevContainer) {
            container.style.overflow = prevContainer.overflow;
            container.style.minHeight = prevContainer.minHeight;
            container.style.height = prevContainer.height;
            container.style.maxHeight = prevContainer.maxHeight;
        }

        requestAnimationFrame(() => {
            chainPanoramaCharts.forEach((c) => {
                try {
                    c.resize();
                } catch (e) {
                    /* ignore */
                }
            });
            if (typeof syncChainPanoramaColumnTableHeights === 'function') {
                syncChainPanoramaColumnTableHeights();
            }
        });
    };

    const doCapture = () => {
        target.scrollTop = 0;
        target.style.flex = 'none';
        target.style.flexGrow = '0';
        target.style.flexShrink = '0';
        target.style.maxHeight = 'none';
        target.style.minHeight = '0';
        target.style.overflow = 'visible';
        target.style.overflowX = 'visible';
        target.style.overflowY = 'visible';

        if (container && prevContainer) {
            container.style.overflow = 'visible';
            container.style.minHeight = '0';
            container.style.maxHeight = 'none';
            container.style.height = 'auto';
        }

        void target.offsetHeight;

        chainPanoramaCharts.forEach((c) => {
            try {
                c.resize();
            } catch (e) {
                /* ignore */
            }
        });
        if (typeof syncChainPanoramaColumnTableHeights === 'function') {
            syncChainPanoramaColumnTableHeights();
        }

        void target.offsetHeight;

        let capW = Math.max(target.scrollWidth, target.clientWidth, target.offsetWidth);
        let capH = target.scrollHeight;
        target.style.height = `${capH}px`;
        void target.offsetHeight;
        capW = Math.max(target.scrollWidth, target.clientWidth, target.offsetWidth);
        capH = target.scrollHeight;

        const MAX_EDGE = 16000;
        let pixelRatio = 2;
        if (capW * pixelRatio > MAX_EDGE || capH * pixelRatio > MAX_EDGE) {
            pixelRatio = Math.max(1, Math.min(2, Math.floor(MAX_EDGE / Math.max(capW, capH, 1))));
        }

        htmlToImage
            .toPng(target, {
                pixelRatio,
                backgroundColor: '#f3f4f6',
                cacheBust: true,
                width: capW,
                height: capH
            })
            .then((dataUrl) => {
                const link = document.createElement('a');
                const now = new Date();
                const dateStr = now.toISOString().split('T')[0];
                const timeStr = now.toTimeString().split(' ')[0].replace(/:/g, '-');
                link.download = `产业链全景_${dateStr}_${timeStr}.png`;
                link.href = dataUrl;
                link.click();
                if (typeof showScreenshotNotification === 'function') {
                    showScreenshotNotification('下载成功！文件已保存为: ' + link.download);
                }
            })
            .catch((err) => {
                console.error(err);
                alert('截图失败: ' + (err.message || String(err)));
            })
            .finally(restore);
    };

    requestAnimationFrame(() => requestAnimationFrame(doCapture));
}

function exitChainPanoramaFullscreen() {
    if (!window.isChainPanoramaFullscreen) return;

    window.isChainPanoramaFullscreen = false;
    const chainContainer = document.getElementById('chain-panorama-container');
    const sidebar = document.querySelector('aside');
    const header = document.querySelector('header');
    const mainContent = document.querySelector('main');

    if (sidebar) sidebar.classList.remove('hidden');
    if (header) header.classList.remove('hidden');
    if (mainContent) {
        mainContent.style.paddingTop = '';
        mainContent.style.height = '';
    }
    document.body.style.overflow = '';

    if (chainContainer) {
        chainContainer.removeAttribute('style');
        chainContainer.style.display = 'flex';
        chainContainer.style.flexDirection = 'column';
        chainContainer.style.width = '100%';
        chainContainer.style.height = '100%';
        chainContainer.style.minHeight = '0';
        chainContainer.style.flex = '1';
    }

    const scrollEl = document.getElementById('chain-panorama-scroll');
    if (scrollEl) {
        scrollEl.style.flex = '';
        scrollEl.style.flexGrow = '';
        scrollEl.style.flexShrink = '';
        scrollEl.style.flexBasis = '';
        scrollEl.style.minHeight = '';
        scrollEl.style.height = '';
        scrollEl.style.overflowY = '';
        scrollEl.style.marginTop = '';
    }

    document.removeEventListener('keydown', handleChainPanoramaFullscreenKeydown);
    window.removeEventListener('resize', chainPanoramaFullscreenViewportHandler);
    if (window.visualViewport) {
        window.visualViewport.removeEventListener('resize', chainPanoramaFullscreenViewportHandler);
        window.visualViewport.removeEventListener('scroll', chainPanoramaFullscreenViewportHandler);
    }
    removeChainPanoramaFullscreenUI();

    const chainZoomBtn = document.getElementById('chain-zoom-btn');
    const chainExitZoomBtn = document.getElementById('chain-exit-zoom-btn');
    const chainScreenshotBtn = document.getElementById('chain-screenshot-btn');
    if (chainZoomBtn) chainZoomBtn.classList.add('hidden');
    if (chainExitZoomBtn) chainExitZoomBtn.classList.add('hidden');
    if (chainScreenshotBtn) chainScreenshotBtn.classList.add('hidden');

    if (typeof updateViewSwitchButtons === 'function') {
        updateViewSwitchButtons('chain');
    }

    requestAnimationFrame(() => {
        chainPanoramaCharts.forEach((c) => {
            try {
                c.resize();
            } catch (e) {
                /* ignore */
            }
        });
    });
}

function toggleChainPanoramaFullscreen() {
    const chainContainer = document.getElementById('chain-panorama-container');
    if (!chainContainer) return;

    if (!window.isChainPanoramaFullscreen) {
        window.isChainPanoramaFullscreen = true;
        const sidebar = document.querySelector('aside');
        const header = document.querySelector('header');
        const mainContent = document.querySelector('main');
        if (sidebar) sidebar.classList.add('hidden');
        if (header) header.classList.add('hidden');
        if (mainContent) {
            mainContent.style.paddingTop = '0';
        }
        document.body.style.overflow = 'hidden';

        const scrollEl = document.getElementById('chain-panorama-scroll');
        if (scrollEl) {
            scrollEl.style.flex = '1 1 0%';
            scrollEl.style.minHeight = '0';
            scrollEl.style.height = '0';
            scrollEl.style.overflowY = 'auto';
            scrollEl.style.overflowX = 'hidden';
            scrollEl.style.marginTop = '0';
            scrollEl.style.width = '100%';
        }

        window.addEventListener('resize', chainPanoramaFullscreenViewportHandler);
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', chainPanoramaFullscreenViewportHandler);
            window.visualViewport.addEventListener('scroll', chainPanoramaFullscreenViewportHandler);
        }

        const chainZoomBtn = document.getElementById('chain-zoom-btn');
        const chainExitZoomBtn = document.getElementById('chain-exit-zoom-btn');
        const chainScreenshotBtn = document.getElementById('chain-screenshot-btn');
        if (chainZoomBtn) chainZoomBtn.classList.add('hidden');
        if (chainExitZoomBtn) chainExitZoomBtn.classList.add('hidden');
        if (chainScreenshotBtn) chainScreenshotBtn.classList.add('hidden');

        document.addEventListener('keydown', handleChainPanoramaFullscreenKeydown);
        createChainPanoramaFullscreenUI();
        if (typeof updateViewSwitchButtons === 'function') {
            updateViewSwitchButtons('chain');
        }

        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                chainPanoramaApplyFullscreenLayout();
            });
        });
    } else {
        exitChainPanoramaFullscreen();
    }
}

window.reloadChainPanorama = reloadChainPanorama;
window.toggleChainPanoramaFullscreen = toggleChainPanoramaFullscreen;
window.exitChainPanoramaFullscreen = exitChainPanoramaFullscreen;
window.captureChainPanoramaScreenshot = captureChainPanoramaScreenshot;
window.openChainColumnSettingsDialog = openChainColumnSettingsDialog;
window.closeChainColumnSettingsDialog = closeChainColumnSettingsDialog;

function switchToChainPanorama() {
    window.graphVizSubView = 'chain';
    window.currentView = 'graph';

    // 记录产业链全景切换日志（系统自动切换时抑制）
    if (typeof uploadActionLog === 'function' && !window.suppressActionLog) {
        uploadActionLog('产业洞察-切换视图-产业链全景', { "view": "chain", "industry": window.currentIndustry || 'ai' });
    }

    const graphContainer = document.getElementById('graph-container');
    const sunburstContainer = document.getElementById('sunburst-container');
    const mindmapContainer = document.getElementById('mindmap-container');
    const chainContainer = document.getElementById('chain-panorama-container');

    if (graphContainer) graphContainer.classList.add('hidden');

    if (sunburstContainer) {
        sunburstContainer.classList.add('hidden');
        sunburstContainer.style.width = '';
        sunburstContainer.style.height = '';
        sunburstContainer.style.display = '';
        sunburstContainer.style.flexDirection = '';
        sunburstContainer.style.position = '';
        sunburstContainer.style.top = '';
        sunburstContainer.style.left = '';
        sunburstContainer.style.zIndex = '';
        sunburstContainer.style.backgroundColor = '';
        const sunburstChartDiv = document.getElementById('sunburst-chart');
        if (sunburstChartDiv) {
            sunburstChartDiv.style.flex = '';
            sunburstChartDiv.style.height = '';
            sunburstChartDiv.style.width = '';
        }
    }

    if (mindmapContainer) {
        mindmapContainer.style.width = '';
        mindmapContainer.style.height = '';
        mindmapContainer.style.display = 'none';
        mindmapContainer.style.flexDirection = '';
        mindmapContainer.style.position = '';
        mindmapContainer.style.top = '';
        mindmapContainer.style.left = '';
        mindmapContainer.style.zIndex = '';
        mindmapContainer.style.backgroundColor = '';
        mindmapContainer.style.overflow = '';
        const mindmapChartDiv = document.getElementById('mindmap-chart');
        if (mindmapChartDiv) {
            mindmapChartDiv.style.flex = '';
            mindmapChartDiv.style.height = '';
            mindmapChartDiv.style.width = '';
        }
        mindmapContainer.classList.add('hidden');
    }

    if (chainContainer) {
        chainContainer.classList.remove('hidden');
        chainContainer.style.display = 'flex';
        chainContainer.style.flexDirection = 'column';
        chainContainer.style.width = '100%';
        chainContainer.style.height = '100%';
        chainContainer.style.minHeight = '0';
        chainContainer.style.flex = '1';
    }

    if (typeof updateViewSwitchButtons === 'function') {
        updateViewSwitchButtons('chain');
    }
    if (typeof enableGraphButtons === 'function') {
        enableGraphButtons(false);
    }

    reloadChainPanorama();
}

window.switchToChainPanorama = switchToChainPanorama;

/**
 * 打开列设置对话框。
 * 从后端拉取最新设置初始化开关状态，确定后保存并刷新全景图。
 */
async function openChainColumnSettingsDialog() {
    await fetchChainColumnSettings();

    const old = document.getElementById('chain-column-settings-dialog');
    if (old) old.remove();

    const overlay = document.createElement('div');
    overlay.id = 'chain-column-settings-dialog';
    overlay.className = 'fixed inset-0 z-[10003] flex items-center justify-center bg-black/40';
    overlay.onclick = function (e) {
        if (e.target === overlay) closeChainColumnSettingsDialog();
    };

    const items = [
        { key: 'l2', label: '二级' },
        { key: 'l2_ratio', label: '二级占比（企业类型）' },
        { key: 'l3', label: '三级' },
        { key: 'l3_ratio', label: '三级占比（企业类型）' },
        { key: 'representative', label: '代表企业' }
    ];

    let rowsHtml = '';
    for (let i = 0; i < items.length; i++) {
        const it = items[i];
        const checked = chainColumnSettings[it.key] ? 'checked' : '';
        rowsHtml += `
            <div class="flex items-center justify-between py-3 px-1 border-b border-gray-100 last:border-b-0">
                <span class="text-sm text-gray-700 select-none">${it.label}</span>
                <label class="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" class="sr-only peer" data-column-key="${it.key}" ${checked}>
                    <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
            </div>`;
    }

    overlay.innerHTML = `
        <div class="bg-white rounded-xl shadow-2xl w-[360px] max-w-[90vw] overflow-hidden" onclick="event.stopPropagation()">
            <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
                <h3 class="text-base font-semibold text-gray-800">列设置</h3>
                <button type="button" onclick="closeChainColumnSettingsDialog()" class="text-gray-400 hover:text-gray-600 transition">
                    <i class="fas fa-times"></i>
                </button>
            </div>
            <div class="px-5 py-2">
                ${rowsHtml}
            </div>
            <div class="px-5 py-3 border-t border-gray-200 flex justify-end gap-3">
                <button type="button" onclick="closeChainColumnSettingsDialog()" class="px-4 py-2 text-sm text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg transition">取消</button>
                <button type="button" id="chain-column-settings-save-btn" class="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition">确定</button>
            </div>
        </div>`;

    document.body.appendChild(overlay);

    document.getElementById('chain-column-settings-save-btn').onclick = async function () {
        // 记录产业链全景列设置日志
        if (typeof uploadActionLog === 'function') {
            uploadActionLog('产业洞察-产业链全景-列设置', { "industry": window.currentIndustry || 'ai' });
        }
        
        const checkboxes = overlay.querySelectorAll('input[data-column-key]');
        const newSettings = {};
        checkboxes.forEach(function (cb) {
            newSettings[cb.getAttribute('data-column-key')] = cb.checked;
        });
        const saved = await saveChainColumnSettings(newSettings);
        if (saved) {
            closeChainColumnSettingsDialog();
        }
    };
}

function closeChainColumnSettingsDialog() {
    const el = document.getElementById('chain-column-settings-dialog');
    if (el) el.remove();
}

/** 切换当前产业后：只要产业链全景容器在页面上可见，即按新产业重拉 JSON（与旭日图同源，不依赖力导图 reload 回调） */
document.addEventListener('industryChanged', (ev) => {
    const d = ev && ev.detail;
    if (d && d.industry != null && d.industry !== '') {
        window.currentIndustry = d.industry;
    }
    const cc = document.getElementById('chain-panorama-container');
    if (!cc || cc.classList.contains('hidden')) return;
    try {
        if (window.getComputedStyle(cc).display === 'none') return;
    } catch (e) {
        return;
    }
    if (typeof reloadChainPanorama !== 'function') return;
    reloadChainPanorama();
});

window.addEventListener('resize', () => {
    if (window.graphVizSubView !== 'chain') return;
    syncChainPanoramaColumnTableHeights();
    chainPanoramaCharts.forEach((c) => {
        try {
            c.resize();
        } catch (e) {
            /* ignore */
        }
    });
});

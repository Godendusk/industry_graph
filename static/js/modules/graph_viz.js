// 图谱可视化逻辑 (使用 ForceGraph + 本地 JSON)
// 包含智能采样、双击展开、内存搜索等完整功能

let Graph;
let isGraphInit = false;
// 存储完整数据（内存里存几十万个纯数据对象没问题，渲染才会有问题）
let allGraphData = { nodes: [], links: [] };
// 预处理后的邻接表，加速查找邻居
let adjacencyList = {};
// 环节骨架视图使用的 level 值
const LEVEL_RING_VALUES = new Set(["1", "2", "3", "1.0", "2.0", "3.0"]);

const customColorScheme = [
    '#1f77b4', // 蓝色
    '#ff7f0e', // 橙色
    '#bcbd22', // 紫色（替换绿色）
    '#d62728', // 红色
    '#9467bd', // 棕色
    '#e377c2', // 粉色
    '#7f7f7f', // 灰色
    '#8c564b', // 黄绿色
    '#17becf', // 青色
    '#2ca02c'  // 绿色（保留但放在最后，尽量不用）
];
const colorScale = d3.scaleOrdinal(customColorScheme);
let backupStatusEl = null;

// 根据公司类型获取颜色
function getColor(type) {
    if (type === '中央企业') return '#FF0000'; // 红
    if (type === '其他国资' || type === '央企/国企' || type === '国有企业') return '#FFB3B3'; // 橙红
    if (type === '外资企业') return '#91cc75'; // 绿
    return '#5470c6'; // 蓝  民营企业
}

// 公司详情悬浮窗口相关变量
let companyDetailTooltip = null;
let currentHoverNode = null;
let tooltipTimeout = null;

// --- 关键配置 ---
// 最大渲染节点数：控制在 500-800 之间
const RENDER_LIMIT = 600;
// 最大渲染连线数：关键优化！防止Hub节点导致连线爆炸卡死
const MAX_VISIBLE_LINKS = 2000;

// 获取当前产业的数据源路径
function getIndustryDataSource() {
    const currentIndustry = window.currentIndustry || 'ai'; // 默认为AI产业
    const API_BASE = window.API_BASE || 'http://127.0.0.1:8000';
    
    if (currentIndustry === 'embodied') {
        return `${API_BASE}/static/data/embodied/graph_data.json`;
    } else if (currentIndustry === 'low_altitude') {
        return `${API_BASE}/static/data/low_altitude/graph_data.json`;
    } else if (currentIndustry === 'sea') {
        return `${API_BASE}/static/data/sea/graph_data.json`;
    } else if (currentIndustry === 'quantum') {
        return `${API_BASE}/static/data/quantum/graph_data.json`;
    } else if (currentIndustry === 'biology') {
        return `${API_BASE}/static/data/biology/graph_data.json`;
    } else if (currentIndustry === 'brain') {
        return `${API_BASE}/static/data/brain/graph_data.json`;
    } else if (currentIndustry === 'material') {
        return `${API_BASE}/static/data/material/graph_data.json`;
    } else {
        // 默认为AI产业
        return `${API_BASE}/static/data/ai/graph_data.json`;
    }
}

// 重置图谱模块的所有变量
function resetGraphVariables() {
    console.log('重置图谱模块变量...');
    
    // 重置数据和状态变量，但不重置Graph对象
    isGraphInit = false;
    allGraphData = { nodes: [], links: [] };
    adjacencyList = {};
    
    // 重置公司详情相关变量
    companyDetailTooltip = null;
    currentHoverNode = null;
    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }
    
    // 重置搜索输入框
    const searchInput = document.getElementById('node-search');
    if (searchInput) {
        searchInput.value = "";
    }
    
    // // 重置状态显示
    // const statusText = document.getElementById('status-text-db');
    // if (statusText) {
    //     statusText.innerText = "等待加载";
    // }
    
    // const statusDot = document.getElementById('status-dot-db');
    // if (statusDot) {
    //     statusDot.className = "w-2 h-2 rounded-full bg-gray-300";
    // }
    
    // 重置统计信息
    const totalEl = document.getElementById('stat-total-nodes');
    if (totalEl) {
        totalEl.innerText = "0";
    }
    
    // 不清空图谱容器，保留Graph对象以便重新加载数据
    console.log('图谱模块变量重置完成');
}

// 初始化图谱可视化
async function initGraphViz() {
    // 设置默认视图为图谱视图
    window.currentView = 'graph';
    
    const elem = document.getElementById('graph-container');
    const searchInput = document.getElementById('node-search');
    if(searchInput) searchInput.value = "";
    backupStatusEl = document.getElementById('graph-backup-status');
    
    // 确保容器有正确的高度
    adjustGraphContainerHeight();

    // 等待浏览器完成布局重绘，确保容器有正确的渲染尺寸
    // 否则 ForceGraph 初始化时可能读到 0 或错误的容器尺寸，导致画布异常、无法拖拽
    // 使用 rAF + setTimeout 组合确保跨浏览器兼容
    await new Promise(resolve => {
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                // 再等一个微任务周期，确保 flex 布局的父容器也完成了重排
                setTimeout(resolve, 50);
            });
        });
    });

    // 强制读取布局信息，触发回流确保尺寸已就绪
    const containerW = elem.offsetWidth;
    const containerH = elem.offsetHeight;
    console.log('ForceGraph 初始化前容器尺寸:', containerW, 'x', containerH);

    // 1. 初始化 ForceGraph 配置，显式设置画布尺寸防止读到0
    Graph = ForceGraph()(elem)
        .width(containerW > 0 ? containerW : window.innerWidth)
        .height(containerH > 0 ? containerH : window.innerHeight - 64)
        .backgroundColor('#ffffff')
        .nodeCanvasObject((node, ctx, globalScale) => {
            const label = node.properties && node.properties.name ? node.properties.name : (node.name || node.id);
            const displayText = label.length > 10 ? label.substring(0, 10) : label;

            // 节点大小根据连接数(val)动态变化
            const r = node.val ? Math.min(node.val, 10) : 4;

            ctx.beginPath();
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
            const group = (node.labels && node.labels[0]) || 'Unknown';
            
            // 确定节点颜色
            let nodeColor;
            if (group === '公司' && node.properties && node.properties.category) {
                // 公司节点使用自定义颜色方案
                // 统一分类名称，确保颜色一致
                const category = node.properties.category;
                let colorType = category;
                if (category === '其他国资' || category === '国有企业' || category === '事业单位' || category === '地方国企' || category === '未知') {
                    colorType = '其他国资';
                }
                nodeColor = getColor(colorType);
            } else {
                // 非公司节点使用默认颜色方案
                nodeColor = colorScale(group);
            }
            
            ctx.fillStyle = nodeColor;
            ctx.fill();

            // 只有当放大到一定程度才显示文字，优化性能
            if(globalScale > 1.5) {
                // 只有当label=环节的时候字体大小为8，其他情况为5
                const isRingNode = node.labels && (node.labels.includes('环节') || node.labels.includes('Root') );
                const fontSize = isRingNode ? 8 : 4;
                ctx.font = `bold ${fontSize}px Sans-Serif`;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillStyle = '#374151';
                ctx.shadowColor = 'rgba(255,255,255,0.8)';
                ctx.shadowBlur = 2;
                ctx.fillText(displayText, node.x, node.y);
                ctx.shadowBlur = 0;
            }
            // 交互区域
            node.__bckgDimensions = [r*2, r*2];
        })
        .nodePointerAreaPaint((node, color, ctx) => {
            ctx.fillStyle = color;
            ctx.beginPath();
            const r = node.val ? Math.min(node.val, 10) : 4;
            ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
            ctx.fill();
        })
        .linkColor(() => 'rgba(150,150,150,0.6)') // 稍微透明一点，显得不那么乱
        .linkWidth(0.5) // 【优化】线变细，提升性能且视觉清爽
        .linkCurvature(0) // 直线比曲线性能好一点点，且在大数据量下更干净
        // 【优化】物理引擎参数：让图尽快稳定下来，不要一直计算
        .d3AlphaDecay(0.04) // 增加衰减，让布局更快稳定（不抖动）
        .d3VelocityDecay(0.6) // 增加摩擦力
        .d3Force('charge', d3.forceManyBody().strength(-120)) // 斥力稍微加大
        .d3Force('link', d3.forceLink().distance(100))
        .onNodeClick(handleNodeInteraction) // 绑定交互事件
        .onNodeRightClick(handleNodeRightClick) // 绑定右键点击事件
        .onLinkClick(link => alert(`关系: ${link.type}`))
        .onNodeHover(handleNodeHover); // 添加鼠标悬浮事件

    // 2. 加载 JSON 数据
    try {
        const statusText = document.getElementById('status-text-db');
        if(statusText) statusText.innerText = "加载中...";

        await reloadGraphData(true);

        isGraphInit = true;

        // 数据加载完成后，执行适应居中，确保图谱在容器中心显示
        if(typeof zoomToFitAndCenter === 'function') zoomToFitAndCenter();

        // 延迟二次 resize 兜底：某些浏览器在隐藏→显示切换后，
        // 首帧的 offsetWidth/offsetHeight 可能尚未稳定，200ms 后再做一次矫正
        setTimeout(() => {
            if (Graph && isGraphForceDirectedViewActive()) {
                const c = document.getElementById('graph-container');
                if (c && c.offsetWidth > 0 && c.offsetHeight > 0) {
                    Graph.width(c.offsetWidth);
                    Graph.height(c.offsetHeight);
                    Graph.zoomToFit(400, 20);
                    console.log('延迟二次 resize 完成，容器尺寸:', c.offsetWidth, 'x', c.offsetHeight);
                }
            }
        }, 300);

        if(statusText) statusText.innerText = "加载完成";
        const statusDot = document.getElementById('status-dot-db');
        if(statusDot) statusDot.className = "w-2 h-2 rounded-full bg-green-500 animate-pulse";

        // 更新总数统计（显示真实总数）
        const totalEl = document.getElementById('stat-total-nodes');
        if(totalEl) totalEl.innerText = allGraphData.nodes.length.toLocaleString();

    } catch (error) {
        console.error("加载图谱数据失败:", error);
        const statusText = document.getElementById('status-text-db');
        if(statusText) statusText.innerText = "加载失败";
        const statusDot = document.getElementById('status-dot-db');
        if(statusDot) statusDot.className = "w-2 h-2 rounded-full bg-red-500";
    }
}

// 刷新图谱数据（重新拉取 graph_data.json 并渲染）
async function reloadGraphData(skipStatus = false, forceReload = false) {
    // 检查当前视图是否为知识图谱视图
    // 如果forceReload为true，则强制刷新（用于行业切换）
    // 否则，如果是旭日图视图，则阻止手动刷新操作
    if (!forceReload && isSunburstViewActive()) {
        console.log('当前为旭日图视图，无法执行"刷新图谱"操作');
        alert('请在知识图谱视图中使用此功能');
        return;
    }
    
    try {
        if(!skipStatus) {
            const statusText = document.getElementById('status-text-db');
            if(statusText) statusText.innerText = "刷新中...";
        }

        const dataSource = getIndustryDataSource();
        console.log(`加载产业数据源: ${dataSource}`);
        const resp = await fetch(dataSource, { cache: "no-cache" });
        if(!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        const nodes = data.nodes || [];
        const links = data.relationships || data.links || [];

        preprocessData(nodes, links);
        allGraphData = { nodes, links };

        const subset = getSmartInitialGraph(nodes, links, RENDER_LIMIT);
        renderSubset(subset);

        // 无论 Graph 是否初始化，都要更新图例和统计
        // Graph 未初始化时 renderSubset 会提前返回，此处确保图例一定会更新
        generateLegend(nodes);

        const totalEl = document.getElementById('stat-total-nodes');
        if(totalEl) totalEl.innerText = nodes.length.toLocaleString();

        if(!skipStatus) {
             const statusText = document.getElementById('status-text-db');
             if(statusText) statusText.innerText = "刷新完成";
        }
    } catch (err) {
        console.error("刷新图谱失败:", err);
        const statusText = document.getElementById('status-text-db');
        if(statusText) statusText.innerText = "刷新失败";
    }
}

// --- 数据预处理：计算度数和邻接表 ---
function preprocessData(nodes, links) {
    adjacencyList = {};
    const nodeDegree = {};

    // 初始化
    nodes.forEach(n => {
        adjacencyList[n.id] = [];
        nodeDegree[n.id] = 0;
    });

    // 遍历关系
    links.forEach(l => {
        const s = (l.source.id !== undefined) ? l.source.id : l.source;
        const t = (l.target.id !== undefined) ? l.target.id : l.target;

        // 记录度数
        if(nodeDegree[s] !== undefined) nodeDegree[s]++;
        if(nodeDegree[t] !== undefined) nodeDegree[t]++;

        // 记录邻居 (存 Link ID 或者直接存 Target ID)
        if(adjacencyList[s]) adjacencyList[s].push({ neighbor: t, link: l });
        if(adjacencyList[t]) adjacencyList[t].push({ neighbor: s, link: l });
    });

    // 把度数写入 Node 属性，用于渲染大小和排序
    nodes.forEach(n => {
        n.val = nodeDegree[n.id] ? Math.sqrt(nodeDegree[n.id]) + 2 : 3; // 视觉大小
        n.degree = nodeDegree[n.id] || 0; // 真实度数
    });
}

// --- 智能采样算法：让初始图更好看 ---
function getSmartInitialGraph(nodes, links, limit) {
    if (nodes.length <= limit) {
        return nodes; // 节点很少，直接全显
    }

    const selectedNodeIds = new Set();
    const resultNodes = [];

    // 1. 分组 (Stratified Sampling)
    // 按 Label 分组，每组选出 Degree 最高的 Top N
    const groups = {};
    nodes.forEach(n => {
        const g = (n.labels && n.labels[0]) || 'Other';
        if (!groups[g]) groups[g] = [];
        groups[g].push(n);
    });

    const groupKeys = Object.keys(groups);
    // 平均每组大概能分多少个名额
    const perGroupLimit = Math.floor((limit * 0.7) / groupKeys.length) || 1; // 增加Top节点的权重

    groupKeys.forEach(key => {
        // 按度数降序排列，选大V
        groups[key].sort((a, b) => b.degree - a.degree);
        // 取前 N 个
        const topNodes = groups[key].slice(0, perGroupLimit);
        topNodes.forEach(n => {
            selectedNodeIds.add(n.id);
            resultNodes.push(n);
        });
    });

    // 2. 补充邻居 (Breadth Expansion)
    // 为了让图连起来，遍历已选节点的邻居，加进来直到达到 Limit
    // 优先加已经选中节点的“共同邻居”

    // 这里简单处理：遍历已选列表，把它们的邻居加进来
    let i = 0;
    while (resultNodes.length < limit && i < resultNodes.length) {
        const seedNode = resultNodes[i];
        const neighbors = adjacencyList[seedNode.id] || [];

        // 随机选几个邻居加进来，而不是全部，防止单个大V把名额占光
        const sampleNeighbors = neighbors.length > 5 ? neighbors.slice(0, 5) : neighbors;

        for (let item of sampleNeighbors) {
            if (!selectedNodeIds.has(item.neighbor)) {
                // 找到这个邻居的原始 Node 对象
                const neighborNode = nodes.find(n => n.id == item.neighbor);
                if (neighborNode) {
                    selectedNodeIds.add(neighborNode.id);
                    resultNodes.push(neighborNode);
                }
                if (resultNodes.length >= limit) break;
            }
        }
        i++;
    }

    // 3. 如果还不够，随机补一点 (Random Fill)
    if (resultNodes.length < limit) {
        const remaining = limit - resultNodes.length;
        const unselected = nodes.filter(n => !selectedNodeIds.has(n.id));
        // 随机打乱取一部分
        for (let j = 0; j < remaining && j < unselected.length; j++) {
            resultNodes.push(unselected[j]);
        }
    }

    return resultNodes;
}

// 辅助函数：渲染数据子集
function renderSubset(subsetNodes) {
    if(!Graph) return;

    // 1. 获取子集节点的 ID 集合
    const subsetIds = new Set(subsetNodes.map(n => n.id));

    // 2. 只保留连接这些子集节点的关系 (Internal Links)
    let subsetLinks = allGraphData.links.filter(l => {
        const sId = (l.source.id !== undefined) ? l.source.id : l.source;
        const tId = (l.target.id !== undefined) ? l.target.id : l.target;
        return subsetIds.has(sId) && subsetIds.has(tId);
    });

    // 【关键优化】如果连线太多，强行截断！
    // 很多时候大V之间互联会导致连线数爆炸，为了流畅度必须舍弃一部分视觉效果不明显的线
    if (subsetLinks.length > MAX_VISIBLE_LINKS) {
        // 优先保留连接"当前视图内节点"的线，这里已经是subset了，所以随机截断或保留权重高的
        // 简单截断
        subsetLinks = subsetLinks.slice(0, MAX_VISIBLE_LINKS);
    }

    // 3. 渲染
    Graph.graphData({
        nodes: subsetNodes,
        links: subsetLinks
    });

    // 4. 更新图例和统计
    updateGraphStats(subsetNodes.length);
    generateLegend(subsetNodes);
}

// 检查当前是否为旭日图视图
function isSunburstViewActive() {
    const sunburstContainer = document.getElementById('sunburst-container');
    return sunburstContainer && !sunburstContainer.classList.contains('hidden');
}

/** 力导向知识图谱画布是否处于可见状态（用于侧栏操作限制） */
function isGraphForceDirectedViewActive() {
    const el = document.getElementById('graph-container');
    return !!(el && !el.classList.contains('hidden'));
}

// 仅看骨架：展示全部“环节”节点及它们之间的全部关系（不限制方向与关系类型）
function showSkeletonGraph() {
    // 检查当前视图是否为知识图谱视图
    if (!isGraphForceDirectedViewActive()) {
        console.log('当前非力导向知识图谱视图，无法执行"仅看骨架"操作');
        alert('请在知识图谱（力导向）视图中使用此功能');
        return;
    }
    
    if (!allGraphData || !allGraphData.nodes.length || !Graph) return;

    // 1. 筛选全部“环节”节点（不限制 level）
    const ringNodes = allGraphData.nodes.filter(n => n.labels &&  (n.labels.includes('环节') || n.labels.includes('Root') ));
    // 兼容：节点/关系端点可能混用 number/string，这里统一用字符串做匹配键
    const ringNodeByIdStr = new Map(ringNodes.map(n => [String(n.id), n]));

    // 2. 保留“环节”节点之间的全部关系
    // 为保证 ForceGraph 能稳定连线（避免 123 vs "123"），将 source/target 绑定为节点对象引用。
    const ringLinks = (allGraphData.links || []).flatMap(l => {
        const rawS = (l.source && l.source.id !== undefined) ? l.source.id : l.source;
        const rawT = (l.target && l.target.id !== undefined) ? l.target.id : l.target;
        const sNode = ringNodeByIdStr.get(String(rawS));
        const tNode = ringNodeByIdStr.get(String(rawT));
        if (!sNode || !tNode) return [];
        return [{ ...l, source: sNode, target: tNode }];
    });

    // 3. 仅计算当前视图的度数/大小（不覆盖全量 adjacencyList，保证任意视图双击都可展开）
    const degree = {};
    ringNodes.forEach(n => { degree[String(n.id)] = 0; });
    ringLinks.forEach(l => {
        const sId = String(l.source.id);
        const tId = String(l.target.id);
        if (degree[sId] !== undefined) degree[sId] += 1;
        if (degree[tId] !== undefined) degree[tId] += 1;
    });
    ringNodes.forEach(n => {
        const d = degree[String(n.id)] || 0;
        n.degree = d;
        n.val = Math.sqrt(d) + 2;
    });

    // 4. 渲染（不走 renderSubset 的连边截断逻辑）
    Graph.graphData({ nodes: ringNodes, links: ringLinks });
    updateGraphStats(ringNodes.length);
    generateLegend(ringNodes);
    if (typeof zoomToFitAndCenter === 'function') zoomToFitAndCenter();
}

// 生成图例
function generateLegend(nodes) {
    const labelCounts = {};
    nodes.forEach(n => {
        let group = (n.labels && n.labels[0]) || 'Unknown';
        // 对于公司节点，使用 category 作为分组依据
        if (group === '公司' && n.properties && n.properties.category) {
            // 统一分类名称，确保颜色一致
            const category = n.properties.category;
            if (category === '中央企业') {
                group = '中央企业';
            } else if (category === '其他国资' || category === '国有企业' || category === '事业单位' || category === '地方国企' || category === '未知') {
                group = '其他国资';
            } else if (category === '外资企业') {
                group = '外资企业';
            } else {
                group = '民营企业'; // 默认归为民营企业
            }
        }
        if(!labelCounts[group]) labelCounts[group] = 0;
        labelCounts[group]++;
    });
    updateLegendUI(labelCounts);
}

// --- 交互逻辑复刻 ---

let lastClickTime = 0; // 用于模拟双击
let selectedNodeId = null;

// 节点悬浮事件处理
function handleNodeHover(node, prevNode) {
    
    // 清除之前的定时器
    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }
    
    // 如果移出节点，隐藏工具提示
    if (!node) {
        hideCompanyDetailTooltip();
        currentHoverNode = null;
        return;
    }
    
    // 如果移入新节点，记录当前节点
    currentHoverNode = node;
    
    // 延迟显示工具提示（避免鼠标快速移动时频繁显示）
    tooltipTimeout = setTimeout(() => {
        // 检查是否还是同一个节点
        if (currentHoverNode === node) {
            // 检查当前视图是否为图谱视图
            const isGraphView = window.currentView === 'graph';
            
            // 只对公司节点显示详情，并且只在图谱视图中显示
            const isCompany = node.labels && node.labels.includes('公司');
            if (isCompany && isGraphView) {
                //显示属性面板
                showProperties(node, `节点: ${node.properties.name || node.id}`);
               
                showCompanyDetailTooltip(node);
            } else {
                hideCompanyDetailTooltip();
            }
        }
    }, 300); // 300ms延迟
    
}

// 显示公司详情工具提示
async function showCompanyDetailTooltip(node) {
    console.log('showCompanyDetailTooltip called for node:', node);
    
    // 检查当前视图是否为图谱视图或旭日图视图
    const isGraphView = window.currentView === 'graph';
    const isSunburstView = window.currentView === 'sunburst';
    
    if (!isGraphView && !isSunburstView) {
        console.log('当前不是图谱视图或旭日图视图，不显示公司详情弹窗');
        return;
    }
    
    // 旭日图视图使用ECharts内置的tooltip，不显示自定义悬浮框
    if (isSunburstView) {
        console.log('旭日图视图，使用ECharts内置tooltip，不显示自定义悬浮框');
        return;
    }
    
    // 获取公司信用代码
    const creditCode = node.properties?.credit_code || node.properties?.social_credit_code || node.properties?.creditCode;
    
    if (!creditCode) {
        console.log('No credit code found, showing basic info');
        // 如果工具提示不存在，创建它
        if (!companyDetailTooltip) {
            console.log('Creating tooltip...');
            createCompanyDetailTooltip();
        }
    
        // 如果没有信用代码，显示基本信息
        updateCompanyDetailTooltip(node, null);
        return;
    }
    
    try {
        // 调用API获取公司详情 - 使用标准API工具函数
        const apiUrl = `https://sasac-rc.com/api/sdServerUrl/company/enterprise/detail/baseInfo?socialCreditCode=${encodeURIComponent(creditCode)}`;
        
        // 使用外部API调用函数
        const response = await fetch(apiUrl, {
            method: 'GET'
        });
        
        // 再次检查当前视图是否为图谱视图或旭日图视图
        const isGraphView = window.currentView === 'graph';
        const isSunburstView = window.currentView === 'sunburst';
        if (!isGraphView && !isSunburstView) {
            console.log('当前不是图谱视图或旭日图视图，不显示公司详情弹窗');
            return;
        }
        
        // 旭日图视图使用ECharts内置的tooltip，不显示自定义悬浮框
        if (isSunburstView) {
            console.log('旭日图视图，使用ECharts内置tooltip，不显示自定义悬浮框');
            return;
        }
        
        // 如果工具提示不存在，创建它
        if (!companyDetailTooltip) {
            console.log('Creating tooltip...');
            createCompanyDetailTooltip();
        }
        

        if (response.ok) {
            const data = await response.json();
            updateCompanyDetailTooltip(node, data.result);
        } else {
            // API调用失败，显示基本信息
            updateCompanyDetailTooltip(node, null);
        }
    } catch (error) {
        console.error('获取公司详情失败:', error);
        updateCompanyDetailTooltip(node, null);
    }
}

// 创建公司详情工具提示
function createCompanyDetailTooltip() {
    companyDetailTooltip = document.createElement('div');
    companyDetailTooltip.id = 'company-detail-tooltip';
    companyDetailTooltip.className = 'fixed bg-white border border-gray-300 rounded-lg shadow-xl p-4 z-[9999] max-w-sm hidden';
    companyDetailTooltip.style.pointerEvents = 'none';
    // 使用 fixed 定位，避免被容器 overflow-hidden 影响
    companyDetailTooltip.style.position = 'fixed';
    companyDetailTooltip.style.left = '0';
    companyDetailTooltip.style.top = '0';
    
    // 将弹窗添加到 body，而不是 graph-container
    document.body.appendChild(companyDetailTooltip);
}

// 更新工具提示位置
function updateTooltipPosition(node) {
    if (!companyDetailTooltip || companyDetailTooltip.classList.contains('hidden')) {
        return;
    }
    
    const tooltip = companyDetailTooltip;
    
    // 等待 DOM 渲染完成后再设置位置
    requestAnimationFrame(() => {
        // 根据当前视图选择容器
        let container = null;
        const isGraphView = window.currentView === 'graph';
        const isSunburstView = window.currentView === 'sunburst';
        
        if (isGraphView) {
            container = document.getElementById('graph-container');
        } else if (isSunburstView) {
            container = document.getElementById('sunburst-container');
        }
        
        if (!container) {
            console.warn('容器未找到，当前视图:', window.currentView);
            return;
        }
        
        // 获取容器的位置
        const containerRect = container.getBoundingClientRect();
        
        // 弹窗固定在容器内的左上角，距离容器左边距和上边距10像素
        const left = containerRect.left + 10;
        const top = containerRect.top + 10;
        
        console.log('Tooltip position fixed at:', { left, top, containerRect, view: window.currentView });
        
        // 使用 setProperty 确保样式优先级
        tooltip.style.setProperty('left', `${left}px`, 'important');
        tooltip.style.setProperty('top', `${top}px`, 'important');
    });
}

// 更新公司详情工具提示内容
function updateCompanyDetailTooltip(node, apiData) {
    console.log('updateCompanyDetailTooltip called:', { node, apiData });
    
    if (!companyDetailTooltip) {
        console.log('companyDetailTooltip is null');
        return;
    }
    
    const tooltip = companyDetailTooltip;
    const companyName = node.properties?.name || node.id;
    const creditCode = node.properties?.credit_code || node.properties?.social_credit_code || node.properties?.creditCode;
    
    console.log('Tooltip element:', tooltip);
    console.log('Tooltip classList:', tooltip.classList);
    console.log('Credit code:', creditCode);
    
    let html = `
        <div class="mb-3">
            <h3 class="font-bold text-lg text-gray-800 mb-1">${companyName}</h3>
        </div>`;
    
    console.log('API data:', apiData);
    
    // 判断逻辑：如果 creditCode 为空，则只显示企业名和企业类型
    if (!creditCode) {
        console.log('Credit code is empty, showing only company name and category');
        const category = node.properties?.category || '未知';
        
        // 辅助函数：检查字段值是否有效（非空、非"未知"）
        function isValidField(value) {
            return value && value.trim() && value.trim() !== '未知' && value.trim() !== 'null' && value.trim() !== 'undefined';
        }
        
        // 收集要显示的字段
        const fields = [];
        
        // 企业类型
        if (category && isValidField(category)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">企业类型:</span>
                    <span class="font-medium text-gray-800">${category}</span>
                </div>
            `);
        }
        
        // 如果有字段显示，则添加到HTML
        if (fields.length > 0) {
            html += `
                <div class="space-y-2 text-sm">
                    ${fields.join('')}
                    <div class="text-xs text-gray-500 italic mt-2">
                        <i class="fas fa-info-circle mr-1"></i> 无信用代码，无法获取详细信息
                    </div>
                </div>
            `;
        } else {
            html += `
                <div class="space-y-2 text-sm">
                    <div class="text-xs text-gray-500 italic">
                        <i class="fas fa-info-circle mr-1"></i> 无信用代码，无法获取详细信息
                    </div>
                </div>
            `;
        }
    } else if (apiData) {
        // creditCode 不为空且有 API 数据，显示完整信息
        console.log('Credit code exists and API data available, showing full info');
        
        // 辅助函数：检查字段值是否有效（非空、非"未知"）
        function isValidField(value) {
            return value && value.trim() && value.trim() !== '未知' && value.trim() !== 'null' && value.trim() !== 'undefined';
        }
        
        // 收集要显示的字段
        const fields = [];
        
        // 企业名称
        if (apiData.name && isValidField(apiData.name)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">企业名称:</span>
                    <span class="font-medium text-gray-800">${apiData.name}</span>
                </div>
            `);
        }
        
        // 所属行业
        if (apiData.industry && isValidField(apiData.industry)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">所属行业:</span>
                    <span class="font-medium text-gray-800">${apiData.industry}</span>
                </div>
            `);
        }
        
        // 法定代表人
        if (apiData.legalPerson && isValidField(apiData.legalPerson)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">法定代表人:</span>
                    <span class="font-medium text-gray-800">${apiData.legalPerson}</span>
                </div>
            `);
        }
        
        // 注册资本
        if (apiData.paidCapital && isValidField(apiData.paidCapital)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">注册资本:</span>
                    <span class="font-medium text-gray-800">${apiData.paidCapital}</span>
                </div>
            `);
        }
        
        // 成立日期
        if (apiData.incorporationDate && isValidField(apiData.incorporationDate)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">成立日期:</span>
                    <span class="font-medium text-gray-800">${apiData.incorporationDate}</span>
                </div>
            `);
        }
        
        // 如果有字段显示，则添加到HTML
        if (fields.length > 0) {
            html += `
                <div class="space-y-2 text-sm">
                    ${fields.join('')}
                </div>
            `;
        } else {
            html += `
                <div class="space-y-2 text-sm">
                    <div class="text-gray-500 italic">
                        暂无详细信息
                    </div>
                </div>
            `;
        }
    } else {
        // creditCode 不为空但无 API 数据，显示基本信息（包括信用代码）
        console.log('Credit code exists but no API data, showing basic info with credit code');
        
        // 辅助函数：检查字段值是否有效（非空、非"未知"）
        function isValidField(value) {
            return value && value.trim() && value.trim() !== '未知' && value.trim() !== 'null' && value.trim() !== 'undefined';
        }
        
        // 收集要显示的字段
        const fields = [];
        
        // 企业类型
        const category = node.properties?.category || '未知';
        if (category && isValidField(category)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">企业类型:</span>
                    <span class="font-medium text-gray-800">${category}</span>
                </div>
            `);
        }
        
        // 企业介绍
        const description = node.properties?.description || node.properties?.企业介绍 || '暂无描述';
        if (description && isValidField(description) && description !== '暂无描述') {
            fields.push(`
                <div class="mt-2">
                    <div class="text-gray-600 mb-1">企业介绍:</div>
                    <div class="text-gray-700 text-xs max-h-20 overflow-y-auto">${description}</div>
                </div>
            `);
        }
        
        // 信用代码
        if (creditCode && isValidField(creditCode)) {
            fields.push(`
                <div class="flex justify-between">
                    <span class="text-gray-600">信用代码:</span>
                    <span class="font-medium text-gray-800">${creditCode}</span>
                </div>
            `);
        }
        
        // 如果有字段显示，则添加到HTML
        if (fields.length > 0) {
            html += `
                <div class="space-y-2 text-sm">
                    ${fields.join('')}
                    <div class="text-xs text-gray-500 italic mt-2">
                        <i class="fas fa-info-circle mr-1"></i> 点击节点查看完整属性
                    </div>
                </div>
            `;
        } else {
            html += `
                <div class="space-y-2 text-sm">
                    <div class="text-xs text-gray-500 italic">
                        <i class="fas fa-info-circle mr-1"></i> 点击节点查看完整属性
                    </div>
                </div>
            `;
        }
    }
    
    tooltip.innerHTML = html;
    console.log('Removing hidden class from tooltip');
    tooltip.classList.remove('hidden');
    console.log('Tooltip classList after removing hidden:', tooltip.classList);
    console.log('Tooltip style.display:', tooltip.style.display);
    console.log('Tooltip computed style:', window.getComputedStyle(tooltip).display);
    
    // 使用节点中心位置更新工具提示位置
    updateTooltipPosition(node);
}

// 隐藏公司详情工具提示
function hideCompanyDetailTooltip() {
    if (companyDetailTooltip) {
        companyDetailTooltip.classList.add('hidden');
    }
}

// 节点交互 (单击 / 双击)
function handleNodeInteraction(node) {
    const now = Date.now();

    // 点击节点时隐藏公司详情弹窗
    hideCompanyDetailTooltip();

    // 检测双击 (300ms 间隔)
    if (now - lastClickTime < 300) {
        // === 双击逻辑：展开邻居 ===
        expandNode(node);
    } else {
        // 检查是否是公司节点
        const isCompany = node.labels && node.labels.includes('公司');
        
        if (isCompany) {
            // 公司节点：进入企业主页
            showCompanyPage(node);
        } else {
            // 非公司节点：显示属性面板
            showProperties(node, `节点: ${node.properties.name || node.id}`);
            // 聚焦到节点
            Graph.centerAt(node.x, node.y, 1000);
            Graph.zoom(4, 2000);
        }
    }
    lastClickTime = now;
}

// 节点右键点击事件处理 - 进入企业主页
function handleNodeRightClick(node, event) {
    // 阻止默认的右键菜单
    if (event) {
        event.preventDefault();
    }
    
    // 点击节点时隐藏公司详情弹窗
    hideCompanyDetailTooltip();
    
    // 检查是否是公司节点
    const isCompany = node.labels && node.labels.includes('公司');
    if (!isCompany) {
        console.log('非公司节点，不显示企业主页');
        return;
    }
    
    // 显示企业主页
    showCompanyPage(node);
}

// 企业主页相关函数已移动到 company.js 模块中

// 展开节点：把该节点的邻居从 allGraphData 加载到当前视图
function expandNode(centerNode) {
    // 1. 获取当前画布上的数据
    const { nodes: currentNodes, links: currentLinks } = Graph.graphData();
    const currentIds = new Set(currentNodes.map(n => n.id));

    // 2. 在全量数据中查找邻居
    // 使用预处理好的邻接表加速
    const neighborsData = adjacencyList[centerNode.id] || [];

    const newNodes = [];
    const newLinks = [];
    let addedCount = 0;
    const MAX_EXPAND = 30; // 【优化】一次展开不要太多，30个足够了

    // 随机打乱一下邻居，避免每次展开都是固定的前几个
    const shuffledNeighbors = neighborsData.sort(() => 0.5 - Math.random());

    for (let item of shuffledNeighbors) {
        if (addedCount >= MAX_EXPAND) break;

        // 处理节点
        if (!currentIds.has(item.neighbor)) {
            const neighborNode = allGraphData.nodes.find(n => n.id == item.neighbor);
            if (neighborNode) {
                // 给个初始位置，让它从中心弹出来
                neighborNode.x = centerNode.x + (Math.random() - 0.5) * 10;
                neighborNode.y = centerNode.y + (Math.random() - 0.5) * 10;

                newNodes.push(neighborNode);
                currentIds.add(item.neighbor); // 标记已加
                addedCount++;
            }
        }

        // 处理连线
        const linkExists = currentLinks.some(l => l.id === item.link.id);
        if (!linkExists) {
             newLinks.push(item.link);
        }
    }

    if (newNodes.length > 0 || newLinks.length > 0) {
        // 如果加入后连线总数超标，也需要截断，防止无限膨胀
        let finalLinks = [...currentLinks, ...newLinks];
        if (finalLinks.length > MAX_VISIBLE_LINKS + 500) { // 允许稍微超一点
             // 如果太多了，就不加那么多线了，只保留必要的
             finalLinks = finalLinks.slice(0, MAX_VISIBLE_LINKS + 500);
        }

        Graph.graphData({
            nodes: [...currentNodes, ...newNodes],
            links: finalLinks
        });

        // 更新统计
        updateGraphStats(currentNodes.length + newNodes.length);
        generateLegend([...currentNodes, ...newNodes]);
    }
}

// 更新统计数字
function updateGraphStats(count) {
    const el = document.getElementById('stat-current-nodes');
    if(count === undefined && Graph && Graph.graphData()) {
        count = Graph.graphData().nodes.length;
    }
    if(el) el.innerText = count;
}

// 重置全图 (恢复到智能采样的初始态)
function resetGraph() {
    // 检查当前视图是否为知识图谱视图
    if (!isGraphForceDirectedViewActive()) {
        console.log('当前非力导向知识图谱视图，无法执行"重置全图"操作');
        alert('请在知识图谱（力导向）视图中使用此功能');
        return;
    }
    
    if(!isGraphInit) return;
    const initialSubset = getSmartInitialGraph(allGraphData.nodes, allGraphData.links, RENDER_LIMIT);
    renderSubset(initialSubset);
    zoomToFitAndCenter();
}

// 内存搜索功能
function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

const handleSearchInput = debounce(function(val) {
    const suggestions = document.getElementById('search-suggestions');
    if (!suggestions) return;

    if (!val || val.trim() === "") {
        suggestions.classList.add('hidden');
        return;
    }

    const term = val.toLowerCase();

    // 在全量数据 allGraphData 中搜
    const matches = allGraphData.nodes.filter(n => {
        const name = (n.properties && n.properties.name) ? n.properties.name.toString() : "";
        return name.toLowerCase().includes(term);
    }).slice(0, 10);

    if (matches.length > 0) {
        // 检查当前视图
        const sunburstContainer = document.getElementById('sunburst-container');
        const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
        
        suggestions.innerHTML = matches.map(n => {
            const name = (n.properties && n.properties.name) ? n.properties.name : `Node ${n.id}`;
            const group = (n.labels && n.labels[0]) || 'Unknown';
            
            // 根据当前视图决定点击事件
            const onClickHandler = isSunburstView ? 
                `handleSunburstSearchClick('${n.id}')` : 
                `focusOnNode('${n.id}')`;
                
            return `
            <div class="suggestion-item px-4 py-2 cursor-pointer border-b border-gray-300 last:border-0 hover:bg-gray-100 transition"
                 onclick="${onClickHandler}">
                 <div class="font-bold text-gray-800">${name}</div>
                 <div class="text-xs text-gray-500">${group}</div>
            </div>
        `}).join('');
        suggestions.classList.remove('hidden');
    } else {
        suggestions.innerHTML = `<div class="px-4 py-2 text-gray-500 text-sm">无相关节点</div>`;
        suggestions.classList.remove('hidden');
    }
}, 300);

// 搜索聚焦：清除当前图，只显示目标节点及其邻居
function focusOnNode(nodeId) {
    const suggestions = document.getElementById('search-suggestions');
    if(suggestions) suggestions.classList.add('hidden');

    const centerNode = allGraphData.nodes.find(n => n.id == nodeId);

    if (centerNode) {
        // 找出所有与该节点相连的节点 (1度邻居)
        const neighborItems = adjacencyList[centerNode.id] || [];
        const subsetIds = new Set();
        subsetIds.add(centerNode.id);

        neighborItems.forEach(item => subsetIds.add(item.neighbor));

        const subsetNodes = allGraphData.nodes.filter(n => subsetIds.has(n.id));

        renderSubset(subsetNodes);

        setTimeout(() => {
            const renderedNode = Graph.graphData().nodes.find(n => n.id == nodeId);
            if(renderedNode) {
                Graph.centerAt(renderedNode.x, renderedNode.y, 1000);
                Graph.zoom(4, 2000);
                showProperties(renderedNode, `节点: ${renderedNode.properties.name || renderedNode.id}`);
            }
        }, 500);
    }
}

// UI 辅助：显示属性 + 编辑/删除
function showProperties(node, title) {
    document.getElementById('panel-legend').classList.add('hidden');
    document.getElementById('panel-properties').classList.remove('hidden');
    const container = document.getElementById('node-properties-content');
    selectedNodeId = node.id;
    const props = node.properties || {};
    const propsStr = JSON.stringify(props, null, 2);
    let html = `<div class="mb-2 font-bold text-gray-800 border-b border-gray-300 pb-1">${title}</div>`;
    html += `<div class="text-[11px] text-gray-500 mb-2">ID: ${node.id} | Label: ${(node.labels && node.labels[0]) || ''}</div>`;
    html += `<textarea id="node-props-editor" class="w-full h-40 bg-gray-50 text-gray-800 text-xs font-mono p-2 rounded border border-gray-300" spellcheck="false">${propsStr}</textarea>`;
    html += `<div class="flex gap-2 mt-2">
                <button onclick="saveSelectedNode()" class="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs px-2 py-1 rounded">保存属性</button>
                <button onclick="deleteSelectedNode()" class="flex-1 bg-red-600 hover:bg-red-500 text-white text-xs px-2 py-1 rounded">删除节点</button>
             </div>
             <div id="node-edit-status" class="text-[11px] text-gray-500 mt-1"></div>`;
    container.innerHTML = html;
}

function showLegendPanel() {
    document.getElementById('panel-properties').classList.add('hidden');
    document.getElementById('panel-legend').classList.remove('hidden');
}

async function saveSelectedNode() {
    const statusEl = document.getElementById('node-edit-status');
    const textarea = document.getElementById('node-props-editor');
    if (!selectedNodeId || !textarea) {
        if (statusEl) statusEl.innerText = '未选中节点';
        return;
    }
    let props;
    try {
        props = JSON.parse(textarea.value);
    } catch (e) {
        if (statusEl) statusEl.innerText = 'JSON 解析失败，请检查格式';
        return;
    }
    try {
        // 获取当前产业
        const currentIndustry = window.currentIndustry || 'ai';
        
        const resp = await fetch(`${API_BASE}/api/graph_node_update`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                id: selectedNodeId, 
                properties: props,
                industry: currentIndustry
            })
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            if (statusEl) statusEl.innerText = data.message || '保存失败';
            return;
        }
        if (statusEl) statusEl.innerText = `保存成功（产业：${data.industry || currentIndustry}），刷新图谱可见`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `保存失败: ${err.message}`;
    }
}

async function deleteSelectedNode() {
    const statusEl = document.getElementById('node-edit-status');
    if (!selectedNodeId) {
        if (statusEl) statusEl.innerText = '未选中节点';
        return;
    }
    if (!confirm('确定删除该节点及其关联关系？')) return;
    try {
        // 获取当前产业
        const currentIndustry = window.currentIndustry || 'ai';
        
        const resp = await fetch(`${API_BASE}/api/graph_node_delete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                id: selectedNodeId,
                industry: currentIndustry
            })
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            if (statusEl) statusEl.innerText = data.message || '删除失败';
            return;
        }
        if (statusEl) statusEl.innerText = `删除成功（产业：${data.industry || currentIndustry}）：节点-${data.removed_nodes}，关系-${data.removed_relationships}。请刷新图谱。`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `删除失败: ${err.message}`;
    }
}

async function backupGraph() {
    const statusEl = backupStatusEl || document.getElementById('graph-backup-status');
    if (statusEl) statusEl.innerText = '备份中...';
    
    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    try {
        const resp = await fetch(`${API_BASE}/api/graph_backup`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                industry: currentIndustry
            })
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            if (statusEl) statusEl.innerText = data.message || '备份失败';
            return;
        }
        if (statusEl) statusEl.innerText = `备份成功：${data.file}（产业：${data.industry || currentIndustry}）`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `备份失败: ${err.message}`;
    }
}

async function downloadGraphJson() {
    const statusEl = document.getElementById('graph-export-status');
    if (statusEl) statusEl.innerText = '导出中...';
    
    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    try {
        const resp = await fetch(`${API_BASE}/api/graph_export?industry=${encodeURIComponent(currentIndustry)}`, {method: 'GET'});
        if (!resp.ok) {
            const errText = await resp.text();
            if (statusEl) statusEl.innerText = `导出失败: ${errText || resp.status}`;
            return;
        }
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `graph_data_${currentIndustry}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
        if (statusEl) statusEl.innerText = `导出成功（产业：${currentIndustry}）`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `导出失败: ${err.message}`;
    }
}

function zoomToFitAndCenter() {
    // 检查当前视图是否为知识图谱视图
    if (!isGraphForceDirectedViewActive()) {
        console.log('当前非力导向知识图谱视图，无法执行"适应居中"操作');
        return;
    }
    
    if(Graph) {
        const c = document.getElementById('graph-container');
        if(c) {
            const w = c.offsetWidth;
            const h = c.offsetHeight;
            // 防止容器尺寸为 0 导致 ForceGraph 异常
            if (w > 0 && h > 0) {
                Graph.width(w);
                Graph.height(h);
                Graph.zoomToFit(400, 20);
            } else {
                // 容器尺寸为 0，延迟重试
                console.warn('zoomToFitAndCenter: 容器尺寸为0，延迟重试', w, h);
                setTimeout(() => {
                    const w2 = c.offsetWidth;
                    const h2 = c.offsetHeight;
                    if (w2 > 0 && h2 > 0) {
                        Graph.width(w2);
                        Graph.height(h2);
                        Graph.zoomToFit(400, 20);
                    }
                }, 200);
            }
        }
    }
}

function updateLegendUI(counts) {
    const container = document.getElementById('graph-legend');
    if(!container) return;

    container.innerHTML = '';
    
    // 定义排序顺序
    const order = ['Root', '环节', '产品', '中央企业', '其他国资', '民营企业', '外资企业'];
    
    // 按照指定顺序排序标签
    const sortedLabels = Object.keys(counts).sort((a, b) => {
        const indexA = order.indexOf(a);
        const indexB = order.indexOf(b);
        
        // 如果都在顺序列表中，按顺序排序
        if (indexA !== -1 && indexB !== -1) {
            return indexA - indexB;
        }
        // 如果只有a在顺序列表中，a排在前面
        if (indexA !== -1) {
            return -1;
        }
        // 如果只有b在顺序列表中，b排在前面
        if (indexB !== -1) {
            return 1;
        }
        // 都不在顺序列表中，按字母顺序排序
        return a.localeCompare(b);
    });
    
    sortedLabels.forEach(label => {
        const item = document.createElement('div');
        item.className = 'legend-item text-gray-700 p-2 rounded mb-1 flex justify-between items-center text-xs cursor-pointer';
        
        // 确定图例颜色
        let legendColor;
        if (label === '中央企业' || label === '其他国资' || label === '民营企业' || label === '外资企业') {
            legendColor = getColor(label);
        } else {
            legendColor = colorScale(label);
        }
        
        item.innerHTML = `<div class="flex items-center"><span class="w-3 h-3 rounded-full mr-2" style="background-color: ${legendColor};"></span><span>${label}</span></div><span class="bg-gray-200 px-1.5 rounded-full text-[10px] text-gray-700">${counts[label]}</span>`;
        // 点击图例：筛选该类型的 Top N 节点显示，而不是全显防止卡死
        item.onclick = () => {
             const typeNodes = allGraphData.nodes.filter(n => {
                 let group = (n.labels && n.labels[0]) || 'Unknown';
                 // 对于公司节点，使用 category 作为分组依据
                 if (group === '公司' && n.properties && n.properties.category) {
                     // 统一分类名称，确保筛选正确
                     const category = n.properties.category;
                     if (category === '中央企业') {
                         group = '中央企业';
                     } else if (category === '其他国资' || category === '国有企业' || category === '事业单位' || category === '地方国企' || category === '未知') {
                         group = '其他国资';
                     } else if (category === '外资企业') {
                         group = '外资企业';
                     } else {
                         group = '民营企业';
                     }
                 }
                 return group === label;
             })
             // 排序并取 Top，防止点击大类卡死
             .sort((a,b) => (b.val || 0) - (a.val || 0))
             .slice(0, RENDER_LIMIT);

             renderSubset(typeNodes);
        };
        container.appendChild(item);
    });
}

// 调整图谱容器高度
function adjustGraphContainerHeight() {
    const graphContainer = document.getElementById('graph-container');
    const viewGraph = document.getElementById('view-graph');
    
    if (!graphContainer || !viewGraph) return;
    
    // 与主内容区同高（header 以下），勿用 100vh，否则产业链/图谱等右侧区域底部会被裁切
    viewGraph.style.height = '100%';
    viewGraph.style.minHeight = '0';
    viewGraph.style.maxHeight = '100%';
    
    // 设置图谱容器高度
    graphContainer.style.height = '100%';
    graphContainer.style.minHeight = '400px'; // 最小高度
    
    // 如果ForceGraph已初始化，更新其尺寸
    if (Graph) {
        Graph.width(graphContainer.offsetWidth);
        Graph.height(graphContainer.offsetHeight);
    }
    
    console.log('Graph container adjusted:', {
        width: graphContainer.offsetWidth,
        height: graphContainer.offsetHeight,
        parentHeight: viewGraph.offsetHeight
    });
}

// 窗口大小变化时重新调整高度
window.addEventListener('resize', function() {
    adjustGraphContainerHeight();
});

// 页面加载完成后调整高度
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', adjustGraphContainerHeight);
} else {
    adjustGraphContainerHeight();
}

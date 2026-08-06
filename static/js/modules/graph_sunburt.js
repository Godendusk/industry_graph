// 旭日图相关变量
let sunburstChart = null;
let isSunburstInitialized = false;
let isSunburstFullscreen = false; // 标记是否处于全屏放大模式
let companyNodeCounter = 0; // 全局企业节点计数器，用于控制label显示
let totalCompanyNodes = 0; // 全局企业节点总数

// 全屏模式下鼠标滚轮缩放及圆心拖动平移相关变量
let sunburstZoomLevel = 1.0;
const SUNBURST_ZOOM_MIN = 0.4;
const SUNBURST_ZOOM_MAX = 3.0;
const SUNBURST_ZOOM_STEP = 0.1;
const SUNBURST_BASE_OUTER_RADIUS = 94; // 基准外半径百分比
let sunburstIsDragging = false;
let sunburstDragLastX = 0;
let sunburstDragLastY = 0;
let sunburstCenterX = 50; // 当前中心 left%
let sunburstCenterY = 50; // 当前中心 top%
let sunburstDragPendingUpdate = false; // 是否有待处理的拖动更新
let sunburstPendingCenterX = 50; // 待处理的中心X
let sunburstPendingCenterY = 50; // 待处理的中心Y
let sunburstAllCompanyNodes = []; // 所有公司节点引用，用于缩放时动态调整label显示
let sunburstTreeData = null; // 树数据引用，用于缩放时重渲染label
// 全屏模式下各层级的基准配置（含样式，参考 sunburst_2k_v7.html）
const SUNBURST_BASE_LEVELS = [
    {},
    {
        r0_pct: 0, r_pct: 10,
        itemStyle: { color: '#364A67', borderWidth: 2 },
        label: { color: '#FFFFFF', position: 'center', rotate: 'tangential' }
    },
    {
        r0_pct: 10, r_pct: 25,
        itemStyle: { color: '#456DA1' },
        label: { color: '#FFFFFF', rotate: 'tangential' }
    },
    {
        r0_pct: 25, r_pct: 40,
        itemStyle: { color: '#6D90BB' },
        label: { color: '#FFFFFF', position: 'inside', padding: 3, silent: false }
    },
    {
        r0_pct: 40, r_pct: 60,
        itemStyle: { color: '#AEC4DF' },
        label: { color: '#000000', position: 'inside', padding: 3, silent: false }
    },
    {
        // 最后一层：叶子节点 (公司)
        r0_pct: 60, r_pct: 94,
        itemStyle: { borderWidth: 0 }
    }
];

// 键盘导航相关变量
let currentSunburstNodePath = []; // 当前选中节点的路径（从根节点到当前节点）
let currentSunburstNodeIndex = -1; // 当前选中节点在路径中的索引
let allMatchedPaths = []; // 所有匹配的节点路径
let currentPathIndex = -1; // 当前显示的路径索引

// 获取当前产业的数据源路径
function getIndustryDataSource() {
    const currentIndustry = window.currentIndustry || 'ai'; // 默认为AI产业
    // const API_BASE = window.API_BASE || 'http://127.0.0.1:8000';
    
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

// 重置旭日图模块的所有变量
function resetSunburstVariables() {
    console.log('重置旭日图模块变量...');
    
    // 重置状态变量，但不重置sunburstChart对象
    isSunburstInitialized = false;
    isSunburstFullscreen = false;
    companyNodeCounter = 0;
    totalCompanyNodes = 0;
    
    // 重置键盘导航变量
    currentSunburstNodePath = [];
    currentSunburstNodeIndex = -1;
    allMatchedPaths = [];
    currentPathIndex = -1;
    
    // 重置搜索输入框
    const searchInput = document.getElementById('sunburst-search-input');
    if (searchInput) {
        searchInput.value = "";
    }
    
    // 重置搜索结果
    const resultsDiv = document.getElementById('sunburst-search-results');
    if (resultsDiv) {
        resultsDiv.innerHTML = "";
        resultsDiv.classList.add('hidden');
    }
    
    console.log('旭日图模块变量重置完成');
}

// 切换视图函数
function switchToSunburst() {
    console.log('切换到旭日图视图');
    if (typeof exitChainPanoramaFullscreen === 'function') exitChainPanoramaFullscreen();
    
    // 记录旭日图切换日志（系统自动切换时抑制）
    if (typeof uploadActionLog === 'function' && !window.suppressActionLog) {
        uploadActionLog('产业洞察-切换视图-旭日图', { "view": "sunburst", "industry": window.currentIndustry || 'ai' });
    }
    
    // 设置当前视图变量
    window.currentView = 'sunburst';
    window.graphVizSubView = 'sunburst';
    
    // 隐藏图谱容器和思维导图容器
    const graphContainer = document.getElementById('graph-container');
    const sunburstContainer = document.getElementById('sunburst-container');
    const mindmapContainer = document.getElementById('mindmap-container');
    const sunburstChartDiv = document.getElementById('sunburst-chart');
    
    if (graphContainer) {
        graphContainer.classList.add('hidden');
    }
    
    // 隐藏思维导图容器并恢复其样式（以防之前是从思维导图切换过来的）
    if (mindmapContainer) {
        mindmapContainer.classList.add('hidden');
        // 恢复思维导图容器的默认样式
        mindmapContainer.style.width = '';
        mindmapContainer.style.height = '';
        mindmapContainer.style.display = '';
        mindmapContainer.style.flexDirection = '';
        mindmapContainer.style.position = '';
        mindmapContainer.style.top = '';
        mindmapContainer.style.left = '';
        mindmapContainer.style.zIndex = '';
        mindmapContainer.style.backgroundColor = '';
        
        const mindmapChartDiv = document.getElementById('mindmap-chart');
        if (mindmapChartDiv) {
            mindmapChartDiv.style.flex = '';
            mindmapChartDiv.style.height = '';
            mindmapChartDiv.style.width = '';
        }
    }
    
    const chainContainer = document.getElementById('chain-panorama-container');
    if (chainContainer) {
        chainContainer.classList.add('hidden');
        chainContainer.style.display = '';
        chainContainer.style.width = '';
        chainContainer.style.height = '';
        chainContainer.style.flexDirection = '';
        chainContainer.style.flex = '';
    }
    
    if (sunburstContainer) {
        sunburstContainer.classList.remove('hidden');
        
        // 强制重新计算容器高度
        const calculateAvailableHeight = () => {
            // 方法1：直接使用视口高度减去导航栏高度（最可靠）
            const viewportHeight = window.innerHeight;
            const headerHeight = 64; // 顶部导航栏高度
            let availableHeight = viewportHeight - headerHeight;
            
            // 方法2：尝试获取父容器高度作为备选
            const viewGraph = document.getElementById('view-graph');
            if (viewGraph && viewGraph.clientHeight > 0) {
                const parentHeight = viewGraph.clientHeight;
                // 取两者中的较大值
                availableHeight = Math.max(availableHeight, parentHeight);
                console.log('使用父容器高度:', parentHeight, '最终高度:', availableHeight);
            } else {
                console.log('使用视口高度计算:', availableHeight);
            }
            
            return availableHeight;
        };
        
        // 立即计算并设置高度
        let availableHeight = calculateAvailableHeight();
        
        // 设置绝对尺寸 - 确保完全重置样式后再设置
        sunburstContainer.style.width = '100%';
        sunburstContainer.style.height = availableHeight + 'px';
        sunburstContainer.style.display = 'flex';
        sunburstContainer.style.flexDirection = 'column';
        
        // 确保图表容器有明确的高度
        if (sunburstChartDiv) {
            // 设置绝对高度
            sunburstChartDiv.style.height = '100%';
            sunburstChartDiv.style.width = '100%';
            sunburstChartDiv.style.flex = '1';
            
            // 延迟一点确保DOM已更新，然后重新计算高度
            setTimeout(() => {
                // 再次计算高度，确保准确
                const recalculatedHeight = calculateAvailableHeight();
                if (recalculatedHeight !== availableHeight) {
                    sunburstContainer.style.height = recalculatedHeight + 'px';
                    console.log('重新计算高度:', recalculatedHeight);
                }
                
                // 调试信息
                console.log('最终容器尺寸:');
                console.log('sunburst-container offsetHeight:', sunburstContainer.offsetHeight);
                console.log('sunburst-container clientHeight:', sunburstContainer.clientHeight);
                console.log('sunburst-chart offsetHeight:', sunburstChartDiv.offsetHeight);
                console.log('sunburst-chart clientHeight:', sunburstChartDiv.clientHeight);
                
                // 强制触发图表resize
                if (sunburstChart) {
                    setTimeout(() => {
                        sunburstChart.resize();
                        console.log('旭日图尺寸已强制调整');
                    }, 100);
                }
            }, 100);
        }
    }
    
    // 搜索框现在在左侧边栏中，会一直显示，不需要隐藏
    
    // 清除之前的导航状态
    currentSunburstNodePath = [];
    currentSunburstNodeIndex = -1;
    allMatchedPaths = [];
    currentPathIndex = -1;
    
    // 隐藏企业信息悬浮框（如果存在）
    if (typeof hideCompanyDetailTooltip === 'function') {
        hideCompanyDetailTooltip();
    }
    
    // 更新按钮状态
    updateViewSwitchButtons('sunburst');
    
    // 初始化旭日图（如果尚未初始化）
    if (!isSunburstInitialized) {
        console.log('初始化旭日图...');
        initSunburstChart();
        isSunburstInitialized = true;
    } else {
        // 如果已经初始化，重新渲染
        console.log('重新渲染旭日图...');
        // 延迟一点确保DOM已更新
        setTimeout(() => {
            renderSunburstChart();
            // 确保图表正确调整尺寸
            if (sunburstChart) {
                setTimeout(() => {
                    sunburstChart.resize();
                    console.log('旭日图尺寸已调整');
                }, 100);
            }
        }, 50);
    }
    
    // 根据侧边栏状态决定图例显隐
    setTimeout(updateSunburstLegendVisibility, 350);
}

function switchToGraph() {
    console.log('切换到图谱视图');
    if (typeof exitChainPanoramaFullscreen === 'function') exitChainPanoramaFullscreen();
    
    // 记录知识图谱切换日志（系统自动切换时抑制）
    if (typeof uploadActionLog === 'function' && !window.suppressActionLog) {
        uploadActionLog('产业洞察-切换视图-知识图谱', { "view": "graph", "industry": window.currentIndustry || 'ai' });
    }
    
    // 设置当前视图变量
    window.currentView = 'graph';
    window.graphVizSubView = 'graph';
    
    // 显示图谱容器
    const graphContainer = document.getElementById('graph-container');
    const sunburstContainer = document.getElementById('sunburst-container');
    const mindmapContainer = document.getElementById('mindmap-container');
    
    if (graphContainer) {
        graphContainer.classList.remove('hidden');
    }
    
    // 隐藏旭日图容器并恢复其样式（显式设置 display:none 覆盖 HTML 模板中的内联 display:flex）
    if (sunburstContainer) {
        sunburstContainer.style.width = '';
        sunburstContainer.style.height = '';
        sunburstContainer.style.display = 'none';
        sunburstContainer.style.flexDirection = '';
        
        const sunburstChartDiv = document.getElementById('sunburst-chart');
        if (sunburstChartDiv) {
            sunburstChartDiv.style.flex = '';
            sunburstChartDiv.style.height = '';
            sunburstChartDiv.style.width = '';
        }
        sunburstContainer.classList.add('hidden');
    }
    
    // 隐藏思维导图容器并恢复其样式（显式设置 display:none）
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
        
        const mindmapChartDiv = document.getElementById('mindmap-chart');
        if (mindmapChartDiv) {
            mindmapChartDiv.style.flex = '';
            mindmapChartDiv.style.height = '';
            mindmapChartDiv.style.width = '';
        }
        mindmapContainer.classList.add('hidden');
    }

    const chainContainer = document.getElementById('chain-panorama-container');
    if (chainContainer) {
        chainContainer.classList.add('hidden');
        chainContainer.style.display = '';
        chainContainer.style.width = '';
        chainContainer.style.height = '';
        chainContainer.style.flexDirection = '';
        chainContainer.style.flex = '';
    }
    
    // 搜索框现在在左侧边栏中，会一直显示，不需要额外显示
    
    // 清除旭日图导航状态
    currentSunburstNodePath = [];
    currentSunburstNodeIndex = -1;
    allMatchedPaths = [];
    currentPathIndex = -1;
    
    // 隐藏企业信息悬浮框（如果存在）
    if (typeof hideCompanyDetailTooltip === 'function') {
        hideCompanyDetailTooltip();
    }
    
    // 更新按钮状态
    updateViewSwitchButtons('graph');

    // 懒加载：如果 ForceGraph 尚未初始化，则进行初始化
    if (typeof isGraphInit !== 'undefined' && !isGraphInit && typeof initGraphViz === 'function') {
        console.log('首次切换到知识图谱视图，初始化 ForceGraph...');
        // 等待浏览器完成布局重绘后再初始化 ForceGraph，
        // 否则容器尺寸可能为 0，导致画布异常、无法拖拽
        requestAnimationFrame(() => {
            initGraphViz();
        });
    } else if (typeof Graph !== 'undefined' && Graph) {
        // 如果已初始化，切换回来时重新计算尺寸并居中（修复视图偏右问题）
        // 同样需要等待布局完成
        requestAnimationFrame(() => {
            if(typeof zoomToFitAndCenter === 'function') zoomToFitAndCenter();
        });
    }
}

// 更新视图切换按钮状态：隐藏当前模式对应按钮，其余三个可见（与原先三模式逻辑一致，含产业链全景）
function updateViewSwitchButtons(currentView) {
    const graphBtn = document.getElementById('switch-to-graph-btn');
    const sunburstBtn = document.getElementById('switch-to-sunburst-btn');
    const mindmapBtn = document.getElementById('switch-to-mindmap-btn');
    const chainBtn = document.getElementById('switch-to-chain-btn');

    if (!graphBtn || !sunburstBtn || !mindmapBtn || !chainBtn) return;

    graphBtn.classList.remove('hidden');
    sunburstBtn.classList.remove('hidden');
    mindmapBtn.classList.remove('hidden');
    chainBtn.classList.remove('hidden');

    if (currentView === 'graph') {
        graphBtn.classList.add('hidden');
        enableGraphButtons(true);
    } else if (currentView === 'sunburst') {
        sunburstBtn.classList.add('hidden');
        enableGraphButtons(false);
    } else if (currentView === 'mindmap') {
        mindmapBtn.classList.add('hidden');
        enableGraphButtons(false);
    } else if (currentView === 'chain') {
        chainBtn.classList.add('hidden');
        enableGraphButtons(false);
    }
}

// 启用或禁用知识图谱相关按钮
function enableGraphButtons(enable) {
    // 获取所有知识图谱相关按钮
    const graphButtons = [
        document.querySelector('button[onclick="showSkeletonGraph()"]'),
        document.querySelector('button[onclick="reloadGraphData()"]'),
        document.querySelector('button[onclick="resetGraph()"]'),
        document.querySelector('button[onclick="zoomToFitAndCenter()"]'),
        document.querySelector('button[onclick*="Graph.d3ReheatSimulation"]')
    ];
    
    graphButtons.forEach(btn => {
        if (btn) {
            if (enable) {
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
                btn.classList.add('cursor-pointer');
            } else {
                btn.disabled = true;
                btn.classList.add('opacity-50', 'cursor-not-allowed');
                btn.classList.remove('cursor-pointer');
            }
        }
    });
}

function getSunBurstColor(type) {
    if (type === '中央企业') return '#AB4232'; // 暗红
    if (type === '其他国资' || type === '央企/国企' || type === '国有企业') return '#D2A450'; // 金色
    if (type === '外资企业' || type === '境外企业') return '#5E9A76'; // 绿
    return '#7B72B7'; // 紫  民营企业
}



// 构建层级数据的辅助函数（指定根节点）
function buildHierarchyWithRoot(nodes, relationships, rootId) {
    const nodeMap = {};
    const childrenMap = {};
    const parentMap = {}; // 记录每个节点的父节点
    const visitedNonLeafNodes = new Set(); // 记录已访问的非叶子节点（避免重复创建）
    const companyNodeCache = {}; // 缓存公司节点模板

    // 初始化 - 统一使用字符串ID确保一致性
    nodes.forEach(node => {
        const nodeId = String(node.id);
        nodeMap[nodeId] = { ...node, children: [] };
        childrenMap[nodeId] = [];
        parentMap[nodeId] = [];
    });

    // 建立父子关系
    // 注意：根据数据结构调整，target 是父节点，source 是子节点
    relationships.forEach(rel => {
        const sourceId = String(rel.source);
        const targetId = String(rel.target);
        if (childrenMap[targetId]) {
            childrenMap[targetId].push(sourceId);
        }
        // 记录父节点关系
        if (parentMap[sourceId]) {
            parentMap[sourceId].push(targetId);
        }
    });

    // 参考量子科技旭日图配色：各层级环节使用统一蓝色系，从深到浅
    var colorList = ['#364A67', '#456DA1', '#6D90BB', '#AEC4DF'];
    
    // 判断是否为公司节点（叶子节点）
    function isCompanyNode(node) {
        return node && node.labels && node.labels.includes('公司');
    }
    
    // 判断是否为产品节点
    function isProductNode(node) {
        return node && node.labels && node.labels.includes('产品');
    }
    
    // 判断是否为环节节点
    function isLinkNode(node) {
        return node && node.labels && node.labels.includes('环节');
    }
    
    // 创建公司节点（叶子节点）- 在创建时进行重复判断
    function createCompanyNode(node, parentNode) {
        const type = node.properties.category || '民营企业';
        const nodeName = node.properties.name || String(node.id);
        
        // 获取父节点名称用于重复判断
        let parentName = '';
        if (parentNode) {
            parentName = parentNode.properties?.name || String(parentNode.id);
        }
        
        // 创建唯一键：公司名 + ID + 父节点名
        const companyKey = `${nodeName}_${node.id}_${parentName}`;
        
        // 检查是否已经见过相同的公司节点（在同一父节点下）
        if (companyNodeCache[companyKey]) {
            // 如果已经存在相同的公司节点，返回null表示跳过
            return null;
        }
        
        // 为每个实例创建唯一的名称，避免ECharts识别冲突
        const uniqueName = `${nodeName}_${node.id}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        // 先不决定是否显示label，在排序后统一处理
        companyNodeCounter++;
       
        // 缓存这个公司节点
        const companyNode = {
            name: uniqueName, // 使用唯一名称
            displayName: nodeName, // 保存原始显示名称
            value: 1, // 默认权重
            itemStyle: { color: getSunBurstColor(type) },
            label: {
                position: 'outside',
                silent: false,
                fontSize: 4,
                color: '#333',
                show: false, // 初始设置为false，在排序后统一设置
                formatter: function(params) {
                    // 显示原始名称，而不是唯一名称
                    const displayName = params.data.displayName || params.name.split('_')[0];
                    // 最多显示8个字符，超过则截取+...
                    if (displayName.length > 8) {
                        return displayName.substring(0, 8) + '...';
                    }
                    return displayName;
                }
            },
            originalData: node, // 保存原始节点数据，包含ID
            isCompany: true, // 标记为公司节点
            originalId: node.id // 保存原始ID用于识别
        };
        
        // 缓存这个公司节点
        companyNodeCache[companyKey] = companyNode;
        
        return companyNode;
    }
    
    // 创建非公司节点（中间节点）- 避免重复创建
    function createNonLeafNode(id) {
        const nodeId = String(id);
        const node = nodeMap[nodeId];
        if (!node) {
            return null;
        }
        
        // 如果已经创建过，返回null（避免重复）
        if (visitedNonLeafNodes.has(nodeId)) {
            return null;
        }
        visitedNonLeafNodes.add(nodeId);
        
        const childIds = childrenMap[nodeId] || [];
        const level = node.properties.level || 0;
        const nodeName = node.properties.name || String(node.id);
        const uniqueName = `${nodeName}_${node.id}`; // 添加ID确保唯一性
        
        // 递归创建子节点
        const children = [];
        childIds.forEach(childId => {
            const childNode = nodeMap[childId];
            if (childNode) {
                if (isCompanyNode(childNode)) {
                    // 公司节点：创建新实例（在创建时进行重复判断）
                    const companyNode = createCompanyNode(childNode, node);
                    if (companyNode) {
                        children.push(companyNode);
                    }
                } else if (isProductNode(childNode)) {
                    // 产品节点：不直接显示，但需要获取其下的公司节点
                    // 获取产品节点的子节点（公司节点）
                    const productChildIds = childrenMap[childId] || [];
                    productChildIds.forEach(companyChildId => {
                        const companyNode = nodeMap[companyChildId];
                        if (companyNode && isCompanyNode(companyNode)) {
                            // 将公司节点作为当前节点的直接子级
                            const createdCompanyNode = createCompanyNode(companyNode, node);
                            if (createdCompanyNode) {
                                children.push(createdCompanyNode);
                            }
                        }
                    });
                } else {
                    // 非公司节点：递归创建（避免重复）
                    const childTree = createNonLeafNode(childId);
                    if (childTree) {
                        children.push(childTree);
                    }
                }
            }
        });
        
        // 对同一层级下的叶子节点（公司）按照category进行排序
        // 定义category的排序优先级
        const categoryOrder = {
            '中央企业': 1,
            '央企/国企': 2,
            '国有企业': 2,
            '其他国资': 3,
            '外资企业': 4,
            '境外企业': 4,
            '民营企业': 5
        };
        
        // 对children数组进行排序（与思维导图保持一致的排序逻辑）
        children.sort((a, b) => {
            // 如果两个都是公司节点，按照category排序，相同category按名称字母顺序排序
            if (a.isCompany && b.isCompany) {
                const categoryA = a.originalData?.properties?.category || '民营企业';
                const categoryB = b.originalData?.properties?.category || '民营企业';
                const orderA = categoryOrder[categoryA] || 6; // 默认优先级最低
                const orderB = categoryOrder[categoryB] || 6;
                
                // 先比较category优先级
                if (orderA !== orderB) {
                    return orderA - orderB;
                }
                
                // 相同category时，使用localeCompare按中文拼音排序（与思维导图一致）
                const nameA = a.displayName || a.originalData?.properties?.name || '';
                const nameB = b.displayName || b.originalData?.properties?.name || '';
                return nameA.localeCompare(nameB, 'zh-CN');
            }
            // 如果一个公司节点一个非公司节点，公司节点排在后面
            if (a.isCompany && !b.isCompany) return 1;
            if (!a.isCompany && b.isCompany) return -1;
            // 如果两个都是非公司节点，保持原有顺序
            return 0;
        });
        
        // 注意：现在不在每个层级单独设置label显示
        // 将在构建完整树数据后统一处理
        
   
        return {
            name: uniqueName, // 使用唯一名称
            displayName: nodeName, // 保存原始显示名称
            children: children,
            // 不再在节点级别设置 itemStyle 颜色，由 levels 配置统一控制各层级颜色
            label: {
                // align: 'center',
                // padding: 1,
                
                position: 'center',
                textAlign: 'center',    // 水平居中
                verticalAlign: 'middle', // 垂直居中
                silent: false,
                
                fontSize: function() {
                    
                    if (level === 0)
                         return 14;
                    if (level === 1){
                        
                        if(window.currentIndustry === 'biology')
                            return 8
                        return 12;
                    }    
                        
                    if (level === 2) {
                                         
                     
                        if(window.currentIndustry === 'ai' && (nodeName==='云原生容器' || nodeName==='云原生Serverless') )
                            return 3;

                        if(window.currentIndustry === 'biology')
                            return 5

                        return 7

                        // if(nodeName==='AI手机' || nodeName==='AI手机' ||  nodeName==='AI PC' || nodeName==='AI中屏' || nodeName==='AI摄像头')
                        //     return 3;

                        // if( nodeName==='数据安全' || nodeName==='数据流通' ||  nodeName==='数据分析' ||  nodeName==='数据治理' ||  nodeName==='数据采集标注')
                        //     return 5;
                        // if( nodeName==='智能网联汽车'  )
                        //     return 3;
                        // if( nodeName==='智能网联汽车'  )
                        //     return 3;
                        // if(nodeName==='AI手机' || nodeName==='AI手机' ||  nodeName==='AI PC' || nodeName==='AI中屏' || nodeName==='AI摄像头')
                        //     return 3;
                        // if( nodeName==='人形机器人'  )
                        //     return 3;
                        // if( nodeName==='AI眼镜'  )
                        //     return 3;
                        // if( nodeName==='智能网联汽车'  )
                        //     return 5;
                        // if( nodeName==='云平台'  )
                        //     return 7;
                        // if( nodeName==='垂直行业应用'  )
                        //     return 8;
                        
                        // if( nodeName==='智能体服务平台'  )
                        //     return 6;
                        // if( nodeName==='模型服务平台'  )
                        //     return 8;
                        
                        return 10;
                    }

                    if (level === 3) {
            
                        // //人工智能
                       
                        // if( nodeName==='服务器/PCB/器件' )
                        //     return 7;
                        // if( nodeName==='数据库')
                        //     return 7;
                       
                        // if( nodeName==='网卡/交换芯片'  || nodeName==='CPU/GPU' ||  nodeName==='光模块' ||  nodeName==='网络设备' )
                        //     return 6;
                        // if( nodeName==='HBM/DRAM' ||  nodeName==='NAND' ||  nodeName==='闪存'  )
                        //     return 5;

                        // if(  nodeName==='封测' ||  nodeName==='材料' || nodeName==='光刻等设备')
                        //     return 8;
                        // if( nodeName==='EDA工业软件' || nodeName==='芯片IP')
                        //     return 6;

                        // if(nodeName==='云原生容器' || nodeName==='云原生Serverless' )
                        //     return 4;


                        // //20260520
                        // if( nodeName==='存储控制/RAID/HBA' ||  nodeName==='智能体服务平台' ||  nodeName==='机械硬盘HDD')
                        //     return 4;

                        // if( nodeName==='电力储能' )
                        //     return 7;

                        // if( nodeName==='算力调度/算力服务' ||  nodeName==='数据平台' || nodeName==='晶圆代工')
                        //     return 5;

                        // if(nodeName==='AI手机' || nodeName==='AI手机'  || nodeName==='AI摄像头')
                        //     return 5;

                        // if(nodeName==='AI中屏'  || nodeName==='数据安全' || nodeName==='数据流通' ||  nodeName==='数据分析' ||  nodeName==='数据治理' ||  nodeName==='数据采集标注')
                        //     return 6;

                        // //低空经济
                        // if( nodeName==='低空科学研究和技术服务'  || nodeName==='低空装备检测服务' ||  nodeName==='低空工业产品设计服务' ||  nodeName==='低空装卸搬运和仓储服务' ||  nodeName==='低空金融服务' ||  nodeName==='低空保险服务' ||  nodeName==='低空会展服务')
                        //     return 4;
                        
                        // if(nodeName==='低空人才教育培训')
                        //     return 8

                        // return 8

                         // 统计当前节点下属的企业节点数量，企业越多扇区角度越大，字号也可相应增大
                         var companyCount = 0;
                         children.forEach(function(child) {
                             if (child.isCompany) companyCount++;
                         });
                         // 企业数>10 → 5, >20 → 6, 依次递增，最大10
                         var size = Math.min(10, 5 + Math.floor((companyCount - 1) / 8));
                         return size;
                     
                    }
                }(),
                formatter: function(params) {
                    // console.log(params);
                    // 显示原始名称，而不是唯一名称
                   
                    const displayName = params.data.displayName || params.name.split('_')[0];

                    // if(level===0 && (displayName==='人工智能11' || displayName==='低空经济11'))
                    //     return displayName+"\n\n";


                    if (displayName.length <= 5) {
                        return displayName;
                    }
                    
                    let j = 5
                    // if(window.currentIndustry === 'biology')
                    //     j = 2

                    let result = '';
                    for (let i = 0; i < displayName.length; i += j) {
                        result += displayName.substring(i, i + j);
                        if (i + j < displayName.length) {
                            result += '\n';
                        }
                    }
                    return result;
                }
            },
            originalData: node, // 保存原始节点数据，包含ID
            isCompany: false // 标记为非公司节点
        };
    }

    // 从根节点开始构建
    return createNonLeafNode(rootId);
}

// 全局统一设置公司节点的label显示
function setGlobalCompanyLabels(treeData) {
    if (!treeData) {
        return treeData;
    }
    
    console.log('开始全局统一设置公司节点label显示...');
    
    // 收集所有公司节点
    const allCompanyNodes = [];
    
    // 递归遍历树结构，收集所有公司节点
    function collectCompanyNodes(node) {
        if (!node) return;
        
        // 如果是公司节点，添加到列表
        if (node.isCompany) {
            allCompanyNodes.push(node);
        }
        
        // 递归处理子节点
        if (node.children && node.children.length > 0) {
            node.children.forEach(child => {
                collectCompanyNodes(child);
            });
        }
    }
    
    // 从根节点开始收集
    collectCompanyNodes(treeData);
    
    // 保存全局引用，供缩放时动态调整label显示使用
    sunburstAllCompanyNodes = allCompanyNodes;
    
    console.log(`总共收集到 ${allCompanyNodes.length} 个公司节点`);
    
    // 全局统一设置label显示：基准缩放时最多显示380个label，放大后逐步增加
    applyCompanyLabelsByZoom(1.0);
    
    // 计算实际显示的label数量
    const visibleLabelCount = allCompanyNodes.filter(node => node.label && node.label.show).length;
    console.log(`全局label显示设置完成，初始显示 ${visibleLabelCount} 个label`);
    return treeData;
}

// 根据缩放级别动态调整公司label的显示数量
// zoom越大，可见面积越大，应显示更多的label
function applyCompanyLabelsByZoom(zoomLevel) {
    if (!sunburstAllCompanyNodes || sunburstAllCompanyNodes.length === 0) return;
    
    const total = sunburstAllCompanyNodes.length;
    // 基准（zoom=1.0）最多显示380个，zoom每增加0.1，最多增加40个，直到全部显示
    const baseMax = 380;
    const incrementPerStep = 40;
    const extraSteps = Math.max(0, Math.floor((zoomLevel - 1.0) / 0.1));
    const maxVisible = Math.min(total, baseMax + extraSteps * incrementPerStep);
    
    let showInterval;
    if (total <= maxVisible) {
        showInterval = 1;
    } else {
        showInterval = Math.max(1, Math.ceil(total / maxVisible));
    }
    
    // 先收集哪些节点需要显示label
    const visibleIndices = [];
    sunburstAllCompanyNodes.forEach((node, index) => {
        if (index % showInterval === 0) {
            visibleIndices.push(index);
        }
    });
    
    // 解决圆形旭日图首尾label重叠问题
    if (visibleIndices.length > 1) {
        const firstIdx = visibleIndices[0];
        const lastIdx = visibleIndices[visibleIndices.length - 1];
        const wrapGap = total - lastIdx + firstIdx;
        if (wrapGap < showInterval) {
            visibleIndices.pop();
        }
    }
    
    // 应用label显示设置
    const visibleSet = new Set(visibleIndices);
    sunburstAllCompanyNodes.forEach((node, index) => {
        if (node.label) {
            node.label.show = visibleSet.has(index);
        }
    });
    
    // 确保至少显示一个label
    if (sunburstAllCompanyNodes.length > 0) {
        let hasVisibleLabel = false;
        sunburstAllCompanyNodes.forEach(node => {
            if (node.label && node.label.show) hasVisibleLabel = true;
        });
        if (!hasVisibleLabel && sunburstAllCompanyNodes[0] && sunburstAllCompanyNodes[0].label) {
            sunburstAllCompanyNodes[0].label.show = true;
        }
    }
    
    const visibleCount = sunburstAllCompanyNodes.filter(n => n.label && n.label.show).length;
    console.log(`[Label缩放] zoom=${zoomLevel.toFixed(1)}, 最大可见=${maxVisible}, 间隔=${showInterval}, 实际显示=${visibleCount}/${total}`);
}

// 过滤重复的公司节点
function filterDuplicateCompanyNodes(treeData) {
    if (!treeData) {
        return treeData;
    }
    
    console.log('开始过滤重复的公司节点...');
    
    // 用于跟踪所有已处理的节点，避免无限递归
    const processedNodes = new Set();
    
    // 递归处理树结构
    function processNode(node, parentNode) {
        if (!node || processedNodes.has(node)) {
            return node;
        }
        processedNodes.add(node);
        
        // 如果有子节点，先处理子节点
        if (node.children && node.children.length > 0) {
            // 处理每个子节点
            const processedChildren = [];
            const seenCompanyKeys = new Set(); // 用于记录当前父节点下已见过的公司节点
            
            for (const child of node.children) {
                const processedChild = processNode(child, node);
                
                if (processedChild) {
                    // 如果是公司节点（叶子节点）
                    if (processedChild.isCompany) {
                        // 获取公司节点的关键信息：公司名、ID和父节点
                        // 注意：companyNode中的name是唯一名称（包含时间戳和随机数），
                        // 我们需要使用displayName或从originalData中获取原始名称
                        let companyName = processedChild.displayName;
                        if (!companyName && processedChild.originalData?.properties?.name) {
                            companyName = processedChild.originalData.properties.name;
                        }
                        if (!companyName) {
                            // 从唯一名称中提取原始名称（去掉后缀）
                            const uniqueName = processedChild.name || '';
                            companyName = uniqueName.split('_')[0];
                        }
                        
                        let companyId = processedChild.originalId;
                        if (!companyId && processedChild.originalData?.id) {
                            companyId = processedChild.originalData.id;
                        }
                        
                        let parentName = '';
                        if (parentNode) {
                            parentName = parentNode.displayName;
                            if (!parentName && parentNode.originalData?.properties?.name) {
                                parentName = parentNode.originalData.properties.name;
                            }
                            if (!parentName) {
                                const parentUniqueName = parentNode.name || '';
                                parentName = parentUniqueName.split('_')[0];
                            }
                        }
                        
                        // 创建唯一键：公司名 + ID + 父节点名
                        const companyKey = `${companyName}_${companyId}_${parentName}`;
                        
                        // 检查是否已经见过相同的公司节点（在同一父节点下）
                        if (seenCompanyKeys.has(companyKey)) {
                            //console.log(`过滤重复公司节点: ${companyName} (ID: ${companyId}), 父节点: ${parentName}`);
                            continue; // 跳过重复节点
                        }
                        
                        seenCompanyKeys.add(companyKey);
                    }
                    
                    processedChildren.push(processedChild);
                }
            }
            
            // 更新节点的子节点列表
            node.children = processedChildren;
        }
        
        return node;
    }
    
    // 从根节点开始处理
    const filteredTree = processNode(treeData, null);
    
    // 统计过滤结果
    function countCompanyNodes(node) {
        if (!node || processedNodes.has(node)) {
            return 0;
        }
        processedNodes.add(node);
        
        let count = 0;
        if (node.isCompany) {
            count = 1;
        }
        
        if (node.children) {
            for (const child of node.children) {
                count += countCompanyNodes(child);
            }
        }
        
        return count;
    }
    
    // 重置processedNodes用于计数
    processedNodes.clear();
    const originalCount = countCompanyNodes(JSON.parse(JSON.stringify(treeData))); // 深拷贝避免影响原数据
    
    processedNodes.clear();
    const filteredCount = countCompanyNodes(JSON.parse(JSON.stringify(filteredTree)));
    
    const removedCount = originalCount - filteredCount;
    
    console.log(`公司节点过滤完成: 原始 ${originalCount} 个, 过滤后 ${filteredCount} 个, 移除 ${removedCount} 个重复节点`);
    
    return filteredTree;
}

// 初始化旭日图
function initSunburstChart() {
    console.log('初始化旭日图...');
    
    // 确保echarts已加载
    if (typeof echarts === 'undefined') {
        console.error('ECharts加载失败');
        return;
    }
    
    console.log('ECharts已加载，开始渲染...');
    renderSunburstChart();
}

// 渲染旭日图
function renderSunburstChart() {
    console.log('开始渲染旭日图...');
    
    // 重置企业节点计数器，确保每次渲染时label显示策略一致
    companyNodeCounter = 0;
    
    // 获取当前图谱数据
    if (typeof allGraphData === 'undefined' || !allGraphData.nodes || allGraphData.nodes.length === 0) {
        console.error('No graph data available');
        // 尝试从后端获取数据
        fetchGraphDataForSunburst();
        return;
    }
    
    console.log('使用数据节点数:', allGraphData.nodes.length);
    
    // 计算总的企业节点数量
    totalCompanyNodes = allGraphData.nodes.filter(node => 
        node.labels && node.labels.includes('公司')
    ).length;
    console.log('企业节点总数:', totalCompanyNodes);
    
    // 调试信息：显示label显示策略
    if (totalCompanyNodes > 100) {
        const displayInterval = Math.max(1, Math.floor(totalCompanyNodes / 100));
        const expectedDisplayCount = Math.floor(totalCompanyNodes / displayInterval);
        console.log(`Label显示策略：总节点数 ${totalCompanyNodes} > 100，显示间隔为 ${displayInterval}，预计显示 ${expectedDisplayCount} 个label`);
    } else {
        console.log(`Label显示策略：总节点数 ${totalCompanyNodes} <= 100，全部显示label`);
    }
    
    // 转换数据格式 - 处理当前图谱的数据结构
    const sunburstData = {
        nodes: allGraphData.nodes.map(node => {
            // 确保节点有正确的属性结构
            const properties = node.properties || {};
            if (!properties.name && node.id) {
                properties.name = String(node.id);
            }
            if (!properties.category) {
                // 根据标签设置默认分类
                if (node.labels && node.labels.includes('公司')) {
                    properties.category = '民营企业'; // 默认分类
                } else if (node.labels && node.labels.includes('环节')) {
                    properties.category = '环节';
                } else if (node.labels && node.labels.includes('产品')) {
                    properties.category = '产品';
                }
            }
            if (properties.level === undefined) {
                // 设置默认层级
                if (node.labels && node.labels.includes('环节')) {
                    // 根据环节名称判断层级
                    const name = properties.name || '';
                    if (name.includes('上游') || name.includes('中游') || name.includes('下游')) {
                        properties.level = 1; // 一级环节
                    } else if (name.includes('基础设施') || name.includes('软件开发') || name.includes('主要产品') || name.includes('应用场景')) {
                        properties.level = 2; // 二级环节
                    } else {
                        properties.level = 3; // 三级环节
                    }
                } else if (node.labels && node.labels.includes('产品')) {
                    properties.level = 4; // 产品层级（虽然不显示）
                } else if (node.labels && node.labels.includes('公司')) {
                    properties.level = 5; // 公司层级
                } else {
                    properties.level = 1; // 默认层级
                }
            }
            
            return {
                id: node.id,
                properties: properties,
                labels: node.labels || []
            };
        }),
        relationships: (allGraphData.links || allGraphData.relationships || []).map(rel => {
            // 处理关系的源和目标 - 从可能的对象中提取ID
            let sourceId = rel.source;
            let targetId = rel.target;
            
            // 如果source是对象，提取id属性
            if (typeof sourceId === 'object' && sourceId !== null) {
                sourceId = sourceId.id;
            }
            // 如果target是对象，提取id属性  
            if (typeof targetId === 'object' && targetId !== null) {
                targetId = targetId.id;
            }
            
            return {
                source: sourceId,
                target: targetId,
                type: rel.type // 保留关系类型信息
            };
        })
    };
    
    console.log('sunburstData', sunburstData);
    // 查找根节点（层级为0的节点）
    const rootNode = sunburstData.nodes.find(node => 
        node.properties.level === 0
    );
    
    // 如果没有找到根节点，使用第一个节点
    const rootId = rootNode ? rootNode.id : (sunburstData.nodes[0] ? sunburstData.nodes[0].id : 'root');
    
    // 修改buildHierarchy函数以使用指定的根节点
    const treeData = buildHierarchyWithRoot(sunburstData.nodes, sunburstData.relationships, rootId);
    
    // 注意：现在buildHierarchyWithRoot函数在构建层级数据时已经进行了重复判断
    // 不再需要单独调用filterDuplicateCompanyNodes函数
    const filteredTreeData = treeData;

    // 全局统一设置公司节点的label显示
    const treeDataWithLabels = setGlobalCompanyLabels(filteredTreeData);

    console.log('treeData', treeDataWithLabels);
    // 保存树数据引用，供缩放时动态调整label使用
    sunburstTreeData = treeDataWithLabels;
    const chartDom = document.getElementById('sunburst-chart');
    if (!chartDom) {
        console.error('Sunburst chart container not found');
        return;
    }
    
    // 确保容器有明确的大小
    if (chartDom.clientHeight === 0 || chartDom.clientWidth === 0) {
        console.warn('图表容器大小为0，尝试修复...');
        // 获取父容器大小
        const parent = chartDom.parentElement;
        if (parent) {
            chartDom.style.height = parent.clientHeight + 'px';
            chartDom.style.width = parent.clientWidth + 'px';
        } else {
            // 设置默认大小
            chartDom.style.height = '600px';
            chartDom.style.width = '800px';
        }
    }    
    // 如果已有图表实例，先销毁
    if (sunburstChart) {
        try {
            sunburstChart.dispose();
        } catch (e) {
            console.warn('销毁旧图表时出错:', e);
        }
    }
    
    sunburstChart = echarts.init(chartDom,null,{renderer: 'svg'});
    const option = {
        title: {
            // text: 'AI 产业图谱 (旭日图)',
            // left: 'center',
            // top: 10
        },
        tooltip: {
            trigger: 'item',
            backgroundColor: 'rgba(255, 255, 255, 0.95)',
            borderColor: '#3b82f6',
            borderWidth: 1,
            borderRadius: 6,
            padding: [12, 16],
            textStyle: {
                color: '#374151',
                fontSize: 12,
                lineHeight: 1.5
            },
            formatter: function(params) {
                const node = params.data;
                const name = node.displayName || '未知节点';
                
                // 检查是否为公司节点
                if (node.isCompany && node.originalData) {
                    const originalNode = node.originalData;
                    const properties = originalNode.properties || {};
                    
                    // 获取信用代码
                    const creditCode = properties.credit_code || properties.social_credit_code || properties.creditCode;
                    
                    // 构建企业信息HTML - 只显示有实际值的字段
                    let html = `
                        <div style="font-weight:bold;color:#1f2937;font-size:14px">
                            ${name}
                        </div>
                    `;
                    
                    // 异步调用API获取公司详情（用于更新更详细的信息）
                    if (creditCode) {
                        fetchCompanyDetailForSunburst(creditCode, name, properties);
                    }
                    
                    return html;
                } 
            }
        },
        series: {
            type: 'sunburst',
            data: [treeDataWithLabels],
            radius: ['0%', '100%'],
            center: ['50%', '50%'], // 确保居中
            nodeClick: false, // 点击节点时跳转到该节点
            sort: undefined,
            emphasis: {
                //focus: 'descendant'
                focus: 'ancestor',
                itemStyle: {
                    shadowBlur: 10,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            },
            levels: [
                {},
                {
                    r0: '0%',
                    r: '10%',
                    itemStyle: { color: '#364A67', borderWidth: 2 },
                    label: { color: '#FFFFFF', position: 'center', rotate: 'tangential' }
                },
                {
                    r0: '10%',
                    r: '25%',
                    itemStyle: { color: '#456DA1' },
                    label: { color: '#FFFFFF', rotate: 'tangential'}
                },
                {
                    r0: '25%',
                    r: '40%',
                    itemStyle: { color: '#6D90BB' },
                    label: { color: '#FFFFFF', position: 'inside', padding: 3, silent: false }
                },
                {
                    r0: '40%',
                    r: '60%',
                    itemStyle: { color: '#AEC4DF' },
                    label: { color: '#000000', position: 'inside', padding: 3, silent: false }
                },
                {
                    // 最后一层：叶子节点 (公司)
                    r0: '60%',
                    r: '94%',
                    itemStyle: {
                        borderWidth: 0
                    }
                }
            ],
            label: {
                fontSize: 10,
                fontWeight: 'bolder'
            },
            itemStyle: {
                borderColor: '#fff',
                borderWidth: 0.5
            }
        }
    };

    try {
        sunburstChart.setOption(option);
        console.log('旭日图渲染成功');
        
        // 添加鼠标事件监听
        setupSunburstMouseEvents();
        
        // 触发一次resize确保图表正确显示
        setTimeout(() => {
            if (sunburstChart) {
                sunburstChart.resize();
                console.log('图表resize完成');
            }
        }, 100);
    } catch (error) {
        console.error('渲染旭日图时出错:', error);
        
    }
    
    // 窗口大小变化时重绘
    window.addEventListener('resize', function() {
        // 如果当前视图是旭日图，重新计算容器高度
        if (window.currentView === 'sunburst') {
            const sunburstContainer = document.getElementById('sunburst-container');
            if (sunburstContainer && !sunburstContainer.classList.contains('hidden')) {
                // 重新计算高度 - 使用与switchToSunburst相同的逻辑
                const calculateAvailableHeight = () => {
                    const viewportHeight = window.innerHeight;
                    const headerHeight = 64; // 顶部导航栏高度
                    let availableHeight = viewportHeight - headerHeight;
                    
                    const viewGraph = document.getElementById('view-graph');
                    if (viewGraph && viewGraph.clientHeight > 0) {
                        const parentHeight = viewGraph.clientHeight;
                        availableHeight = Math.max(availableHeight, parentHeight);
                    }
                    
                    return availableHeight;
                };
                
                const availableHeight = calculateAvailableHeight();
                sunburstContainer.style.height = availableHeight + 'px';
                console.log('窗口大小变化，旭日图容器高度已调整:', availableHeight);
                
                // 延迟一点确保DOM更新后再调整图表
                setTimeout(() => {
                    if (sunburstChart) {
                        sunburstChart.resize();
                        console.log('窗口大小变化后图表已调整');
                    }
                }, 50);
            }
        } else if (sunburstChart) {
            // 即使不是旭日图视图，如果图表存在也调整尺寸（可能在其他地方使用）
            sunburstChart.resize();
        }
    });
}

// 从后端获取图谱数据
function fetchGraphDataForSunburst() {
    const dataSource = getIndustryDataSource();
    console.log(`加载旭日图产业数据源: ${dataSource}`);
    fetch(dataSource, { cache: "no-cache" })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('成功获取图谱数据:', data);
            // 确保数据格式正确
            if (data && (data.nodes || data.relationships)) {
                allGraphData = {
                    nodes: data.nodes || [],
                    links: data.relationships || data.links || []
                };
                renderSunburstChart();
            } else {
                console.error('数据格式不正确:', data);
            }
        })
        .catch(error => {
            console.error('Failed to fetch graph data:', error);
            
        });
}

// 当图谱数据更新时，重新渲染旭日图
if (typeof reloadGraphData === 'function') {
    const originalReloadGraphData = reloadGraphData;
    reloadGraphData = async function(skipStatus = false, forceReload = false) {
        await originalReloadGraphData(skipStatus, forceReload);
        // 产业切换后，allGraphData 已刷新，需要重新渲染旭日图
        const sunburstContainer = document.getElementById('sunburst-container');
        if (sunburstContainer && !sunburstContainer.classList.contains('hidden')) {
            console.log('图谱数据已刷新，重新渲染旭日图...');
            renderSunburstChart();
            // 重新渲染后刷新图例（统计数据可能已变化）
            setTimeout(updateSunburstLegendVisibility, 600);
        }
    };
}

// 旭日图搜索聚焦：查找并放大到匹配的节点
function focusOnSunburstNode(nodeId) {
    console.log('旭日图聚焦到节点:', nodeId);
    
    if (!sunburstChart) {
        console.error('旭日图未初始化');
        return false;
    }
    
    // 获取当前旭日图的数据
    const option = sunburstChart.getOption();
    if (!option || !option.series || !option.series[0] || !option.series[0].data) {
        console.error('无法获取旭日图数据');
        return false;
    }
    
    // 递归查找所有匹配的节点和路径
    function findAllNodesAndPaths(tree, targetId, path = [], results = []) {
        if (!tree) return results;
        
        // 将当前节点添加到路径
        const currentPath = [...path, tree];
        
        // 检查当前节点是否匹配 - 使用类型无关的比较
        const matchesId = (tree.originalData && String(tree.originalData.id) === String(targetId));
        const matchesName = (tree.name && tree.name === targetId);
        const matchesPropertiesName = (tree.originalData && tree.originalData.properties && 
                                     tree.originalData.properties.name === targetId);
        const matchesDisplayName = (tree.displayName && tree.displayName === targetId);
        const matchesOriginalId = (tree.originalId && String(tree.originalId) === String(targetId));
        
        if (matchesId || matchesName || matchesPropertiesName || matchesDisplayName || matchesOriginalId) {
            results.push({ node: tree, path: currentPath });
        }
        
        // 检查子节点
        if (tree.children) {
            for (let i = 0; i < tree.children.length; i++) {
                const child = tree.children[i];
                findAllNodesAndPaths(child, targetId, currentPath, results);
            }
        }
        
        return results;
    }
    
    // 在旭日图数据中查找所有匹配的节点和路径
    const treeData = option.series[0].data[0];
    const allResults = findAllNodesAndPaths(treeData, nodeId);
    
    if (allResults.length > 0) {
        // 如果有多个匹配，选择第一个进行聚焦
        const result = allResults[0];
        const targetNode = result.node;
        
        console.log(`找到 ${allResults.length} 个匹配节点:`);
        allResults.forEach((r, index) => {
            const pathNames = r.path.map(n => n.displayName || n.name.split('_')[0]);
            console.log(`  ${index + 1}. ${r.node.displayName || r.node.name} - 路径: ${pathNames.join(' → ')}`);
        });
        
        // 保存所有匹配结果到全局变量，方便调试
        window.allMatchedResults = allResults;
        
        // 保存所有匹配的路径
        allMatchedPaths = allResults.map(r => r.path);
        currentPathIndex = 0; // 从第一条路径开始
        
        // 保存当前节点路径用于键盘导航（使用第一条路径）
        currentSunburstNodePath = allMatchedPaths[0];
        currentSunburstNodeIndex = currentSunburstNodePath.length - 1; // 当前选中最后一个节点（目标节点）
        
        console.log('聚焦到节点:', targetNode.displayName || targetNode.name);
        console.log(`找到 ${allMatchedPaths.length} 条路径，当前显示第 ${currentPathIndex + 1} 条`);
        console.log('当前节点路径:', currentSunburstNodePath.map(n => n.displayName || n.name));
        console.log('当前节点索引:', currentSunburstNodeIndex);
        
        try {
            // 记录最后搜索的节点，用于tooltip中显示标记
            // 记录最后搜索的节点，用于tooltip中显示标记
            window.lastSearchedNode = targetNode.displayName || targetNode.name;
            
            // 获取节点的唯一名称
            const uniqueNodeName = targetNode.name; // 这是唯一名称（包含ID）
            
            // 方法1：使用sunburstSelect动作模拟点击节点，触发nodeClick: 'rootToNode'行为
            // 这会自动旋转并放大到该节点
            // 现在使用唯一名称，避免同名节点问题
            sunburstChart.dispatchAction({
                type: 'sunburstSelect',
                seriesIndex: 0,
                name: uniqueNodeName
            });
            
            // 方法2：高亮所有匹配的节点实例
            // 首先清除之前的高亮
            sunburstChart.dispatchAction({
                type: 'downplay',
                seriesIndex: 0
            });
            
            // 高亮所有匹配的节点
            const allUniqueNames = allResults.map(r => r.node.name);
            sunburstChart.dispatchAction({
                type: 'highlight',
                seriesIndex: 0,
                name: allUniqueNames
            });
            
            // 方法3：显示默认的tooltip（搜索定位后显示）
            // 延迟一点确保图表已经更新
            setTimeout(() => {
                try {
                    sunburstChart.dispatchAction({
                        type: 'showTip',
                        seriesIndex: 0,
                        name: uniqueNodeName,
                        position: 'right', // 可以设置为'top', 'bottom', 'left', 'right'或具体坐标
                
                    });
                } catch (tipError) {
                    console.warn('显示tooltip失败:', tipError);
                }
            }, 300);
            
            console.log('旭日图已聚焦到节点:', targetNode.displayName || targetNode.name);
            return true;
            
        } catch (error) {
            console.warn('sunburstSelect动作失败，尝试替代方法:', error);
           
        }
    } else {
        console.log('未在旭日图中找到节点:', nodeId);
        
        // 尝试通过名称模糊匹配
        if (typeof allGraphData !== 'undefined' && allGraphData.nodes) {
            const node = allGraphData.nodes.find(n => String(n.id) === String(nodeId));
            if (node && node.properties && node.properties.name) {
                console.log('尝试通过名称查找:', node.properties.name);
                return focusOnSunburstNode(node.properties.name);
            }
        }
        
        return false;
    }
}


// 全局搜索处理函数（旭日图版本）
function handleSunburstSearch(searchTerm) {
    console.log('旭日图搜索:', searchTerm);
    
    if (!searchTerm || searchTerm.trim() === '') {
        return;
    }
    
    // 在全量数据中搜索匹配的节点
    if (typeof allGraphData === 'undefined' || !allGraphData.nodes) {
        console.error('图谱数据未加载');
        return;
    }
    
    const term = searchTerm.toLowerCase();
    const matches = allGraphData.nodes.filter(n => {
        const name = (n.properties && n.properties.name) ? n.properties.name.toString() : '';
        return name.toLowerCase().includes(term);
    });
    
    if (matches.length > 0) {
        // 取第一个匹配的节点
        const firstMatch = matches[0];
        console.log('找到匹配节点:', firstMatch.properties.name, 'ID:', firstMatch.id);
        
        // 尝试在旭日图中聚焦该节点
        const focused = focusOnSunburstNode(firstMatch.id);
        
        if (!focused) {
            // 如果无法直接找到，尝试通过名称查找
            focusOnSunburstNode(firstMatch.properties.name);
        }
    } else {
        console.log('未找到匹配的节点');
    }
}

// 处理旭日图视图下的搜索点击
function handleSunburstSearchClick(nodeId) {
    console.log('旭日图搜索点击:', nodeId);
    
    // 隐藏搜索建议
    const suggestions = document.getElementById('search-suggestions');
    if(suggestions) suggestions.classList.add('hidden');
    
    // 聚焦到旭日图节点
    focusOnSunburstNode(nodeId);
}

// 将函数暴露到全局作用域，以便HTML onclick属性可以调用
window.handleSunburstSearchClick = handleSunburstSearchClick;

// 全局搜索输入处理函数
function handleGlobalSearchInput(value) {
    console.log('全局搜索输入:', value);
    
    // 检查当前视图
    const sunburstContainer = document.getElementById('sunburst-container');
    const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
    
    if (isSunburstView) {
        // 旭日图视图：调用handleSearchInput显示下拉列表
        // handleSearchInput会根据当前视图自动生成正确的点击事件
        if (typeof handleSearchInput === 'function') {
            handleSearchInput(value);
        }
    } else {
        // 知识图谱视图：调用原有的搜索处理函数
        if (typeof handleSearchInput === 'function') {
            handleSearchInput(value);
        }
    }
}

// 调试函数
function debugSunburst() {
    console.log('=== 旭日图调试信息 ===');
    
    const sunburstContainer = document.getElementById('sunburst-container');
    const sunburstChartDiv = document.getElementById('sunburst-chart');
    const viewGraph = document.getElementById('view-graph');
    
    console.log('sunburst-container:', sunburstContainer);
    console.log('sunburst-chart:', sunburstChartDiv);
    console.log('view-graph:', viewGraph);
    
    if (sunburstContainer) {
        console.log('容器类名:', sunburstContainer.className);
        console.log('容器是否隐藏:', sunburstContainer.classList.contains('hidden'));
        console.log('容器大小:', sunburstContainer.clientWidth, 'x', sunburstContainer.clientHeight);
        console.log('容器offset:', sunburstContainer.offsetWidth, 'x', sunburstContainer.offsetHeight);
        console.log('容器样式:', sunburstContainer.style.cssText);
    }
    
    if (sunburstChartDiv) {
        console.log('图表div大小:', sunburstChartDiv.clientWidth, 'x', sunburstChartDiv.clientHeight);
        console.log('图表div offset:', sunburstChartDiv.offsetWidth, 'x', sunburstChartDiv.offsetHeight);
        console.log('图表div样式:', sunburstChartDiv.style.cssText);
    }
    
    if (viewGraph) {
        console.log('父容器大小:', viewGraph.clientWidth, 'x', viewGraph.clientHeight);
        console.log('父容器offset:', viewGraph.offsetWidth, 'x', viewGraph.offsetHeight);
        console.log('父容器样式:', viewGraph.style.cssText);
    }
    
    console.log('窗口大小:', window.innerWidth, 'x', window.innerHeight);
    console.log('当前视图:', window.currentView);
    console.log('ECharts已加载:', typeof echarts !== 'undefined');
    console.log('sunburstChart实例:', sunburstChart);
    console.log('allGraphData:', typeof allGraphData, allGraphData ? `节点数: ${allGraphData.nodes.length}` : '未定义');
    console.log('=== 调试结束 ===');
    
    // 尝试强制重新渲染
    if (sunburstChart) {
        console.log('尝试重新渲染...');
        sunburstChart.resize();
    }
}

// 键盘导航：在节点路径中上下移动
function navigateSunburstNode(direction) {
    // direction: 'up' 向上移动到父节点，'down' 向下移动到子节点
    
    if (!sunburstChart || currentSunburstNodePath.length === 0) {
        console.log('没有可导航的节点路径');
        return;
    }
    
    let newIndex = currentSunburstNodeIndex;
    
    if (direction === 'up') {
        // 向上移动到父节点（路径中的前一个节点）
        if (currentSunburstNodeIndex > 0) {
            newIndex = currentSunburstNodeIndex - 1;
        } else {
            console.log('已经在根节点，无法向上移动');
            return;
        }
    } else if (direction === 'down') {
        // 向下移动到子节点（路径中的后一个节点）
        if (currentSunburstNodeIndex < currentSunburstNodePath.length - 1) {
            newIndex = currentSunburstNodeIndex + 1;
        } else {
            console.log('已经在叶子节点，无法向下移动');
            return;
        }
    } else {
        console.log('无效的导航方向:', direction);
        return;
    }
    
    // 更新当前节点索引
    currentSunburstNodeIndex = newIndex;
    const targetNode = currentSunburstNodePath[newIndex];
    
    console.log(`导航到${direction === 'up' ? '父' : '子'}节点:`, targetNode.name, `索引: ${newIndex}`);
    
    try {
        // 清除之前的高亮
        sunburstChart.dispatchAction({
            type: 'downplay',
            seriesIndex: 0
        });
        
        // 高亮新节点
        sunburstChart.dispatchAction({
            type: 'highlight',
            seriesIndex: 0,
            name: targetNode.name
        });
        
        // 显示tooltip
        sunburstChart.dispatchAction({
            type: 'showTip',
            seriesIndex: 0,
            name: targetNode.name,
            position: 'right'
        });
        
    } catch (error) {
        console.warn('导航时出错:', error);
    }
}

// 切换到不同的路径
function switchSunburstPath(direction) {
    if (allMatchedPaths.length <= 1) {
        console.log('只有一条路径，无需切换');
        return;
    }
    
    // 计算新的路径索引
    let newPathIndex;
    if (direction === 'left') {
        newPathIndex = (currentPathIndex - 1 + allMatchedPaths.length) % allMatchedPaths.length;
    } else if (direction === 'right') {
        newPathIndex = (currentPathIndex + 1) % allMatchedPaths.length;
    } else {
        return;
    }
    
    // 更新路径索引
    currentPathIndex = newPathIndex;
    currentSunburstNodePath = allMatchedPaths[currentPathIndex];
    currentSunburstNodeIndex = currentSunburstNodePath.length - 1; // 选中最后一个节点（目标节点）
    
    console.log(`切换到第 ${currentPathIndex + 1}/${allMatchedPaths.length} 条路径`);
    console.log('新路径:', currentSunburstNodePath.map(n => n.displayName || n.name));
    
    // 获取目标节点
    const targetNode = currentSunburstNodePath[currentSunburstNodeIndex];
    
    try {
        // 清除之前的高亮
        if (sunburstChart) {
            sunburstChart.dispatchAction({
                type: 'downplay',
                seriesIndex: 0
            });
        }
        
        // 聚焦到新路径的目标节点
        if (sunburstChart && targetNode) {
            // 使用sunburstSelect动作模拟点击节点
            sunburstChart.dispatchAction({
                type: 'sunburstSelect',
                seriesIndex: 0,
                name: targetNode.name
            });
            
            // 高亮目标节点
            sunburstChart.dispatchAction({
                type: 'highlight',
                seriesIndex: 0,
                name: targetNode.name
            });
            
            // 显示tooltip
            sunburstChart.dispatchAction({
                type: 'showTip',
                seriesIndex: 0,
                name: targetNode.name,
                position: 'right'
            });
        }
        
    } catch (error) {
        console.warn('切换路径时出错:', error);
    }
}

// 处理键盘事件
function handleSunburstKeyboardNavigation(event) {
    // 检查当前是否在旭日图视图中
    const sunburstContainer = document.getElementById('sunburst-container');
    const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
    
    if (!isSunburstView || currentSunburstNodePath.length === 0) {
        return; // 不在旭日图视图或没有节点路径，不处理键盘事件
    }
    
    // 检查是否在输入框中，如果是则忽略键盘事件
    const activeElement = document.activeElement;
    if (activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA')) {
        return;
    }
    
    switch (event.key) {
        case 'ArrowUp':
            event.preventDefault();
            navigateSunburstNode('up');
            break;
            
        case 'ArrowDown':
            event.preventDefault();
            navigateSunburstNode('down');
            break;
            
        case 'ArrowLeft':
            event.preventDefault();
            switchSunburstPath('left');
            break;
            
        case 'ArrowRight':
            event.preventDefault();
            switchSunburstPath('right');
            break;
            
        case 'Escape':
            // 退出导航模式
            event.preventDefault();
            console.log('退出旭日图导航模式');
            
            // 清除高亮
            if (sunburstChart) {
                sunburstChart.dispatchAction({
                    type: 'downplay',
                    seriesIndex: 0
                });
            }
            
            // 清除路径
            currentSunburstNodePath = [];
            currentSunburstNodeIndex = -1;
            allMatchedPaths = [];
            currentPathIndex = -1;
            break;
    }
}

// 设置旭日图鼠标事件
function setupSunburstMouseEvents() {
    if (!sunburstChart) {
        console.error('旭日图未初始化，无法设置鼠标事件');
        return;
    }
    
    console.log('设置旭日图鼠标事件...');
    
    // 鼠标移入事件 - 现在使用ECharts内置的tooltip，不需要额外处理
    sunburstChart.on('mouseover', function(params) {
        console.log('旭日图鼠标移入:', params.name || params.data?.displayName);
        
        // 检查当前是否在旭日图视图中
        const sunburstContainer = document.getElementById('sunburst-container');
        const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
        
        if (!isSunburstView) {
            return; // 不在旭日图视图中，不处理
        }
        
        // 设置当前视图为旭日图
        window.currentView = 'sunburst';
    });
    
    // 鼠标移出事件 - 确保隐藏自定义悬浮框
    sunburstChart.on('mouseout', function(params) {
        console.log('旭日图鼠标移出:', params.name || params.data?.displayName);
        
        // 检查当前是否在旭日图视图中
        const sunburstContainer = document.getElementById('sunburst-container');
        const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
        
        if (!isSunburstView) {
            return; // 不在旭日图视图中，不处理
        }
        
        // 隐藏企业信息悬浮框（如果存在）
        if (typeof hideCompanyDetailTooltip === 'function') {
            hideCompanyDetailTooltip();
        }
    });
    
    // 全局鼠标移出图表容器事件
    const sunburstChartDiv = document.getElementById('sunburst-chart');
    if (sunburstChartDiv) {
        sunburstChartDiv.addEventListener('mouseleave', function() {
            console.log('鼠标离开旭日图容器');
            
            // 检查当前是否在旭日图视图中
            const sunburstContainer = document.getElementById('sunburst-container');
            const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
            
            if (isSunburstView) {
                // 隐藏企业信息悬浮框
                if (typeof hideCompanyDetailTooltip === 'function') {
                    hideCompanyDetailTooltip();
                }
            }
        });
    }
    
    // 点击事件 - 处理企业节点点击跳转到企业主页
    sunburstChart.on('click', function(params) {
        console.log('旭日图点击事件:', params);
        
        // 检查当前是否在旭日图视图中
        const sunburstContainer = document.getElementById('sunburst-container');
        const isSunburstView = sunburstContainer && !sunburstContainer.classList.contains('hidden');
        
        if (!isSunburstView) {
            return; // 不在旭日图视图中，不处理
        }
        
        // 检查是否是公司节点
        const isCompany = params.data?.isCompany || false;
        if (!isCompany) {
            console.log('点击的是非公司节点，不跳转企业主页');
            return;
        }
        
        // 获取原始节点数据
        const originalData = params.data?.originalData;
        if (!originalData) {
            console.error('无法获取原始节点数据');
            return;
        }

        if(!originalData.properties.credit_code){
            console.log('没有信用代码，不跳转企业主页');
            return;
        }
           
        
        console.log('点击公司节点，准备跳转到企业主页:', originalData.properties.name || originalData.id);
        
        // 如果处于全屏放大状态，先退出全屏再跳转企业主页
        if (isSunburstFullscreen) {
            console.log('检测到全屏放大状态，先退出全屏再跳转企业主页');
            // 存储要跳转的企业数据
            window.pendingCompanyData = originalData;
            // 退出全屏
            exitSunburstFullscreen();
            // 增加延迟时间，确保UI完全恢复后再跳转
            setTimeout(() => {
                if (window.pendingCompanyData) {
                    const companyData = window.pendingCompanyData;
                    window.pendingCompanyData = null;
                    if (typeof showCompanyPage === 'function') {
                        showCompanyPage(companyData);
                    } else {
                        console.error('showCompanyPage函数未定义，请确保company.js已加载');
                        // 如果company.js未加载，尝试动态加载
                        const script = document.createElement('script');
                        script.src = '/static/js/modules/company.js';
                        script.onload = () => {
                            if (typeof showCompanyPage === 'function') {
                                showCompanyPage(companyData);
                            } else {
                                console.error('加载company.js后仍无法找到showCompanyPage函数');
                            }
                        };
                        script.onerror = () => {
                            console.error('加载company.js失败');
                        };
                        document.head.appendChild(script);
                    }
                }
            }, 300); // 增加延迟时间到300ms
        } else {
            // 正常状态直接跳转
            if (typeof showCompanyPage === 'function') {
                showCompanyPage(originalData);
            } else {
                console.error('showCompanyPage函数未定义，请确保company.js已加载');
                // 如果company.js未加载，尝试动态加载
                const script = document.createElement('script');
                script.src = '/static/js/modules/company.js';
                script.onload = () => {
                    if (typeof showCompanyPage === 'function') {
                        showCompanyPage(originalData);
                    } else {
                        console.error('加载company.js后仍无法找到showCompanyPage函数');
                    }
                };
                script.onerror = () => {
                    console.error('加载company.js失败');
                };
                document.head.appendChild(script);
            }
        }
    });
    
    console.log('旭日图鼠标事件设置完成');
}

// 全屏模式下：判断点击是否在圆心区域（根节点范围）
function isClickOnSunburstCenter(e) {
    const chartDom = sunburstChart ? sunburstChart.getDom() : null;
    if (!chartDom) return false;
    const rect = chartDom.getBoundingClientRect();
    const cx = rect.left + rect.width * sunburstCenterX / 100;
    const cy = rect.top + rect.height * sunburstCenterY / 100;
    const clickX = e.clientX;
    const clickY = e.clientY;
    const dist = Math.sqrt((clickX - cx) ** 2 + (clickY - cy) ** 2);
    // 根节点半径：第一层 r_pct(10%) * zoomLevel，乘以0.7适配椭圆
    const rootRadius = rect.width * 0.10 * sunburstZoomLevel * 0.7;
    return dist < rootRadius;
}

// 全屏模式下：圆心拖动时的RAF更新函数（限流到每帧一次）
function sunburstDragRafUpdate() {
    sunburstDragPendingUpdate = false;
    if (!sunburstIsDragging) return;
    // 拖动时关闭动画，避免弧线与文字标签因过渡动画不同步而产生视觉错位
    sunburstChart.setOption({
        series: [{ center: [sunburstPendingCenterX + '%', sunburstPendingCenterY + '%'] }]
    }, {transition: false });
}

// 全屏模式各层级的基准字号（对应 zoom=1.0）
//const SUNBURST_BASE_FONT_SIZES = [0, 14, 12, 10, 10, 4];

// 全屏模式下：应用缩放
function applySunburstZoom(newZoomLevel) {
    sunburstZoomLevel = Math.max(SUNBURST_ZOOM_MIN, Math.min(SUNBURST_ZOOM_MAX, newZoomLevel));
    const outerRadius = Math.round(SUNBURST_BASE_OUTER_RADIUS * sunburstZoomLevel);

    // 根据缩放级别动态调整公司label的显示数量
    applyCompanyLabelsByZoom(sunburstZoomLevel);

    // 根据缩放级别调整各层级的字体大小和半径
    const newLevels = SUNBURST_BASE_LEVELS.map((base, i) => {
        if (i === 0) return {};
        const scale = sunburstZoomLevel;
        // const baseFontSize = SUNBURST_BASE_FONT_SIZES[i] || 10;
        // const scaledFontSize = Math.round(Math.max(3, baseFontSize * scale));
        const merged = {
            r0: Math.round(base.r0_pct * sunburstZoomLevel) + '%',
            r: Math.round(base.r_pct * sunburstZoomLevel) + '%'
        };
        if (base.itemStyle) merged.itemStyle = { ...base.itemStyle };
        if (base.label) merged.label = { ...base.label};
        // else merged.label = { fontSize: scaledFontSize };
        return merged;
    });

    // 遍历树节点，同步缩放非叶子节点和公司节点的 label 字号
    // 因为节点级 label.fontSize 优先级高于 levels 配置，必须直接修改节点数据
    // 企业节点字号：zoom=1.0→4px，zoom=3.0时具身智能→6px，其他→7px，线性插值，最小2px
    const isMore = (window.currentIndustry === 'embodied' || window.currentIndustry === 'low_altitude');
    const companyMaxFontSize = isMore ? 6 : 7;
    const companyFontSize = Math.round(Math.max(2, Math.min(companyMaxFontSize, 4 + (sunburstZoomLevel - 1) * ((companyMaxFontSize - 4) / 2))));
    function scaleNodeLabels(node) {
        if (!node) return;
        if (node.isCompany) {
            // 公司节点（叶子节点）
            if (node.label) {
                node.label.fontSize = companyFontSize;
            }
        } else if (node.label && node.label.fontSize !== undefined) {
            // 非叶子节点：首次缩放时记录原始字号作为基准
            if (node._baseFontSize === undefined) {
                node._baseFontSize = node.label.fontSize;
            }
            node.label.fontSize = Math.round(Math.max(3, node._baseFontSize * sunburstZoomLevel));
        }
        if (node.children) {
            node.children.forEach(function(child) { scaleNodeLabels(child); });
        }
    }
    if (sunburstTreeData) {
        scaleNodeLabels(sunburstTreeData);
    }

    // 通过 setOption 刷新 data，让 ECharts 拾取 label 变化
    sunburstChart.setOption({
        series: [{
            data: [sunburstTreeData],
            radius: ['0%', outerRadius + '%'],
            center: [sunburstCenterX + '%', sunburstCenterY + '%'],
            levels: newLevels
        }]
    });
}

// 全屏模式下：设置缩放和拖动事件
function setupSunburstFullscreenZoomAndDrag() {
    if (!sunburstChart) return;
    const chartDom = sunburstChart.getDom();
    if (!chartDom) return;

    // 重置缩放和拖动状态
    sunburstZoomLevel = 1.0;
    sunburstCenterX = 50;
    sunburstCenterY = 50;
    sunburstIsDragging = false;
    sunburstDragPendingUpdate = false;
    sunburstDragPendingUpdate = false;

    // 鼠标滚轮缩放
    chartDom.addEventListener('wheel', function(e) {
        if (!isSunburstFullscreen) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -SUNBURST_ZOOM_STEP : SUNBURST_ZOOM_STEP;
        applySunburstZoom(sunburstZoomLevel + delta);
    }, { passive: false });

    // 任意位置拖动平移（不限于圆心）
    chartDom.addEventListener('mousedown', function(e) {
        if (!isSunburstFullscreen) return;
        // 只响应左键拖动
        if (e.button !== 0) return;
        sunburstIsDragging = true;
        sunburstDragLastX = e.clientX;
        sunburstDragLastY = e.clientY;
        chartDom.style.cursor = 'grabbing';
        e.preventDefault();
    });

    window.addEventListener('mousemove', function(e) {
        if (!isSunburstFullscreen || !sunburstIsDragging) return;
        const rect = chartDom.getBoundingClientRect();
        const dx = (e.clientX - sunburstDragLastX) / rect.width * 100;
        const dy = (e.clientY - sunburstDragLastY) / rect.height * 100;
        sunburstDragLastX = e.clientX;
        sunburstDragLastY = e.clientY;
        sunburstCenterX += dx;
        sunburstCenterY += dy;
        sunburstPendingCenterX = sunburstCenterX;
        sunburstPendingCenterY = sunburstCenterY;
        // 使用 requestAnimationFrame 限流，避免高频 setOption 导致卡顿
        if (!sunburstDragPendingUpdate) {
            sunburstDragPendingUpdate = true;
            requestAnimationFrame(sunburstDragRafUpdate);
        }
    });

    window.addEventListener('mouseup', function() {
        if (sunburstIsDragging) {
            sunburstIsDragging = false;
            chartDom.style.cursor = '';
        }
    });

    // 鼠标悬停时显示可拖动手型（全屏模式下任意位置均可拖动）
    chartDom.addEventListener('mousemove', function(e) {
        if (sunburstIsDragging) return;
        if (!isSunburstFullscreen) {
            chartDom.style.cursor = '';
            return;
        }
        chartDom.style.cursor = 'grab';
    });
}

// 全屏模式下：移除缩放和拖动事件（通过重置标志让后续 mousemove/mouseup 不再生效）
function teardownSunburstFullscreenZoomAndDrag() {
    // 重置状态即可，事件监听器会检查 isSunburstFullscreen 标志
    sunburstIsDragging = false;
    sunburstDragPendingUpdate = false;
    sunburstZoomLevel = 1.0;
    sunburstCenterX = 50;
    sunburstCenterY = 50;
    const chartDom = sunburstChart ? sunburstChart.getDom() : null;
    if (chartDom) {
        chartDom.style.cursor = '';
    }
}

// 页面加载完成后初始化按钮状态和键盘事件
document.addEventListener('DOMContentLoaded', function() {
    // 默认显示知识图谱视图，所以隐藏知识图谱按钮，显示旭日图按钮
    updateViewSwitchButtons('graph');
    
    // 测试旭日图搜索功能（开发时使用）
    window.testSunburstSearch = function(nodeName) {
        console.log('测试旭日图搜索:', nodeName);
        if (typeof handleGlobalSearchInput === 'function') {
            handleGlobalSearchInput(nodeName);
        }
    };
    
    // 添加键盘事件监听器
    document.addEventListener('keydown', handleSunburstKeyboardNavigation);
    
    // 添加调试函数
    window.debugSunburstNavigation = function() {
        console.log('=== 旭日图导航调试信息 ===');
        console.log('当前节点路径:', currentSunburstNodePath.map(n => n.name));
        console.log('当前节点索引:', currentSunburstNodeIndex);
        console.log('路径长度:', currentSunburstNodePath.length);
        console.log('所有匹配路径数量:', allMatchedPaths.length);
        console.log('当前路径索引:', currentPathIndex);
        if (allMatchedPaths.length > 0) {
            console.log('所有路径详情:');
            allMatchedPaths.forEach((path, index) => {
                const pathNames = path.map(n => n.displayName || n.name.split('_')[0]);
                console.log(`  ${index + 1}. ${pathNames.join(' → ')}`);
            });
        }
        console.log('=== 调试结束 ===');
    };
});

// 调试函数：查找所有可能的tooltip元素
function debugFindTooltipElements(companyName) {
    console.log('=== 查找tooltip元素调试 ===');
    console.log('目标公司名称:', companyName);
    
    // 查找所有可能的tooltip元素
    const selectors = [
        '.echarts-tooltip',
        '.echarts-tooltip-content',
        '[class*="echarts-tooltip"]',
        'div[style*="position: absolute"]',
        'div[style*="background"]',
        'div[style*="border"]'
    ];
    
    selectors.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        console.log(`选择器 "${selector}" 找到 ${elements.length} 个元素:`);
        
        elements.forEach((el, index) => {
            const style = el.style.cssText || '';
            const hasCompanyName = el.innerHTML.includes(companyName) || el.textContent.includes(companyName);
            console.log(`  ${index + 1}. 类名: "${el.className}", 样式长度: ${style.length}, 包含公司名: ${hasCompanyName}`);
            if (style.length < 100) {
                console.log(`     样式: ${style}`);
            }
        });
    });
    
    console.log('=== 调试结束 ===');
}

// 为旭日图异步获取公司详情并更新tooltip
async function fetchCompanyDetailForSunburst(creditCode, companyName, basicProperties) {
    try {
        console.log('旭日图开始获取公司详情:', companyName, '信用代码:', creditCode);
        
        // 先调试查找tooltip元素
        debugFindTooltipElements(companyName);
        
        // 调用API获取公司详情 - 使用与graph_viz.js相同的API
        const apiUrl = `https://sasac-rc.com/api/sdServerUrl/company/enterprise/detail/baseInfo?socialCreditCode=${encodeURIComponent(creditCode)}`;
        
        const response = await fetch(apiUrl, {
            method: 'GET'
        });
        
        if (response.ok) {
            const data = await response.json();
            const companyDetail = data.result;
            
            console.log('旭日图获取到公司详情:', companyName);
            
            // 更新tooltip内容
            updateSunburstTooltipContent(companyName, basicProperties, companyDetail);
        } else {
            console.log('旭日图API调用失败，显示基本信息');
            updateSunburstTooltipContent(companyName, basicProperties, null);
        }
    } catch (error) {
        console.error('旭日图获取公司详情失败:', error);
        updateSunburstTooltipContent(companyName, basicProperties, null);
    }
}

// 更新旭日图tooltip内容
function updateSunburstTooltipContent(companyName, basicProperties, companyDetail) {
    console.log('更新旭日图tooltip内容:', companyDetail);
    
    // 查找当前显示的tooltip - 尝试多种ECharts tooltip类名
    let tooltipElements = document.querySelectorAll('.echarts-tooltip');
    if (tooltipElements.length === 0) {
        // 尝试其他可能的类名
        tooltipElements = document.querySelectorAll('.echarts-tooltip-content');
        if (tooltipElements.length === 0) {
            tooltipElements = document.querySelectorAll('[class*="echarts-tooltip"]');
            if (tooltipElements.length === 0) {
                // 尝试查找所有包含tooltip的div
                tooltipElements = document.querySelectorAll('div[style*="position: absolute"]');
                // 过滤出可能是ECharts tooltip的元素
                tooltipElements = Array.from(tooltipElements).filter(el => {
                    const style = el.style.cssText || '';
                    return style.includes('background') && style.includes('border') && 
                           (el.innerHTML.includes(companyName) || el.textContent.includes(companyName));
                });
                if (tooltipElements.length === 0) {
                    console.error('无法找到任何可能的tooltip元素');
                    return;
                }
            }
        }
    }
    
    // 获取最新的tooltip
    const tooltip = tooltipElements[tooltipElements.length - 1];
    
    // 构建企业信息HTML - 只显示有实际值的字段
    let html = `
        <div style="font-weight:bold;color:#1f2937;font-size:14px;margin-bottom:8px;border-bottom:1px solid #e5e7eb;padding-bottom:6px;line-height:1.2">
            ${companyName}
        </div>
    `;
    
    // 辅助函数：检查字段值是否有效（非空、非"未知"）
    function isValidField(value) {
        return value && value.trim() && value.trim() !== '未知' && value.trim() !== 'null' && value.trim() !== 'undefined';
    }
    
    // 收集要显示的字段
    const fields = [];
    
    // 1. 所属行业
    if (companyDetail && companyDetail.industry && isValidField(companyDetail.industry)) {
        fields.push(`<div style="margin-bottom:4px;line-height:1.6"><span style="color:#6b7280">所属行业:</span> <span style="color:#374151">${companyDetail.industry}</span></div>`);
    }
    
    // 2. 法定代表人
    if (companyDetail && companyDetail.legalPerson && isValidField(companyDetail.legalPerson)) {
        fields.push(`<div style="margin-bottom:4px;line-height:1.6"><span style="color:#6b7280">法定代表人:</span> <span style="color:#374151">${companyDetail.legalPerson}</span></div>`);
    }
    
    // // 3. 注册资本（如果API返回的是paidCapital字段）
    // if (companyDetail && companyDetail.paidCapital && isValidField(companyDetail.paidCapital)) {
    //     fields.push(`<div style="margin-bottom:4px;line-height:1.6"><span style="color:#6b7280">注册资本:</span> <span style="color:#374151">${companyDetail.paidCapital}</span></div>`);
    // }
    
    // 4. 成立日期
    if (companyDetail && companyDetail.incorporationDate && isValidField(companyDetail.incorporationDate)) {
        fields.push(`<div style="margin-bottom:4px;line-height:1.6"><span style="color:#6b7280">成立日期:</span> <span style="color:#374151">${companyDetail.incorporationDate}</span></div>`);
    }
    
    // // 5. 企业类型（从基础属性获取）
    // if (basicProperties && basicProperties.category && isValidField(basicProperties.category)) {
    //     fields.push(`<div style="margin-bottom:4px"><span style="color:#6b7280">企业类型:</span> <span style="color:#374151">${basicProperties.category}</span></div>`);
    // }
    
    // // 6. 信用代码（从基础属性获取）
    // const creditCode = basicProperties?.credit_code || basicProperties?.social_credit_code || basicProperties?.creditCode;
    // if (creditCode && isValidField(creditCode)) {
    //     fields.push(`<div style="margin-bottom:4px"><span style="color:#6b7280">信用代码:</span> <span style="color:#374151">${creditCode}</span></div>`);
    // }
    
    // 添加所有字段到HTML
    if (fields.length > 0) {
        html += fields.join('');
    } else {
        html += `<div style="color:#6b7280;font-style:italic;margin-top:8px;line-height:1.6">暂无详细信息</div>`;
    }
    
    // 更新tooltip内容
    tooltip.innerHTML = html;
    
    console.log('更新后的tooltip内容:', html);
    // 调整tooltip大小和位置
    setTimeout(() => {
        if (sunburstChart && sunburstChart._api) {
            sunburstChart._api.dispatchAction({
                type: 'showTip',
                seriesIndex: 0
            });
        }
    }, 50);
}

// 旭日图全屏放大功能
function toggleSunburstFullscreen() {
    const sunburstContainer = document.getElementById('sunburst-container');
    const zoomBtn = document.getElementById('sunburst-zoom-btn');
    const exitZoomBtn = document.getElementById('sunburst-exit-zoom-btn');
    const sidebar = document.querySelector('aside'); // 左侧导航栏
    const header = document.querySelector('header'); // 顶部标题栏
    const mainContent = document.querySelector('main'); // 主内容区域
    
    if (!sunburstContainer || !zoomBtn || !exitZoomBtn) {
        console.error('无法找到旭日图相关元素');
        return;
    }
    
    // 切换到全屏模式
    isSunburstFullscreen = true;
    
    // 隐藏其他UI元素
    if (sidebar) sidebar.classList.add('hidden');
    if (header) header.classList.add('hidden');
    if (mainContent) {
        mainContent.style.paddingTop = '0';
        mainContent.style.height = '100vh';
    }
    
    // 显示退出按钮，隐藏放大按钮
    zoomBtn.classList.add('hidden');
    exitZoomBtn.classList.remove('hidden');
    
    // 调整旭日图容器为全屏，并设置为flex布局
    sunburstContainer.classList.remove('hidden');
    sunburstContainer.style.position = 'fixed';
    sunburstContainer.style.top = '0';
    sunburstContainer.style.left = '0';
    sunburstContainer.style.width = '100vw';
    sunburstContainer.style.height = '100vh';
    sunburstContainer.style.zIndex = '1000';
    sunburstContainer.style.backgroundColor = 'white';
    sunburstContainer.style.display = 'flex';
    sunburstContainer.style.flexDirection = 'row';
    sunburstContainer.style.justifyContent = 'center'; // 水平居中
    sunburstContainer.style.alignItems = 'center'; // 垂直居中
    
    // 创建左侧图例容器
    createSunburstLegend();
    
    const sunburstChartDiv = document.getElementById('sunburst-chart');
    if (sunburstChartDiv) {
        // 调整图表容器为flex: 1，占据剩余空间，保持全高
        sunburstChartDiv.style.width = '100%';
        sunburstChartDiv.style.height = '100%'; // 保持全高
        sunburstChartDiv.style.flex = '1';
        sunburstChartDiv.style.display = 'flex';
        sunburstChartDiv.style.justifyContent = 'center'; // 水平居中
        sunburstChartDiv.style.alignItems = 'center'; // 垂直居中
    }
    
    // 创建并显示全屏模式下的UI（搜索框和退出按钮）
    createFullscreenUI();
    
    // 调整ECharts配置以适应放大模式 - 增大字体
    if (sunburstChart) {
        const currentOption = sunburstChart.getOption();
        currentOption.series[0].label.fontSize = 14; // 增大字体
        currentOption.series[0].radius = ['0%', '95%']; // 调整半径避免超出边界
        
        // 调整各层级的标签配置 - 增大字体，但保持标签显示
        if (currentOption.series[0].levels) {
            currentOption.series[0].levels.forEach((level, index) => {
                if (level.label) {
                    level.label.fontSize = Math.max(12, 16 - index * 2); // 根据层级调整字体大小
                    level.label.silent = false;
                }
            });
        }
        
        sunburstChart.setOption(currentOption, true);
        sunburstChart.resize();
    }
    
    console.log('旭日图已进入全屏放大模式，左侧图例高度调整为页面一半');
    
    // 设置全屏模式下的鼠标滚轮缩放和圆心拖动
    setupSunburstFullscreenZoomAndDrag();
}

/**
 * 统计旭日图中各类型节点数量
 * 依赖全局变量 allGraphData，统计 Root、环节、四种企业类型（中央企业/其他国资/民营企业/外资企业）
 * @returns {Object} 包含六类节点计数的对象
 */
function countSunburstNodeTypes() {
    const counts = {
        '产业': 0,
        '一级环节': 0,
        '二级环节': 0,
        '三级环节': 0,
        '中央企业': 0,
        '其他国资': 0,
        '民营企业': 0,
        '外资企业': 0
    };
    
    // 从 allGraphData 中统计
    if (typeof allGraphData !== 'undefined' && allGraphData.nodes) {
        allGraphData.nodes.forEach(node => {
            if (node.labels && node.labels.includes('公司')) {
                const category = node.properties?.category || '民营企业';
                
                // 统一分类映射（与图谱图例保持一致）
                if (category === '中央企业') {
                    counts['中央企业']++;
                } else if (category === '其他国资' || category === '国有企业' || category === '地方国企' || category === '事业单位' || category === '未知') {
                    counts['其他国资']++;
                } else if (category === '外资企业' || category === '境外企业') {
                    counts['外资企业']++;
                } else {
                    counts['民营企业']++;
                }
            } else if (node.labels && node.labels.includes('Root')) {
                counts['产业']++;
            } else if (node.labels && node.labels.includes('环节')) {
                // 根据层级拆分为一级/二级/三级环节
                const level = node.properties?.level;
                const name = (node.properties?.name || '');
                if (level === 1 || (!level && (name.includes('上游') || name.includes('中游') || name.includes('下游')))) {
                    counts['一级环节']++;
                } else if (level === 2 || (!level && (name.includes('基础设施') || name.includes('软件开发') || name.includes('主要产品') || name.includes('应用场景')))) {
                    counts['二级环节']++;
                } else {
                    counts['三级环节']++;
                }
            }
        });
    }
    
    return counts;
}

// 创建旭日图图例
// 每次调用时都会用最新的 allGraphData 重新构建统计数据，确保产业切换后图例数据正确刷新
function createSunburstLegend() {
    // 如果已存在旧图例，先移除再用新数据重建
    let legendContainer = document.getElementById('sunburst-legend-container');
    if (legendContainer) {
        legendContainer.remove();
    }
    
    // 创建图例容器
    legendContainer = document.createElement('div');
    legendContainer.id = 'sunburst-legend-container';
    legendContainer.className = 'w-48 bg-white/95 backdrop-blur flex flex-col z-[50] p-3 overflow-y-auto';
    legendContainer.style.border = 'none';
    legendContainer.style.borderRadius = '0';
    legendContainer.style.boxShadow = 'none';
    legendContainer.style.height = 'auto'; // 自适应内容高度
    legendContainer.style.position = 'absolute'; // 绝对定位
    legendContainer.style.left = '40px'; // 左边距
    legendContainer.style.top = '50%'; // 垂直居中
    legendContainer.style.transform = 'translateY(-50%)'; // 垂直居中调整
    
    // 图例内容
    const legendContent = document.createElement('div');
    legendContent.id = 'sunburst-legend-content';
    legendContent.className = '';
    legendContent.style.display = 'flex';
    legendContent.style.flexDirection = 'column';
    legendContent.style.gap = '0';
    
    // 定义图例类型和颜色（与旭日图 levels 配色一致，参考量子科技配色）
    const legendTypes = [
        // { type: '产业', color: '#364A67' },
        // { type: '一级环节', color: '#456DA1' },
        // { type: '二级环节', color: '#6D90BB' },
        // { type: '三级环节', color: '#AEC4DF' },
        { type: '中央企业', color: '#AB4232' },
        { type: '其他国资', color: '#D2A450' },
        { type: '民营企业', color: '#7B72B7' },
        { type: '外资企业', color: '#5E9A76' }
    ];
    
    // 获取各类型节点数量统计
    const typeCounts = countSunburstNodeTypes();
    
    // 添加图例项
    legendTypes.forEach(item => {
        const legendItem = document.createElement('div');
        // 使用图谱图例样式：两端对齐，无 hover 效果，无 cursor-pointer
        legendItem.className = 'flex justify-between items-center text-gray-700 p-2 rounded text-sm w-full';
        
        // 左侧：圆形色块 + 类型名称
        const leftContent = document.createElement('div');
        leftContent.className = 'flex items-center gap-2';
        
        // 圆形色块（与图谱图例一致：w-3 h-3 rounded-full）
        const colorDot = document.createElement('span');
        colorDot.className = 'w-3 h-3 rounded-full';
        colorDot.style.backgroundColor = item.color;
        
        // 类型名称
        const typeName = document.createElement('span');
        typeName.textContent = item.type;
        
        leftContent.appendChild(colorDot);
        leftContent.appendChild(typeName);
        
        // 右侧：数量统计标签
        const countBadge = document.createElement('span');
        countBadge.className = 'bg-gray-200 px-1.5 rounded-full text-[10px] text-gray-700 ml-4 w-8 text-center';
        countBadge.textContent = typeCounts[item.type] || 0;
        
        // 组装图例项
        legendItem.appendChild(leftContent);
        legendItem.appendChild(countBadge);
        legendContent.appendChild(legendItem);
    });
    
    // 组装图例容器
    legendContainer.appendChild(legendContent);
    
    // 将图例容器添加到旭日图容器中（作为第一个子元素）
    const sunburstContainer = document.getElementById('sunburst-container');
    if (sunburstContainer) {
        sunburstContainer.insertBefore(legendContainer, sunburstContainer.firstChild);
    }
}

// 根据侧边栏和导航栏状态更新图例显隐（非全屏模式下使用）
function updateSunburstLegendVisibility() {
    // 全屏模式下不处理（由 createSunburstLegend/exitSunburstFullscreen 管理）
    if (isSunburstFullscreen) return;
    
    const navSidebar = document.getElementById('nav-sidebar');
    const graphSidebar = document.getElementById('graph-sidebar');
    const sunburstContainer = document.getElementById('sunburst-container');
    
    // 仅在旭日图可见时处理
    if (!sunburstContainer || sunburstContainer.classList.contains('hidden')) return;
    
    const navCollapsed = navSidebar && navSidebar.classList.contains('collapsed');
    const graphCollapsed = graphSidebar && graphSidebar.classList.contains('collapsed');
    
    console.log('[旭日图例] navCollapsed:', navCollapsed, 'graphCollapsed:', graphCollapsed);
    
    if (navCollapsed && graphCollapsed) {
        // 侧边栏和导航栏都收起，用最新数据重建图例
        createSunburstLegend();
        const legendContainer = document.getElementById('sunburst-legend-container');
        if (legendContainer) {
            legendContainer.style.display = '';
            legendContainer.style.position = 'absolute';
            legendContainer.style.left = '40px';
            legendContainer.style.top = '50%';
            legendContainer.style.transform = 'translateY(-50%)';
        }
        sunburstContainer.style.overflow = 'visible';
    } else {
        // 任一展开，彻底移除图例
        const legendContainer = document.getElementById('sunburst-legend-container');
        if (legendContainer) {
            legendContainer.remove();
        }
        sunburstContainer.style.overflow = '';
    }
}

// 确保函数全局可访问
window.updateSunburstLegendVisibility = updateSunburstLegendVisibility;

// 创建全屏模式下的搜索框和退出按钮
function createFullscreenUI() {
    // 创建行业切换栏 + 搜索框容器（水平排列）
    let fullscreenSearchBox = document.getElementById('sunburst-fullscreen-search');
    if (!fullscreenSearchBox) {
        fullscreenSearchBox = document.createElement('div');
        fullscreenSearchBox.id = 'sunburst-fullscreen-search';
        fullscreenSearchBox.className = 'absolute top-4 left-4 z-[1002] flex gap-3 items-start';
        fullscreenSearchBox.innerHTML = `
            <!-- 行业切换栏 -->
            <div class="relative" style="z-index: 100004;">
                <div class="relative w-48">
                    <input type="text" id="sunburst-fullscreen-industry-input"
                        class="w-full bg-white/95 text-gray-800 border-2 border-blue-500 rounded-full pl-8 pr-6 py-1.5 text-sm font-medium focus:outline-none focus:border-blue-400 focus:ring-4 focus:ring-blue-500/30 shadow-xl transition-all placeholder-gray-500"
                        placeholder="选择产业..."
                        autocomplete="off"
                        oninput="handleSunburstFullscreenIndustrySearch(this.value)"
                        onfocus="handleSunburstFullscreenIndustrySearch(this.value)"
                        readonly>
                    <i class="fas fa-industry absolute left-3 top-1/2 transform -translate-y-1/2 text-blue-500 text-xs"></i>
                    <i class="fas fa-chevron-down absolute right-2 top-1/2 transform -translate-y-1/2 text-gray-400 pointer-events-none text-xs"></i>
                </div>
                <div id="sunburst-fullscreen-industry-results" class="hidden absolute w-48 mt-1 bg-white border border-gray-300 rounded-xl shadow-xl z-[100005] text-sm text-gray-800 overflow-hidden max-h-64 overflow-y-auto"></div>
            </div>
            <!-- 搜索框 -->
            <div class="relative group w-48">
                <input type="text" id="sunburst-search-input" placeholder="搜索节点..."
                    class="w-full bg-white/95 text-gray-800 border-2 border-blue-500 rounded-full pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:border-blue-400 focus:ring-4 focus:ring-blue-500/30 shadow-xl transition-all placeholder-gray-500"
                    oninput="handleSunburstFullscreenSearch(this.value)" 
                    onkeydown="if(event.key === 'Enter') handleSunburstFullscreenSearch(this.value)">
                <i class="fas fa-search absolute left-3 top-1/2 transform -translate-y-1/2 text-blue-500 text-sm"></i>
                <!-- 搜索建议列表 -->
                <div id="sunburst-search-suggestions" class="hidden absolute w-full mt-1 bg-white border border-gray-300 rounded-xl shadow-xl z-[1003] text-sm text-gray-800 overflow-hidden"></div>
            </div>
        `;
        document.body.appendChild(fullscreenSearchBox);
    } else {
        fullscreenSearchBox.classList.remove('hidden');
    }

    // 初始化行业切换栏当前值
    const industryInput = document.getElementById('sunburst-fullscreen-industry-input');
    if (industryInput && typeof industryOptions !== 'undefined') {
        const current = window.currentIndustry || 'ai';
        const currentOption = industryOptions.find(o => o.value === current);
        industryInput.value = currentOption ? currentOption.text : industryOptions[0].text;
    }

    // 行业切换栏点击展开
    const industryInputEl = document.getElementById('sunburst-fullscreen-industry-input');
    if (industryInputEl && !industryInputEl._fsIndustryBound) {
        industryInputEl._fsIndustryBound = true;
        industryInputEl.addEventListener('click', function() {
            handleSunburstFullscreenIndustrySearch('');
        });
    }

    // 点击页面其他地方隐藏行业下拉
    if (!window._fsIndustryClickBound) {
        window._fsIndustryClickBound = true;
        document.addEventListener('click', function(event) {
            const resultsDiv = document.getElementById('sunburst-fullscreen-industry-results');
            const input = document.getElementById('sunburst-fullscreen-industry-input');
            if (resultsDiv && !resultsDiv.classList.contains('hidden')) {
                if (!resultsDiv.contains(event.target) && (!input || !input.contains(event.target))) {
                    resultsDiv.classList.add('hidden');
                }
            }
        });
    }
    
    // 创建退出按钮
    let fullscreenExitBtn = document.getElementById('sunburst-fullscreen-exit-btn');
    if (!fullscreenExitBtn) {
        fullscreenExitBtn = document.createElement('div');
        fullscreenExitBtn.id = 'sunburst-fullscreen-exit-btn';
        fullscreenExitBtn.className = 'absolute top-4 right-4 z-[1002]';
        fullscreenExitBtn.innerHTML = `
            <button onclick="exitSunburstFullscreen()" class="bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm">
                <i class="fas fa-compress text-xs"></i>
                <span>退出</span>
            </button>
        `;
        document.body.appendChild(fullscreenExitBtn);
    } else {
        fullscreenExitBtn.classList.remove('hidden');
    }
    
    // 创建截图按钮
    let fullscreenScreenshotBtn = document.getElementById('sunburst-fullscreen-screenshot-btn');
    if (!fullscreenScreenshotBtn) {
        fullscreenScreenshotBtn = document.createElement('div');
        fullscreenScreenshotBtn.id = 'sunburst-fullscreen-screenshot-btn';
        fullscreenScreenshotBtn.className = 'absolute top-4 right-24 z-[1002]';
        fullscreenScreenshotBtn.innerHTML = `
            <button onclick="exportEChartsToPng(1)" class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm">
                <i class="fas fa-camera text-xs"></i>
                <span>下载</span>
            </button>
        `;
        document.body.appendChild(fullscreenScreenshotBtn);
    } else {
        fullscreenScreenshotBtn.classList.remove('hidden');
    }
}

// 全屏模式下的行业切换搜索处理
function handleSunburstFullscreenIndustrySearch(value) {
    const searchValue = value || "";
    const resultsDiv = document.getElementById('sunburst-fullscreen-industry-results');
    const input = document.getElementById('sunburst-fullscreen-industry-input');
    
    if (!resultsDiv || !input) return;
    
    input.removeAttribute('readonly');
    resultsDiv.classList.remove('hidden');
    resultsDiv.innerHTML = '';
    
    // 复用全局 industryOptions 数据
    if (typeof industryOptions === 'undefined') return;
    
    const filteredOptions = industryOptions.filter(option => {
        const optionText = option.text.toLowerCase();
        const searchText = searchValue.toLowerCase();
        return optionText.includes(searchText);
    });
    
    if (filteredOptions.length > 0) {
        filteredOptions.forEach(option => {
            const resultItem = document.createElement('div');
            resultItem.className = 'px-4 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100 last:border-b-0';
            resultItem.textContent = option.text;
            resultItem.onclick = () => {
                input.value = option.text;
                input.setAttribute('readonly', 'readonly');
                resultsDiv.classList.add('hidden');
                
                // 记录切换产业日志
                if (typeof uploadActionLog === 'function') {
                    uploadActionLog('产业洞察-切换产业-' + option.text, { "industry": option.value, "industryName": option.text });
                }
                
                // 全屏模式下只刷新旭日图和图例，不影响其他模块
                // 保存原始数据（首次切换时保存，后续切换在已保存的基础上操作）
                if (!window._fsOriginalGraphData) {
                    window._fsOriginalGraphData = JSON.parse(JSON.stringify(allGraphData));
                    window._fsOriginalIndustry = window.currentIndustry;
                }
                
                // 临时设置 currentIndustry 以获取正确的数据源
                window.currentIndustry = option.value;
                
                const dataSource = getIndustryDataSource();
                fetch(dataSource, { cache: "no-cache" })
                    .then(response => {
                        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                        return response.json();
                    })
                    .then(data => {
                        if (data && (data.nodes || data.relationships)) {
                            allGraphData = {
                                nodes: data.nodes || [],
                                links: data.relationships || data.links || []
                            };
                            // 重新渲染旭日图
                            renderSunburstChart();
                            // 重建图例（使用新产业数据统计）
                            createSunburstLegend();
                            // 重新应用全屏模式下的 ECharts 配置
                            if (sunburstChart) {
                                const currentOption = sunburstChart.getOption();
                                currentOption.series[0].label.fontSize = 14;
                                currentOption.series[0].radius = ['0%', '95%'];
                                if (currentOption.series[0].levels) {
                                    currentOption.series[0].levels.forEach((level, index) => {
                                        if (level.label) {
                                            level.label.fontSize = Math.max(12, 16 - index * 2);
                                            level.label.silent = false;
                                        }
                                    });
                                }
                                sunburstChart.setOption(currentOption, true);
                                sunburstChart.resize();
                            }
                        }
                    })
                    .catch(error => {
                        console.error('全屏模式切换产业数据失败:', error);
                    });
            };
            resultsDiv.appendChild(resultItem);
        });
    } else {
        const noResult = document.createElement('div');
        noResult.className = 'px-4 py-2 text-gray-500 text-center';
        noResult.textContent = '未找到匹配的产业';
        resultsDiv.appendChild(noResult);
    }
}

// 全屏模式下的搜索处理函数
function handleSunburstFullscreenSearch(searchTerm) {
    console.log('全屏模式搜索:', searchTerm);
    
    if (!searchTerm || searchTerm.trim() === '') {
        // 清空搜索建议
        const suggestions = document.getElementById('sunburst-search-suggestions');
        if (suggestions) suggestions.classList.add('hidden');
        return;
    }
    
    // 在全量数据中搜索匹配的节点
    if (typeof allGraphData === 'undefined' || !allGraphData.nodes) {
        console.error('图谱数据未加载');
        return;
    }
    
    const term = searchTerm.toLowerCase();
    const matches = allGraphData.nodes.filter(n => {
        const name = (n.properties && n.properties.name) ? n.properties.name.toString() : '';
        return name.toLowerCase().includes(term);
    }).slice(0, 10); // 限制显示前10个结果
    
    if (matches.length > 0) {
        // 生成搜索建议HTML
        let suggestionsHtml = '';
        matches.forEach(match => {
            const name = match.properties.name || String(match.id);
            suggestionsHtml += `
                <div class="px-4 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100 last:border-b-0"
                     onclick="handleSunburstFullscreenSearchClick('${match.id}')">
                    ${name}
                </div>
            `;
        });
        
        const suggestions = document.getElementById('sunburst-search-suggestions');
        if (suggestions) {
            suggestions.innerHTML = suggestionsHtml;
            suggestions.classList.remove('hidden');
        }
    } else {
        // 没有匹配结果
        const suggestions = document.getElementById('sunburst-search-suggestions');
        if (suggestions) {
            suggestions.classList.add('hidden');
        }
    }
}

// 全屏模式下的搜索点击处理
function handleSunburstFullscreenSearchClick(nodeId) {
    console.log('全屏模式搜索点击:', nodeId);
    
    // 隐藏搜索建议
    const suggestions = document.getElementById('sunburst-search-suggestions');
    if (suggestions) suggestions.classList.add('hidden');
    
    // 聚焦到旭日图节点
    focusOnSunburstNode(nodeId);
    
    // 清空搜索框
    const searchInput = document.getElementById('sunburst-search-input');
    if (searchInput) searchInput.value = '';
}

// 退出旭日图全屏放大模式
function exitSunburstFullscreen() {
    const sunburstContainer = document.getElementById('sunburst-container');
    const zoomBtn = document.getElementById('sunburst-zoom-btn');
    const exitZoomBtn = document.getElementById('sunburst-exit-zoom-btn');
    const sidebar = document.querySelector('aside');
    const header = document.querySelector('header');
    const mainContent = document.querySelector('main');
    
    if (!sunburstContainer || !zoomBtn || !exitZoomBtn) {
        console.error('无法找到旭日图相关元素');
        return;
    }
    
    // 退出全屏模式
    isSunburstFullscreen = false;
    
    // 恢复全屏切换行业前的原始数据（如果发生过切换）
    if (window._fsOriginalGraphData) {
        allGraphData = window._fsOriginalGraphData;
        window.currentIndustry = window._fsOriginalIndustry;
        window._fsOriginalGraphData = null;
        window._fsOriginalIndustry = null;
    }
    
    // 恢复其他UI元素
    if (sidebar) sidebar.classList.remove('hidden');
    if (header) header.classList.remove('hidden');
    if (mainContent) {
        mainContent.style.paddingTop = '';
        mainContent.style.height = '';
    }
    
    // 显示放大按钮，隐藏退出按钮
    zoomBtn.classList.remove('hidden');
    exitZoomBtn.classList.add('hidden');
    
    // 恢复旭日图容器的正常布局
    sunburstContainer.style.position = '';
    sunburstContainer.style.top = '';
    sunburstContainer.style.left = '';
    sunburstContainer.style.width = '';
    sunburstContainer.style.height = '';
    sunburstContainer.style.zIndex = '';
    sunburstContainer.style.backgroundColor = '';
    sunburstContainer.style.display = '';
    sunburstContainer.style.flexDirection = '';
    sunburstContainer.style.justifyContent = ''; // 恢复水平居中
    sunburstContainer.style.alignItems = ''; // 恢复垂直居中
    
    // 退出全屏后，根据侧边栏状态决定图例显隐
    updateSunburstLegendVisibility();
    
    // 移除全屏UI元素
    const fullscreenSearchBox = document.getElementById('sunburst-fullscreen-search');
    if (fullscreenSearchBox) {
        fullscreenSearchBox.remove();
    }
    const fullscreenExitBtn = document.getElementById('sunburst-fullscreen-exit-btn');
    if (fullscreenExitBtn) {
        fullscreenExitBtn.remove();
    }
    
    // 恢复正常的高度计算
    const viewportHeight = window.innerHeight;
    const headerHeight = 64; // 顶部导航栏高度
    const availableHeight = viewportHeight - headerHeight;
    sunburstContainer.style.height = availableHeight + 'px';
    
    const sunburstChartDiv = document.getElementById('sunburst-chart');
    if (sunburstChartDiv) {
        sunburstChartDiv.style.width = '100%';
        sunburstChartDiv.style.height = '100%';
        sunburstChartDiv.style.flex = '1';
        sunburstChartDiv.style.display = ''; // 恢复显示属性
        sunburstChartDiv.style.justifyContent = ''; // 恢复水平居中
        sunburstChartDiv.style.alignItems = ''; // 恢复垂直居中
    }
    
    // 恢复ECharts的原始配置
    if (sunburstChart) {
        // 恢复 center 为默认值
        sunburstChart.setOption({
            series: [{
                center: ['50%', '50%'],
                radius: ['0%', '100%']
            }]
        });
        renderSunburstChart(); // 重新渲染以恢复原始配置
    }
    
    // 重置缩放和拖动状态
    teardownSunburstFullscreenZoomAndDrag();
    
    console.log('旭日图已退出全屏放大模式');
}

// 在updateViewSwitchButtons函数中添加对放大按钮和截图按钮的控制
const originalUpdateViewSwitchButtons = updateViewSwitchButtons;
updateViewSwitchButtons = function(currentView) {
    originalUpdateViewSwitchButtons(currentView);
    
    const zoomBtn = document.getElementById('sunburst-zoom-btn');
    const exitZoomBtn = document.getElementById('sunburst-exit-zoom-btn');
    const screenshotBtn = document.getElementById('sunburst-screenshot-btn');
    const techRouteBtn = document.getElementById('switch-to-techroute-btn');
    
    // 放大/退出/截图按钮仅在旭日图视图下控制
    if (zoomBtn && exitZoomBtn && screenshotBtn) {
        if (currentView === 'sunburst') {
            // 在旭日图视图下显示放大按钮和截图按钮（如果不是全屏模式）
            if (!isSunburstFullscreen) {
                zoomBtn.classList.remove('hidden');
                exitZoomBtn.classList.add('hidden');
                screenshotBtn.classList.add('hidden'); // 非全屏模式隐藏截图按钮
            } else {
                zoomBtn.classList.add('hidden');
                exitZoomBtn.classList.remove('hidden');
                screenshotBtn.classList.remove('hidden'); // 全屏模式显示截图按钮
            }
        } else {
            // 在其他视图下隐藏放大相关按钮
            zoomBtn.classList.add('hidden');
            exitZoomBtn.classList.add('hidden');
            screenshotBtn.classList.add('hidden');
        }
    }
    
    // 技术路线按钮：独立于视图模式，仅在量子科技产业时显示（所有视图下都可见）
    if (techRouteBtn) {
        if (window.currentIndustry === 'quantum') {
            techRouteBtn.classList.remove('hidden');
        } else {
            techRouteBtn.classList.add('hidden');
        }
    }
};

// 添加ESC键退出全屏功能
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' && isSunburstFullscreen) {
        exitSunburstFullscreen();
    }
});


function exportEChartsToPng() {
    // 记录旭日图截图下载日志
    if (typeof uploadActionLog === 'function') {
        const industryNameMap = {
            'ai': '人工智能', 'embodied': '具身智能', 'low_altitude': '低空经济',
            'sea': '海洋经济', 'quantum': '量子科技', 'biology': '生物制造',
            'brain': '脑机接口', 'material': '新材料'
        };
        const industryName = industryNameMap[window.currentIndustry] || window.currentIndustry || '人工智能';
        uploadActionLog('产业洞察-旭日图下载-' + industryName, { "industry": window.currentIndustry || 'ai' });
    }
    
    // 获取当前产业的数据源路径，传递给截图专用页面
    const dataSource = getIndustryDataSource();
    const currentIndustry = window.currentIndustry || 'ai';
    
    // 构造截图页面URL，附带数据源和产业信息参数
    const screenshotUrl = `${window.location.origin}/indusgraph/sunburst_screenshot?data_source=${encodeURIComponent(dataSource)}&industry=${encodeURIComponent(currentIndustry)}`;
    
    console.log('打开旭日图截图页面:', screenshotUrl);
    
    // 在新标签页中打开截图专用页面
    window.open(screenshotUrl, '_blank');
  }

  
// 旭日图截图功能
function captureSunburstScreenshot() {
    console.log('开始截图旭日图...');
    
    if (!sunburstChart) {
        console.error('旭日图未初始化');
        alert('请先加载旭日图');
        return;
    }
    
    // 检查是否在全屏模式下
    if (!isSunburstFullscreen) {
        console.warn('截图功能建议在全屏模式下使用，效果更佳');
    }
    
    try {
        // ECharts提供getDataURL方法获取图表图片
        const screenshotUrl = sunburstChart.getDataURL({
            type: 'png',
            pixelRatio: 3, // 高清截图
            backgroundColor: '#ffffff',
            excludeComponents: ['tooltip'] // 排除tooltip
        });
        
        // 创建下载链接
        const downloadLink = document.createElement('a');
        downloadLink.href = screenshotUrl;
        
        // 生成文件名：旭日图_日期_时间
        const now = new Date();
        const dateStr = now.toISOString().split('T')[0];
        const timeStr = now.toTimeString().split(' ')[0].replace(/:/g, '-');
        const fileName = `旭日图_${dateStr}_${timeStr}.png`;
        
        downloadLink.download = fileName;
        document.body.appendChild(downloadLink);
        downloadLink.click();
        document.body.removeChild(downloadLink);
        
        console.log('旭日图截图已保存:', fileName);
        
        // 显示成功消息
        showScreenshotNotification('下载成功！文件已保存为: ' + fileName);
        
    } catch (error) {
        console.error('截图失败:', error);
        alert('截图失败: ' + error.message);
    }
}

// 显示截图通知
function showScreenshotNotification(message) {
    // 检查是否已存在通知
    let notification = document.getElementById('screenshot-notification');
    if (!notification) {
        notification = document.createElement('div');
        notification.id = 'screenshot-notification';
        notification.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 z-[2000] bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-fade-in-up';
        document.body.appendChild(notification);
    }
    
    notification.innerHTML = `
        <i class="fas fa-check-circle text-lg"></i>
        <span class="font-medium">${message}</span>
        <button onclick="this.parentElement.remove()" class="ml-4 text-white/80 hover:text-white">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    // 3秒后自动消失
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 3000);
}
   

// 在退出全屏时移除截图按钮
const originalExitSunburstFullscreen = exitSunburstFullscreen;
exitSunburstFullscreen = function() {
    originalExitSunburstFullscreen();
    
    // 移除全屏截图按钮
    const fullscreenScreenshotBtn = document.getElementById('sunburst-fullscreen-screenshot-btn');
    if (fullscreenScreenshotBtn) {
        fullscreenScreenshotBtn.remove();
    }
    
    // 隐藏普通截图按钮
    const screenshotBtn = document.getElementById('sunburst-screenshot-btn');
    if (screenshotBtn) {
        screenshotBtn.classList.add('hidden');
    }
};

// ========== 量子科技技术路线查看器 ==========
// 技术路线图片配置
const TECH_ROUTE_IMAGES = [
    { name: '三大技术方向', file: '三大技术方向.png' },
    { name: '量子计算',       file: '量子计算.png'      },
    { name: '量子通信',       file: '量子通信.png'      },
    { name: '量子精密测量',   file: '量子精密测量.png'  },
];
let isTechRouteViewerActive = false;  // 技术路线查看器是否激活
let techRouteCurrentIndex = 0;        // 当前图片索引

// 打开技术路线查看器（全屏图片展示）
function openTechRouteViewer() {
    console.log('打开技术路线查看器...');
    
    // 记录技术路线切换日志
    if (typeof uploadActionLog === 'function') {
        uploadActionLog('产业洞察-切换视图-技术路线', { "view": "tech", "industry": window.currentIndustry || 'quantum' });
    }
    
    // 防止重复进入
    if (isTechRouteViewerActive) {
        return;
    }
    isTechRouteViewerActive = true;
    techRouteCurrentIndex = 0;
    
    // 隐藏左侧导航栏
    const navSidebar = document.getElementById('nav-sidebar');
    if (navSidebar) {
        navSidebar.style.display = 'none';
    }
    
    // 隐藏图谱侧边栏
    const graphSidebar = document.getElementById('graph-sidebar');
    if (graphSidebar) {
        graphSidebar.style.display = 'none';
    }
    
    // 隐藏侧边栏缩放把手
    const sidebarHandle = document.getElementById('graph-sidebar-handle');
    if (sidebarHandle) {
        sidebarHandle.style.display = 'none';
    }
    
    // 隐藏右上角按钮组
    const btnContainer = document.querySelector('#view-graph > .absolute');
    if (btnContainer) {
        btnContainer.style.display = 'none';
    }
    
    // 创建全屏覆盖层 DOM
    const viewerHTML = `
        <div id="tech-route-viewer" 
             style="position:fixed;top:0;left:0;width:100vw;height:100vh;
                    background:#F2F3F5;z-index:10000;display:flex;
                    align-items:center;justify-content:center;">
            <!-- 退出按钮（右上角） -->
            <button id="tech-route-exit-btn"
                    onclick="exitTechRouteViewer()"
                    style="position:absolute;top:16px;right:16px;z-index:10;
                           background:rgba(0,0,0,0.08);color:#374151;border:none;
                           border-radius:8px;padding:8px 16px;cursor:pointer;
                           font-size:14px;display:flex;align-items:center;gap:6px;">
                <i class="fas fa-times"></i> 退出
            </button>
            <!-- 左箭头 -->
            <button id="tech-route-prev-btn"
                    onclick="switchTechRouteImage(-1)"
                    style="position:absolute;left:16px;top:50%;transform:translateY(-50%);z-index:10;
                           width:48px;height:48px;border-radius:50%;
                           background:rgba(0,0,0,0.08);color:#374151;border:none;
                           cursor:pointer;display:flex;align-items:center;justify-content:center;
                           font-size:24px;">
                <i class="fas fa-chevron-left"></i>
            </button>
            <!-- 图片 -->
            <img id="tech-route-image"
                 style="width:100vw;height:100vh;object-fit:contain;border-radius:0;"
                 alt="技术路线图片">
            <!-- 右箭头 -->
            <button id="tech-route-next-btn"
                    onclick="switchTechRouteImage(1)"
                    style="position:absolute;right:16px;top:50%;transform:translateY(-50%);z-index:10;
                           width:48px;height:48px;border-radius:50%;
                           background:rgba(0,0,0,0.08);color:#374151;border:none;
                           cursor:pointer;display:flex;align-items:center;justify-content:center;
                           font-size:24px;">
                <i class="fas fa-chevron-right"></i>
            </button>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', viewerHTML);
    
    // 加载第一张图片
    loadTechRouteImage(0);
    
    // 注册键盘事件
    document.addEventListener('keydown', handleTechRouteKeyDown);
}

// 加载指定索引的图片
function loadTechRouteImage(index) {
    const img = document.getElementById('tech-route-image');
    if (!img) return;
    
    const imageInfo = TECH_ROUTE_IMAGES[index];
    if (!imageInfo) return;
    
    // 显示加载中状态
    img.style.opacity = '0.4';
    img.alt = `加载中... ${imageInfo.name}`;
    
    // 加载图片
    const API_BASE = "https://sasac-rc.com/indusgraph/";
    img.src = `${API_BASE}/static/images/industry/${encodeURIComponent(imageInfo.file)}`;
    img.alt = imageInfo.name;
    
    // 图片加载失败处理
    img.onerror = function() {
        this.style.display = 'none';
        // 显示错误占位文字
        let errorEl = document.getElementById('tech-route-error');
        if (!errorEl) {
            errorEl = document.createElement('div');
            errorEl.id = 'tech-route-error';
            errorEl.style.color = 'rgba(0,0,0,0.4)';
            errorEl.style.fontSize = '16px';
            img.parentElement.insertBefore(errorEl, img.nextSibling);
        }
        errorEl.textContent = `图片加载失败: ${imageInfo.name}`;
    };
    
    // 图片加载成功时移除错误提示
    img.onload = function() {
        this.style.display = '';
        this.style.opacity = '1';
        const errorEl = document.getElementById('tech-route-error');
        if (errorEl) {
            errorEl.remove();
        }
    };
}

// 切换技术路线图片
function switchTechRouteImage(direction) {
    if (!isTechRouteViewerActive) return;
    
    const total = TECH_ROUTE_IMAGES.length;
    // 循环切换
    techRouteCurrentIndex = (techRouteCurrentIndex + direction + total) % total;
    
    // 更新图片
    loadTechRouteImage(techRouteCurrentIndex);
}

// 技术路线查看器键盘事件处理
function handleTechRouteKeyDown(event) {
    if (!isTechRouteViewerActive) return;
    
    switch (event.key) {
        case 'ArrowLeft':
            event.preventDefault();
            switchTechRouteImage(-1);
            break;
        case 'ArrowRight':
            event.preventDefault();
            switchTechRouteImage(1);
            break;
        case 'Escape':
            event.preventDefault();
            exitTechRouteViewer();
            break;
    }
}

// 退出技术路线查看器
function exitTechRouteViewer() {
    console.log('退出技术路线查看器...');
    
    if (!isTechRouteViewerActive) {
        return;
    }
    isTechRouteViewerActive = false;
    techRouteCurrentIndex = 0;
    
    // 移除键盘事件监听
    document.removeEventListener('keydown', handleTechRouteKeyDown);
    
    // 移除全屏覆盖层 DOM
    const viewer = document.getElementById('tech-route-viewer');
    if (viewer) {
        viewer.remove();
    }
    
    // 恢复左侧导航栏
    const navSidebar = document.getElementById('nav-sidebar');
    if (navSidebar) {
        navSidebar.style.display = '';
    }
    
    // 恢复图谱侧边栏
    const graphSidebar = document.getElementById('graph-sidebar');
    if (graphSidebar) {
        graphSidebar.style.display = '';
    }
    
    // 恢复侧边栏缩放把手
    const sidebarHandle = document.getElementById('graph-sidebar-handle');
    if (sidebarHandle) {
        sidebarHandle.style.display = '';
    }
    
    // 恢复右上角按钮组
    const btnContainer = document.querySelector('#view-graph > .absolute');
    if (btnContainer) {
        btnContainer.style.display = '';
    }
    
    // 恢复按钮显隐状态
    if (typeof updateViewSwitchButtons === 'function') {
        updateViewSwitchButtons(window.currentView || 'sunburst');
    }
    
    // 触发一次旭日图 resize 以恢复正确尺寸
    setTimeout(() => {
        if (sunburstChart) {
            sunburstChart.resize();
        }
    }, 100);
    
    console.log('技术路线查看器已退出');
}

// 确保全屏模式行业切换函数全局可访问
window.handleSunburstFullscreenIndustrySearch = handleSunburstFullscreenIndustrySearch;
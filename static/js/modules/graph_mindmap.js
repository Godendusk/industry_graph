// 思维导图模块 - Markmap 实现
// 架构参照 graph_sunburt.js

// 思维导图相关变量
let markmapView = null;
let isMindmapInitialized = false;
let isMindmapFullscreen = false;
let mindmapRootData = null;  // 存储根节点数据，供外部 resize 使用

// 获取当前产业的数据源路径
function getIndustryDataSource() {
    const currentIndustry = window.currentIndustry || 'ai';
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
        return `${API_BASE}/static/data/ai/graph_data.json`;
    }
}

// 重置思维导图模块的所有变量
function resetMindmapVariables() {
    console.log('重置思维导图模块变量...');
    isMindmapInitialized = false;
    isMindmapFullscreen = false;
    if (markmapView) {
        try { markmapView.destroy(); } catch (e) { console.warn('销毁 Markmap 实例时出错:', e); }
        markmapView = null;
    }
    window.mindmapNodeTypes = {};
    window.mindmapNodeLevels = {};
    const svgContainer = document.getElementById('mindmap-svg');
    if (svgContainer) svgContainer.innerHTML = '';
    console.log('思维导图模块变量重置完成');
}

// 切换到思维导图视图
function switchToMindmap() {
    console.log('切换到思维导图视图');
    if (typeof exitChainPanoramaFullscreen === 'function') exitChainPanoramaFullscreen();
    
    // 记录思维导图切换日志（系统自动切换时抑制）
    if (typeof uploadActionLog === 'function' && !window.suppressActionLog) {
        uploadActionLog('产业洞察-切换视图-思维导图', { "view": "mindmap", "industry": window.currentIndustry || 'ai' });
    }
    
    window.currentView = 'mindmap';
    window.graphVizSubView = 'mindmap';

    const graphContainer = document.getElementById('graph-container');
    const sunburstContainer = document.getElementById('sunburst-container');
    const mindmapContainer = document.getElementById('mindmap-container');

    if (graphContainer) graphContainer.classList.add('hidden');

    // 隐藏旭日图容器并恢复其样式
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

    const chainContainer = document.getElementById('chain-panorama-container');
    if (chainContainer) {
        chainContainer.classList.add('hidden');
        chainContainer.style.display = '';
        chainContainer.style.width = '';
        chainContainer.style.height = '';
        chainContainer.style.flexDirection = '';
        chainContainer.style.flex = '';
    }

    if (mindmapContainer) {
        mindmapContainer.classList.remove('hidden');
        mindmapContainer.style.width = '100%';
        mindmapContainer.style.height = '100%';
        mindmapContainer.style.display = 'flex';
        mindmapContainer.style.flexDirection = 'column';
        const svgContainer = document.getElementById('mindmap-svg');
        if (svgContainer) {
            svgContainer.style.width = '100%';
            svgContainer.style.height = '100%';
            svgContainer.style.flex = '1';
        }
    }

    updateViewSwitchButtons('mindmap');

    if (!isMindmapInitialized) {
        console.log('初始化思维导图...');
        initMindmapChart();
        isMindmapInitialized = true;
    } else {
        console.log('重新渲染思维导图...');
        setTimeout(renderMindmapChart, 50);
    }
    
    // 根据侧边栏状态决定图例显隐
    setTimeout(updateMindmapLegendVisibility, 350);
}

// 切换到知识图谱视图
function switchToGraph() {
    console.log('切换到图谱视图');
    if (typeof exitChainPanoramaFullscreen === 'function') exitChainPanoramaFullscreen();
    
    // 记录知识图谱切换日志（系统自动切换时抑制）
    if (typeof uploadActionLog === 'function' && !window.suppressActionLog) {
        uploadActionLog('产业洞察-切换视图-知识图谱', { "view": "graph", "industry": window.currentIndustry || 'ai' });
    }
    
    window.currentView = 'graph';
    window.graphVizSubView = 'graph';

    const graphContainer = document.getElementById('graph-container');
    const sunburstContainer = document.getElementById('sunburst-container');
    const mindmapContainer = document.getElementById('mindmap-container');

    if (graphContainer) graphContainer.classList.remove('hidden');

    // 隐藏旭日图容器并恢复其样式（显式设置 display:none 覆盖 HTML 模板中的内联 display:flex）
    if (sunburstContainer) {
        sunburstContainer.style.width = '';
        sunburstContainer.style.height = '';
        sunburstContainer.style.display = 'none';
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
        mindmapContainer.style.overflow = '';
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

// 更新视图切换按钮状态（包装已有函数，追加思维导图 / 产业链全景 放大按钮逻辑）
(function() {
    const originalUpdateViewSwitchButtons = typeof updateViewSwitchButtons === 'function' ? updateViewSwitchButtons : function() {};
    updateViewSwitchButtons = function(currentView) {
        originalUpdateViewSwitchButtons(currentView);
        const mindmapZoomBtn = document.getElementById('mindmap-zoom-btn');
        const mindmapExitZoomBtn = document.getElementById('mindmap-exit-zoom-btn');
        const mindmapScreenshotBtn = document.getElementById('mindmap-screenshot-btn');
        const chainZoomBtn = document.getElementById('chain-zoom-btn');
        const chainExitZoomBtn = document.getElementById('chain-exit-zoom-btn');
        const chainScreenshotBtn = document.getElementById('chain-screenshot-btn');
        const chainFs = typeof window.isChainPanoramaFullscreen === 'boolean' ? window.isChainPanoramaFullscreen : false;

        if (currentView === 'mindmap') {
            if (mindmapZoomBtn && !isMindmapFullscreen) mindmapZoomBtn.classList.remove('hidden');
            if (mindmapExitZoomBtn && isMindmapFullscreen) mindmapExitZoomBtn.classList.remove('hidden');
            if (mindmapScreenshotBtn && isMindmapFullscreen) mindmapScreenshotBtn.classList.remove('hidden');
        } else {
            if (mindmapZoomBtn) mindmapZoomBtn.classList.add('hidden');
            if (mindmapExitZoomBtn) mindmapExitZoomBtn.classList.add('hidden');
            if (mindmapScreenshotBtn) mindmapScreenshotBtn.classList.add('hidden');
        }

        if (currentView === 'chain') {
            if (chainZoomBtn && !chainFs) chainZoomBtn.classList.remove('hidden');
            if (chainExitZoomBtn && chainFs) chainExitZoomBtn.classList.remove('hidden');
            if (chainScreenshotBtn && chainFs) chainScreenshotBtn.classList.remove('hidden');
        } else {
            if (chainZoomBtn) chainZoomBtn.classList.add('hidden');
            if (chainExitZoomBtn) chainExitZoomBtn.classList.add('hidden');
            if (chainScreenshotBtn) chainScreenshotBtn.classList.add('hidden');
        }
    };
})();

// 启用或禁用知识图谱相关按钮
function enableGraphButtons(enable) {
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

// 根据节点类型获取颜色
function getColor(type) {
    if (type === '中央企业') return '#AB4232'; // 暗红
    if (type === '其他国资' || type === '央企/国企' || type === '国有企业') return '#D2A450'; // 金色
    if (type === '外资企业' || type === '境外企业') return '#5E9A76'; // 绿
    return '#7B72B7'; // 紫  民营企业
}

// 构建 Markdown 格式的思维导图数据
function buildMarkdownMindmap(nodes, relationships, rootId) {
    const nodeMap = {};
    const childrenMap = {};
    // 节点名称到企业性质的映射，供 color 回调使用
    window.mindmapNodeTypes = {};
    // 节点名称到层级的映射（环节/产业节点用），供 color 回调使用
    window.mindmapNodeLevels = {};

    nodes.forEach(node => {
        const nodeId = String(node.id);
        nodeMap[nodeId] = node;
        childrenMap[nodeId] = [];
    });

    relationships.forEach(rel => {
        const sourceId = String(rel.source);
        const targetId = String(rel.target);
        if (nodeMap[sourceId] && nodeMap[targetId]) {
            if (childrenMap[targetId]) {
                childrenMap[targetId].push(sourceId);
            }
        }
    });

    // 已访问环节节点集合，防止环节节点循环引用
    const visitedLinkNodes = new Set();

    // 判断节点类型（与旭日图一致）
    function isCompanyNode(node) {
        return node && node.labels && node.labels.includes('公司');
    }
    function isProductNode(node) {
        return node && node.labels && node.labels.includes('产品');
    }
    function isLinkNode(node) {
        return node && node.labels && node.labels.includes('环节');
    }

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

    function getCategorySortKey(node) {
        const cat = node.properties?.category || '民营企业';
        const name = node.properties?.name || '';
        return [categoryOrder[cat] !== undefined ? categoryOrder[cat] : 99, name];
    }

    function buildNodeMarkdown(nodeId, depth, visitedInBranch) {
        const node = nodeMap[nodeId];
        if (!node) return '';

        // 环节节点防重复
        if (isLinkNode(node) && visitedLinkNodes.has(nodeId)) return '';
        if (isLinkNode(node)) visitedLinkNodes.add(nodeId);

        // 企业节点防重复：同一父层级下同一企业只出现一次
        if (isCompanyNode(node)) {
            if (visitedInBranch.has(nodeId)) return '';
            visitedInBranch.add(nodeId);
        }

        const nodeName = node.properties?.name || '节点 ' + nodeId;
        const indent = '  '.repeat(depth);

        // 记录节点名称对应的企业性质
        if (isCompanyNode(node)) {
            window.mindmapNodeTypes[nodeName] = node.properties?.category || '民营企业';
        }
        // 记录环节/产业节点的层级
        if (isLinkNode(node) || (node.labels && node.labels.includes('Root'))) {
            window.mindmapNodeLevels[nodeName] = node.properties?.level || 0;
        }

        // 处理子节点：参照旭日图 createNonLeafNode 逻辑
        const childIds = childrenMap[nodeId] || [];
        var result = indent + '- ' + nodeName + '\n';

        // 收集当前层级下所有需要渲染的子节点，按category排序后统一输出
        var childEntries = [];

        childIds.forEach(function(childId) {
            const childNode = nodeMap[childId];
            if (!childNode) return;

            if (isCompanyNode(childNode)) {
                childEntries.push({
                    type: 'company',
                    nodeId: childId,
                    sortKey: getCategorySortKey(childNode)
                });
            } else if (isProductNode(childNode)) {
                // 产品节点：不显示，将其下的公司节点提升到当前层级
                const productChildIds = childrenMap[childId] || [];
                productChildIds.forEach(function(companyChildId) {
                    const companyNode = nodeMap[companyChildId];
                    if (companyNode && isCompanyNode(companyNode)) {
                        childEntries.push({
                            type: 'company',
                            nodeId: companyChildId,
                            sortKey: getCategorySortKey(companyNode)
                        });
                    }
                });
            } else {
                // 环节节点：递归创建子树
                childEntries.push({
                    type: 'link',
                    nodeId: childId,
                    sortKey: 0
                });
            }
        });

        // 按sortKey排序，环节节点（sortKey=0）排在前面，企业节点按category排序，相同category按名称字母顺序排序
        childEntries.sort(function(a, b) {
            // 如果sortKey是数组（企业节点），先比较category优先级，再比较名称
            if (Array.isArray(a.sortKey) && Array.isArray(b.sortKey)) {
                if (a.sortKey[0] !== b.sortKey[0]) {
                    return a.sortKey[0] - b.sortKey[0];
                }
                return a.sortKey[1].localeCompare(b.sortKey[1], 'zh-CN');
            }
            // 环节节点（sortKey=0）排在前面
            return a.sortKey - b.sortKey;
        });

        childEntries.forEach(function(entry) {
            if (entry.type === 'company') {
                result += buildNodeMarkdown(entry.nodeId, depth + 1, visitedInBranch);
            } else if (entry.type === 'link') {
                result += buildNodeMarkdown(entry.nodeId, depth + 1, new Set());
            }
        });

        return result;
    }

    return buildNodeMarkdown(rootId, 0, new Set());
}

// 初始化思维导图
function initMindmapChart() {
    console.log('初始化 Markmap 思维导图...');
    if (typeof window.markmap === 'undefined') {
        console.error('Markmap 库未加载');
        setTimeout(initMindmapChart, 300);
        return;
    }
    console.log('Markmap 库已加载，开始渲染思维导图...');
    renderMindmapChart();
}

// 渲染思维导图
function renderMindmapChart(isFullscreen) {
    console.log('开始渲染 Markmap 思维导图...', isFullscreen ? '(全屏模式)' : '(普通模式)');

    // 获取当前图谱数据
    if (typeof allGraphData === 'undefined' || !allGraphData.nodes || allGraphData.nodes.length === 0) {
        console.error('No graph data available for mindmap');
        fetchGraphDataForMindmap();
        return;
    }

    console.log('思维导图使用数据节点数:', allGraphData.nodes.length);

    // 转换数据格式
    const mindmapData = {
        nodes: allGraphData.nodes.map(function(node) {
            const properties = node.properties || {};
            if (!properties.name && node.id) properties.name = String(node.id);
            if (!properties.category) {
                if (node.labels && node.labels.includes('公司')) properties.category = '民营企业';
                else if (node.labels && node.labels.includes('环节')) properties.category = '环节';
                else if (node.labels && node.labels.includes('产品')) properties.category = '产品';
            }
            return { id: node.id, properties: properties, labels: node.labels || [] };
        }),
        relationships: (allGraphData.links || allGraphData.relationships || []).map(function(rel) {
            let sourceId = rel.source;
            let targetId = rel.target;
            if (typeof sourceId === 'object' && sourceId !== null) sourceId = sourceId.id;
            if (typeof targetId === 'object' && targetId !== null) targetId = targetId.id;
            return { source: sourceId, target: targetId, type: rel.type };
        })
    };

    // 查找根节点
    const rootNode = mindmapData.nodes.find(function(node) {
        return node.properties.level === 0;
    });
    const rootId = rootNode ? rootNode.id : (mindmapData.nodes[0] ? mindmapData.nodes[0].id : 'root');

    // 构建 Markdown
    const markdownContent = buildMarkdownMindmap(mindmapData.nodes, mindmapData.relationships, rootId);

    // console.log('思维导图 Markdown 内容:', markdownContent);
    const svgContainer = document.getElementById('mindmap-svg');
    if (!svgContainer) {
        console.error('Markmap SVG 容器未找到');
        return;
    }

    // 销毁旧实例
    if (markmapView) {
        try { markmapView.destroy(); } catch (e) {}
        markmapView = null;
    }
    svgContainer.innerHTML = '';

    try {
        if (typeof window.markmap === 'undefined') {
            throw new Error('Markmap 库未加载');
        }

        const transformer = new window.markmap.Transformer();
        const data = transformer.transform(markdownContent);

        // 根据节点文本查找企业性质或层级，返回对应颜色
        function getNodeColor(text) {
            if (!text) return '#9467bd';
            var type = window.mindmapNodeTypes && window.mindmapNodeTypes[text];
            if (type) {
                if (type === '中央企业') return '#AB4232';
                if (type === '其他国资' || type === '央企/国企' || type === '国有企业') return '#D2A450';
                if (type === '外资企业' || type === '境外企业') return '#5E9A76';
                if (type === '民营企业') return '#7B72B7';
            }
            // 环节/产业节点：按层级返回颜色
            var level = window.mindmapNodeLevels && window.mindmapNodeLevels[text];
            if (level !== undefined) {
                if (level === 0) return '#364A67'; // 产业（根节点）
                if (level === 1) return '#456DA1'; // 一级环节
                if (level === 2) return '#6D90BB'; // 二级环节
                return '#AEC4DF';                  // 三级环节
            }
            return '#9467bd';
        }

        // 全屏模式用更大的参数
        const mmOptions = isFullscreen ? {
            autoFit: false,
            duration: 0,
            maxWidth: 800,
            initialExpandLevel: 99,
            //fontSize: 14,
            nodeMinHeight: 12,
            spacingVertical: 10,
            spacingHorizontal: 80,
            paddingX: 10,
            paddingY: 15,
            //fitRatio: 18,
            color: function(node) { return getNodeColor(node.content); },
            lineColor: function(node) { return getNodeColor(node.content); }
        } : {
            autoFit: false,
            duration: 0,
            maxWidth: 300,
            initialExpandLevel: 99,
            //fontSize: 8,
            nodeMinHeight: 8,
            spacingVertical: 8,
            spacingHorizontal: 60,
            paddingX: 30,
            paddingY: 5,
            //fitRatio: 2,
            color: function(node) { return getNodeColor(node.content); },
            lineColor: function(node) { return getNodeColor(node.content); }
        };

        markmapView = window.markmap.Markmap.create(svgContainer, mmOptions);
        markmapView.setData(data.root);
        mindmapRootData = data.root;  // 保存根节点数据，供外部 resize 使用

       

        setTimeout(function() {
            if (!markmapView) return;
            // if (!isFullscreen) {
            //     markmapView.fit();
            // } else {
                // 放大模式：fit后通过centerNode将根节点居中，再向左偏移
               // markmapView.fit();
                setTimeout(function() {
                    markmapView.centerNode(data.root).then(function() {
                        // 居中后将视图向左偏移，使根节点居中靠左
                        var svgEl = markmapView.svg.node();
                        if (svgEl && typeof d3 !== 'undefined') {
                            var currentTransform = d3.zoomTransform(svgEl);
                            var newX = currentTransform.x - svgContainer.clientWidth * (isFullscreen?0.45:0.35);

                            var newTransform = d3.zoomIdentity.translate(newX, currentTransform.y).scale(isFullscreen?1:0.6);
                            d3.select(svgEl).transition().call(markmapView.zoom.transform, newTransform);
                        }
                    }).catch(function(e) {
                        console.warn('centerNode时出错:', e);
                    });
                }, 100);
            // }
        }, 100);

        console.log('Markmap 思维导图渲染成功');
    } catch (error) {
        console.error('渲染 Markmap 思维导图时出错:', error);
        svgContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#666;font-size:14px">思维导图渲染失败: ' + error.message + '</div>';
    }

    // 窗口大小变化时调整
    window.addEventListener('resize', handleMindmapResize);
}

// 处理思维导图窗口大小变化
let mindmapResizeTimer = null;
function handleMindmapResize() {
    if (window.currentView === 'mindmap' && markmapView) {
        // clearTimeout(mindmapResizeTimer);
        // mindmapResizeTimer = setTimeout(function() {
        //     markmapView.fit();
        //     console.log('窗口大小变化后 Markmap 已调整');
        // }, 300);
    }
}

// 从后端获取图谱数据
function fetchGraphDataForMindmap() {
    const dataSource = getIndustryDataSource();
    // console.log('加载思维导图产业数据源:', dataSource);
    fetch(dataSource, { cache: 'no-cache' })
        .then(function(response) {
            if (!response.ok) throw new Error('HTTP error! status: ' + response.status);
            return response.json();
        })
        .then(function(data) {
            // console.log('成功获取思维导图数据:', data);
            if (data && (data.nodes || data.relationships)) {
                allGraphData = {
                    nodes: data.nodes || [],
                    links: data.relationships || data.links || []
                };
                renderMindmapChart();
            } else {
                console.error('数据格式不正确:', data);
            }
        })
        .catch(function(error) {
            console.error('Failed to fetch graph data for mindmap:', error);
        });
}

// 当图谱数据更新时，重新渲染思维导图
if (typeof reloadGraphData === 'function') {
    const originalReloadGraphData = reloadGraphData;
    reloadGraphData = async function(skipStatus, forceReload) {
        const result = await originalReloadGraphData(skipStatus, forceReload);
        // 思维导图：重新渲染图表并刷新图例
        const mindmapContainer = document.getElementById('mindmap-container');
        if (mindmapContainer && !mindmapContainer.classList.contains('hidden')) {
            setTimeout(renderMindmapChart, 500);
            setTimeout(updateMindmapLegendVisibility, 800);
        }
        // 旭日图：重新渲染图表并刷新图例（graph_sunburt.js 的包装被覆盖，在此补上）
        const sunburstContainer = document.getElementById('sunburst-container');
        if (sunburstContainer && !sunburstContainer.classList.contains('hidden')) {
            if (typeof renderSunburstChart === 'function') {
                renderSunburstChart();
            }
            if (typeof updateSunburstLegendVisibility === 'function') {
                setTimeout(updateSunburstLegendVisibility, 600);
            }
        }
        return result;
    };
}

// 思维导图搜索聚焦
function focusOnMindmapNode(nodeId) {
    console.log('Markmap 聚焦到节点:', nodeId);
    console.warn('Markmap 暂不支持节点聚焦功能');
    return false;
}

// 思维导图全屏切换
function toggleMindmapFullscreen() {
    const mindmapContainer = document.getElementById('mindmap-container');
    const svgContainer = document.getElementById('mindmap-svg');
    const mindmapZoomBtn = document.getElementById('mindmap-zoom-btn');
    const mindmapExitZoomBtn = document.getElementById('mindmap-exit-zoom-btn');
    const mindmapScreenshotBtn = document.getElementById('mindmap-screenshot-btn');
    const sidebar = document.querySelector('aside');
    const header = document.querySelector('header');
    const mainContent = document.querySelector('main');

    if (!mindmapContainer || !svgContainer) return;

    if (!isMindmapFullscreen) {
        // 进入全屏模式
        isMindmapFullscreen = true;
        if (sidebar) sidebar.classList.add('hidden');
        if (header) header.classList.add('hidden');
        if (mainContent) {
            mainContent.style.paddingTop = '0';
            mainContent.style.height = '100vh';
        }
        mindmapContainer.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:9999;background:#fff;display:flex;flex-direction:row;overflow:hidden';
        svgContainer.style.cssText = 'width:100%;height:100%;flex:1;padding-left:240px';
        document.body.style.overflow = 'hidden';
        if (mindmapZoomBtn) mindmapZoomBtn.classList.add('hidden');
        if (mindmapExitZoomBtn) mindmapExitZoomBtn.classList.add('hidden');
        if (mindmapScreenshotBtn) mindmapScreenshotBtn.classList.add('hidden');
        updateViewSwitchButtons('mindmap');
        document.addEventListener('keydown', handleMindmapFullscreenKeydown);
        // 创建左侧图例
        createMindmapLegend();
        // 创建右上角下载和退出按钮
        createMindmapFullscreenUI();
        // 全屏模式用更大参数重新渲染
        setTimeout(function() { renderMindmapChart(true); }, 100);
    } else {
        exitMindmapFullscreen();
    }
}

// 处理全屏模式下的键盘事件
function handleMindmapFullscreenKeydown(event) {
    if (event.key === 'Escape' || event.key === 'Esc') {
        exitMindmapFullscreen();
    }
}

// 退出思维导图全屏
function exitMindmapFullscreen() {
    if (!isMindmapFullscreen) return;
    isMindmapFullscreen = false;

    const mindmapContainer = document.getElementById('mindmap-container');
    const svgContainer = document.getElementById('mindmap-svg');
    const mindmapZoomBtn = document.getElementById('mindmap-zoom-btn');
    const mindmapExitZoomBtn = document.getElementById('mindmap-exit-zoom-btn');
    const mindmapScreenshotBtn = document.getElementById('mindmap-screenshot-btn');
    const sidebar = document.querySelector('aside');
    const header = document.querySelector('header');
    const mainContent = document.querySelector('main');

    if (!mindmapContainer || !svgContainer) return;

    if (sidebar) sidebar.classList.remove('hidden');
    if (header) header.classList.remove('hidden');
    if (mainContent) {
        mainContent.style.paddingTop = '';
        mainContent.style.height = '';
    }
    mindmapContainer.style.cssText = 'display:flex;flex-direction:column;width:100%;height:100%';
    svgContainer.style.cssText = 'width:100%;height:100%;flex:1';
    document.body.style.overflow = '';
    if (mindmapZoomBtn) mindmapZoomBtn.classList.remove('hidden');
    if (mindmapExitZoomBtn) mindmapExitZoomBtn.classList.add('hidden');
    if (mindmapScreenshotBtn) mindmapScreenshotBtn.classList.add('hidden');
    document.removeEventListener('keydown', handleMindmapFullscreenKeydown);
    // 退出全屏时先移除旧图例（全屏定位不同），再根据侧边栏状态重建
    removeMindmapLegend();
    removeMindmapFullscreenUI();
    updateViewSwitchButtons('mindmap');
    // 退出全屏，用普通模式参数重新渲染
    setTimeout(function() { renderMindmapChart(false); }, 100);
    console.log('思维导图退出放大模式，页面状态已恢复');
}

// 创建思维导图放大模式左侧图例
// 注意：图例仅在首次调用时创建并缓存，不会随 allGraphData 变化而自动刷新统计数据
function createMindmapLegend() {
    let legendContainer = document.getElementById('mindmap-legend-container');
    if (!legendContainer) {
        legendContainer = document.createElement('div');
        legendContainer.id = 'mindmap-legend-container';
        legendContainer.className = 'w-48 bg-white/95 backdrop-blur flex flex-col z-[10001] p-3 overflow-y-auto';
        legendContainer.style.border = 'none';
        legendContainer.style.borderRadius = '0';
        legendContainer.style.boxShadow = 'none';
        legendContainer.style.height = '50vh';
        legendContainer.style.position = 'absolute';
        legendContainer.style.left = '20px';
        legendContainer.style.top = '50%';
        legendContainer.style.transform = 'translateY(-50%)';

        const legendContent = document.createElement('div');
        legendContent.id = 'mindmap-legend-content';
        legendContent.className = '';
        legendContent.style.display = 'flex';
        legendContent.style.flexDirection = 'column';
        legendContent.style.gap = '0';

        // 定义图例类型和颜色（与旭日图图例一致，参考量子科技配色）
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

        // 获取各类型节点数量统计（复用 countSunburstNodeTypes）
        const typeCounts = typeof countSunburstNodeTypes === 'function' ? countSunburstNodeTypes() : {};

        legendTypes.forEach(function(item) {
            const legendItem = document.createElement('div');
            legendItem.className = 'flex justify-between items-center text-gray-700 p-2 rounded text-sm w-full';

            // 左侧：圆形色块 + 类型名称
            const leftContent = document.createElement('div');
            leftContent.className = 'flex items-center gap-2';

            const colorDot = document.createElement('span');
            colorDot.className = 'w-3 h-3 rounded-full';
            colorDot.style.backgroundColor = item.color;

            const typeName = document.createElement('span');
            typeName.textContent = item.type;

            leftContent.appendChild(colorDot);
            leftContent.appendChild(typeName);

            // 右侧：数量统计标签
            const countBadge = document.createElement('span');
            countBadge.className = 'bg-gray-200 px-1.5 rounded-full text-[10px] text-gray-700 ml-4 w-8 text-center';
            countBadge.textContent = typeCounts[item.type] || 0;

            legendItem.appendChild(leftContent);
            legendItem.appendChild(countBadge);
            legendContent.appendChild(legendItem);
        });

        legendContainer.appendChild(legendContent);

        const mindmapContainer = document.getElementById('mindmap-container');
        if (mindmapContainer) {
            mindmapContainer.insertBefore(legendContainer, mindmapContainer.firstChild);
        }
    } else {
        legendContainer.classList.remove('hidden');
    }
}

// 移除思维导图图例
function removeMindmapLegend() {
    const legendContainer = document.getElementById('mindmap-legend-container');
    if (legendContainer) {
        legendContainer.remove();
    }
}

// 根据侧边栏和导航栏状态更新图例显隐（非全屏模式下使用）
function updateMindmapLegendVisibility() {
    // 全屏模式下不处理
    if (isMindmapFullscreen) return;
    
    const navSidebar = document.getElementById('nav-sidebar');
    const graphSidebar = document.getElementById('graph-sidebar');
    const mindmapContainer = document.getElementById('mindmap-container');
    
    // 仅在思维导图可见时处理
    if (!mindmapContainer || mindmapContainer.classList.contains('hidden')) return;
    
    const navCollapsed = navSidebar && navSidebar.classList.contains('collapsed');
    const graphCollapsed = graphSidebar && graphSidebar.classList.contains('collapsed');
    
    console.log('[思维导图例] navCollapsed:', navCollapsed, 'graphCollapsed:', graphCollapsed);
    
    if (navCollapsed && graphCollapsed) {
        // 侧边栏和导航栏都收起，先移除旧图例再用新数据重建
        let legendContainer = document.getElementById('mindmap-legend-container');
        if (legendContainer) legendContainer.remove();
        createMindmapLegend();
        legendContainer = document.getElementById('mindmap-legend-container');
        if (legendContainer) {
            legendContainer.style.display = '';
            legendContainer.style.position = 'absolute';
            legendContainer.style.left = '20px';
            legendContainer.style.top = '50%';
            legendContainer.style.transform = 'translateY(-50%)';
        }
        mindmapContainer.style.overflow = 'visible';
    } else {
        // 任一展开，彻底移除图例
        const legendContainer = document.getElementById('mindmap-legend-container');
        if (legendContainer) {
            legendContainer.remove();
        }
        mindmapContainer.style.overflow = '';
    }
}

// 确保函数全局可访问
window.updateMindmapLegendVisibility = updateMindmapLegendVisibility;

// 创建思维导图放大模式右上角下载和退出按钮
function createMindmapFullscreenUI() {
    // 下载按钮
    let downloadBtn = document.getElementById('mindmap-fullscreen-download-btn');
    if (!downloadBtn) {
        downloadBtn = document.createElement('div');
        downloadBtn.id = 'mindmap-fullscreen-download-btn';
        downloadBtn.className = 'fixed top-4 right-24 z-[10002]';
        downloadBtn.innerHTML = '<button onclick="captureMindmapScreenshot()" class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm"><i class="fas fa-camera text-xs"></i><span>下载</span></button>';
        document.body.appendChild(downloadBtn);
    } else {
        downloadBtn.classList.remove('hidden');
    }

    // 退出按钮
    let exitBtn = document.getElementById('mindmap-fullscreen-exit-btn');
    if (!exitBtn) {
        exitBtn = document.createElement('div');
        exitBtn.id = 'mindmap-fullscreen-exit-btn';
        exitBtn.className = 'fixed top-4 right-4 z-[10002]';
        exitBtn.innerHTML = '<button onclick="exitMindmapFullscreen()" class="bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-md shadow transition flex items-center gap-1.5 text-sm"><i class="fas fa-compress text-xs"></i><span>退出</span></button>';
        document.body.appendChild(exitBtn);
    } else {
        exitBtn.classList.remove('hidden');
    }
}

// 移除思维导图全屏UI
function removeMindmapFullscreenUI() {
    const downloadBtn = document.getElementById('mindmap-fullscreen-download-btn');
    if (downloadBtn) downloadBtn.remove();
    const exitBtn = document.getElementById('mindmap-fullscreen-exit-btn');
    if (exitBtn) exitBtn.remove();
}

// 思维导图截图
function captureMindmapScreenshot() {
    console.log('开始截图思维导图（完整内容）...');
    const svgContainer = document.getElementById('mindmap-svg');
    if (!svgContainer) {
        alert('思维导图未初始化');
        return;
    }
    if (typeof htmlToImage === 'undefined') {
        alert('截图功能需要 html-to-image 库支持');
        return;
    }

    try {
        var svgEl = markmapView ? markmapView.svg.node() : svgContainer.querySelector('svg');
        if (!svgEl) {
            alert('未找到SVG元素');
            return;
        }
        var gEl = svgEl.querySelector('g');
        if (!gEl) {
            alert('未找到内容元素');
            return;
        }

        // 保存原始状态
        var originalTransform = gEl.getAttribute('transform') || '';
        var originalWidth = svgEl.getAttribute('width');
        var originalHeight = svgEl.getAttribute('height');
        var originalViewBox = svgEl.getAttribute('viewBox');
        var originalStyle = svgEl.getAttribute('style');

        // 移除zoom变换，获取完整内容包围盒
        gEl.setAttribute('transform', '');
        var bbox = gEl.getBBox();
        var padding = 20;
        var fullW = bbox.width + padding * 2;
        var fullH = bbox.height + padding * 2;

        // 设置SVG为完整内容尺寸
        svgEl.setAttribute('width', fullW);
        svgEl.setAttribute('height', fullH);
        svgEl.setAttribute('viewBox', (bbox.x - padding) + ' ' + (bbox.y - padding) + ' ' + fullW + ' ' + fullH);
        svgEl.removeAttribute('style');

        // 截图
        htmlToImage.toPng(svgEl, { pixelRatio: 3, backgroundColor: '#fff', cacheBust: true })
            .then(function(dataUrl) {
                // 恢复原始状态
                gEl.setAttribute('transform', originalTransform);
                if (originalWidth) svgEl.setAttribute('width', originalWidth); else svgEl.removeAttribute('width');
                if (originalHeight) svgEl.setAttribute('height', originalHeight); else svgEl.removeAttribute('height');
                if (originalViewBox) svgEl.setAttribute('viewBox', originalViewBox); else svgEl.removeAttribute('viewBox');
                if (originalStyle) svgEl.setAttribute('style', originalStyle);

                var link = document.createElement('a');
                var now = new Date();
                var dateStr = now.toISOString().split('T')[0];
                var timeStr = now.toTimeString().split(' ')[0].replace(/:/g, '-');
                link.download = '思维导图_' + dateStr + '_' + timeStr + '.png';
                link.href = dataUrl;
                link.click();
                console.log('思维导图完整截图已保存');
                showScreenshotNotification('下载成功！文件已保存为: ' + link.download);
            })
            .catch(function(error) {
                // 恢复原始状态
                gEl.setAttribute('transform', originalTransform);
                if (originalWidth) svgEl.setAttribute('width', originalWidth); else svgEl.removeAttribute('width');
                if (originalHeight) svgEl.setAttribute('height', originalHeight); else svgEl.removeAttribute('height');
                if (originalViewBox) svgEl.setAttribute('viewBox', originalViewBox); else svgEl.removeAttribute('viewBox');
                if (originalStyle) svgEl.setAttribute('style', originalStyle);

                console.error('截图失败:', error);
                alert('截图失败: ' + error.message);
            });
    } catch (e) {
        console.error('截图准备时出错:', e);
        alert('截图失败: ' + e.message);
    }
}

// 显示截图通知
function showScreenshotNotification(message) {
    // 检查是否已存在通知
    let notification = document.getElementById('screenshot-notification');
    if (!notification) {
        notification = document.createElement('div');
        notification.id = 'screenshot-notification';
        notification.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 z-[20000] bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-fade-in-up';
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

// 导出函数供全局使用
window.switchToMindmap = switchToMindmap;
window.switchToGraph = switchToGraph;
window.toggleMindmapFullscreen = toggleMindmapFullscreen;
window.exitMindmapFullscreen = exitMindmapFullscreen;
window.captureMindmapScreenshot = captureMindmapScreenshot;
window.focusOnMindmapNode = focusOnMindmapNode;

// 确保在 DOM 加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('Markmap 思维导图模块已加载');
    if (typeof window.switchToMindmap === 'function') {
        console.log('✓ switchToMindmap 函数已正确导出');
    } else {
        console.error('✗ switchToMindmap 函数导出失败');
    }
});

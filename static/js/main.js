// 全局逻辑 (负责视图切换、初始化、健康检查)

// 通用操作日志上报函数，复用外部平台 uploadLog 接口
function uploadActionLog(title, params = {}) {
    fetch('https://sasac-rc.com/api/v4/user/uploadLog', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'accessToken': sessionStorage.getItem('token') || ''
        },
        body: JSON.stringify({
            "title": title,
            "uri": "/indusgraph/",
            "params": params
        })
    }).catch(error => console.error('日志上传失败:', error));
}

// 定义 API 基础路径
// 确保这个变量在全局范围内可用，因为其他模块（如 policy_sim.js）会用到它
// 如果是生产环境，可能需要修改为实际域名
// const API_BASE = "http://localhost:8000"; 
// 在 base.html 中已经定义了 API_BASE，这里直接使用即可，或者作为后备

// 视图切换逻辑
function switchView(viewName) {
    if (viewName === 'chain') {
        window.pendingGraphSubView = 'chain';
        viewName = 'graph';
    }
    // 进入企业详情前记下当前知识图谱子视图，返回「知识图谱」时恢复（产业链全景 / 旭日图 / 思维导图 / 力导向）
    if (viewName === 'company') {
        window.graphResumeSubView = window.graphVizSubView || null;
    }
    if (viewName !== 'graph') {
        window.graphVizSubView = null;
    }
    if (viewName !== 'graph' && viewName !== 'company') {
        window.graphResumeSubView = null;
    }
    if (viewName !== 'graph' && typeof exitChainPanoramaFullscreen === 'function') {
        exitChainPanoramaFullscreen();
    }

    console.log(`切换视图到: ${viewName}`);

    // 权限拦截：产业报告仅 userId=493 可访问
    if (viewName === 'industry-report' && !checkIndustryReportPermission()) {
        console.warn('当前用户无权访问产业报告功能');
        return;
    }

    // 记录菜单切换日志
    const menuNameMap = {
        'dashboard': '系统概览',
        'graph': '知识图谱',
        'risk': '风险分析',
        'policy': '政策推演',
        'rag': '智能问答',
        'news-list': '行业资讯',
        'company': '企业详情',
        'news-detail': '新闻详情',
        'company-news-detail': '企业新闻详情',
        'industry-report': '产业报告'
    };
    const menuName = menuNameMap[viewName] || viewName;
    if (!window.suppressActionLog) {
        uploadActionLog('产业洞察-切换菜单-' + menuName, { "menu": viewName, "industry": window.currentIndustry || 'ai' });
    }

    // 保存当前视图
    window.currentView = viewName;

    // 隐藏所有视图
    ['dashboard', 'graph', 'risk', 'policy', 'industry-report', 'rag', 'company', 'news-detail', 'news-list', 'company-news-detail'].forEach(v => {
        const el = document.getElementById(`view-${v}`);
        if (el) {
            console.log(`隐藏视图: view-${v}, 当前类名: ${el.className}`);
            el.classList.add('hidden');
        }
    });

    // 显示目标视图
    const targetEl = document.getElementById(`view-${viewName}`);
    if (targetEl) {
        console.log(`显示视图: view-${viewName}, 移除hidden前类名: ${targetEl.className}`);
        targetEl.classList.remove('hidden');
        targetEl.classList.add('fade-in');
        console.log(`显示视图: view-${viewName}, 移除hidden后类名: ${targetEl.className}`);

        // 调试：检查是否真的移除了hidden类
        setTimeout(() => {
            if (targetEl.classList.contains('hidden')) {
                console.error(`警告：view-${viewName}仍然包含hidden类！`);
                console.log('当前类名:', targetEl.className);
                console.log('计算样式:', window.getComputedStyle(targetEl).display);
            }
        }, 100);
    } else {
        console.error(`目标视图元素不存在: view-${viewName}`);
    }

    // 更新导航栏按钮样式
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(btn => {
        btn.classList.remove('bg-blue-50', 'text-blue-600', 'border-blue-200', 'bg-cyan-50', 'text-cyan-700', 'border-cyan-200', 'shadow-sm');
        btn.classList.add('text-gray-600', 'border-transparent');
        // 重置图标颜色
        const icon = btn.querySelector('i');
        if (icon) {
            icon.classList.remove('text-blue-600', 'text-red-600', 'text-purple-600', 'text-emerald-600', 'text-cyan-600');
            icon.classList.add('text-gray-500');
        }
    });

    // 激活当前导航按钮（企业主页没有导航按钮）
    if (viewName !== 'company') {
        const activeId = viewName === 'dashboard' ? 'nav-dashboard' : `nav-${viewName}`;
        const activeBtn = document.getElementById(activeId);
        if (activeBtn) {
            activeBtn.classList.remove('text-gray-600', 'border-transparent');
            activeBtn.classList.add('bg-blue-50', 'text-blue-600', 'border-blue-200', 'shadow-sm');
            const icon = activeBtn.querySelector('i');
            if (icon) {
                icon.classList.remove('text-gray-500');
                icon.classList.add('text-blue-600');
            }
        }
    }

    // 特殊处理：如果是图谱视图，先加载数据再进入子视图（默认旭日图，或 pending / 从企业页返回时恢复）
    if (viewName === 'graph') {
        loadGraphDataForSunburst().then(() => {
            const pending = window.pendingGraphSubView;
            window.pendingGraphSubView = null;
            const resume = window.graphResumeSubView;
            window.graphResumeSubView = null;
            const effective = pending || resume || window.graphVizSubView;

            // 系统自动切换子视图，抑制日志记录
            window.suppressActionLog = true;
            if (effective === 'chain') {
                if (typeof switchToChainPanorama === 'function') switchToChainPanorama();
            } else if (effective === 'mindmap' && typeof switchToMindmap === 'function') {
                switchToMindmap();
            } else if (effective === 'graph' && typeof switchToGraph === 'function') {
                switchToGraph();
                focusPendingGraphNodeFromUrl();
            } else if (effective === 'sunburst' && typeof switchToSunburst === 'function') {
                switchToSunburst();
            } else if (typeof switchToSunburst === 'function') {
                switchToSunburst();
            }
            window.suppressActionLog = false;
        });
    }

    // 触发视图切换事件，让其他模块知道
    const event = new CustomEvent('viewChanged', {
        detail: { viewName: viewName }
    });
    document.dispatchEvent(event);
}

function showDashboard() {
    switchView('dashboard');
}

// 仅加载图谱数据到 allGraphData（不初始化 ForceGraph），供旭日图使用
async function loadGraphDataForSunburst() {
    // 如果数据已存在，直接返回
    if (typeof allGraphData !== 'undefined' && allGraphData.nodes && allGraphData.nodes.length > 0) {
        console.log('图谱数据已存在，跳过加载');
        return;
    }

    console.log('加载图谱数据供旭日图使用...');
    try {
        const dataSource = getIndustryDataSource();
        const resp = await fetch(dataSource, { cache: "no-cache" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        const nodes = data.nodes || [];
        const links = data.relationships || data.links || [];
        allGraphData = { nodes, links };

        console.log(`图谱数据加载完成: ${nodes.length} 个节点, ${links.length} 条关系`);

        // 更新节点统计（JSON 节点总数）
        const totalEl = document.getElementById('stat-total-nodes');
        if (totalEl) totalEl.innerText = nodes.length.toLocaleString();

        // 更新图谱图例
        if (typeof generateLegend === 'function') {
            generateLegend(nodes);
        }
    } catch (err) {
        console.error('加载图谱数据失败:', err);
    }
}

// 后端健康检查逻辑
// 每 5 秒检查一次后端是否在线
setInterval(() => {
    if (typeof API_BASE === 'undefined') return;

    fetch(`${API_BASE}/api/health`)
        .then(() => {
            const dot = document.getElementById('status-dot-api');
            const text = document.getElementById('status-text-api');
            if (dot) dot.className = "w-2 h-2 rounded-full bg-green-500 animate-pulse";
            if (text) {
                text.innerText = "正常";
                text.className = "text-xs font-mono text-green-400";
            }
        })
        .catch(() => {
            const dot = document.getElementById('status-dot-api');
            const text = document.getElementById('status-text-api');
            if (dot) dot.className = "w-2 h-2 rounded-full bg-red-500";
            if (text) {
                text.innerText = "异常";
                text.className = "text-xs font-mono text-red-400";
            }
        });
}, 5000);

// 检查当前用户是否有权访问产业报告功能（userId=493 或 3487 可见）
function checkIndustryReportPermission() {
    return true;
    try {
        const raw = sessionStorage.getItem('userInfo');
        if (!raw) return false;
        const info = JSON.parse(raw);
        return ['493', '3487', '3393', '442'].includes(String(info.userId));
    } catch (e) {
        console.error('解析 userInfo 失败:', e);
        return false;
    }
}

// 根据权限控制产业报告相关元素的显隐
function applyIndustryReportPermission() {
    const allowed = checkIndustryReportPermission();
    // 导航栏按钮
    const navBtn = document.getElementById('nav-industry-report');
    if (navBtn) {
        navBtn.style.display = allowed ? '' : 'none';
    }
    // 仪表盘卡片（通过 data 属性标记，避免依赖 DOM 位置）
    const dashboardCards = document.querySelectorAll('#view-dashboard [onclick*="industry-report"]');
    dashboardCards.forEach(el => {
        el.style.display = allowed ? '' : 'none';
    });
}

// 全局初始化
window.addEventListener('load', () => {
    // 根据用户权限控制产业报告功能显隐
    applyIndustryReportPermission();

    // 默认显示知识图谱（系统自动进入，抑制日志记录）
    window.suppressActionLog = true;
    if (!handleInitialAppRoute()) {
        switchView('graph');
    }
    window.suppressActionLog = false;
    // 如果想要一开始就加载图谱数据（静默加载），也可以在这里调用
    // if(typeof initGraphViz === 'function') initGraphViz();
});

function handleInitialAppRoute() {
    const params = new URLSearchParams(window.location.search);
    const view = params.get('view');
    const subview = params.get('subview');
    const node = params.get('node');
    const industry = params.get('industry');
    if (!view) return false;
    if (industry) setCurrentIndustryFromRoute(industry);
    if (view === 'graph') {
        window.pendingGraphSubView = subview || (node ? 'graph' : null);
        window.pendingGraphFocusNodeId = node || "";
    }
    switchView(view);
    return true;
}

function setCurrentIndustryFromRoute(industryValue) {
    const option = industryOptions.find(item => item.value === industryValue);
    if (!option) return;
    window.currentIndustry = option.value;
    const input = document.getElementById('industry-search-input');
    if (input) {
        input.value = option.text;
        input.setAttribute('readonly', 'readonly');
    }
}

function focusPendingGraphNodeFromUrl() {
    const nodeId = window.pendingGraphFocusNodeId;
    if (!nodeId) return;
    window.pendingGraphFocusNodeId = "";
    retryFocusGraphNode(nodeId, 0);
}

function retryFocusGraphNode(nodeId, attempt) {
    setTimeout(() => {
        if (typeof focusOnNode === 'function') {
            const ready = typeof allGraphData !== 'undefined' && allGraphData.nodes && allGraphData.nodes.length > 0;
            if (ready) {
                focusOnNode(nodeId);
                return;
            }
        }
        if (attempt < 12) retryFocusGraphNode(nodeId, attempt + 1);
    }, 500);
}

// 窗口大小改变时调整图谱
window.addEventListener('resize', () => {
    const graphView = document.getElementById('view-graph');
    if (typeof Graph !== 'undefined' && Graph && graphView && !graphView.classList.contains('hidden')) {
        if (typeof zoomToFitAndCenter === 'function') zoomToFitAndCenter();
    }
});


// 全局拦截获取token
// 保存原生 fetch 方法
const originalFetch = window.fetch;

// 覆盖全局 fetch 方法
window.fetch = async function (url, options = {}) {
    // 从本地存储获取 token
    let token = sessionStorage.getItem('token');
    token = 'eyJ0eXAiOiJKV1QiLCJ0aW1lU3RyIjoiMTc4NTMwNjU0OTM5NyIsImFsZyI6IkhTMjU2In0.eyJ0aW1lU3RyIjoiMTc4NTMwNjU0OTM5NyIsInVzZXJJZCI6IjM0ODcifQ.GK3fj6IXI7s-CRnCx23nMfQgZDXlHIj4Zp3wPVYXy8A'
    if (!token) {
        window.location.href = "https://sasac-rc.com";
    }

    // 统一添加 header
    const headers = {
        'accessToken': token || '',
        'token': token || '',
        ...(options.headers || {}), // 保留传入的 headers
    };


    // 调用原生 fetch
    const response = await originalFetch(url, {
        ...options,
        headers,
    });

    if (response.status === 401 || response.status === 403) {
        window.location.href = "https://sasac-rc.com";
    }

    return response;
};

uploadActionLog('访问产业洞察系统');

// 产业搜索功能
const industryOptions = [
    { value: 'ai', text: '人工智能' },
    { value: 'embodied', text: '具身智能' },
    { value: 'low_altitude', text: '低空经济' },
    { value: 'sea', text: '海洋经济' },
    { value: 'quantum', text: '量子科技' },
    { value: 'biology', text: '生物制造' },
    { value: 'brain', text: '脑机接口' },
    { value: 'material', text: '新材料' }
];

function handleIndustrySearch(value) {
    const searchValue = value || "";
    const resultsDiv = document.getElementById('industry-search-results');
    const input = document.getElementById('industry-search-input');

    if (resultsDiv && input) {
        // 移除只读属性，允许用户输入
        input.removeAttribute('readonly');

        resultsDiv.classList.remove('hidden');

        // 清空之前的结果
        resultsDiv.innerHTML = '';

        // 过滤匹配的选项
        const filteredOptions = industryOptions.filter(option => {
            const optionText = option.text.toLowerCase();
            const searchText = searchValue.toLowerCase();
            return optionText.includes(searchText);
        });

        // 显示结果
        if (filteredOptions.length > 0) {
            filteredOptions.forEach(option => {
                const resultItem = document.createElement('div');
                resultItem.className = 'px-4 py-2 hover:bg-blue-50 cursor-pointer border-b border-gray-100 last:border-b-0';
                resultItem.textContent = option.text;
                resultItem.onclick = () => {
                    // 更新输入框的值
                    input.value = option.text;
                    // 设置当前选择的产业
                    window.currentIndustry = option.value;
                    // 隐藏搜索结果
                    resultsDiv.classList.add('hidden');
                    // 添加只读属性，防止直接编辑
                    input.setAttribute('readonly', 'readonly');

                    console.log(`选择了产业: ${option.text} (${option.value})`);

                    // 记录切换产业日志
                    uploadActionLog('产业洞察-切换产业-' + option.text, { "industry": option.value, "industryName": option.text });

                    // 触发产业切换事件
                    const industryChangedEvent = new CustomEvent('industryChanged', {
                        detail: {
                            industry: option.value,
                            industryName: option.text,
                            timestamp: new Date().toISOString()
                        }
                    });
                    document.dispatchEvent(industryChangedEvent);

                    // 切换产业数据
                    loadIndustryData(option.value);
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
}

// 点击输入框时显示所有选项
document.getElementById('industry-search-input')?.addEventListener('click', function () {
    handleIndustrySearch('');
});

// 用户实际输入搜索词时记录搜索日志（onfocus/onclick 不会触发 input 事件）
document.getElementById('industry-search-input')?.addEventListener('input', function (e) {
    const keyword = (e.target.value || '').trim();
    if (keyword) {
        uploadActionLog('产业洞察-行业搜索-搜索', { "keyword": keyword, "industry": window.currentIndustry || 'ai' });
    }
});

// 点击页面其他地方时隐藏搜索结果
document.addEventListener('click', function (event) {
    const resultsDiv = document.getElementById('industry-search-results');
    const input = document.getElementById('industry-search-input');

    if (resultsDiv && !resultsDiv.classList.contains('hidden')) {
        if (!resultsDiv.contains(event.target) && (!input || !input.contains(event.target))) {
            resultsDiv.classList.add('hidden');
        }
    }
});

// 初始化时设置输入框的值
window.addEventListener('load', function () {
    const input = document.getElementById('industry-search-input');

    if (input) {
        // 默认选择第一个选项（AI产业）
        const defaultOption = industryOptions[0];
        if (!window.currentIndustry) {
            input.value = defaultOption.text;
            window.currentIndustry = defaultOption.value;
        }
    }
});

// 加载产业数据
function loadIndustryData(industryValue) {
    console.log(`切换产业数据: ${industryValue}`);
    /** 与下拉框等调用方对齐，避免仅依赖外部赋值顺序 */
    window.currentIndustry = industryValue;

    // 保存当前视图状态
    const originalView = window.currentView || 'graph';
    // 在 resetSunburstVariables 之前保存全屏状态（该函数会重置 isSunburstFullscreen）
    const wasSunburstFullscreen = originalView === 'sunburst' && typeof isSunburstFullscreen !== 'undefined' ? isSunburstFullscreen : false;
    if (typeof exitChainPanoramaFullscreen === 'function') exitChainPanoramaFullscreen();

    // 无论当前是什么视图，都重置所有模块的变量（必须在切换视图之前执行）
    console.log('开始重置所有模块变量...');

    // 重置知识图谱模块
    if (typeof resetGraphVariables === 'function') {
        console.log('重置知识图谱变量...');
        resetGraphVariables();
    }

    // 重置旭日图模块
    if (typeof resetSunburstVariables === 'function') {
        console.log('重置旭日图变量...');
        resetSunburstVariables();
    }

    // 重置思维导图模块
    if (typeof resetMindmapVariables === 'function') {
        console.log('重置思维导图变量...');
        resetMindmapVariables();
    }

    // 重置风险分析模块
    if (typeof resetRiskVariables === 'function') {
        console.log('重置风险分析变量...');
        resetRiskVariables();
    }

    // 重置政策分析模块
    if (typeof resetPolicyVariables === 'function') {
        console.log('重置政策分析变量...');
        resetPolicyVariables();
    }

    console.log('所有模块变量重置完成');

    // 根据原始视图重新加载数据
    if (originalView === 'graph' || originalView === 'sunburst' || originalView === 'mindmap') {
        // 图谱/旭日图/思维导图视图：先加载数据，再切换到对应子视图
        setTimeout(() => {
            if (typeof reloadGraphData === 'function') {
                console.log(`切换产业，重新加载图谱数据（原视图：${originalView}）...`);
                reloadGraphData(false, true).then(() => {
                    // 数据加载完成后，切换到对应子视图（系统自动切换，抑制日志记录）
                    window.suppressActionLog = true;
                    if (originalView === 'sunburst') {
                        console.log('数据加载完成，切换到旭日图视图');
                        switchToSunburst();
                        // 如果之前是全屏模式，重新进入全屏
                        if (wasSunburstFullscreen && typeof toggleSunburstFullscreen === 'function') {
                            // switchToSunburst 后需要等待渲染完成再进入全屏
                            setTimeout(() => {
                                if (!isSunburstFullscreen) {
                                    toggleSunburstFullscreen();
                                }
                            }, 200);
                        }
                    } else if (originalView === 'mindmap') {
                        console.log('数据加载完成，切换到思维导图视图');
                        switchToSunburst(); // 原逻辑：思维导图切换产业后默认进入旭日图
                    }
                    // 自动切换完成，解除日志抑制
                    window.suppressActionLog = false;
                });
            } else {
                console.warn('reloadGraphData 函数未定义');
            }
        }, 100);
    } else if (originalView === 'risk') {
        // 如果是风险分析视图，重新加载风险节点
        if (typeof loadRiskNodes === 'function') {
            console.log('重新加载风险分析节点列表...');
            loadRiskNodes();
        }
    } else if (originalView === 'policy') {
        // 如果是政策分析视图，重新加载政策列表
        if (typeof loadPolicyList === 'function') {
            console.log('重新加载政策分析列表...');
            loadPolicyList("");
        }
    } else if (originalView === 'rag') {
        // 如果是RAG视图，重新加载RAG数据
        if (typeof loadRAGData === 'function') {
            console.log('重新加载RAG数据...');
            loadRAGData();
        }
    } else if (originalView === 'news-list') {
        // 如果是新闻列表视图，重新加载新闻数据
        if (typeof loadNewsList === 'function') {
            console.log('重新加载新闻列表数据...');
            loadNewsList();
        }
    }
}

// 更新导航栏状态为知识图谱视图
function updateNavigationForGraphView() {
    // 获取导航按钮（通过id）
    const graphNavBtn = document.getElementById('nav-graph');
    const riskNavBtn = document.getElementById('nav-risk');
    const policyNavBtn = document.getElementById('nav-policy');
    const ragNavBtn = document.getElementById('nav-rag');
    const newsListNavBtn = document.getElementById('nav-news-list');

    // 移除所有按钮的激活状态
    if (graphNavBtn) graphNavBtn.classList.remove('bg-blue-600', 'text-white');
    if (riskNavBtn) riskNavBtn.classList.remove('bg-blue-600', 'text-white');
    if (policyNavBtn) policyNavBtn.classList.remove('bg-blue-600', 'text-white');
    if (ragNavBtn) ragNavBtn.classList.remove('bg-blue-600', 'text-white');
    if (newsListNavBtn) newsListNavBtn.classList.remove('bg-blue-600', 'text-white');

    // 添加默认样式
    if (graphNavBtn) graphNavBtn.classList.add('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
    if (riskNavBtn) riskNavBtn.classList.add('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
    if (policyNavBtn) policyNavBtn.classList.add('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
    if (ragNavBtn) ragNavBtn.classList.add('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
    if (newsListNavBtn) newsListNavBtn.classList.add('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');

    // 设置知识图谱按钮为激活状态
    if (graphNavBtn) {
        graphNavBtn.classList.remove('bg-gray-100', 'text-gray-700', 'hover:bg-gray-200');
        graphNavBtn.classList.add('bg-blue-600', 'text-white');
    }

    // 注意：不再直接操作容器显示/隐藏，因为switchView函数会处理这些
    // 容器显示/隐藏由switchView函数统一管理
}

// ========== 左侧导航栏收缩/展开 ==========
function toggleNavSidebar() {
    const aside = document.getElementById('nav-sidebar');
    const icon = document.getElementById('nav-toggle-icon');
    const btn = document.getElementById('nav-toggle-btn');

    if (!aside || !icon) return;

    const isCollapsed = aside.classList.contains('collapsed');

    if (isCollapsed) {
        aside.classList.remove('collapsed');
        icon.style.transform = 'rotate(0deg)';
        if (btn) {
            btn.title = '收起导航栏';
            btn.style.left = '248px';
        }
    } else {
        aside.classList.add('collapsed');
        icon.style.transform = 'rotate(180deg)';
        if (btn) {
            btn.title = '展开导航栏';
            btn.style.left = '4px';
        }
    }

    // class 切换后立即触发 resize（CSS width 已即时生效，transition 只影响视觉呈现）
    requestAnimationFrame(() => {
        triggerSubViewResize();
    });

    // 更新旭日图/思维导图图例显隐
    if (typeof updateSunburstLegendVisibility === 'function') {
        setTimeout(updateSunburstLegendVisibility, 350);
    }
    if (typeof updateMindmapLegendVisibility === 'function') {
        setTimeout(updateMindmapLegendVisibility, 350);
    }
}

// ========== 图谱侧边栏收缩/展开 ==========
function toggleGraphSidebar() {
    const sidebar = document.getElementById('graph-sidebar');
    const handle = document.getElementById('graph-sidebar-handle');
    const icon = document.getElementById('graph-sidebar-handle-icon');

    if (!sidebar || !handle) return;

    const isCollapsed = sidebar.classList.contains('collapsed');

    if (isCollapsed) {
        // 展开侧边栏
        sidebar.classList.remove('collapsed');
        handle.style.left = '384px';
        if (icon) {
            icon.classList.remove('fa-chevron-right');
            icon.classList.add('fa-chevron-left');
        }
        handle.title = '收起侧边栏';
    } else {
        // 收起侧边栏
        sidebar.classList.add('collapsed');
        handle.style.left = '0px';
        if (icon) {
            icon.classList.remove('fa-chevron-left');
            icon.classList.add('fa-chevron-right');
        }
        handle.title = '展开侧边栏';
    }

    // class 切换后立即触发 resize（CSS width 已即时生效，transition 只影响视觉呈现）
    requestAnimationFrame(() => {
        triggerSubViewResize();
    });

    // 更新旭日图/思维导图图例显隐
    if (typeof updateSunburstLegendVisibility === 'function') {
        setTimeout(updateSunburstLegendVisibility, 350);
    }
    if (typeof updateMindmapLegendVisibility === 'function') {
        setTimeout(updateMindmapLegendVisibility, 350);
    }
}

// ========== 侧边栏切换后触发各子视图 resize ==========
function triggerSubViewResize() {
    // 等待 CSS transition 结束（nav-sidebar/graph-sidebar 均为 duration-300）再读取容器尺寸，避免拿到动画中间态导致右侧留白
    const transitionDuration = 350;
    setTimeout(() => {
        _doResize();
    }, transitionDuration);
}

function _doResize() {
    const currentView = window.currentView;
    const subView = window.graphVizSubView;

    // 图谱子视图可能设置 currentView 为 'sunburst'/'mindmap' 等，只要 subView 有值就说明在知识图谱内
    const graphViews = ['graph', 'sunburst', 'mindmap', 'chain'];
    if (!graphViews.includes(currentView) && !graphViews.includes(subView)) {
        return;
    }

    // 力导向图
    if (subView === 'graph' || !subView) {
        if (typeof Graph !== 'undefined' && Graph) {
            try {
                const container = document.getElementById('graph-container');
                if (container) {
                    const w = container.offsetWidth;
                    const h = container.offsetHeight;
                    if (w > 0 && h > 0) {
                        Graph.width(w);
                        Graph.height(h);
                        Graph.zoomToFit(400, 20);
                    }
                }
            } catch (e) {
                console.warn('力导向图 resize 失败:', e);
            }
        }
    }

    // 旭日图
    if (subView === 'sunburst') {
        if (typeof sunburstChart !== 'undefined' && sunburstChart) {
            try {
                const sunburstContainer = document.getElementById('sunburst-container');
                if (sunburstContainer && !sunburstContainer.classList.contains('hidden')) {
                    const viewportHeight = window.innerHeight;
                    const headerHeight = 64;
                    const availableHeight = Math.max(viewportHeight - headerHeight, document.getElementById('view-graph')?.clientHeight || 0);
                    sunburstContainer.style.height = availableHeight + 'px';
                }
                sunburstChart.resize();
            } catch (e) {
                console.warn('旭日图 resize 失败:', e);
            }
        }
    }

    // 思维导图
    if (subView === 'mindmap') {
        if (typeof markmapView !== 'undefined' && markmapView) {
            try {
                const mindmapContainer = document.getElementById('mindmap-container');
                const mindmapSvg = document.getElementById('mindmap-svg');
                if (mindmapContainer && mindmapSvg) {
                    const w = mindmapContainer.offsetWidth;
                    const h = mindmapContainer.offsetHeight;
                    if (w > 0 && h > 0) {
                        mindmapSvg.setAttribute('width', w);
                        mindmapSvg.setAttribute('height', h);
                        mindmapSvg.style.width = w + 'px';
                        mindmapSvg.style.height = h + 'px';
                    }
                }
                // markmapView.fit();

                markmapView.centerNode(mindmapRootData).then(function () {
                    var svgEl = markmapView.svg.node();
                    if (svgEl && typeof d3 !== 'undefined') {
                        var currentTransform = d3.zoomTransform(svgEl);
                        var newX = currentTransform.x - svgEl.clientWidth * 0.3;
                        var newTransform = d3.zoomIdentity.translate(newX, currentTransform.y).scale(0.8);
                        d3.select(svgEl).transition().call(markmapView.zoom.transform, newTransform);
                    }
                }).catch(function (e) {
                    console.warn('思维导图 centerNode 出错:', e);
                });

            } catch (e) {
                console.warn('思维导图 fit 失败:', e);
            }
        }
    }

    // 产业链全景
    if (subView === 'chain') {
        if (typeof chainPanoramaCharts !== 'undefined' && chainPanoramaCharts) {
            try {
                chainPanoramaCharts.forEach(function (c) {
                    if (c && !c.isDisposed()) {
                        c.resize();
                    }
                });
            } catch (e) {
                console.warn('产业链全景 resize 失败:', e);
            }
        }
    }
}

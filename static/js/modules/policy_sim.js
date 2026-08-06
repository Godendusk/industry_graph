// 政策推演前端逻辑

let currentSelectedPolicyId = null;
let currentSelectedPolicyTitle = "";
let policyCache = [];

// 重置政策分析模块的所有变量
function resetPolicyVariables() {
    console.log('重置政策分析模块变量...');
    
    // 重置主要变量
    currentSelectedPolicyId = null;
    currentSelectedPolicyTitle = "";
    policyCache = [];
    
    // 重置搜索输入框
    const searchInput = document.getElementById('policy-search-input');
    if (searchInput) {
        searchInput.value = "";
    }
    
    // 重置搜索结果
    const resultsDiv = document.getElementById('policy-search-results');
    if (resultsDiv) {
        resultsDiv.innerHTML = "";
        resultsDiv.classList.add('hidden');
    }
    
    // 重置已选政策容器
    const selectedBox = document.getElementById('selected-policy-container');
    if (selectedBox) {
        selectedBox.classList.add('hidden');
    }
    
    const selectedTitle = document.getElementById('selected-policy-title');
    if (selectedTitle) {
        selectedTitle.innerText = "";
    }
    
    // 重置报告和图片
    const reportBox = document.getElementById('policy-report');
    if (reportBox) {
        reportBox.innerHTML = "";
    }
    
    const imagesBox = document.getElementById('policy-images');
    if (imagesBox) {
        imagesBox.innerHTML = '<div class="text-gray-400 text-sm">暂无图片，运行推演后显示。</div>';
    }
    
    // 重置按钮状态
    const btn = document.getElementById('btn-run-policy');
    if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play"></i> 开始推演';
    }
    
    console.log('政策分析模块变量重置完成');
}

// 获取当前选择的产业（从全局变量获取）
function getCurrentPolicyIndustry() {
    return window.currentIndustry || 'ai';
}

function renderPolicyList(keyword = "") {
    const resultsDiv = document.getElementById('policy-search-results');
    if (!resultsDiv) return;
    resultsDiv.classList.remove('hidden');
    const kw = (keyword || "").toLowerCase();
    const items = policyCache.filter(item => {
        if (!kw) return true;
        return (item.title || "").toLowerCase().includes(kw);
    });
    if (!items.length) {
        resultsDiv.innerHTML = '<div class="px-4 py-3 text-sm text-gray-500 text-center">未找到相关政策</div>';
        return;
    }
    resultsDiv.innerHTML = items.map(item => `
        <div class="px-4 py-3 cursor-pointer border-b border-gray-100 last:border-0 hover:bg-purple-50 transition text-sm text-gray-700"
             onclick="selectPolicy(${item.id}, '${(item.title || '').replace(/'/g, "\\'")}')">
            <i class="fas fa-file-alt text-purple-400 mr-2"></i>${item.title}
        </div>
    `).join('');
}

async function loadPolicyList(keyword = "") {
    const resultsDiv = document.getElementById('policy-search-results');
    if (!resultsDiv) return;
    resultsDiv.classList.remove('hidden');
    resultsDiv.innerHTML = '<div class="px-4 py-3 text-sm text-gray-500">加载中...</div>';
    
    const industry = getCurrentPolicyIndustry();
    
    try {
        const resp = await fetch(`${API_BASE}/api/policy/list?industry=${encodeURIComponent(industry)}`);
        const data = await resp.json();
        if (data.status === 'success') {
            policyCache = data.data || [];
            console.log(`加载了 ${policyCache.length} 条政策数据（产业：${industry}）`);
            renderPolicyList(keyword);
        } else {
            throw new Error(data.message || "加载失败");
        }
    } catch (err) {
        console.error('政策分析 - 加载列表失败:', err);
        resultsDiv.innerHTML = `<div class="px-4 py-3 text-sm text-red-500 text-center">${err.message || '请求失败'}</div>`;
    }
}

function handlePolicyInput(value) {
    const v = value || "";
    loadPolicyList(v);
}

function selectPolicy(id, title) {
    currentSelectedPolicyId = id;
    currentSelectedPolicyTitle = title;
    const resultsDiv = document.getElementById('policy-search-results');
    const input = document.getElementById('policy-search-input');
    const selectedBox = document.getElementById('selected-policy-container');
    const selectedTitle = document.getElementById('selected-policy-title');
    if (resultsDiv) resultsDiv.classList.add('hidden');
    if (input) input.value = '';
    if (selectedBox) selectedBox.classList.remove('hidden');
    if (selectedTitle) selectedTitle.innerText = title || '';
}

function renderPolicyReport(reportText) {
    const reportBox = document.getElementById('policy-report');
    if (!reportBox) return;
    const mdRenderer = typeof renderMarkdown === 'function' ? renderMarkdown : null;
    const html = mdRenderer ? mdRenderer(reportText || '') : (reportText || '').replace(/\n/g, '<br>');
    reportBox.innerHTML = html || '报告为空';
    if (typeof ensureMarkdownStyle === 'function') ensureMarkdownStyle();
}

function renderPolicyImages(images) {
    const box = document.getElementById('policy-images');
    if (!box) return;
    if (!images || !images.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">暂无图片，运行推演后显示。</div>';
        return;
    }
    box.innerHTML = images.map(url => `
        <div class="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
            <img src="${url}" class="w-full h-auto block" alt="policy-visual">
            <div class="p-2 text-xs text-gray-500 truncate">${url}</div>
        </div>
    `).join('');
}

async function runPolicyAnalysis() {
    const btn = document.getElementById('btn-run-policy');
    if (currentSelectedPolicyId === null) {
        alert('请先选择一条政策');
        return;
    }
    
    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    // 记录政策推演日志
    if (typeof uploadActionLog === 'function') {
        uploadActionLog('产业洞察-政策推演-开始推演', { "policy_index": currentSelectedPolicyId, "industry": currentIndustry });
    }
    
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> 推演中...';
    }
    renderPolicyReport('正在生成报告...');
    renderPolicyImages([]);
    try {
        // const resp = await fetch(`http://127.0.0.1:8000/api/policy/run`, {
        const resp = await fetch(`${API_BASE}/api/policy/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                policy_index: currentSelectedPolicyId,
                industry: currentIndustry 
            })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            renderPolicyReport(data.report || '报告为空');
            renderPolicyImages(data.images || []);
        } else {
            renderPolicyReport('');
        }
    } catch (e) {
        renderPolicyReport('');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play"></i> 开始推演';
        }
    }
}

function exportPolicyPdf() {
    const reportBox = document.getElementById('policy-report');
    const imagesBox = document.getElementById('policy-images');

    if (typeof html2pdf === 'undefined') {
        alert('html2pdf 未加载，无法导出 PDF');
        return;
    }

    const wrapper = document.createElement('div');
    wrapper.style.padding = '16px';
    wrapper.innerHTML = `
        <h2 style="font-size:20px;margin-bottom:8px;">政策推演报告</h2>
        <p style="margin:4px 0 12px;color:#374151;">政策：${currentSelectedPolicyTitle || currentSelectedPolicyId || '未选择'}</p>
        <h3 style="font-size:16px;margin:12px 0 8px;">LLM 推演报告</h3>
        <div>${reportBox ? reportBox.innerHTML : ''}</div>
    `;

    if (imagesBox && imagesBox.children.length) {
        const imgSection = document.createElement('div');
        imgSection.style.marginTop = '16px';
        imgSection.innerHTML = '<h3 style="font-size:16px;margin-bottom:8px;">可视化结果</h3>';
        const cloned = imagesBox.cloneNode(true);
        cloned.querySelectorAll('img').forEach(img => { img.style.maxWidth = '100%'; });
        imgSection.appendChild(cloned);
        wrapper.appendChild(imgSection);
    }

    document.body.appendChild(wrapper);
    const opt = {
        margin: 0.3,
        filename: 'policy_analysis.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2 },
        jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' }
    };
    html2pdf().set(opt).from(wrapper).save().finally(() => wrapper.remove());
}

// 初始化政策分析模块
function initPolicyModule() {
    console.log('初始化政策分析模块...');
    
    // 加载政策列表
    loadPolicyList("");
    
    // 监听产业切换事件
    document.addEventListener('industryChanged', function(e) {
        console.log('政策分析模块 - 检测到产业切换事件:', e.detail);
        
        // 无论当前在哪个视图，都重新加载政策列表
        console.log('切换产业，重新加载政策列表...');
        resetPolicyVariables();
        loadPolicyList("");
    });
}

window.addEventListener('load', initPolicyModule);

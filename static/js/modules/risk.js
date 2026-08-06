// 风险推断前端逻辑

// 重置风险分析模块的所有变量
function resetRiskVariables() {
    console.log('重置风险分析模块变量...');
    
    // 重置节点选择框
    const select = document.getElementById('risk-node-select');
    if (select) {
        select.innerHTML = '<option value="">请选择节点</option>';
    }
    
    // 重置报告
    const reportBox = document.getElementById('risk-report');
    if (reportBox) {
        reportBox.innerHTML = "";
    }
    
    // 重置图片
    const imagesBox = document.getElementById('risk-images');
    if (imagesBox) {
        imagesBox.innerHTML = '<div class="text-gray-400 text-sm">暂无图片，运行分析后显示。</div>';
    }
    
    // 重置按钮状态
    const btn = document.getElementById('btn-run-risk');
    if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-play"></i> 开始分析';
    }
    
    console.log('风险分析模块变量重置完成');
}

// 获取当前选择的产业（从全局变量获取）
function getCurrentRiskIndustry() {
    return window.currentIndustry || 'ai'; // 默认AI产业
}

async function loadRiskNodes() {
    const select = document.getElementById('risk-node-select');
    if (!select) return;
    select.innerHTML = '<option value="">加载中...</option>';
    
    // 获取当前选择的产业
    const industry = getCurrentRiskIndustry();
    
    try {
        // 传递产业参数，使用当前选择的产业
        // const resp = await fetch(`http://127.0.0.1:8000/api/risk/nodes?industry=${encodeURIComponent(industry)}`);
        const resp = await fetch(`${API_BASE}/api/risk/nodes?industry=${encodeURIComponent(industry)}`);
        const data = await resp.json();
        if (data.status === 'success') {
            const nodes = data.nodes || [];
            if (!nodes.length) {
                select.innerHTML = `<option value="">暂无可用节点</option>`;
                return;
            }
            select.innerHTML = nodes.map(n => `<option value="${n}">${n}</option>`).join('');
            console.log(`风险分析 - 加载节点完成，共 ${nodes.length} 个节点`);
        } else {
            select.innerHTML = `<option value="">${data.message || '加载失败'}</option>`;
        }
    } catch (e) {
        select.innerHTML = '<option value="">加载失败</option>';
        console.error('风险分析 - 加载节点失败:', e);
    }
}

function renderRiskImages(images) {
    const box = document.getElementById('risk-images');
    if (!box) return;
    if (!images || !images.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">暂无图片，运行分析后显示。</div>';
        return;
    }
    box.innerHTML = images.map(url => `
        <div class="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
            <img src="${url}" class="w-full h-auto block" alt="risk-visual">
            <div class="p-2 text-xs text-gray-500 truncate">${url}</div>
        </div>
    `).join('');
}

function renderRiskReport(reportText) {
    const reportBox = document.getElementById('risk-report');
    if (!reportBox) return;
    const mdRenderer = typeof renderMarkdown === 'function' ? renderMarkdown : simpleRenderMarkdown;
    const html = mdRenderer ? mdRenderer(reportText || '') : (reportText || '').replace(/\n/g, '<br>');
    reportBox.innerHTML = html || '报告为空';
    if (typeof ensureMarkdownStyle === 'function') {
        ensureMarkdownStyle();
    } else {
        ensureMarkdownStyleFallback();
    }
}

async function runRiskAnalysis() {
    const select = document.getElementById('risk-node-select');
    const btn = document.getElementById('btn-run-risk');
    const nodeName = select ? select.value : '';
    
    if (!nodeName) {
        alert('请先选择一个节点');
        return;
    }
    
    // 获取当前选择的产业
    const industry = getCurrentRiskIndustry();
    
    // 记录风险分析日志
    if (typeof uploadActionLog === 'function') {
        uploadActionLog('产业洞察-风险分析-开始分析', { "node_name": nodeName, "industry": industry });
    }
    
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> 分析中...';
    }
    
    renderRiskReport(`正在生成风险分析报告...`);
    renderRiskImages([]);
    
    try {
        // const resp = await fetch(`http://127.0.0.1:8000/api/risk/run`, {
        const resp = await fetch(`${API_BASE}/api/risk/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                node_name: nodeName,
                industry: industry
            })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            renderRiskReport(data.report || '报告为空');
            renderRiskImages(data.images || []);
            console.log(`风险分析完成 - 节点: ${nodeName}`);
        } else {
            renderRiskReport(`分析失败: ${data.message || '未知错误'}`);
        }
    } catch (e) {
        renderRiskReport(`请求失败: ${e.message}`);
        console.error('风险分析请求失败:', e);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play"></i> 开始分析';
        }
    }
}

function exportRiskPdf() {
    const reportBox = document.getElementById('risk-report');
    const imagesBox = document.getElementById('risk-images');
    const select = document.getElementById('risk-node-select');

    if (typeof html2pdf === 'undefined') {
        alert('html2pdf 未加载，无法导出 PDF');
        return;
    }

    const wrapper = document.createElement('div');
    wrapper.style.padding = '16px';
    
    // 获取产业名称（用于PDF导出，但不在页面上显示）
    const industry = getCurrentRiskIndustry();
    const industryNames = {
        'ai': '人工智能',
        'embodied': '具身智能',
        'low_altitude': '低空经济',
        'sea': '海洋经济',
        'quantum': '量子科技',
        'biology': '生物制造',
        'brain': '脑机接口',
        'material': '新材料'
    };
    const industryName = industryNames[industry] || '未知产业';
    
    wrapper.innerHTML = `
        <h2 style="font-size:20px;margin-bottom:8px;">风险推断分析报告</h2>
        <p style="margin:4px 0 12px;color:#374151;">产业：${industryName}</p>
        <p style="margin:4px 0 12px;color:#374151;">节点：${(select && select.value) || '未选择'}</p>
        <h3 style="font-size:16px;margin:12px 0 8px;">LLM 风险报告</h3>
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
        filename: 'risk_analysis.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2 },
        jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' }
    };
    html2pdf().set(opt).from(wrapper).save().finally(() => wrapper.remove());
}

// 初始化风险分析模块
function initRiskModule() {
    console.log('初始化风险分析模块...');
    
    // 加载节点列表
    loadRiskNodes();
    
    // 监听产业切换事件
    document.addEventListener('industryChanged', function(e) {
        console.log('风险分析模块 - 检测到产业切换事件:', e.detail);
        
        // 无论当前在哪个视图，都重新加载风险分析节点列表
        console.log('切换产业，重新加载风险分析节点列表...');
        // 重置风险分析模块变量
        resetRiskVariables();
        // 重新加载节点列表
        loadRiskNodes();
    });
}

window.addEventListener('load', initRiskModule);

// ---- 简易 Markdown 渲染与样式（当全局未提供 renderMarkdown/ensureMarkdownStyle 时使用） ----
function simpleRenderMarkdown(md) {
    if (!md) return '';
    const escapeHtml = (str) => str.replace(/[&<>"']/g, (ch) => {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
        return map[ch] || ch;
    });
    let html = escapeHtml(md);
    html = html.replace(/```([\s\S]*?)```/g, (m, p1) => `<pre><code>${p1}</code></pre>`);
    html = html.replace(/^###### (.*)$/gm, '<h6>$1</h6>');
    html = html.replace(/^##### (.*)$/gm, '<h5>$1</h5>');
    html = html.replace(/^#### (.*)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.*)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.*)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.*)$/gm, '<h1>$1</h1>');
    html = html.replace(/^\s*-\s+(.*)$/gm, '<li>$1</li>');
    html = html.replace(/<li>([\s\S]*?)<\/li>/g, (m, p1) => `<li>${p1}</li>`);
    html = html.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function ensureMarkdownStyleFallback() {
    if (document.getElementById('markdown-style')) return;
    const style = document.createElement('style');
    style.id = 'markdown-style';
    style.textContent = `
      .markdown-body { line-height: 1.7; font-size: 0.95rem; color: #1f2937; }
      .markdown-body h1, .markdown-body h2, .markdown-body h3,
      .markdown-body h4, .markdown-body h5, .markdown-body h6 {
        font-weight: 700; margin: 1em 0 0.5em; color: #111827;
      }
      .markdown-body h1 { font-size: 1.5em; border-bottom: 1px solid #e5e7eb; padding-bottom: .3em; }
      .markdown-body h2 { font-size: 1.3em; }
      .markdown-body h3 { font-size: 1.15em; }
      .markdown-body ul, .markdown-body ol { padding-left: 1.5em; margin: 0.5em 0 1em; }
      .markdown-body li { margin-bottom: 0.25em; }
      .markdown-body pre { background: #111827; color: #e5e7eb; padding: 12px; border-radius: 8px; overflow-x: auto; }
      .markdown-body code { background: #f3f4f6; padding: 2px 4px; border-radius: 4px; font-size: 0.9em; }
      .markdown-body pre code { background: transparent; color: inherit; padding: 0; }
      .markdown-body p { margin-bottom: 1em; }
    `;
    document.head.appendChild(style);
}

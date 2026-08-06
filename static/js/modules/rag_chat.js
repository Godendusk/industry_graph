// RAG 智能问答逻辑

async function handleRAGSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('rag-input');
    const query = input.value.trim();
    if (!query) return;

    const history = document.getElementById('chat-history');
    
    // 1. 添加用户消息
    history.innerHTML += `
        <div class="flex gap-3 flex-row-reverse fade-in">
            <div class="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center text-white text-xs flex-shrink-0">Me</div>
            <div class="bg-blue-600 text-white p-3 rounded-lg rounded-tr-none shadow-md text-sm max-w-[80%]">${query}</div>
        </div>
    `;
    
    input.value = '';
    history.scrollTop = history.scrollHeight;

    // 2. 添加 Loading 占位符
    const loadingId = 'loading-' + Date.now();
    history.innerHTML += `
        <div id="${loadingId}" class="flex gap-3 fade-in">
            <div class="w-8 h-8 bg-slate-700 rounded-full flex items-center justify-center text-white text-xs flex-shrink-0">AI</div>
            <div class="bg-white p-3 rounded-lg rounded-tl-none shadow-sm text-sm text-gray-500 border border-gray-100 max-w-[80%]">
                <i class="fas fa-circle-notch fa-spin"></i> 思考中...
            </div>
        </div>
    `;
    history.scrollTop = history.scrollHeight;

    try {
        // 获取当前产业
        const currentIndustry = window.currentIndustry || 'ai';
        
        const response = await fetch(`${API_BASE}/api/rag_query`, { 
        // const response = await fetch(`http://127.0.0.1:8000/api/rag_query`, { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({ query: query, industry: currentIndustry }) 
        });
        const data = await response.json();
        
        // 移除 Loading
        const loadingEl = document.getElementById(loadingId);
        if(loadingEl) loadingEl.remove();

        // 3. 添加 AI 回复 + 导出按钮
        const msgContentId = 'ai-msg-' + Date.now();
        const md = data.status === 'success' ? (data.markdown || '') : `[Error] ${data.message}`;
        const answer = renderMarkdown(md || '');
        ensureMarkdownStyle();

        history.innerHTML += `
            <div class="flex gap-3 fade-in">
                <div class="w-8 h-8 bg-slate-700 rounded-full flex items-center justify-center text-white text-xs flex-shrink-0">AI</div>
                <div class="relative bg-white p-3 rounded-lg rounded-tl-none shadow-sm text-sm text-gray-700 border border-gray-100 max-w-[80%] markdown-body">
                    <button onclick="exportAiPdf('${msgContentId}')"
                        class="absolute -top-3 right-0 text-[10px] text-emerald-600 hover:text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded shadow-sm border border-emerald-100">
                        导出PDF
                    </button>
                    <div id="${msgContentId}">${answer}</div>
                </div>
            </div>
        `;
    } catch (err) { 
        console.error(err); 
        const loadingEl = document.getElementById(loadingId);
        if(loadingEl) loadingEl.remove();
        
        history.innerHTML += `
            <div class="flex gap-3 fade-in">
                <div class="w-8 h-8 bg-slate-700 rounded-full flex items-center justify-center text-white text-xs flex-shrink-0 bg-red-500">Err</div>
                <div class="bg-red-50 text-red-600 p-3 rounded-lg rounded-tl-none shadow-sm text-sm border border-red-100 max-w-[80%]">
                    请求失败，请检查后端服务。
                </div>
            </div>
        `;
    }
    history.scrollTop = history.scrollHeight;
}

// ===== Markdown 渲染 =====
function renderMarkdown(md) {
    if (!md) return '';

    // 优先使用 marked + DOMPurify（如果页面已引入）
    if (window.marked) {
        let html = window.marked.parse(md);
        if (window.DOMPurify) {
            html = window.DOMPurify.sanitize(html);
        }
        return html;
    }

    // 简易回退渲染（仅处理常见格式）
    const escapeHtml = (str) => str.replace(/[&<>"']/g, (ch) => {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
        return map[ch] || ch;
    });

    let html = escapeHtml(md);
    // 代码块 ``` ```
    html = html.replace(/```([\s\S]*?)```/g, (m, p1) => `<pre><code>${p1}</code></pre>`);
    // 标题 ######~#
    html = html.replace(/^###### (.*)$/gm, '<h6>$1</h6>');
    html = html.replace(/^##### (.*)$/gm, '<h5>$1</h5>');
    html = html.replace(/^#### (.*)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.*)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.*)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.*)$/gm, '<h1>$1</h1>');
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // 粗体/斜体
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    // 换行
    html = html.replace(/\n/g, '<br>');
    return html;
}

function ensureMarkdownStyle() {
    if (document.getElementById('markdown-style')) return;
    const style = document.createElement('style');
    style.id = 'markdown-style';
    style.textContent = `
      /* 基础容器样式 */
      .markdown-body { 
          line-height: 1.75; 
          font-size: 0.95rem;
          color: #374151; /* gray-700 */
      }

      /* 段落间距 - 解决排版太挤的问题 */
      .markdown-body p {
          margin-bottom: 1em;
      }

      /* 标题样式 - 恢复层级感 */
      .markdown-body h1, .markdown-body h2, .markdown-body h3, 
      .markdown-body h4, .markdown-body h5, .markdown-body h6 { 
          font-weight: 700; 
          margin-top: 1.5em; 
          margin-bottom: 0.75em; 
          line-height: 1.3;
          color: #111827; /* gray-900 */
      }
      .markdown-body h1 { font-size: 1.5em; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.3em; }
      .markdown-body h2 { font-size: 1.25em; }
      .markdown-body h3 { font-size: 1.1em; }

      /* 列表样式 - 解决没有圆点和缩进的问题 */
      .markdown-body ul, .markdown-body ol {
          padding-left: 1.5em; /* 添加左侧缩进 */
          margin-bottom: 1em;
      }
      .markdown-body ul {
          list-style-type: disc; /* 实心圆点 */
      }
      .markdown-body ol {
          list-style-type: decimal; /* 数字序号 */
      }
      .markdown-body li {
          margin-bottom: 0.25em;
      }

      /* 代码块 */
      .markdown-body pre { 
          background: #1e293b; 
          color: #e2e8f0; 
          padding: 1rem; 
          border-radius: 0.5rem; 
          overflow-x: auto; 
          margin-bottom: 1em;
      }
      
      /* 行内代码 */
      .markdown-body code { 
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; 
          background: #f3f4f6; 
          color: #ef4444; 
          padding: 0.2em 0.4em; 
          border-radius: 0.25rem; 
          font-size: 0.875em;
      }
      .markdown-body pre code {
          background: transparent;
          color: inherit;
          padding: 0;
      }

      /* 强调与引用 */
      .markdown-body strong { font-weight: 700; color: #000; }
      .markdown-body em { font-style: italic; }
      
      .markdown-body blockquote {
          border-left: 4px solid #e5e7eb;
          padding-left: 1em;
          color: #6b7280;
          font-style: italic;
          margin-bottom: 1em;
      }
      
      /* 链接 */
      .markdown-body a {
          color: #2563eb;
          text-decoration: underline;
      }
    `;
    document.head.appendChild(style);
}

// 导出单条 AI 回复为 PDF
function exportAiPdf(contentId) {
    const target = document.getElementById(contentId);
    if (!target) return;
    if (typeof html2pdf === 'undefined') {
        console.warn('html2pdf 未加载，无法导出');
        return;
    }
    const opt = {
        margin: 0.3,
        filename: 'ai_reply.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2 },
        jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' },
        pagebreak: { mode: ['avoid-all', 'css', 'legacy'] }
    };
    // 尝试避免分页截断
    target.style.pageBreakInside = 'avoid';
    target.style.breakInside = 'avoid';
    html2pdf().set(opt).from(target).save().finally(() => {
        target.style.pageBreakInside = '';
        target.style.breakInside = '';
    });
}

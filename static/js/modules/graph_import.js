// 图谱导入：上传 -> 解析 -> 勾选 -> 入图

let importSessionId = null;
let importCandidates = { nodes: [], links: [] };
let selectedImportNodes = new Set();
let selectedImportLinks = new Set();
let pendingFile = null;
let graphJsonFiles = [];

function handleGraphImportUpload(evt) {
    pendingFile = evt.target.files && evt.target.files[0] ? evt.target.files[0] : null;
    const statusEl = document.getElementById('graph-import-status');
    if (pendingFile && statusEl) {
        statusEl.innerText = `已选择：${pendingFile.name}`;
    }
}

function handleGraphJsonUpload(evt) {
    graphJsonFiles = evt.target.files ? Array.from(evt.target.files) : [];
    const statusEl = document.getElementById('graph-json-status');
    if (graphJsonFiles.length && statusEl) {
        statusEl.innerText = `已选择 ${graphJsonFiles.length} 个文件`;
    }
}

async function uploadGraphJson() {
    const statusEl = document.getElementById('graph-json-status');
    if (!graphJsonFiles.length) {
        if (statusEl) statusEl.innerText = '请先选择 JSON 文件。';
        return;
    }
    if (statusEl) statusEl.innerText = '上传中，请稍候...';

    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    const form = new FormData();
    graphJsonFiles.forEach(f => form.append('files', f));
    form.append('industry', currentIndustry);
    try {
        const resp = await fetch(`${API_BASE}/api/graph_import_json`, {
            method: 'POST',
            body: form
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            statusEl.innerText = data.message || '上传失败';
            return;
        }
        statusEl.innerText = `上传成功：新增节点 ${data.added_nodes}，新增关系 ${data.added_links}（产业：${data.industry || currentIndustry}）。当前总节点 ${data.nodes}，总关系 ${data.relationships}。请刷新图谱查看。`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `上传失败: ${err.message}`;
    }
}

async function uploadGraphJsonReplace() {
    const statusEl = document.getElementById('graph-json-status');
    if (!graphJsonFiles.length) {
        if (statusEl) statusEl.innerText = '请先选择 JSON 文件。';
        return;
    }
    if (statusEl) statusEl.innerText = '覆盖上传中，请稍候...';

    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    const form = new FormData();
    form.append('file', graphJsonFiles[0]); // 仅取第一个文件覆盖
    form.append('industry', currentIndustry);
    try {
        const resp = await fetch(`${API_BASE}/api/graph_import_json_replace`, {
            method: 'POST',
            body: form
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            statusEl.innerText = data.message || '覆盖失败';
            return;
        }
        statusEl.innerText = `覆盖成功：节点 ${data.nodes}，关系 ${data.relationships}（产业：${data.industry || currentIndustry}）。请刷新图谱查看。`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `覆盖失败: ${err.message}`;
    }
}

async function triggerGraphImport() {
    const statusEl = document.getElementById('graph-import-status');
    if (!pendingFile) {
        if (statusEl) statusEl.innerText = '请先选择文件。';
        return;
    }
    if (statusEl) statusEl.innerText = '解析中，请稍候...';

    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    const form = new FormData();
    form.append('file', pendingFile);
    form.append('industry', currentIndustry);
    try {
        const resp = await fetch(`${API_BASE}/api/graph_import/upload`, {
            method: 'POST',
            body: form
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            statusEl.innerText = data.message || '解析失败';
            return;
        }
        importSessionId = data.session_id;
        importCandidates = data.data || { nodes: [], links: [] };
        selectedImportNodes = new Set(importCandidates.nodes.map(n => n.temp_id));
        selectedImportLinks = new Set(importCandidates.links.map(l => l.temp_id));
        statusEl.innerText = `解析成功：节点 ${importCandidates.nodes.length} 条，关系 ${importCandidates.links.length} 条（产业：${data.industry || currentIndustry}）`;
        renderImportLists();
    } catch (err) {
        if (statusEl) statusEl.innerText = `解析失败: ${err.message}`;
    }
}

function renderImportLists() {
    const nodesBox = document.getElementById('graph-import-nodes');
    const linksBox = document.getElementById('graph-import-links');

    // temp_id -> name map for better relationship display
    const nodeNameMap = new Map();
    importCandidates.nodes.forEach(n => {
        const name = (n.properties && (n.properties.name || n.properties["名称"])) || n.temp_id;
        nodeNameMap.set(n.temp_id, name);
    });

    if (nodesBox) {
        nodesBox.innerHTML = importCandidates.nodes.map(n => {
            const checked = selectedImportNodes.has(n.temp_id) ? 'checked' : '';
            const label = (n.labels && n.labels[0]) || '节点';
            const name = n.properties && (n.properties.name || n.properties.名称) || '';
            return `<label class="flex items-center gap-2 px-2 py-1 rounded bg-gray-100 border border-gray-300">
                <input type="checkbox" ${checked} onchange="toggleImportNode('${n.temp_id}', this.checked)">
                <span class="text-gray-800">${label}</span>
                <span class="text-gray-600 truncate" title="${name}">${name}</span>
            </label>`;
        }).join('') || '<div class="text-gray-500">暂无候选节点</div>';
    }
    if (linksBox) {
        linksBox.innerHTML = importCandidates.links.map(l => {
            const checked = selectedImportLinks.has(l.temp_id) ? 'checked' : '';
            const sourceName = nodeNameMap.get(l.source) || l.source;
            const targetName = nodeNameMap.get(l.target) || l.target;
            return `<label class="flex items-center gap-2 px-2 py-1 rounded bg-gray-100 border border-gray-300">
                <input type="checkbox" ${checked} onchange="toggleImportLink('${l.temp_id}', this.checked)">
                <span class="text-gray-800">${l.type || '关联'}</span>
                <span class="text-gray-500 text-[11px]" title="${sourceName} -> ${targetName}">(${sourceName} -> ${targetName})</span>
            </label>`;
        }).join('') || '<div class="text-gray-500">暂无候选关系</div>';
    }
}

function toggleImportNode(id, checked) {
    if (checked) {
        selectedImportNodes.add(id);
    } else {
        selectedImportNodes.delete(id);
        // 同时取消关联的关系
        importCandidates.links.forEach(l => {
            if (l.source === id || l.target === id) selectedImportLinks.delete(l.temp_id);
        });
        renderImportLists();
    }
}

function toggleImportLink(id, checked) {
    if (checked) {
        selectedImportLinks.add(id);
    } else {
        selectedImportLinks.delete(id);
    }
}

function resetImportSelections() {
    // 清空候选与选择
    importCandidates = { nodes: [], links: [] };
    selectedImportNodes = new Set();
    selectedImportLinks = new Set();
    importSessionId = null;
    renderImportLists();
    const statusEl = document.getElementById('graph-import-status');
    if (statusEl) statusEl.innerText = '已清空候选节点与关系，请重新上传解析。';
    // 清空文件选择
    const fileInput = document.getElementById('graph-import-file');
    if (fileInput) fileInput.value = '';
}

async function commitGraphImport() {
    const statusEl = document.getElementById('graph-import-status');
    if (!importSessionId) {
        if (statusEl) statusEl.innerText = '请先完成解析预览。';
        return;
    }
    if (statusEl) statusEl.innerText = '写入中...';
    
    // 获取当前产业
    const currentIndustry = window.currentIndustry || 'ai';
    
    try {
        const resp = await fetch(`${API_BASE}/api/graph_import/commit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: importSessionId,
                nodes: Array.from(selectedImportNodes),
                links: Array.from(selectedImportLinks),
                industry: currentIndustry
            })
        });
        const data = await resp.json();
        if (data.status !== 'success') {
            statusEl.innerText = data.message || '写入失败';
            return;
        }
        statusEl.innerText = `写入成功：新增节点 ${data.added_nodes}，新增关系 ${data.added_links}（产业：${data.industry || currentIndustry}）。如需立即查看，请刷新图谱。`;
    } catch (err) {
        if (statusEl) statusEl.innerText = `写入失败: ${err.message}`;
    }
}

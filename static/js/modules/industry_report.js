// 产业报告生成：基于当前 /api/report/* 分步 Agent API 的前端适配

let industryReportWorkspace = {
    historyId: "",
    currentStage: "idle",
    activeStep: "requirement",
    completedSteps: [],
    flowCollapsed: false,
    userPrompt: "",
    reportTitle: "人工智能产业报告",
    abstractText: "",
    industry: "ai",
    pageIndustry: "ai",
    taskCard: null,
    outlineTemplate: null,
    outline: [],
    writingTasks: [],
    coordination: null,
    review: null,
    deliveryReasons: [],
    adjustmentNotes: [],
    bodySections: [],
    references: [],
    warnings: [],
    activeSectionId: "",
    rewriteMaterials: null,
    busy: false,
    exportState: "",
    selectedAgentStep: "requirement",
    bodyProgressById: {},
    coordinatorProgressById: {},
    executionLogTimeByKey: {},
    stepTimingByKey: {},
    bodyTotal: 0,
    coordinatorTotal: 0,
    outlineLocked: false,
    requirementRewriteSeq: 0,
    previewTarget: { type: "all", key: "" },
    lastSectionPreviewKey: "",
};

let industryReportHistoryIndex = [];
let industryReportRequirementRewriteSeq = 0;
let industryReportWorkflowTimerId = null;
let industryReportTemplateDraft = [];
let industryReportTemplateFinalDraft = [];
let industryReportTemplateImporting = false;
let industryReportTemplateImportSeq = 0;
let industryReportTemplateFocus = null;
let industryReportTemplateBodyOverflow = "";

function industryReportTemplateContext() {
    return JSON.stringify([
        getIndustryReportCurrentIndustry(),
        document.getElementById("industry-report-selected-industry")?.value || "",
        document.getElementById("industry-report-task-title")?.value || "",
        document.getElementById("industry-report-task-requirement")?.value || "",
    ]);
}

function markIndustryReportTemplateForReview() {
    if (industryReportWorkspace.outlineTemplate) {
        industryReportWorkspace.outlineTemplate.needsReview = true;
        industryReportWorkspace.outlineTemplate.confirmed = false;
    }
    syncIndustryReportTemplateSummary();
    const modal = document.getElementById("industry-report-template-modal");
    if (industryReportWorkspace.outlineTemplate && modal && !modal.hidden) {
        document.getElementById("industry-report-template-notice").textContent = "报告信息已变化，请检查模版。";
    }
    syncIndustryReportTemplateConfirm();
}

function syncIndustryReportTemplateSummary() {
    const template = industryReportWorkspace.outlineTemplate;
    const summary = document.getElementById("industry-report-template-summary");
    if (summary) summary.textContent = template ? `${template.level1_titles.length} 个一级标题 · ${template.confirmed ? "已确认" : "待确认"}` : "";
    const warning = document.getElementById("industry-report-template-warning");
    if (warning) {
        warning.textContent = template?.needsReview ? "报告信息已变化，请检查模版。" : "请确认最终一级标题。";
        warning.classList.toggle("hidden", !template || template.confirmed);
    }
}

function normalizeIndustryReportTemplate(template) {
    if (!template) return null;
    const titles = Array.isArray(template.level1_titles) ? [...template.level1_titles] : [];
    const legacy = !Array.isArray(template.source_titles);
    return {
        ...template,
        source_titles: legacy ? [...titles] : [...template.source_titles],
        level1_titles: titles,
        generated_titles: [...(template.generated_titles || titles)],
        confirmed: !legacy && Boolean(template.confirmed) && !template.needsReview,
        needsReview: legacy || Boolean(template.needsReview),
    };
}

function industryReportTemplateIndustryName() {
    const key = document.getElementById("industry-report-selected-industry")?.value || "";
    if (!key) return "";
    const match = (industryReportWorkspace.taskCard?.industry_matches || []).find(item => item.key === key);
    return String(match?.name || getIndustryReportIndustryName(key) || "").trim();
}

function industryReportTemplateHasPlaceholder(title) {
    return /\{\{产业\}\}|\{产业\}|xxx|ｘｘｘ|×××/i.test(title);
}

function completeIndustryReportTemplateTitles(titles, industryName) {
    if (!industryName) return [...titles];
    return titles.map(title => title.replace(/\{\{产业\}\}|\{产业\}|xxx|ｘｘｘ|×××/gi, (placeholder, offset, text) => {
        return industryName.endsWith("产业") && text.slice(offset + placeholder.length).startsWith("产业")
            ? industryName.slice(0, -2) : industryName;
    }));
}

function syncIndustryReportTemplateConfirm() {
    const button = document.getElementById("industry-report-template-confirm");
    if (!button) return;
    const template = industryReportWorkspace.outlineTemplate;
    const sourceSaved = template && JSON.stringify(industryReportTemplateDraft.map(title => title.trim())) === JSON.stringify(template.source_titles);
    let issue = "";
    try { validateIndustryReportTemplate(industryReportTemplateFinalDraft.map(title => title.trim())); } catch (error) { issue = error.message; }
    const unresolved = industryReportTemplateFinalDraft.some(industryReportTemplateHasPlaceholder);
    const missingIndustry = industryReportTemplateDraft.some(industryReportTemplateHasPlaceholder) && !industryReportTemplateIndustryName();
    if (unresolved) issue = "最终标题中仍有产业占位符。";
    if (!sourceSaved) issue = "请先保存左侧原始模版。";
    if (missingIndustry) issue = "请先选择最终产业方向。";
    button.disabled = industryReportTemplateImporting || Boolean(issue);
    const validation = document.getElementById("industry-report-template-validation");
    if (validation) validation.textContent = issue;
}

function editIndustryReportTemplateRow(side, index, value) {
    const titles = side === "source" ? industryReportTemplateDraft : industryReportTemplateFinalDraft;
    titles[index] = value;
    markIndustryReportTemplateForReview();
}

function validateIndustryReportTemplate(titles) {
    if (!titles.length || titles.length > 30) throw new Error("模版需要 1～30 个一级标题");
    if (titles.some(title => !title || Array.from(title).length > 120)) throw new Error("一级标题不能为空，且不能超过 120 字");
    if (new Set(titles).size !== titles.length) throw new Error("一级标题不能重复");
}

function renderIndustryReportTemplateRows(side = "source") {
    const titles = side === "source" ? industryReportTemplateDraft : industryReportTemplateFinalDraft;
    const rows = document.getElementById(side === "source" ? "industry-report-template-rows" : "industry-report-template-final-rows");
    rows.innerHTML = titles.map((title, index) => `
        <div class="industry-report-template-row">
            <span class="text-sm text-gray-500">${index + 1}</span>
            <input aria-label="${side === "source" ? "原始" : "最终"}一级标题 ${index + 1}" value="${escapeIndustryReportHtml(title)}" oninput="editIndustryReportTemplateRow('${side}',${index},this.value)">
            <div class="flex">
                <button type="button" title="上移" aria-label="上移一级标题 ${index + 1}" ${index === 0 ? "disabled" : ""} onclick="moveIndustryReportTemplateRow(${index},-1,'${side}')"><i class="fas fa-arrow-up"></i></button>
                <button type="button" title="下移" aria-label="下移一级标题 ${index + 1}" ${index === titles.length - 1 ? "disabled" : ""} onclick="moveIndustryReportTemplateRow(${index},1,'${side}')"><i class="fas fa-arrow-down"></i></button>
                <button type="button" title="删除" aria-label="删除一级标题 ${index + 1}" onclick="deleteIndustryReportTemplateRow(${index},'${side}')"><i class="fas fa-trash"></i></button>
            </div>
        </div>`).join("");
    syncIndustryReportTemplateConfirm();
}

function addIndustryReportTemplateRow(side = "source") {
    const titles = side === "source" ? industryReportTemplateDraft : industryReportTemplateFinalDraft;
    if (titles.length >= 30) return;
    titles.push("");
    markIndustryReportTemplateForReview();
    renderIndustryReportTemplateRows(side);
    const id = side === "source" ? "industry-report-template-rows" : "industry-report-template-final-rows";
    document.querySelector(`#${id} .industry-report-template-row:last-child input`)?.focus();
}

function deleteIndustryReportTemplateRow(index, side) {
    (side === "source" ? industryReportTemplateDraft : industryReportTemplateFinalDraft).splice(index, 1);
    markIndustryReportTemplateForReview();
    renderIndustryReportTemplateRows(side);
}

function moveIndustryReportTemplateRow(index, offset, side = "source") {
    const titles = side === "source" ? industryReportTemplateDraft : industryReportTemplateFinalDraft;
    const target = index + offset;
    if (target < 0 || target >= titles.length) return;
    [titles[index], titles[target]] = [titles[target], titles[index]];
    markIndustryReportTemplateForReview();
    renderIndustryReportTemplateRows(side);
    const id = side === "source" ? "industry-report-template-rows" : "industry-report-template-final-rows";
    document.querySelectorAll(`#${id} input`)[target]?.focus();
}

function openIndustryReportTemplate() {
    if (isIndustryReportTaskCardLocked()) {
        setIndustryReportStatus("写作任务卡已确认，如需修改请先回退。", "info");
        syncIndustryReportEditableState();
        return;
    }
    const modal = document.getElementById("industry-report-template-modal");
    if (!modal.hidden) return;
    industryReportTemplateFocus = document.activeElement;
    industryReportWorkspace.outlineTemplate = normalizeIndustryReportTemplate(industryReportWorkspace.outlineTemplate);
    industryReportTemplateDraft = [...(industryReportWorkspace.outlineTemplate?.source_titles || [""])];
    industryReportTemplateFinalDraft = [...(industryReportWorkspace.outlineTemplate?.level1_titles || [])];
    document.getElementById("industry-report-template-notice").textContent = industryReportWorkspace.outlineTemplate?.needsReview ? "报告信息已变化，请检查模版。" : "";
    renderIndustryReportTemplateRows();
    renderIndustryReportTemplateRows("final");
    syncIndustryReportTemplateSummary();
    modal.hidden = false;
    industryReportTemplateBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    modal.querySelector("input:not([type=file])")?.focus();
}

function closeIndustryReportTemplate() {
    const modal = document.getElementById("industry-report-template-modal");
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    industryReportTemplateImportSeq += 1;
    industryReportTemplateImporting = false;
    document.getElementById("industry-report-template-save").disabled = false;
    document.getElementById("industry-report-template-import").disabled = false;
    modal.querySelector(".industry-report-template-content").inert = false;
    document.body.style.overflow = industryReportTemplateBodyOverflow;
    industryReportTemplateFocus?.focus();
}

function saveIndustryReportTemplate() {
    if (industryReportTemplateImporting) return;
    const titles = industryReportTemplateDraft.map(title => title.trim());
    try {
        validateIndustryReportTemplate(titles);
    } catch (error) {
        document.getElementById("industry-report-template-notice").textContent = error.message;
        return;
    }
    const previous = industryReportWorkspace.outlineTemplate;
    const edited = industryReportTemplateFinalDraft.length && JSON.stringify(industryReportTemplateFinalDraft) !== JSON.stringify(previous?.generated_titles || []);
    if (edited && !window.confirm("重新补全将覆盖右侧手动修改的标题，是否继续？")) return;
    const industryName = industryReportTemplateIndustryName();
    const completed = completeIndustryReportTemplateTitles(titles, industryName);
    industryReportTemplateFinalDraft = [...completed];
    industryReportTemplateDraft = [...titles];
    industryReportWorkspace.outlineTemplate = {
        source_titles: [...titles], level1_titles: [...completed], generated_titles: [...completed],
        confirmed: false, needsReview: false, context: "",
    };
    document.getElementById("industry-report-template-notice").textContent = !industryName && titles.some(industryReportTemplateHasPlaceholder)
        ? "请先选择最终产业方向，再补全并确认标题。" : "";
    renderIndustryReportTemplateRows();
    renderIndustryReportTemplateRows("final");
    syncIndustryReportTemplateSummary();
}

function confirmIndustryReportTemplate() {
    if (industryReportTemplateImporting) return;
    const template = industryReportWorkspace.outlineTemplate;
    const titles = industryReportTemplateFinalDraft.map(title => title.trim());
    try {
        if (!template || JSON.stringify(industryReportTemplateDraft.map(title => title.trim())) !== JSON.stringify(template.source_titles)) throw new Error("请先保存左侧原始模版。");
        validateIndustryReportTemplate(titles);
        if (titles.some(industryReportTemplateHasPlaceholder)) throw new Error("最终标题中仍有产业占位符，请补全后确认。");
        if (template.source_titles.some(industryReportTemplateHasPlaceholder) && !industryReportTemplateIndustryName()) throw new Error("请先选择最终产业方向。");
    } catch (error) {
        document.getElementById("industry-report-template-notice").textContent = error.message;
        return;
    }
    industryReportWorkspace.outlineTemplate = { ...template, level1_titles: titles, confirmed: true, needsReview: false, context: industryReportTemplateContext() };
    syncIndustryReportTemplateSummary();
    closeIndustryReportTemplate();
}

function cancelIndustryReportTemplate() {
    if (!window.confirm("取消使用模版后，将按默认方式生成大纲，是否继续？")) return;
    industryReportWorkspace.outlineTemplate = null;
    syncIndustryReportTemplateSummary();
    closeIndustryReportTemplate();
}

async function importIndustryReportTemplate(input) {
    const file = input.files?.[0];
    input.value = "";
    if (!file || industryReportTemplateImporting) return;
    const notice = document.getElementById("industry-report-template-notice");
    if (!file.name.toLowerCase().endsWith(".docx")) { notice.textContent = "请将旧版 .doc 另存为 .docx 后导入"; return; }
    if (file.size > 10 * 1024 * 1024) { notice.textContent = "Word 文件不能超过 10MB"; return; }
    if (industryReportTemplateDraft.some(title => title.trim()) && !window.confirm("导入将替换当前一级标题，是否继续？")) return;
    const seq = ++industryReportTemplateImportSeq;
    const form = new FormData();
    form.append("file", file);
    industryReportTemplateImporting = true;
    syncIndustryReportTemplateConfirm();
    document.getElementById("industry-report-template-save").disabled = true;
    document.getElementById("industry-report-template-import").disabled = true;
    document.querySelector(".industry-report-template-content").inert = true;
    notice.textContent = "正在识别 Word 一级标题…";
    try {
        const response = await fetch(`${API_BASE}/api/report/template/import`, { method: "POST", body: form });
        const data = await response.json();
        if (seq !== industryReportTemplateImportSeq) return;
        if (!response.ok || data.status === "error") throw new Error(data.message || "Word 导入失败");
        validateIndustryReportTemplate(data.level1_titles);
        industryReportTemplateDraft = [...data.level1_titles];
        markIndustryReportTemplateForReview();
        renderIndustryReportTemplateRows();
        notice.textContent = data.message;
    } catch (error) {
        if (seq === industryReportTemplateImportSeq) notice.textContent = error.message;
    } finally {
        if (seq === industryReportTemplateImportSeq) {
            industryReportTemplateImporting = false;
            document.getElementById("industry-report-template-save").disabled = false;
            document.getElementById("industry-report-template-import").disabled = false;
            document.querySelector(".industry-report-template-content").inert = false;
            syncIndustryReportTemplateConfirm();
        }
    }
}

document.addEventListener("input", event => {
    if (["industry-report-task-title", "industry-report-title", "industry-report-prompt"].includes(event.target.id)) markIndustryReportTemplateForReview();
});
document.addEventListener("keydown", event => {
    const modal = document.getElementById("industry-report-template-modal");
    if (!modal || modal.hidden) return;
    if (event.key === "Escape") { event.preventDefault(); closeIndustryReportTemplate(); }
    if (event.key === "Tab") {
        const elements = [...modal.querySelectorAll("button:not(:disabled), input:not([hidden])")].filter(element => !element.closest("[inert]"));
        const first = elements[0], last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
});

function nextIndustryReportRequirementRewriteSeq() {
    const workspaceSeq = Number(industryReportWorkspace?.requirementRewriteSeq) || 0;
    industryReportRequirementRewriteSeq = Math.max(industryReportRequirementRewriteSeq, workspaceSeq) + 1;
    industryReportWorkspace.requirementRewriteSeq = industryReportRequirementRewriteSeq;
    return industryReportRequirementRewriteSeq;
}

const INDUSTRY_REPORT_STAGE_LABELS = {
    idle: "未开始",
    outline: "大纲生成",
    coordinator: "统筹任务",
    body: "正文生成",
    done: "已完成",
    error: "失败",
};

const INDUSTRY_REPORT_FLOW_STEPS = [
    { key: "requirement", title: "需求理解", detail: "生成可编辑任务卡", tone: "violet" },
    { key: "outline", title: "大纲生成", detail: "生成报告章节结构", tone: "blue" },
    { key: "coordinator", title: "统筹任务", detail: "检索资料并拆分任务", tone: "amber" },
    { key: "body", title: "正文生成", detail: "按小节生成正文", tone: "sky" },
    { key: "review", title: "审查与导出", detail: "精简重复内容、摘要、导出", tone: "green" },
];

const INDUSTRY_REPORT_SUPPORTED_INDUSTRIES = new Set(["ai", "embodied"]);

function isIndustryReportSupported(industry) {
    return INDUSTRY_REPORT_SUPPORTED_INDUSTRIES.has(industry);
}

function getIndustryReportCurrentIndustry() {
    return window.currentIndustry || "ai";
}

function getIndustryReportIndustryName(value) {
    const map = {
        ai: "人工智能",
        embodied: "具身智能",
        low_altitude: "低空经济",
        sea: "海洋经济",
        quantum: "量子科技",
        biology: "生物制造",
        brain: "脑机接口",
        material: "新材料",
    };
    return map[value || getIndustryReportCurrentIndustry()] || "人工智能";
}

function getIndustryReportDefaultTitle(industry = getIndustryReportCurrentIndustry()) {
    return `${getIndustryReportIndustryName(industry)}产业报告`;
}

function syncIndustryReportTitlePlaceholder(industry = getIndustryReportCurrentIndustry()) {
    const titleInput = document.getElementById("industry-report-title");
    if (!titleInput) return;
    titleInput.placeholder = getIndustryReportDefaultTitle(industry);
}

function appendIndustryReportWarnings(items) {
    const existing = industryReportWorkspace.warnings || [];
    const combined = [...existing, ...(Array.isArray(items) ? items : [])];
    const seen = new Set();
    industryReportWorkspace.warnings = combined.filter(item => {
        const key = JSON.stringify(item || {});
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function getIndustryReportRagWarning() {
    return (industryReportWorkspace.warnings || []).find(item =>
        item?.code === "rag_store_empty"
        || String(item?.message || "").includes("RAG 向量库暂无资料")
    );
}

function getIndustryReportRequirementFallbackWarning(items) {
    return (Array.isArray(items) ? items : []).find(item =>
        item?.code === "report_requirement_fallback"
    );
}

function getIndustryReportCitationValidationWarning(items) {
    return (Array.isArray(items) ? items : []).find(item =>
        ["citation_validation", "word_export_citation_validation"].includes(item?.stage)
        && (item?.invalid_citation_ids?.length || item?.malformed_citation_markers?.length)
    );
}

function industryReportCitationWarningText(warning) {
    if (warning?.malformed_citation_markers?.length) {
        return `已移除 ${warning.malformed_citation_markers.length} 个异常引用标记，未推定资料编号，请核对该句证据。`;
    }
    return `已移除 ${warning.invalid_citation_ids.length} 个不在本节资料中的引用编号：${warning.invalid_citation_ids.join("、")}`;
}

function showIndustryReportCitationValidationWarning(items) {
    const warning = getIndustryReportCitationValidationWarning(items);
    if (warning) setIndustryReportStatus(industryReportCitationWarningText(warning), "info");
}

function setIndustryReportCompletionStatus(successText) {
    const ragWarning = getIndustryReportRagWarning();
    const citationWarning = getIndustryReportCitationValidationWarning(industryReportWorkspace.warnings);
    if (citationWarning) {
        setIndustryReportStatus(industryReportCitationWarningText(citationWarning), "info");
        return;
    }
    setIndustryReportStatus(ragWarning?.message || successText, ragWarning ? "info" : "success");
}

function industryReportFallbackSuffix(count) {
    return count > 0 ? `，其中${count}节使用备用任务书` : "";
}

function industryReportCoordinationText(meta) {
    const changed = (meta?.changed_outline_ids || []).length;
    const rejected = (meta?.rejected_outline_ids || []).length;
    if (meta?.status === "completed") return `分工协调完成：调整${changed}节`;
    if (meta?.status === "partial") return `分工协调部分完成：调整${changed}节，保留${rejected}节原决策`;
    if (meta?.status === "failed") return "分工协调失败，保留逐节决策";
    if (meta?.status === "skipped_budget") return "分工协调输入超预算，未调用模型，保留逐节决策";
    return "";
}

function industryReportCoordinatorCompletionText(data) {
    const coordinationText = industryReportCoordinationText(industryReportWorkspace.coordination);
    return `统筹任务完成：已统筹 ${data.success_count ?? industryReportWorkspace.writingTasks.length} / 共 ${industryReportWorkspace.coordinatorTotal || industryReportWorkspace.writingTasks.length} 个任务${coordinationText ? `；${coordinationText}` : ""}${industryReportFallbackSuffix(data.fallback_count)}`;
}

function setIndustryReportButtonDisabled(btn, disabled) {
    if (!btn) return;
    btn.disabled = Boolean(disabled);
    btn.classList?.toggle?.("opacity-60", Boolean(disabled));
    btn.classList?.toggle?.("cursor-not-allowed", Boolean(disabled));
}

function isIndustryReportRequirementLocked() {
    return Boolean(
        hasIndustryReportOutline()
        || (industryReportWorkspace.writingTasks || []).length
        || (industryReportWorkspace.bodySections || []).length
        || (industryReportWorkspace.completedSteps || []).some(step => ["outline", "coordinator", "body", "review"].includes(step))
    );
}

function isIndustryReportTaskCardLocked() {
    return Boolean(
        hasIndustryReportOutline()
        || (industryReportWorkspace.writingTasks || []).length
        || (industryReportWorkspace.bodySections || []).length
        || (industryReportWorkspace.completedSteps || []).some(step => ["outline", "coordinator", "body", "review"].includes(step))
    );
}

function syncIndustryReportRequirementControls() {
    const locked = industryReportWorkspace.busy || isIndustryReportRequirementLocked();
    const titleInput = document.getElementById("industry-report-title");
    const promptInput = document.getElementById("industry-report-prompt");
    const submitBtn = document.getElementById("report-outline-btn");
    if (titleInput) titleInput.disabled = locked;
    if (promptInput) promptInput.disabled = locked;
    setIndustryReportButtonDisabled(submitBtn, locked);
    titleInput?.classList?.toggle?.("cursor-not-allowed", locked);
    promptInput?.classList?.toggle?.("cursor-not-allowed", locked);
}

function syncIndustryReportTaskCardControls() {
    const locked = industryReportWorkspace.busy || isIndustryReportTaskCardLocked();
    ["industry-report-task-title", "industry-report-selected-industry"].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.disabled = locked;
            el.classList?.toggle?.("cursor-not-allowed", locked);
        }
    });
    const match = getIndustryReportSelectedMatch();
    const useGraph = document.getElementById("industry-report-use-graph");
    const useExternalRag = document.getElementById("industry-report-use-external-rag");
    if (useGraph) {
        useGraph.disabled = locked || !match?.graph_available;
        useGraph.classList?.toggle?.("cursor-not-allowed", locked);
    }
    if (useExternalRag) {
        useExternalRag.disabled = locked || !match?.external_rag_available;
        useExternalRag.classList?.toggle?.("cursor-not-allowed", locked);
    }
    const requirement = document.getElementById("industry-report-task-requirement");
    const requirementPreview = document.getElementById("industry-report-task-requirement-preview");
    if (requirement) requirement.disabled = locked;
    if (requirementPreview) {
        requirementPreview.contentEditable = locked ? "false" : "true";
        requirementPreview.classList?.toggle?.("cursor-not-allowed", locked);
    }
    setIndustryReportButtonDisabled(document.getElementById("industry-report-template-open"), locked);
    setIndustryReportButtonDisabled(
        document.getElementById("report-task-card-confirm-btn"),
        locked || !industryReportWorkspace.taskCard,
    );
    document.querySelectorAll?.("input[name='industry-report-title-suggestion']").forEach(input => {
        input.disabled = locked;
    });
}

function getIndustryReportRollbackTarget() {
    if (industryReportWorkspace.busy) return null;
    const completed = new Set(industryReportWorkspace.completedSteps || []);
    if (industryReportWorkspace.currentStage === "done" || completed.has("body") || (industryReportWorkspace.bodySections || []).length) {
        return { key: "coordinator", label: "统筹任务" };
    }
    if (completed.has("coordinator") || (industryReportWorkspace.writingTasks || []).length || Object.keys(industryReportWorkspace.coordinatorProgressById || {}).length) {
        return { key: "outline", label: "大纲编辑" };
    }
    if (completed.has("outline") || hasIndustryReportOutline()) {
        return { key: "taskCard", label: "写作任务卡" };
    }
    if (completed.has("requirement") || industryReportWorkspace.taskCard) {
        return { key: "requirement", label: "报告需求" };
    }
    return null;
}

function syncIndustryReportRollbackButton() {
    const btn = document.getElementById("industry-report-rollback-btn");
    if (!btn) return;
    const target = getIndustryReportRollbackTarget();
    const disabled = !target || industryReportWorkspace.busy;
    btn.title = target ? `回退到${target.label}` : "暂无可回退步骤";
    setIndustryReportButtonDisabled(btn, disabled);
}

function syncIndustryReportEditableState() {
    syncIndustryReportRequirementControls();
    syncIndustryReportTaskCardControls();
    syncIndustryReportRollbackButton();
}

function setIndustryReportBusy(isBusy, text = "") {
    industryReportWorkspace.busy = Boolean(isBusy);
    ["report-outline-btn", "report-task-card-confirm-btn", "report-outline-confirm-btn", "report-generate-btn"].forEach(id => {
        const btn = document.getElementById(id);
        const shouldDisable = Boolean(isBusy)
            || (id === "report-outline-btn" && isIndustryReportRequirementLocked())
            || (id === "report-task-card-confirm-btn" && isIndustryReportTaskCardLocked())
            || (id === "report-task-card-confirm-btn" && !industryReportWorkspace.taskCard)
            || (id === "report-outline-confirm-btn" && !hasIndustryReportOutline())
            || (id === "report-generate-btn" && !hasConfirmedIndustryReportOutline());
        setIndustryReportButtonDisabled(btn, shouldDisable);
    });
    document.querySelectorAll('button[onclick="saveIndustryReportHistory()"]')
        .forEach(btn => {
            btn.disabled = Boolean(isBusy);
            btn.classList.toggle("opacity-60", Boolean(isBusy));
            btn.classList.toggle("cursor-not-allowed", Boolean(isBusy));
        });
    syncIndustryReportOutlineConfirmButton();
    syncIndustryReportGenerateButton();
    syncIndustryReportEditableState();
    if (text) setIndustryReportStatus(text, isBusy ? "loading" : "info");
}

function setIndustryReportStatus(text, type = "info") {
    const el = document.getElementById("industry-report-status");
    if (!el) return;
    const classes = {
        info: "text-xs text-gray-500",
        loading: "text-xs text-blue-600",
        success: "text-xs text-emerald-600",
        error: "text-xs text-red-600",
    };
    el.className = classes[type] || classes.info;
    el.textContent = text || "";
}

function setIndustryReportRequirementSubmittedStatus(warnings = []) {
    const fallbackWarning = getIndustryReportRequirementFallbackWarning(warnings);
    if (fallbackWarning) {
        setIndustryReportStatus(fallbackWarning.message, "info");
        return;
    }
    setIndustryReportStatus("报告需求已提交", "success");
}

function setIndustryReportStage(stage, detail = "") {
    const meta = document.getElementById("report-flow-meta");
    const stageEl = document.getElementById("report-flow-stage");
    const label = INDUSTRY_REPORT_STAGE_LABELS[stage] || stage || "未开始";
    industryReportWorkspace.currentStage = stage || "idle";
    industryReportWorkspace.activeStep = getIndustryReportActiveStepKey(stage);
    if (meta) meta.textContent = detail || label;
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage);
    syncIndustryReportEditableState();
    if (!stageEl) return;
    const dot = stageEl.querySelector("span:first-child");
    const text = stageEl.querySelector("span:last-child");
    if (text) text.textContent = label;
    if (dot) {
        dot.className = "w-2 h-2 rounded-full";
        const color = getIndustryReportStageDotColor(stage);
        dot.classList.add(...color.split(" "));
    }
}

function rollbackIndustryReportWorkflow() {
    const target = getIndustryReportRollbackTarget();
    if (!target) return;
    closeIndustryReportTemplate();
    closeIndustryReportRewriteModal();
    industryReportWorkspace.historyId = "";
    industryReportWorkspace.exportState = "";
    industryReportWorkspace.pendingRewrite = null;
    industryReportWorkspace.rewriteMaterials = null;
    industryReportWorkspace.activeSectionId = "";
    industryReportWorkspace.previewTarget = { type: "all", key: "" };
    industryReportWorkspace.lastSectionPreviewKey = "";

    if (target.key === "coordinator") {
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.bodyProgressById = {};
        industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
        industryReportWorkspace.bodyTotal = industryReportWorkspace.writingTasks.length;
        clearIndustryReportStepDone(["body", "review"]);
        clearIndustryReportStepTiming(["body", "review"]);
        industryReportWorkspace.currentStage = "coordinator";
        industryReportWorkspace.activeStep = "coordinator";
        industryReportWorkspace.selectedAgentStep = "coordinator";
        industryReportWorkspace.outlineLocked = true;
    } else if (target.key === "outline") {
        industryReportWorkspace.writingTasks = [];
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.references = [];
        industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
        industryReportWorkspace.bodyProgressById = {};
        industryReportWorkspace.coordinatorProgressById = {};
        industryReportWorkspace.bodyTotal = 0;
        industryReportWorkspace.coordinatorTotal = countIndustryReportSubsections(industryReportWorkspace.outline);
        industryReportWorkspace.outlineLocked = false;
        clearIndustryReportStepDone(["coordinator", "body", "review"]);
        clearIndustryReportStepTiming(["coordinator", "body", "review"]);
        industryReportWorkspace.currentStage = "outline";
        industryReportWorkspace.activeStep = "outline";
        industryReportWorkspace.selectedAgentStep = "outline";
    } else if (target.key === "taskCard") {
        industryReportWorkspace.outline = [];
        industryReportWorkspace.writingTasks = [];
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.references = [];
        industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
        industryReportWorkspace.bodyProgressById = {};
        industryReportWorkspace.coordinatorProgressById = {};
        industryReportWorkspace.bodyTotal = 0;
        industryReportWorkspace.coordinatorTotal = 0;
        industryReportWorkspace.outlineLocked = false;
        clearIndustryReportStepDone(["outline", "coordinator", "body", "review"]);
        clearIndustryReportStepTiming(["outline", "coordinator", "body", "review"]);
        industryReportWorkspace.currentStage = "idle";
        industryReportWorkspace.activeStep = "requirement";
        industryReportWorkspace.selectedAgentStep = "requirement";
    } else if (target.key === "requirement") {
        const industry = industryReportWorkspace.pageIndustry || getIndustryReportCurrentIndustry();
        industryReportWorkspace.taskCard = null;
        industryReportWorkspace.outlineTemplate = null;
        industryReportWorkspace.outline = [];
        industryReportWorkspace.writingTasks = [];
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.references = [];
        industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
        industryReportWorkspace.warnings = [];
        industryReportWorkspace.bodyProgressById = {};
        industryReportWorkspace.coordinatorProgressById = {};
        industryReportWorkspace.bodyTotal = 0;
        industryReportWorkspace.coordinatorTotal = 0;
        industryReportWorkspace.outlineLocked = false;
        industryReportWorkspace.industry = industry;
        clearIndustryReportStepDone(["requirement", "outline", "coordinator", "body", "review"]);
        clearIndustryReportStepTiming(["requirement", "outline", "coordinator", "body", "review"]);
        industryReportWorkspace.currentStage = "idle";
        industryReportWorkspace.activeStep = "requirement";
        industryReportWorkspace.selectedAgentStep = "requirement";
    }

    renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
    renderIndustryReportOutline(industryReportWorkspace.outline);
    renderIndustryReportProgress(buildIndustryReportRollbackProgress(target.key));
    renderIndustryReportPreview();
    syncIndustryReportHeader();
    setIndustryReportStage(industryReportWorkspace.currentStage, `已回退到${target.label}`);
    if (target.key === "requirement") {
        setIndustryReportStatus("等待输入题目", "info");
    } else {
        setIndustryReportRequirementSubmittedStatus();
    }
    syncIndustryReportEditableState();
}

function buildIndustryReportRollbackProgress(targetKey) {
    if (targetKey === "coordinator") {
        return [
            { key: "outline", title: "推荐大纲", status: "done", detail: `${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题` },
            { key: "coordinator", title: "写作任务", status: "done", detail: `${(industryReportWorkspace.writingTasks || []).length} 个任务` },
            { key: "body", title: "正文生成", status: "pending", detail: "等待开始" },
        ];
    }
    if (targetKey === "outline") {
        return [
            { key: "outline", title: "推荐大纲", status: "done", detail: `${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题` },
            { key: "coordinator", title: "写作任务", status: "pending", detail: "等待确认大纲" },
            { key: "body", title: "正文生成", status: "pending", detail: "等待开始" },
        ];
    }
    return [];
}

function getIndustryReportStageDotColor(stage) {
    if (stage === "error") return "bg-red-500";
    if (stage === "idle") return "bg-gray-300";
    if (stage === "done") return "bg-emerald-500";
    const activeStep = getIndustryReportActiveStepKey(stage);
    if ((industryReportWorkspace.completedSteps || []).includes(activeStep)) return "bg-emerald-500";
    return "bg-blue-500 animate-pulse";
}

function getIndustryReportActiveStepKey(stage) {
    const map = {
        idle: "requirement",
        outline: "outline",
        coordinator: "coordinator",
        body: "body",
        done: "review",
        error: industryReportWorkspace.activeStep || "requirement",
    };
    return map[stage] || "requirement";
}

function markIndustryReportStepDone(stepKey) {
    if (!stepKey) return;
    if (!industryReportWorkspace.completedSteps.includes(stepKey)) {
        industryReportWorkspace.completedSteps.push(stepKey);
    }
    completeIndustryReportStepTiming(stepKey);
}

function clearIndustryReportStepDone(stepKeys) {
    const remove = new Set(stepKeys || []);
    industryReportWorkspace.completedSteps = (industryReportWorkspace.completedSteps || []).filter(key => !remove.has(key));
}

function startIndustryReportStepTiming(stepKey) {
    if (!stepKey) return;
    industryReportWorkspace.stepTimingByKey = industryReportWorkspace.stepTimingByKey || {};
    industryReportWorkspace.stepTimingByKey[stepKey] = {
        startedAt: Date.now(),
        completedAt: null,
    };
}

function completeIndustryReportStepTiming(stepKey) {
    if (!stepKey) return;
    industryReportWorkspace.stepTimingByKey = industryReportWorkspace.stepTimingByKey || {};
    const timing = industryReportWorkspace.stepTimingByKey[stepKey];
    if (!timing?.startedAt || timing.completedAt) return;
    timing.completedAt = Date.now();
}

function clearIndustryReportStepTiming(stepKeys) {
    const remove = new Set(stepKeys || []);
    if (!remove.size) return;
    industryReportWorkspace.stepTimingByKey = industryReportWorkspace.stepTimingByKey || {};
    remove.forEach(key => {
        delete industryReportWorkspace.stepTimingByKey[key];
    });
}

function getIndustryReportStepState(stepKey, stage) {
    if (stage === "error" && industryReportWorkspace.activeStep === stepKey) return "failed";
    if ((industryReportWorkspace.completedSteps || []).includes(stepKey)) return "done";
    if (industryReportWorkspace.activeStep === stepKey) return "active";
    return "pending";
}

function renderIndustryReportFlowSteps(stage = "idle") {
    renderIndustryReportAgentHub(stage);
    const box = document.getElementById("industry-report-stepper");
    if (!box) {
        renderIndustryReportActiveStepDetail(stage);
        renderIndustryReportExecutionLog(stage);
        syncIndustryReportWorkflowTimer();
        return;
    }
    const selectedKey = industryReportWorkspace.selectedAgentStep;
    const activeStep = selectedKey
        ? INDUSTRY_REPORT_FLOW_STEPS.find(step => step.key === selectedKey)
        : null;
    const activeState = activeStep ? getIndustryReportStepState(activeStep.key, stage) : "";
    const activeStyle = activeStep ? getIndustryReportWorkflowStyle(activeStep, activeState) : null;
    const stepsHtml = INDUSTRY_REPORT_FLOW_STEPS.map((step, index) => {
        const state = getIndustryReportStepState(step.key, stage);
        return renderIndustryReportAgentCard(step, index, getIndustryReportWorkflowStyle(step, state), state, activeStep && step.key === activeStep.key);
    }).join("");
    const previousBand = typeof box.querySelector === "function"
        ? box.querySelector(".industry-report-workflow-band")
        : null;
    const previousScrollLeft = previousBand ? previousBand.scrollLeft : 0;
    box.innerHTML = `
        <div class="industry-report-workflow-band rounded-lg border border-blue-100 bg-gradient-to-r from-blue-50 via-white to-blue-50 px-5 py-5 overflow-x-auto">
            <div class="industry-report-milestone-row min-w-[920px]">${stepsHtml}</div>
        </div>
    `;
    const nextBand = typeof box.querySelector === "function"
        ? box.querySelector(".industry-report-workflow-band")
        : null;
    if (nextBand) nextBand.scrollLeft = previousScrollLeft;
    renderIndustryReportActiveStepDetail(stage, activeStep, activeStyle);
    renderIndustryReportExecutionLog(stage);
    syncIndustryReportWorkflowTimer();
}

function renderIndustryReportAgentHub(stage = industryReportWorkspace.currentStage || "idle") {
    const box = document.getElementById("industry-report-agent-hub");
    const summaryEl = document.getElementById("industry-report-agent-hub-summary");
    if (!box) return;
    const agents = buildIndustryReportAgentHubItems(stage);
    if (summaryEl) summaryEl.textContent = getIndustryReportAgentHubSummary(agents);
    box.innerHTML = `
        <div class="industry-report-agent-hub-shell">
            <div class="industry-report-agent-hub-lines" aria-hidden="true">
                <svg viewBox="0 0 100 100" preserveAspectRatio="none">
                    <path d="M50 50 C38 36 27 24 16 20"></path>
                    <path d="M50 50 C38 64 27 76 16 80"></path>
                    <path d="M50 50 C62 64 73 76 84 80"></path>
                    <path d="M50 50 C62 36 73 24 84 20"></path>
                </svg>
            </div>
            <div class="industry-report-agent-hub-center">
                <div class="industry-report-agent-hub-center-icon"><i class="fas fa-network-wired"></i></div>
                <div class="font-bold text-blue-800">协作中枢</div>
            </div>
            <div class="industry-report-agent-hub-grid">
                ${agents.map(item => renderIndustryReportAgentHubNode(item)).join("")}
            </div>
        </div>
    `;
}

function buildIndustryReportAgentHubItems(stage) {
    const visibleStepKeys = ["requirement", "outline", "coordinator", "body"];
    return visibleStepKeys.map(stepKey => INDUSTRY_REPORT_FLOW_STEPS.find(step => step.key === stepKey)).filter(Boolean).map(step => {
        const state = getIndustryReportStepState(step.key, stage);
        const metric = getIndustryReportAgentHubMetric(step.key, state);
        const progress = getIndustryReportAgentHubProgress(step.key, state);
        return {
            key: step.key,
            title: getIndustryReportAgentName(step.key),
            role: getIndustryReportAgentHubRole(step.key),
            state,
            stateLabel: getIndustryReportAgentHubStateLabel(state),
            actionLabel: getIndustryReportAgentHubActionLabel(step.key, state),
            metric,
            progress,
            elapsed: getIndustryReportStepElapsedLabel(step.key),
            icon: getIndustryReportAgentHubIcon(step.key),
        };
    });
}

function getIndustryReportAgentHubRole(stepKey) {
    const map = {
        requirement: "需求分析",
        outline: "大纲规划",
        coordinator: "任务统筹",
        body: "正文写作",
        review: "汇总预览、摘要与导出结果",
    };
    return map[stepKey] || "暂无职责说明";
}

function getIndustryReportAgentHubIcon(stepKey) {
    const map = {
        requirement: "fas fa-chart-simple",
        outline: "fas fa-list-check",
        coordinator: "fas fa-circle-nodes",
        body: "fas fa-file-lines",
    };
    return map[stepKey] || "fas fa-microchip";
}

function getIndustryReportAgentHubStateLabel(state) {
    const map = {
        active: "运行中",
        done: "已完成",
        failed: "失败",
        pending: "待开始",
    };
    return map[state] || "待开始";
}

function getIndustryReportAgentHubActionLabel(stepKey, state) {
    if (state === "done") return "已完成";
    if (state === "failed") return "执行失败";
    if (state === "pending") return "等待中";
    const map = {
        requirement: "正在分析",
        outline: "正在规划",
        coordinator: "正在统筹",
        body: "正在写作",
    };
    return map[stepKey] || "运行中";
}

function getIndustryReportAgentHubMetric(stepKey, state) {
    if (stepKey === "requirement") {
        return industryReportWorkspace.taskCard ? "任务卡已生成" : "暂无状态数据";
    }
    if (stepKey === "outline") {
        const total = countIndustryReportSubsections(industryReportWorkspace.outline);
        return total ? `${total} 个二级标题` : "暂无状态数据";
    }
    if (stepKey === "coordinator") {
        const items = getIndustryReportStepSubitems("coordinator");
        const total = getIndustryReportCoordinatorTotal(items);
        const done = items.filter(item => item.statusState === "done").length;
        const failed = items.filter(item => item.statusState === "failed").length;
        if (!total) return "暂无状态数据";
        return failed ? `${done}/${total} 完成，${failed} 失败` : `${done}/${total} 完成`;
    }
    if (stepKey === "body") {
        const items = getIndustryReportStepSubitems("body");
        const total = getIndustryReportBodyTotal(items);
        const done = items.filter(item => item.statusState === "done").length;
        const failed = items.filter(item => item.statusState === "failed").length;
        if (!total) return "暂无状态数据";
        return failed ? `${done}/${total} 完成，${failed} 失败` : `${done}/${total} 完成`;
    }
    if (stepKey === "review") {
        return (industryReportWorkspace.bodySections || []).length ? "可预览和导出" : "暂无状态数据";
    }
    return "暂无状态数据";
}

function getIndustryReportAgentHubProgress(stepKey, state) {
    if (state === "done") return 100;
    if (stepKey === "requirement") return industryReportWorkspace.taskCard ? 100 : 0;
    if (stepKey === "outline") {
        const total = countIndustryReportSubsections(industryReportWorkspace.outline);
        return total ? 100 : 0;
    }
    if (stepKey === "coordinator") {
        const items = getIndustryReportStepSubitems("coordinator");
        const total = getIndustryReportCoordinatorTotal(items);
        if (!total) return 0;
        const done = items.filter(item => item.statusState === "done").length;
        return Math.round((done / total) * 100);
    }
    if (stepKey === "body") {
        const items = getIndustryReportStepSubitems("body");
        const total = getIndustryReportBodyTotal(items);
        if (!total) return 0;
        const done = items.filter(item => item.statusState === "done").length;
        return Math.round((done / total) * 100);
    }
    return state === "active" ? 35 : 0;
}

function getIndustryReportAgentHubSummary(agents) {
    const active = agents.find(item => item.state === "active");
    if (active) return `${active.title}运行中`;
    if (agents.some(item => item.state === "failed")) return "存在失败任务";
    if (agents.every(item => item.state === "done")) return "全部完成";
    if (agents.some(item => item.state === "done")) return "Agent协同推进中";
    return "暂无状态数据";
}

function renderIndustryReportAgentHubNode(item) {
    const stateClass = `is-${item.state}`;
    const pulseClass = item.state === "active" ? "industry-report-agent-hub-pulse" : "";
    const progress = Math.max(0, Math.min(100, Number(item.progress) || 0));
    const elapsed = item.elapsed || "--";
    return `
        <button type="button"
                onclick="jumpToIndustryReportAgentTarget('${escapeIndustryReportJs(item.key)}')"
                class="industry-report-agent-hub-node ${stateClass} ${pulseClass}">
            <div class="flex items-start gap-3">
                <span class="industry-report-agent-hub-node-icon"><i class="${item.icon}"></i></span>
                <div class="min-w-0 flex-1">
                    <div class="font-semibold text-gray-800 leading-5 truncate">${escapeIndustryReportHtml(item.title)}</div>
                    <div class="industry-report-agent-hub-status">
                        <span class="industry-report-agent-hub-status-dot"></span>
                        ${escapeIndustryReportHtml(item.actionLabel)}
                    </div>
                    <div class="mt-1 text-xs leading-5 text-gray-500">${escapeIndustryReportHtml(item.role)}</div>
                    <div class="industry-report-agent-hub-progress">
                        <span class="industry-report-agent-hub-progress-bar" style="width: ${progress}%"></span>
                    </div>
                    <div class="mt-1 flex items-center justify-between gap-2 text-[11px] font-semibold text-slate-400">
                        <span>${escapeIndustryReportHtml(elapsed)}</span>
                        <span>${progress}%</span>
                    </div>
                </div>
            </div>
        </button>
    `;
}

function jumpToIndustryReportAgentTarget(stepKey) {
    industryReportWorkspace.selectedAgentStep = stepKey || "";
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
    const targetMap = {
        requirement: "industry-report-requirement-panel",
        outline: "industry-report-outline-panel",
        coordinator: "industry-report-outline-panel",
        body: "industry-report-generation-panel",
    };
    const target = document.getElementById(targetMap[stepKey] || "industry-report-stepper");
    if (target?.scrollIntoView) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

function getIndustryReportAgentHubStatusIcon(state) {
    if (state === "done") return "fas fa-check-circle";
    if (state === "active") return "fas fa-spinner fa-spin";
    if (state === "failed") return "fas fa-circle-exclamation";
    return "far fa-clock";
}

function syncIndustryReportWorkflowTimer() {
    const hasRunningTiming = Object.values(industryReportWorkspace.stepTimingByKey || {})
        .some(timing => timing?.startedAt && !timing.completedAt);
    if (hasRunningTiming && !industryReportWorkflowTimerId && typeof setInterval === "function") {
        industryReportWorkflowTimerId = setInterval(() => {
            renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
        }, 1000);
    }
    if (!hasRunningTiming && industryReportWorkflowTimerId && typeof clearInterval === "function") {
        clearInterval(industryReportWorkflowTimerId);
        industryReportWorkflowTimerId = null;
    }
}

function renderIndustryReportActiveStepDetail(stage = "idle", activeStep = null, activeStyle = null) {
    const detailBox = document.getElementById("industry-report-step-detail");
    if (!detailBox) return;
    const selectedKey = industryReportWorkspace.selectedAgentStep;
    const step = activeStep || (selectedKey ? INDUSTRY_REPORT_FLOW_STEPS.find(item => item.key === selectedKey) : null);
    if (!step) {
        detailBox.innerHTML = "";
        detailBox.dataset.stepKey = "";
        return;
    }
    const state = getIndustryReportStepState(step.key, stage);
    const style = activeStyle || getIndustryReportWorkflowStyle(step, state);
    const previousScrollBox = typeof detailBox.querySelector === "function"
        ? detailBox.querySelector(".industry-report-step-detail-scroll")
        : null;
    detailBox.dataset = detailBox.dataset || {};
    const previousScrollTop = detailBox.dataset.stepKey === step.key && previousScrollBox
        ? previousScrollBox.scrollTop
        : 0;
    detailBox.innerHTML = renderIndustryReportActiveStepPanel(step, style);
    detailBox.dataset.stepKey = step.key;
    const nextScrollBox = typeof detailBox.querySelector === "function"
        ? detailBox.querySelector(".industry-report-step-detail-scroll")
        : null;
    if (nextScrollBox) nextScrollBox.scrollTop = previousScrollTop;
}

function renderIndustryReportAgentCard(step, index, style, state, selected) {
    const summary = getIndustryReportAgentSummary(step.key);
    const selectedClass = selected ? "is-selected" : "";
    const stateClass = `is-${state}`;
    const statusHtml = getIndustryReportMilestoneStatusHtml(index, state);
    const agentHtml = step.key === "body"
        ? renderIndustryReportBodyAgentBadges(state)
        : step.key === "coordinator"
            ? renderIndustryReportCoordinatorAgentBadges(state)
            : renderIndustryReportSingleAgentBadge(step, state);
    const metric = getIndustryReportStepMetric(step.key, state);
    return `
        <button type="button"
                onclick="selectIndustryReportAgentStep('${escapeIndustryReportJs(step.key)}')"
                class="industry-report-milestone ${stateClass} ${selectedClass}">
            <div class="industry-report-milestone-node ${state === "active" ? "animate-pulse" : ""}">
                ${statusHtml}
            </div>
            <div class="industry-report-milestone-content">
                <div class="text-[15px] font-bold ${style.title} leading-5">${index + 1}. ${escapeIndustryReportHtml(step.title)}</div>
                <div class="mt-1 text-xs ${style.detail} leading-5 min-h-[1.25rem]">${escapeIndustryReportHtml(summary)}</div>
                <div class="mt-3 flex flex-wrap justify-center gap-2">${agentHtml}</div>
                <div class="mt-3 inline-flex items-center gap-1.5 rounded-full ${metric.className} px-3 py-1 text-xs font-semibold">
                    <i class="${metric.icon}"></i>
                    ${escapeIndustryReportHtml(metric.label)}
                </div>
            </div>
        </button>
    `;
}

function getIndustryReportMilestoneStatusHtml(index, state) {
    if (state === "done") return '<i class="fas fa-check"></i>';
    if (state === "failed") return '<i class="fas fa-exclamation"></i>';
    return String(index + 1);
}

function renderIndustryReportSingleAgentBadge(step, state) {
    const iconClass = state === "done" ? "text-emerald-600 bg-emerald-50 border-emerald-100"
        : state === "active" ? "text-blue-600 bg-blue-50 border-blue-100"
            : "text-slate-500 bg-white border-slate-200";
    return `
        <span class="inline-flex items-center gap-2 rounded-lg border ${iconClass} px-3 py-2 text-xs font-semibold shadow-sm">
            <i class="fas fa-robot"></i>
            ${escapeIndustryReportHtml(getIndustryReportAgentName(step.key))}
        </span>
    `;
}

function renderIndustryReportBodyAgentBadges(state) {
    const workerCount = getIndustryReportNumber("industry-report-workers", 3);
    const cls = state === "done" ? "text-emerald-600 bg-emerald-50 border-emerald-100"
        : state === "active" ? "text-blue-600 bg-blue-50 border-blue-100"
            : state === "failed" ? "text-red-600 bg-red-50 border-red-100"
                : "text-sky-600 bg-white border-sky-100";
    return `
        <span class="inline-flex items-center gap-2 rounded-lg border ${cls} px-3 py-2 text-xs font-semibold shadow-sm">
            <i class="fas fa-robot"></i>
            写作 Agent 1-${Math.max(1, workerCount)}
        </span>
    `;
}

function renderIndustryReportCoordinatorAgentBadges(state) {
    const workerCount = getIndustryReportNumber("industry-report-coordinator-workers", 3);
    const cls = state === "done" ? "text-emerald-600 bg-emerald-50 border-emerald-100"
        : state === "active" ? "text-blue-600 bg-blue-50 border-blue-100"
            : state === "failed" ? "text-red-600 bg-red-50 border-red-100"
                : "text-amber-600 bg-white border-amber-100";
    return `
        <span class="inline-flex items-center gap-2 rounded-lg border ${cls} px-3 py-2 text-xs font-semibold shadow-sm">
            <i class="fas fa-robot"></i>
            调度 Agent 1-${Math.max(1, workerCount)}
        </span>
    `;
}

function getIndustryReportAgentName(stepKey) {
    const map = {
        requirement: "分析Agent",
        outline: "规划Agent",
        coordinator: "统筹Agent",
    };
    return map[stepKey] || "写作Agent";
}

function getIndustryReportStepMetric(stepKey, state) {
    if (state === "active") {
        const elapsed = getIndustryReportStepElapsedLabel(stepKey);
        return { label: elapsed ? `进行中 ${elapsed}` : "进行中", icon: "fas fa-spinner fa-spin", className: "bg-blue-100 text-blue-700" };
    }
    if (state === "failed") {
        return { label: "需处理", icon: "fas fa-circle-exclamation", className: "bg-red-100 text-red-700" };
    }
    if (state === "done") {
        const elapsed = getIndustryReportStepElapsedLabel(stepKey);
        return { label: elapsed || "完成", icon: "fas fa-clock", className: "bg-emerald-100 text-emerald-700" };
    }
    return { label: "待开始", icon: "far fa-clock", className: "bg-slate-100 text-slate-500" };
}

function getIndustryReportStepElapsedLabel(stepKey) {
    const timing = industryReportWorkspace.stepTimingByKey?.[stepKey];
    if (!timing?.startedAt) return "";
    const endAt = timing.completedAt || Date.now();
    const seconds = Math.max(0, Math.round((endAt - timing.startedAt) / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

function getIndustryReportWorkflowStyle(step, state) {
    if (state === "failed") {
        return {
            item: "border-red-200 bg-red-50",
            robot: "bg-red-500 text-white",
            title: "text-red-800",
            detail: "text-red-600",
            panel: "border-red-200 bg-red-50",
            label: "Failed",
        };
    }
    const tones = {
        violet: {
            item: "border-violet-200 bg-violet-50",
            robotIdle: "bg-white text-violet-500 border border-violet-100",
            title: "text-violet-900",
            detail: "text-violet-600",
            panel: "border-violet-200 bg-violet-50/70",
        },
        blue: {
            item: "border-blue-200 bg-blue-50",
            robotIdle: "bg-white text-blue-500 border border-blue-100",
            title: "text-blue-900",
            detail: "text-blue-600",
            panel: "border-blue-200 bg-blue-50/70",
        },
        amber: {
            item: "border-amber-200 bg-amber-50",
            robotIdle: "bg-white text-amber-600 border border-amber-100",
            title: "text-amber-900",
            detail: "text-amber-700",
            panel: "border-amber-200 bg-amber-50/70",
        },
        sky: {
            item: "border-sky-200 bg-sky-50",
            robotIdle: "bg-white text-sky-500 border border-sky-100",
            title: "text-sky-900",
            detail: "text-sky-600",
            panel: "border-sky-200 bg-sky-50/70",
        },
        green: {
            item: "border-emerald-200 bg-emerald-50",
            robotIdle: "bg-white text-emerald-600 border border-emerald-100",
            title: "text-emerald-900",
            detail: "text-emerald-600",
            panel: "border-emerald-200 bg-emerald-50/70",
        },
    };
    const tone = tones[step.tone] || tones.blue;
    return {
        item: state === "active" ? `${tone.item} shadow-sm` : tone.item,
        robot: state === "active"
            ? "bg-blue-600 text-white"
            : state === "done"
                ? "bg-emerald-500 text-white"
                : tone.robotIdle,
        title: tone.title,
        detail: tone.detail,
        panel: tone.panel,
        label: state === "active" ? "Working" : state === "done" ? "Done" : "Pending",
    };
}

function renderIndustryReportBodyRobots(state) {
    const workerCount = getIndustryReportNumber("industry-report-workers", 3);
    const bodyItems = getIndustryReportStepSubitems("body");
    const activeCount = bodyItems.filter(item => item.statusState === "active").length;
    const doneCount = bodyItems.filter(item => item.statusState === "done").length;
    const failedCount = bodyItems.filter(item => item.statusState === "failed").length;
    const robots = [];
    for (let index = 0; index < workerCount; index += 1) {
        let cls = "bg-white text-sky-500 border-sky-100";
        let title = "空闲";
        if (state === "active" && index < Math.max(1, Math.min(workerCount, activeCount || bodyItems.length))) {
            cls = "bg-blue-600 text-white border-blue-500 animate-pulse";
            title = "生成中";
        } else if (failedCount && index < failedCount) {
            cls = "bg-red-100 text-red-600 border-red-200";
            title = "有失败";
        } else if (doneCount) {
            cls = "bg-emerald-500 text-white border-emerald-500";
            title = "已完成";
        }
        robots.push(`<span class="w-12 h-12 rounded-xl border ${cls} flex items-center justify-center text-xl shadow-sm" title="${title}"><i class="fas fa-robot"></i></span>`);
    }
    return `<div class="mx-auto grid grid-cols-3 gap-2 justify-items-center max-w-[168px]">${robots.join("")}</div>`;
}

function getIndustryReportAgentSummary(stepKey) {
    if (stepKey === "requirement") return industryReportWorkspace.taskCard ? "任务卡已生成" : "等待提交题目与需求";
    if (stepKey === "outline") return `${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题`;
    if (stepKey === "coordinator") {
        const items = getIndustryReportStepSubitems("coordinator");
        const done = items.filter(item => item.statusState === "done").length;
        const failed = items.filter(item => item.statusState === "failed").length;
        const total = getIndustryReportCoordinatorTotal(items);
        return failed ? `已统筹 ${done}/${total}，失败 ${failed}` : `已统筹 ${done}/${total}`;
    }
    if (stepKey === "body") {
        const items = getIndustryReportStepSubitems("body");
        const done = items.filter(item => item.statusState === "done").length;
        const failed = items.filter(item => item.statusState === "failed").length;
        const total = getIndustryReportBodyTotal(items);
        return failed ? `已生成 ${done}/${total}，失败 ${failed}` : `已生成 ${done}/${total}`;
    }
    if (stepKey === "review") return (industryReportWorkspace.bodySections || []).length ? "可预览、重写或导出" : "等待正文完成";
    return "";
}

function selectIndustryReportAgentStep(stepKey) {
    industryReportWorkspace.selectedAgentStep = industryReportWorkspace.selectedAgentStep === stepKey ? "" : stepKey;
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
}

function toggleIndustryReportFlowCollapsed() {
    industryReportWorkspace.flowCollapsed = !industryReportWorkspace.flowCollapsed;
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
}

function flattenIndustryReportOutlineSubsections() {
    const items = [];
    (industryReportWorkspace.outline || []).forEach((section, sectionIndex) => {
        (section.subsections || []).forEach((sub, subIndex) => {
            items.push({
                key: sub.outline_id || `${sectionIndex + 1}.${subIndex + 1}`,
                title: sub.title || `二级标题 ${subIndex + 1}`,
                parent: section.level1_title || "",
                indexLabel: `${sectionIndex + 1}.${subIndex + 1}`,
                statusState: "pending",
            });
        });
    });
    return items;
}

function getIndustryReportStepSubitems(stepKey) {
    if (stepKey === "outline") {
        const outlineDone = (industryReportWorkspace.completedSteps || []).includes("outline");
        return flattenIndustryReportOutlineSubsections().map(item => ({
            ...item,
            status: outlineDone ? "已生成" : "待生成",
            statusState: outlineDone ? "done" : "pending",
        }));
    }
    if (stepKey === "coordinator") {
        const hasTasks = (industryReportWorkspace.writingTasks || []).length > 0;
        const progressById = industryReportWorkspace.coordinatorProgressById || {};
        const outlineItems = flattenIndustryReportOutlineSubsections();
        const writingTaskById = new Map((industryReportWorkspace.writingTasks || [])
            .map((task, index) => [task?.outline_id || `task_${index + 1}`, { task, index }]));
        const sourceItems = outlineItems.length
            ? outlineItems
            : (industryReportWorkspace.writingTasks || []).map((task, index) => ({
                key: task.outline_id || `task_${index + 1}`,
                title: task.title || `写作任务 ${index + 1}`,
                parent: task.parent_level1_title || "",
                indexLabel: task.outline_id || String(index + 1),
                statusState: "pending",
            }));
        const tasks = sourceItems.map((item, index) => {
            const matched = writingTaskById.get(item.key);
            const task = matched?.task || {};
            const progress = progressById[item.key] || {};
            return {
                ...item,
                title: task.title || item.title || `写作任务 ${index + 1}`,
                parent: task.parent_level1_title || item.parent || "",
                indexLabel: task.outline_id || item.indexLabel || String(index + 1),
                status: progress.status || "待统筹检索",
                statusState: progress.statusState || "pending",
            };
        });
        if (hasTasks && !outlineItems.length) {
            (industryReportWorkspace.writingTasks || []).forEach((task, index) => {
                const key = task?.outline_id || `task_${index + 1}`;
                if (tasks.some(item => item.key === key)) return;
                const progress = progressById[key] || {};
                tasks.push({
                    key,
                    title: task.title || `写作任务 ${index + 1}`,
                    parent: task.parent_level1_title || "",
                    indexLabel: task.outline_id || String(index + 1),
                    status: progress.status || "待统筹检索",
                    statusState: progress.statusState || "pending",
                });
            });
        }
        return tasks;
    }
    if (stepKey === "body") {
        const generatedById = new Map((industryReportWorkspace.bodySections || []).map(section => [section.outline_id, section]));
        const progressById = industryReportWorkspace.bodyProgressById || {};
        const source = (industryReportWorkspace.writingTasks || []).length
            ? industryReportWorkspace.writingTasks.map((task, index) => ({
                key: task.outline_id || `task_${index + 1}`,
                title: task.title || `正文章节 ${index + 1}`,
                parent: task.parent_level1_title || "",
                indexLabel: task.outline_id || String(index + 1),
            }))
            : flattenIndustryReportOutlineSubsections();
        const items = source.map(item => {
            const generated = generatedById.get(item.key);
            const progress = progressById[item.key];
            const failed = generated && generated.status !== "success";
            if (progress?.statusState) {
                return {
                    ...item,
                    status: progress.status,
                    statusState: progress.statusState,
                };
            }
            return {
                ...item,
                status: failed ? "失败" : generated ? "已生成" : "待生成",
                statusState: failed ? "failed" : generated ? "done" : "pending",
            };
        });
        if (industryReportWorkspace.currentStage === "body") {
            items.forEach(item => {
                if (item.statusState === "pending") {
                    item.status = "生成中";
                    item.statusState = "active";
                }
            });
        }
        return items;
    }
    if (stepKey === "review") {
        return (industryReportWorkspace.bodySections || []).map((section, index) => ({
            key: section.outline_id || `section_${index + 1}`,
            title: section.title || `正文章节 ${index + 1}`,
            parent: section.parent_level1_title || "",
            indexLabel: section.outline_id || String(index + 1),
            status: section.status === "success" ? "可预览" : "需补齐",
            statusState: section.status === "success" ? "done" : "failed",
        }));
    }
    return [];
}

function renderIndustryReportActiveStepPanel(step, style) {
    const items = getIndustryReportStepSubitems(step.key);
    const groups = groupIndustryReportStepItems(items);
    const emptyText = getIndustryReportStepEmptyText(step.key);
    const summary = getIndustryReportActiveStepSummary(step.key, items);
    return `
        <div class="mt-3 border ${style.panel} rounded-lg px-4 py-3 min-h-[86px]">
            <div class="flex items-center justify-between gap-3 mb-2">
                <div class="font-semibold ${style.title}">${escapeIndustryReportHtml(step.title)}任务明细</div>
                <div class="text-xs ${style.detail}">${escapeIndustryReportHtml(summary || style.label)}</div>
            </div>
            ${groups.length ? `
                <div class="industry-report-step-detail-scroll space-y-3 max-h-64 overflow-y-auto pr-1">
                    ${groups.map(group => renderIndustryReportStepGroup(group)).join("")}
                </div>
            ` : `<div class="text-sm ${style.detail}">${escapeIndustryReportHtml(emptyText)}</div>`}
        </div>
    `;
}

function getIndustryReportActiveStepSummary(stepKey, items) {
    const fallbackTotal = (items || []).length;
    const total = stepKey === "coordinator"
        ? getIndustryReportCoordinatorTotal(items)
        : stepKey === "body"
            ? getIndustryReportBodyTotal(items)
            : fallbackTotal;
    if (!total) return "";
    const done = items.filter(item => item.statusState === "done").length;
    const failed = items.filter(item => item.statusState === "failed").length;
    if (stepKey === "body") {
        return failed
            ? `已生成 ${done} / 共 ${total} 个小节，失败 ${failed} 个`
            : `已生成 ${done} / 共 ${total} 个小节`;
    }
    if (stepKey === "review") return `已生成 ${done} / 共 ${total} 个小节`;
    if (stepKey === "coordinator") return `已统筹 ${done} / 共 ${total} 个任务`;
    if (stepKey === "outline") return `已生成 ${done} / 共 ${total} 个二级标题`;
    return "";
}

function renderIndustryReportExecutionLog(stage = industryReportWorkspace.currentStage || "idle") {
    const box = document.getElementById("industry-report-execution-log");
    if (!box) return;
    const items = stampIndustryReportExecutionLogItems(buildIndustryReportExecutionLogItems(stage));
    box.dataset = box.dataset || {};
    const previousKeyList = box.dataset.logKeys || "";
    const nextKeyList = items.map(item => item.key).join("|");
    if (!items.length) {
        box.innerHTML = '<div class="text-sm text-slate-400">等待任务启动后显示执行记录</div>';
        box.dataset.logKeys = "";
        return;
    }
    box.innerHTML = `
        <div class="industry-report-log-timeline">
            ${items.map(item => {
                const style = getIndustryReportLogStyle(item.statusState, item.key);
                return `
                    <div class="industry-report-log-item">
                        <div class="industry-report-log-time">${escapeIndustryReportHtml(item.time)}</div>
                        <div class="industry-report-log-dot ${style.dot}"></div>
                        <div class="min-w-0 flex-1">
                            <div class="flex items-start gap-2">
                                <span class="inline-flex w-8 h-8 shrink-0 items-center justify-center rounded-full ${style.icon}">
                                    <i class="${style.iconHtml}"></i>
                                </span>
                                <div class="min-w-0">
                                    <div class="text-sm font-semibold text-slate-800 leading-5">${escapeIndustryReportHtml(item.title)}</div>
                                    ${item.subtitle ? `<div class="text-xs leading-5 text-slate-500 break-words">${escapeIndustryReportHtml(item.subtitle)}</div>` : ""}
                                    ${item.detail ? `<div class="text-xs leading-5 ${style.text} break-words">${escapeIndustryReportHtml(item.detail)}</div>` : ""}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join("")}
        </div>
    `;
    box.dataset.logKeys = nextKeyList;
    if (nextKeyList !== previousKeyList) {
        box.scrollTop = box.scrollHeight;
    }
}

function buildIndustryReportExecutionLogItems(stage = "idle") {
    const items = [];
    const completed = new Set(industryReportWorkspace.completedSteps || []);
    const pushStep = (key, title, doneDetail, pendingDetail) => {
        const state = getIndustryReportStepState(key, stage);
        if (state === "pending" && !completed.has(key) && key !== "requirement") return;
        items.push({
            key,
            title,
            detail: state === "done" ? doneDetail : pendingDetail,
            statusState: state,
        });
    };
    pushStep("requirement", "分析 Agent 完成需求理解", "任务卡已生成", "等待提交题目与需求");
    pushStep("outline", "规划 Agent 生成报告大纲", `已生成 ${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题`, "正在生成报告结构");

    const coordinatorItems = getIndustryReportStepSubitems("coordinator");
    const coordinatorTotal = getIndustryReportCoordinatorTotal(coordinatorItems);
    getIndustryReportStepSubitems("coordinator")
        .filter(item => item.statusState === "done" || item.statusState === "failed")
        .forEach((item, index) => {
            const progressLabel = `(${Math.min(index + 1, coordinatorTotal || coordinatorItems.length || 1)}/${coordinatorTotal || coordinatorItems.length || 1})`;
            items.push({
                key: `coordinator_${item.key}`,
                title: item.statusState === "failed" ? `调度 Agent 统筹失败 ${progressLabel}` : `调度 Agent 完成任务分发 ${progressLabel}`,
                subtitle: item.title || "",
                detail: item.status || item.parent || "已完成检索与写作任务拆分",
                statusState: item.statusState,
            });
        });

    getIndustryReportStepSubitems("body")
        .filter(item => item.statusState === "done" || item.statusState === "failed")
        .forEach((item, index) => {
            const workerCount = Math.max(1, getIndustryReportNumber("industry-report-workers", 3));
            const agentName = `写作 Agent ${(index % workerCount) + 1}`;
            items.push({
                key: `body_${item.key}`,
                title: item.statusState === "failed" ? `${agentName} 生成失败` : `${agentName} ${item.statusState === "done" ? "已完成" : "正在生成"}`,
                subtitle: item.title || "",
                detail: item.statusState === "failed" ? "生成失败" : "",
                statusState: item.statusState,
            });
        });

    if (industryReportWorkspace.exportState) {
        const reviewState = industryReportWorkspace.exportState;
        items.push({
            key: "review",
            title: reviewState === "done" ? "导出 Agent 完成报告整理" : reviewState === "failed" ? "导出 Agent 导出失败" : "导出 Agent 准备最终报告",
            detail: reviewState === "done" ? "Word 已生成并下载" : reviewState === "failed" ? "请检查导出失败原因" : "正在生成 Word 文件",
            statusState: reviewState,
        });
    }
    return items;
}

function stampIndustryReportExecutionLogItems(items) {
    industryReportWorkspace.executionLogTimeByKey = industryReportWorkspace.executionLogTimeByKey || {};
    return (items || []).map(item => {
        const key = item.key || `${item.title}_${item.detail}`;
        if (!industryReportWorkspace.executionLogTimeByKey[key]) {
            industryReportWorkspace.executionLogTimeByKey[key] = getIndustryReportCurrentTimeLabel();
        }
        return {
            ...item,
            time: industryReportWorkspace.executionLogTimeByKey[key],
        };
    });
}

function getIndustryReportCurrentTimeLabel() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

function getIndustryReportLogStyle(statusState, itemKey = "") {
    const map = {
        done: {
            dot: "bg-emerald-500",
            icon: "bg-emerald-100 text-emerald-600",
            text: "text-slate-500",
            iconHtml: "fas fa-robot",
        },
        active: {
            dot: "bg-blue-500",
            icon: "bg-blue-100 text-blue-600",
            text: "text-blue-600",
            iconHtml: "fas fa-robot",
        },
        failed: {
            dot: "bg-red-500",
            icon: "bg-red-100 text-red-600",
            text: "text-red-600",
            iconHtml: "fas fa-triangle-exclamation",
        },
        pending: {
            dot: "bg-slate-300",
            icon: "bg-slate-100 text-slate-500",
            text: "text-slate-400",
            iconHtml: "far fa-clock",
        },
    };
    const style = map[statusState] || map.pending;
    const agentIcons = {
        requirement: "bg-violet-100 text-violet-600",
        outline: "bg-blue-100 text-blue-600",
        coordinator: "bg-amber-100 text-amber-700",
        body: "bg-cyan-100 text-cyan-700",
        review: "bg-emerald-100 text-emerald-600",
    };
    const agentIcon = agentIcons[String(itemKey).split("_")[0]];
    return style.iconHtml === "fas fa-robot" && agentIcon ? { ...style, icon: agentIcon } : style;
}

function groupIndustryReportStepItems(items) {
    const groups = [];
    const byTitle = {};
    (items || []).forEach(item => {
        const title = item.parent || "当前任务";
        if (!byTitle[title]) {
            byTitle[title] = { title, children: [] };
            groups.push(byTitle[title]);
        }
        byTitle[title].children.push(item);
    });
    return groups;
}

function renderIndustryReportStepGroup(group) {
    return `
        <div class="rounded-lg border border-white/80 bg-white/70 p-3">
            <div class="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-2">
                <i class="fas fa-folder-open text-gray-400"></i>
                ${escapeIndustryReportHtml(group.title)}
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
                ${group.children.map(item => renderIndustryReportStepItem(item)).join("")}
            </div>
        </div>
    `;
}

function renderIndustryReportStepItem(item) {
    const styles = {
        active: "bg-blue-50 border-blue-200 text-blue-800 ring-1 ring-blue-200",
        done: "bg-emerald-50 border-emerald-200 text-emerald-800",
        failed: "bg-red-50 border-red-200 text-red-700",
        pending: "bg-gray-50 border-gray-200 text-gray-600",
    };
    const cls = styles[item.statusState] || styles.pending;
    return `
        <div class="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs min-w-0 ${cls}">
            <span class="w-10 shrink-0 font-semibold">${escapeIndustryReportHtml(item.indexLabel || "")}</span>
            <span class="min-w-0 flex-1 truncate">${escapeIndustryReportHtml(item.title || "")}</span>
            <span class="shrink-0 font-medium">${escapeIndustryReportHtml(item.status || "")}</span>
        </div>
    `;
}

function getIndustryReportStepEmptyText(stepKey) {
    const map = {
        requirement: "填写报告题目和需求后，提交生成写作任务卡。",
        outline: "大纲生成后，这里会列出二级小标题。",
        coordinator: "确认大纲后，这里会列出统筹拆分出的写作任务。",
        body: "开始生成正文后，这里会显示每个二级标题的生成状态。",
        review: "正文生成完成后，可以在下方预览、重写、保存或导出。",
    };
    return map[stepKey] || "等待任务开始。";
}

function acceptIndustryReportRunResult(data) {
    if (data.runtime_budget) industryReportWorkspace.runtimeBudget = data.runtime_budget;
    if (data.report_scope) {
        industryReportWorkspace.reportScope = data.report_scope;
        if (data.report_scope.effective_title) {
            industryReportWorkspace.reportTitle = data.report_scope.effective_title;
            const input = document.getElementById("industry-report-title");
            if (input) input.value = data.report_scope.effective_title;
        }
    }
    if (data.delivery_status) industryReportWorkspace.deliveryStatus = data.delivery_status;
    if (Array.isArray(data.delivery_reasons)) industryReportWorkspace.deliveryReasons = data.delivery_reasons;
    if (data.docx_path) {
        if (Array.isArray(data.adjustment_notes)) industryReportWorkspace.adjustmentNotes = data.adjustment_notes;
        appendIndustryReportWarnings(data.warnings);
    }
    if (data.summary_review) industryReportWorkspace.summaryReview = data.summary_review;
}

function withIndustryReportRuntime(payload) {
    return {...payload, runtime_budget: industryReportWorkspace.runtimeBudget || {},
        report_scope: industryReportWorkspace.reportScope || null};
}

async function industryReportApi(path, options = {}) {
    if (options.body && /^\/api\/report\/(coordinator|body|summary|export\/word)(\/stream)?$/.test(path)) {
        options = {...options, body: JSON.stringify(withIndustryReportRuntime(JSON.parse(options.body)))};
    }

    const resp = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
    });
    let data = {};
    try {
        data = await resp.json();
    } catch (err) {
        data = {};
    }
    acceptIndustryReportRunResult(data);
    if (!resp.ok || data.status === "error") {
        throw new Error(data.message || data.error?.message || `接口请求失败：${resp.status}`);
    }
    return data;
}

function hasIndustryReportContent() {
    return Boolean(
        industryReportWorkspace.historyId
        || (industryReportWorkspace.outline || []).length
        || (industryReportWorkspace.writingTasks || []).length
        || (industryReportWorkspace.bodySections || []).length
    );
}

function syncIndustryReportHeader() {
    const currentIndustry = getIndustryReportCurrentIndustry();
    if (!hasIndustryReportContent() && !industryReportWorkspace.taskCard) {
        industryReportWorkspace.industry = currentIndustry;
    }
    const industry = industryReportWorkspace.industry || currentIndustry;
    const pill = document.getElementById("report-industry-pill");
    if (pill) {
        const name = industryReportWorkspace.taskCard?.selected_industry_name
            || getIndustryReportIndustryName(industry);
        pill.textContent = name;
        pill.className = "text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100";
    }
}

function applyIndustryReportResolvedIndustry(industry, industryName) {
    if (!industry || industry === getIndustryReportCurrentIndustry()) return;
    // 自动切换标题识别出的受支持行业，但不派发 industryChanged，避免清空刚生成的报告工作区。
    window.currentIndustry = industry;
    syncIndustryReportTitlePlaceholder(industry);
    const input = document.getElementById("industry-search-input");
    if (input) {
        input.value = industryName || getIndustryReportIndustryName(industry);
        input.setAttribute("readonly", "readonly");
    }
    if (typeof loadIndustryData === "function") loadIndustryData(industry);
}

function resetIndustryReportWorkspace() {
    closeIndustryReportTemplate();
    const industry = getIndustryReportCurrentIndustry();
    const defaultTitle = getIndustryReportDefaultTitle(industry);
    const requirementRewriteSeq = nextIndustryReportRequirementRewriteSeq();
    industryReportWorkspace = {
        historyId: "",
        currentStage: "idle",
        activeStep: "requirement",
        completedSteps: [],
        flowCollapsed: false,
        userPrompt: "",
        reportTitle: defaultTitle,
        abstractText: "",
        industry,
        pageIndustry: industry,
        taskCard: null,
        outlineTemplate: null,
        outline: [],
        writingTasks: [],
        coordination: null,
        bodySections: [],
        references: [],
        warnings: [],
        activeSectionId: "",
        rewriteMaterials: null,
        busy: false,
        exportState: "",
        selectedAgentStep: "requirement",
        bodyProgressById: {},
        coordinatorProgressById: {},
        executionLogTimeByKey: {},
        stepTimingByKey: {},
        bodyTotal: 0,
        coordinatorTotal: 0,
        outlineLocked: false,
        requirementRewriteSeq,
        previewTarget: { type: "all", key: "" },
        lastSectionPreviewKey: "",
    };
    const titleInput = document.getElementById("industry-report-title");
    if (titleInput) {
        titleInput.value = "";
        titleInput.placeholder = defaultTitle;
    }
    renderIndustryReportOutline([]);
    renderIndustryReportTaskCard(null);
    renderIndustryReportProgress([]);
    renderIndustryReportPreview();
    closeIndustryReportRewriteModal();
    setIndustryReportStage("idle", "等待输入报告题目");
    setIndustryReportStatus("等待输入题目", "info");
    syncIndustryReportHeader();
    void refreshIndustryReportHistorySelect();
}

function getIndustryReportFormValues() {
    const prompt = (document.getElementById("industry-report-prompt")?.value || "").trim();
    const industry = getIndustryReportCurrentIndustry();
    const title = (document.getElementById("industry-report-title")?.value || "").trim()
        || getIndustryReportDefaultTitle(industry);
    return { prompt, title, industry };
}

async function submitIndustryReportRequirement() {
    if (isIndustryReportRequirementLocked()) {
        setIndustryReportStatus("报告需求已提交，如需修改请先回退。", "info");
        syncIndustryReportEditableState();
        return;
    }
    markIndustryReportTemplateForReview();
    const { prompt, title, industry } = getIndustryReportFormValues();
    if (!title) {
        setIndustryReportStatus("请先输入报告标题", "error");
        return;
    }
    const taskCardSeq = nextIndustryReportRequirementRewriteSeq();
    setIndustryReportBusy(true, "正在理解题目与需求并生成写作任务卡...");
    clearIndustryReportStepDone(["requirement", "outline", "coordinator", "body", "review"]);
    clearIndustryReportStepTiming(["requirement", "outline", "coordinator", "body", "review"]);
    startIndustryReportStepTiming("requirement");
    setIndustryReportStage("idle", "正在生成写作任务卡");
    try {
        const data = await industryReportApi("/api/report/task-card", {
            method: "POST",
            body: JSON.stringify({ title, user_requirement: prompt, page_industry: industry }),
        });
        if (industryReportWorkspace.requirementRewriteSeq !== taskCardSeq) return;
        industryReportWorkspace.historyId = "";
        industryReportWorkspace.userPrompt = prompt;
        industryReportWorkspace.reportTitle = title;
        industryReportWorkspace.pageIndustry = industry;
        industryReportWorkspace.industry = data.task_card?.selected_industry || "";
        industryReportWorkspace.taskCard = data.task_card || null;
        industryReportWorkspace.outline = [];
        industryReportWorkspace.writingTasks = [];
        industryReportWorkspace.coordination = null;
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.outlineLocked = false;
        industryReportWorkspace.references = [];
        industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
        industryReportWorkspace.warnings = [];
        appendIndustryReportWarnings(data.warnings);
        renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
        renderIndustryReportOutline([]);
        renderIndustryReportProgress([]);
        renderIndustryReportPreview();
        markIndustryReportStepDone("requirement");
        setIndustryReportStage("idle", "写作任务卡已生成，等待确认");
        setIndustryReportRequirementSubmittedStatus(data.warnings);
    } catch (err) {
        if (industryReportWorkspace.requirementRewriteSeq !== taskCardSeq) return;
        setIndustryReportStage("error", "写作任务卡生成失败");
        setIndustryReportStatus(`写作任务卡生成失败：${err.message}`, "error");
    } finally {
        if (industryReportWorkspace.requirementRewriteSeq === taskCardSeq) {
            setIndustryReportBusy(false);
        }
    }
}

function renderIndustryReportTaskCard(taskCard) {
    syncIndustryReportTemplateSummary();
    const section = document.getElementById("industry-report-task-card-section");
    if (!section) return;
    section.classList.remove("hidden");

    const empty = document.getElementById("industry-report-task-card-empty");
    const content = document.getElementById("industry-report-task-card-content");
    const actions = document.getElementById("industry-report-task-card-actions");
    const originalTitle = document.getElementById("industry-report-original-title");
    const selectedTitle = document.getElementById("industry-report-task-title");
    const requirement = document.getElementById("industry-report-task-requirement");
    const recognizedIndustry = document.getElementById("industry-report-recognized-industry");
    const selectedIndustry = document.getElementById("industry-report-selected-industry");
    const useGraph = document.getElementById("industry-report-use-graph");
    const useExternalRag = document.getElementById("industry-report-use-external-rag");
    const state = document.getElementById("industry-report-task-card-state");
    const confirmBtn = document.getElementById("report-task-card-confirm-btn");
    const suggestionBox = document.getElementById("industry-report-title-suggestions");
    const suggestionOptions = document.getElementById("industry-report-title-suggestion-options");
    const resultBox = document.getElementById("industry-report-match-result");

    if (!taskCard) {
        const industry = getIndustryReportCurrentIndustry();
        if (empty) empty.classList.remove("hidden");
        if (content) content.classList.add("hidden");
        if (actions) actions.classList.add("hidden");
        if (originalTitle) originalTitle.value = "";
        if (selectedTitle) selectedTitle.value = "";
        if (requirement) requirement.value = "";
        syncIndustryReportRequirementPreview("");
        if (recognizedIndustry) recognizedIndustry.textContent = "待生成";
        if (selectedIndustry) {
            selectedIndustry.innerHTML = `<option value="${escapeIndustryReportHtml(industry)}">${escapeIndustryReportHtml(getIndustryReportIndustryName(industry))}</option>`;
            selectedIndustry.value = industry;
        }
        if (useGraph) {
            useGraph.checked = false;
            useGraph.disabled = true;
        }
        if (useExternalRag) {
            useExternalRag.checked = false;
            useExternalRag.disabled = true;
        }
        if (suggestionBox) suggestionBox.classList.add("hidden");
        if (suggestionOptions) suggestionOptions.innerHTML = "";
        if (resultBox) resultBox.innerHTML = '<div>提交题目与需求后，系统会生成可编辑的写作任务卡、参考标题和产业匹配结果。</div>';
        if (state) state.textContent = "待生成";
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.classList.add("opacity-60", "cursor-not-allowed");
        }
        syncIndustryReportEditableState();
        return;
    }

    if (empty) empty.classList.add("hidden");
    if (content) content.classList.remove("hidden");
    if (actions) actions.classList.remove("hidden");
    if (state) state.textContent = "等待确认";
    if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.classList.remove("opacity-60", "cursor-not-allowed");
    }

    if (originalTitle) originalTitle.value = taskCard.original_title || "";
    if (selectedTitle) selectedTitle.value = taskCard.selected_title || taskCard.original_title || "";
    if (requirement) {
        requirement.disabled = false;
        requirement.value = taskCard.report_requirement || "";
        syncIndustryReportRequirementPreview(requirement.value);
    }
    if (recognizedIndustry) recognizedIndustry.textContent = taskCard.recognized_industry || "未识别";

    const suggestions = Array.isArray(taskCard.suggested_titles) ? taskCard.suggested_titles : [];
    if (suggestionOptions) {
        const titleOptions = suggestions
            .map(title => String(title || "").trim())
            .filter((title, index, array) => title && array.indexOf(title) === index);
        if (suggestionBox) suggestionBox.classList.toggle("hidden", !titleOptions.length);
        suggestionOptions.innerHTML = titleOptions.map((title, index) => {
            const checked = title === (selectedTitle?.value || "") ? " checked" : "";
            return `
                <label class="flex items-start gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 cursor-pointer hover:border-blue-200 hover:bg-blue-50/40">
                    <input type="radio" name="industry-report-title-suggestion" value="${escapeIndustryReportHtml(title)}"
                           onchange="selectIndustryReportSuggestedTitle(this.value)" class="mt-1 text-blue-600"${checked}>
                    <span class="leading-5">${escapeIndustryReportHtml(title)}</span>
                </label>
            `;
        }).join("");
    }

    if (selectedIndustry) {
        const matches = Array.isArray(taskCard.industry_matches) ? taskCard.industry_matches : [];
        selectedIndustry.innerHTML = matches.map(item => {
            const graphText = item.graph_available ? "图谱可用" : "图谱不可用";
            const ragText = item.external_rag_available ? "外部资料库可用" : "外部资料库不可用";
            const label = `${item.name || item.key || "未知产业"}（${graphText}，${ragText}）`;
            return `<option value="${escapeIndustryReportHtml(item.key || "")}">${escapeIndustryReportHtml(label)}</option>`;
        }).join("");
        selectedIndustry.value = taskCard.selected_industry || "";
    }
    updateIndustryReportTaskCardMatch();
    if (state && isIndustryReportTaskCardLocked()) state.textContent = "已确认";
    syncIndustryReportEditableState();
}

function getIndustryReportSelectedMatch(taskCard = industryReportWorkspace.taskCard) {
    const selectedKey = document.getElementById("industry-report-selected-industry")?.value || "";
    return (taskCard?.industry_matches || []).find(item => item.key === selectedKey) || null;
}

function setIndustryReportSourceCheckboxState(input, row, available, checked) {
    if (!input) return;
    input.disabled = !available;
    input.checked = Boolean(available && checked);
    if (row) {
        row.classList.toggle("text-gray-400", !available);
        row.classList.toggle("text-gray-700", Boolean(available));
    }
}

function syncIndustryReportRequirementPreview(value) {
    const preview = document.getElementById("industry-report-task-requirement-preview");
    const textarea = document.getElementById("industry-report-task-requirement");
    if (!preview) return;
    const raw = value !== undefined
        ? String(value || "")
        : String(textarea?.value || "");
    const text = raw.trim();
    if (textarea) textarea.value = raw;
    if (!text) {
        preview.innerHTML = '<div class="text-gray-400">报告需求生成后将在这里分段预览，下面仍可编辑原文。</div>';
        return;
    }
    const parts = text
        .replace(/\s+/g, "")
        .split(/(?<=[。；;])/) 
        .map(item => item.trim())
        .filter(Boolean);
    const displayParts = parts.length ? parts : [text];
    preview.innerHTML = displayParts
        .map(item => `<p class="m-0">${escapeIndustryReportHtml(item)}</p>`)
        .join('<div class="h-2"></div>');
}

function handleIndustryReportRequirementPreviewInput() {
    if (isIndustryReportTaskCardLocked()) {
        syncIndustryReportRequirementPreview();
        setIndustryReportStatus("写作任务卡已确认，如需修改请先回退。", "info");
        return;
    }
    markIndustryReportTemplateForReview();
    const preview = document.getElementById("industry-report-task-requirement-preview");
    const textarea = document.getElementById("industry-report-task-requirement");
    if (!preview || !textarea) return;
    const text = String(preview.innerText || preview.textContent || "")
        .replace(/\u00a0/g, " ")
        .split("\n")
        .map(item => item.trim())
        .filter(Boolean)
        .join("\n");
    textarea.value = text;
}

function handleIndustryReportSourceToggle() {
    if (isIndustryReportTaskCardLocked()) {
        renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
        setIndustryReportStatus("写作任务卡已确认，如需修改请先回退。", "info");
        return;
    }
    const taskCard = industryReportWorkspace.taskCard;
    if (!taskCard) return;
    const match = getIndustryReportSelectedMatch(taskCard);
    const useGraph = document.getElementById("industry-report-use-graph");
    const useExternalRag = document.getElementById("industry-report-use-external-rag");
    industryReportWorkspace.taskCard = {
        ...taskCard,
        use_graph: Boolean(match?.graph_available && useGraph?.checked),
        use_external_rag: Boolean(match?.external_rag_available && useExternalRag?.checked),
    };
    updateIndustryReportTaskCardMatch();
}

function selectIndustryReportSuggestedTitle(title) {
    if (isIndustryReportTaskCardLocked()) {
        setIndustryReportStatus("写作任务卡已确认，如需修改请先回退。", "info");
        return;
    }
    markIndustryReportTemplateForReview();
    const input = document.getElementById("industry-report-task-title");
    if (input) input.value = title || "";
}

async function handleIndustryReportSelectedIndustryChange() {
    if (isIndustryReportTaskCardLocked()) {
        renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
        setIndustryReportStatus("写作任务卡已确认，如需修改请先回退。", "info");
        return;
    }
    markIndustryReportTemplateForReview();
    updateIndustryReportTaskCardMatch();
    const taskCard = industryReportWorkspace.taskCard;
    if (!taskCard) return;
    const rewriteSeq = nextIndustryReportRequirementRewriteSeq();
    const selectedIndustry = document.getElementById("industry-report-selected-industry")?.value || "";
    const requirementInput = document.getElementById("industry-report-task-requirement");
    const confirmBtn = document.getElementById("report-task-card-confirm-btn");
    if (!selectedIndustry) {
        if (requirementInput) {
            requirementInput.disabled = false;
            requirementInput.value = taskCard.report_requirement || requirementInput.value;
            syncIndustryReportRequirementPreview(requirementInput.value);
        }
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.classList.remove("opacity-60", "cursor-not-allowed");
        }
        return;
    }

    const match = (taskCard.industry_matches || []).find(item => item.key === selectedIndustry);
    if (!match) return;

    const title = (document.getElementById("industry-report-task-title")?.value || taskCard.selected_title || taskCard.original_title || "").trim();
    const userRequirement = taskCard.original_requirement || "";

    if (requirementInput) {
        requirementInput.disabled = true;
        requirementInput.value = "正在重新生成报告需求...";
        syncIndustryReportRequirementPreview(requirementInput.value);
    }
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.classList.add("opacity-60", "cursor-not-allowed");
    }
    setIndustryReportStatus("正在根据用户原始需求、切换后的产业方向和标题重新生成报告需求...", "loading");

    try {
        const data = await industryReportApi("/api/report/task-card/rewrite-requirement", {
            method: "POST",
            body: JSON.stringify({
                title,
                user_requirement: userRequirement,
                industry: selectedIndustry,
                industry_name: match.name || "",
            }),
        });
        if (industryReportWorkspace.requirementRewriteSeq !== rewriteSeq) return;
        const rewrittenRequirement = data.report_requirement || "";
        industryReportWorkspace.taskCard = {
            ...industryReportWorkspace.taskCard,
            selected_title: title,
            report_requirement: rewrittenRequirement,
            selected_industry: selectedIndustry,
            selected_industry_name: match.name || "",
            selection_source: "user",
            use_graph: Boolean(match.graph_available),
            use_external_rag: Boolean(match.external_rag_available),
            graph_match: {
                status: match.graph_available ? "matched" : "unavailable",
                industry: selectedIndustry,
                industry_name: match.name || "",
                graph_available: Boolean(match.graph_available),
            },
            external_rag_match: {
                status: match.external_rag_available ? "matched" : "unavailable",
                industry: selectedIndustry,
                industry_name: match.name || "",
                external_rag_available: Boolean(match.external_rag_available),
            },
        };
        industryReportWorkspace.userPrompt = rewrittenRequirement;
        industryReportWorkspace.industry = selectedIndustry;
        if (requirementInput) {
            requirementInput.value = rewrittenRequirement;
            syncIndustryReportRequirementPreview(rewrittenRequirement);
        }
        appendIndustryReportWarnings(data.warnings);
        const fallback = getIndustryReportRequirementFallbackWarning(data.warnings);
        setIndustryReportStatus(
            fallback?.message || "报告需求已根据新的最终产业方向更新",
            fallback ? "info" : "success",
        );
    } catch (err) {
        if (industryReportWorkspace.requirementRewriteSeq !== rewriteSeq) return;
        if (requirementInput) {
            requirementInput.value = taskCard.report_requirement || "";
            syncIndustryReportRequirementPreview(requirementInput.value);
        }
        setIndustryReportStatus(`报告需求重写失败：${err.message}`, "error");
    } finally {
        if (industryReportWorkspace.requirementRewriteSeq === rewriteSeq && requirementInput) {
            requirementInput.disabled = false;
        }
        if (industryReportWorkspace.requirementRewriteSeq === rewriteSeq && confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.classList.remove("opacity-60", "cursor-not-allowed");
        }
    }
}

function updateIndustryReportTaskCardMatch() {
    const taskCard = industryReportWorkspace.taskCard;
    const resultBox = document.getElementById("industry-report-match-result");
    if (!taskCard || !resultBox) return;
    const match = getIndustryReportSelectedMatch(taskCard);
    const useGraph = document.getElementById("industry-report-use-graph");
    const useExternalRag = document.getElementById("industry-report-use-external-rag");
    const graphRow = document.getElementById("industry-report-use-graph-row");
    const ragRow = document.getElementById("industry-report-use-external-rag-row");
    const conflict = taskCard.industry_conflict
        ? `<div class="mb-2 text-amber-700">当前页面产业与模型识别结果不同，请确认最终产业方向。</div>`
        : "";
    if (!match) {
        setIndustryReportSourceCheckboxState(useGraph, graphRow, false, false);
        setIndustryReportSourceCheckboxState(useExternalRag, ragRow, false, false);
        resultBox.innerHTML = `${conflict}<div>未选择产业图谱。系统将基于已有资料和大模型能力继续生成，后续不会使用特定产业图谱作为证据源。</div>`;
        return;
    }
    const desiredGraph = taskCard.selected_industry === match.key
        ? taskCard.use_graph !== false
        : Boolean(match.graph_available);
    const desiredExternal = taskCard.selected_industry === match.key
        ? taskCard.use_external_rag !== false
        : Boolean(match.external_rag_available);
    setIndustryReportSourceCheckboxState(useGraph, graphRow, Boolean(match.graph_available), desiredGraph);
    setIndustryReportSourceCheckboxState(useExternalRag, ragRow, Boolean(match.external_rag_available), desiredExternal);
    const graphText = match.graph_available
        ? "已匹配可用产业图谱，勾选后后续生成将调用该图谱。"
        : "该产业暂无可用图谱，不能勾选使用。";
    const ragText = match.external_rag_available
        ? "已匹配可用外部资料库，勾选后后续生成将调用该资料库。"
        : "该产业暂无可用外部资料库，不能勾选使用。";
    const reasonText = String(match.reason || "").trim() || "系统支持";
    const reason = `<div class="mt-1"><span class="font-semibold text-gray-700">依据：</span>${escapeIndustryReportHtml(reasonText)}</div>`;
    resultBox.innerHTML = `${conflict}<div><span class="font-semibold text-gray-700">当前选择产业：</span>${escapeIndustryReportHtml(match.name || match.key)}</div>${reason}<div class="mt-1"><span class="font-semibold text-gray-700">图谱匹配：</span>${graphText}</div><div class="mt-1"><span class="font-semibold text-gray-700">外部资料库匹配：</span>${ragText}</div><div class="mt-1 text-xs text-gray-500">最终产业方向只决定产业上下文，是否调用资料源以勾选状态为准。</div>`;
}

function readIndustryReportTaskCardFromDom() {
    const taskCard = industryReportWorkspace.taskCard;
    if (!taskCard) return null;
    const selectedIndustry = document.getElementById("industry-report-selected-industry")?.value || "";
    const match = (taskCard.industry_matches || []).find(item => item.key === selectedIndustry);
    const useGraph = document.getElementById("industry-report-use-graph");
    const useExternalRag = document.getElementById("industry-report-use-external-rag");
    return {
        ...taskCard,
        outline_template: industryReportWorkspace.outlineTemplate?.confirmed ? { level1_titles: [...industryReportWorkspace.outlineTemplate.level1_titles] } : undefined,
        selected_title: (document.getElementById("industry-report-task-title")?.value || "").trim(),
        report_requirement: (document.getElementById("industry-report-task-requirement")?.value || "").trim(),
        selected_industry: selectedIndustry,
        selected_industry_name: match?.name || "",
        selection_source: "user",
        use_graph: Boolean(match?.graph_available && useGraph?.checked),
        use_external_rag: Boolean(match?.external_rag_available && useExternalRag?.checked),
        graph_match: {
            status: match?.graph_available ? "matched" : "unavailable",
            industry: selectedIndustry,
            industry_name: match?.name || "",
            graph_available: Boolean(match?.graph_available),
        },
        external_rag_match: {
            status: match?.external_rag_available ? "matched" : "unavailable",
            industry: selectedIndustry,
            industry_name: match?.name || "",
            external_rag_available: Boolean(match?.external_rag_available),
        },
    };
}

async function generateIndustryReportOutline() {
    if (isIndustryReportTaskCardLocked()) {
        setIndustryReportStatus("写作任务卡已确认，如需修改请先回退。", "info");
        syncIndustryReportEditableState();
        return;
    }
    const template = industryReportWorkspace.outlineTemplate;
    if (template?.confirmed && template.context !== industryReportTemplateContext()) markIndustryReportTemplateForReview();
    if (template && (!template.confirmed || template.needsReview)) {
        openIndustryReportTemplate();
        document.getElementById("industry-report-template-notice").textContent = "请检查并确认右侧最终一级标题，再生成大纲。";
        return;
    }
    const taskCard = readIndustryReportTaskCardFromDom();
    const title = taskCard?.selected_title || "";
    if (!title) {
        setIndustryReportStatus("请填写任务卡中的最终报告标题", "error");
        return;
    }
    if (!taskCard?.report_requirement) {
        setIndustryReportStatus("请填写任务卡中的报告需求", "error");
        return;
    }
    setIndustryReportBusy(true);
    clearIndustryReportStepDone(["outline", "coordinator", "body", "review"]);
    clearIndustryReportStepTiming(["outline", "coordinator", "body", "review"]);
    markIndustryReportStepDone("requirement");
    startIndustryReportStepTiming("outline");
    setIndustryReportStage("outline", "正在生成推荐大纲");
    try {
        const data = await industryReportApi("/api/report/outline", {
            method: "POST",
            body: JSON.stringify({ task_card: taskCard }),
        });
        industryReportWorkspace.taskCard = taskCard;
        industryReportWorkspace.userPrompt = taskCard.report_requirement;
        industryReportWorkspace.historyId = "";
        industryReportWorkspace.reportTitle = title;
        industryReportWorkspace.industry = taskCard.selected_industry || "";
        industryReportWorkspace.outline = normalizeIndustryReportOutline(data.outline || []);
        industryReportWorkspace.warnings = [];
        appendIndustryReportWarnings(data.warnings);
        industryReportWorkspace.writingTasks = [];
        industryReportWorkspace.coordination = null;
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
        const titleInput = document.getElementById("industry-report-title");
        if (titleInput) titleInput.value = title;
        syncIndustryReportHeader();
        renderIndustryReportOutline(industryReportWorkspace.outline);
        renderIndustryReportProgress([
            { key: "outline", title: "推荐大纲", status: "done", detail: `${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题` },
            { key: "coordinator", title: "写作任务", status: "pending", detail: "等待确认大纲" },
            { key: "body", title: "正文生成", status: "pending", detail: "等待开始" },
        ]);
        renderIndustryReportPreview();
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        setIndustryReportStage("outline", "推荐大纲已生成，可编辑后确认");
        setIndustryReportRequirementSubmittedStatus();
    } catch (err) {
        setIndustryReportStage("error", "大纲生成失败");
        setIndustryReportStatus(`大纲生成失败：${err.message}`, "error");
    } finally {
        setIndustryReportBusy(false);
    }
}

function normalizeIndustryReportOutline(outline) {
    if (!Array.isArray(outline)) return [];
    return outline
        .filter(item => item && item.section_type !== "abstract")
        .map((section, index) => {
            const level1Id = section.level1_id || section.node_id || `S${index + 1}`;
            const subsections = Array.isArray(section.subsections) ? section.subsections : (section.children || []);
            return {
                level1_id: level1Id,
                level1_title: section.level1_title || section.title || `章节 ${index + 1}`,
                section_type: "body",
                template_requirement: section.template_requirement || section.generation_instruction || "",
                section_retrieval_query: section.section_retrieval_query || "",
                graph_retrieval: section.graph_retrieval || {},
                external_rag_retrieval: section.external_rag_retrieval || {},
                warnings: section.warnings || [],
                subsections: subsections.map((sub, subIndex) => ({
                    outline_id: sub.outline_id || sub.node_id || `${level1Id}.${subIndex + 1}`,
                    title: sub.title || `二级标题 ${subIndex + 1}`,
                    generation_instruction: sub.generation_instruction || "",
                    expected_words: sub.expected_words || 800,
                })),
            };
        });
}

function countIndustryReportSubsections(outline) {
    return (outline || []).reduce((sum, section) => sum + ((section.subsections || []).length), 0);
}

function getIndustryReportCoordinatorTotal(items = null) {
    const outlineTotal = countIndustryReportSubsections(industryReportWorkspace.outline);
    const progressTotal = Object.keys(industryReportWorkspace.coordinatorProgressById || {}).length;
    const taskTotal = (industryReportWorkspace.writingTasks || []).length;
    const itemTotal = Array.isArray(items) ? items.length : 0;
    return Math.max(
        Number(industryReportWorkspace.coordinatorTotal) || 0,
        outlineTotal,
        progressTotal,
        taskTotal,
        itemTotal,
    );
}

function getIndustryReportBodyTotal(items = null) {
    const progressTotal = Object.keys(industryReportWorkspace.bodyProgressById || {}).length;
    const taskTotal = (industryReportWorkspace.writingTasks || []).length;
    const sectionTotal = (industryReportWorkspace.bodySections || []).length;
    const itemTotal = Array.isArray(items) ? items.length : 0;
    return Math.max(
        Number(industryReportWorkspace.bodyTotal) || 0,
        progressTotal,
        taskTotal,
        sectionTotal,
        itemTotal,
    );
}

function hasIndustryReportOutline(outline = industryReportWorkspace.outline) {
    return Array.isArray(outline) && countIndustryReportSubsections(outline) > 0;
}

function hasConfirmedIndustryReportOutline() {
    return hasIndustryReportOutline(industryReportWorkspace.outline)
        && Array.isArray(industryReportWorkspace.writingTasks)
        && industryReportWorkspace.writingTasks.length > 0;
}

function isIndustryReportOutlineLocked() {
    const activeStages = new Set(["coordinator", "body", "done"]);
    return Boolean(industryReportWorkspace.outlineLocked)
        || activeStages.has(industryReportWorkspace.currentStage)
        || (industryReportWorkspace.completedSteps || []).some(step => ["coordinator", "body", "review"].includes(step))
        || (industryReportWorkspace.writingTasks || []).length > 0
        || Object.keys(industryReportWorkspace.coordinatorProgressById || {}).length > 0;
}

function invalidateIndustryReportConfirmedOutline() {
    industryReportWorkspace.writingTasks = [];
    industryReportWorkspace.coordination = null;
    industryReportWorkspace.runtimeBudget = null;
    industryReportWorkspace.reportScope = null;
    industryReportWorkspace.deliveryStatus = "incomplete";
    industryReportWorkspace.deliveryReasons = [];
    industryReportWorkspace.bodySections = [];
    industryReportWorkspace.review = null;
    industryReportWorkspace.adjustmentNotes = [];
    industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
    industryReportWorkspace.bodyProgressById = {};
    industryReportWorkspace.coordinatorProgressById = {};
    industryReportWorkspace.bodyTotal = 0;
    industryReportWorkspace.coordinatorTotal = countIndustryReportSubsections(industryReportWorkspace.outline);
    clearIndustryReportStepDone(["coordinator", "body", "review"]);
}

function syncIndustryReportOutlineConfirmButton(outline = industryReportWorkspace.outline) {
    const btn = document.getElementById("report-outline-confirm-btn");
    const addBtn = document.getElementById("report-outline-add-section-btn");
    const outlineLocked = isIndustryReportOutlineLocked();
    const confirmDisabled = industryReportWorkspace.busy || outlineLocked || !hasIndustryReportOutline(outline);
    if (btn) {
        btn.disabled = confirmDisabled;
        btn.classList.toggle("opacity-60", confirmDisabled);
        btn.classList.toggle("cursor-not-allowed", confirmDisabled);
    }
    if (addBtn) {
        addBtn.disabled = industryReportWorkspace.busy || outlineLocked;
        addBtn.classList.toggle("opacity-60", addBtn.disabled);
        addBtn.classList.toggle("cursor-not-allowed", addBtn.disabled);
    }
    syncIndustryReportRollbackButton();
}

function syncIndustryReportGenerateButton(outline = industryReportWorkspace.outline) {
    const btn = document.getElementById("report-generate-btn");
    if (!btn) return;
    const disabled = industryReportWorkspace.busy
        || !hasIndustryReportOutline(outline)
        || !hasConfirmedIndustryReportOutline();
    btn.disabled = disabled;
    btn.classList.toggle("opacity-60", disabled);
    btn.classList.toggle("cursor-not-allowed", disabled);
    syncIndustryReportRollbackButton();
}

function renderIndustryReportOutline(outline) {
    const box = document.getElementById("industry-report-outline");
    if (!box) return;
    const previousScrollTop = box.scrollTop;
    const outlineLocked = isIndustryReportOutlineLocked();
    const lockedInputClass = outlineLocked ? " cursor-not-allowed text-slate-500" : "";
    const lockedButtonClass = outlineLocked ? " opacity-50 cursor-not-allowed" : "";
    const lockedDragClass = outlineLocked ? " cursor-not-allowed opacity-40" : " hover:text-blue-500 cursor-grab active:cursor-grabbing";
    const lockedAttr = outlineLocked ? "disabled" : "";
    const lockedDragAttr = outlineLocked ? 'draggable="false" aria-disabled="true"' : 'draggable="true"';
    updateIndustryReportOutlineSummary(outline || []);
    renderIndustryReportPreviewNav();
    if (!outline || !outline.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">生成推荐大纲后可编辑</div>';
        syncIndustryReportOutlineConfirmButton([]);
        syncIndustryReportGenerateButton([]);
        renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
        return;
    }
    box.innerHTML = outline.map((section, sectionIndex) => `
        <div class="industry-report-outline-section overflow-hidden rounded-lg border border-blue-100 bg-white" data-report-section="${sectionIndex}">
            <div class="flex items-center gap-3 bg-blue-50/70 px-3 py-2">
                <button type="button" onclick="toggleIndustryReportOutlineSection(${sectionIndex})"
                        class="industry-report-outline-toggle w-7 h-7 rounded-lg text-slate-500 hover:bg-white hover:text-blue-600" title="展开或收起">
                    <i class="fas fa-chevron-down"></i>
                </button>
                <span class="inline-flex w-7 h-7 shrink-0 items-center justify-center rounded-full border border-blue-200 bg-white text-sm font-bold text-blue-600">${sectionIndex + 1}</span>
                <input class="report-section-title min-w-0 flex-1 bg-transparent px-2 py-1 text-sm font-bold text-slate-800 outline-none focus:bg-white focus:ring-2 focus:ring-blue-100 rounded${lockedInputClass}"
                       oninput="handleIndustryReportOutlineInput()"
                       ${lockedAttr}
                       value="${escapeIndustryReportHtml(section.level1_title || "")}">
                <button onclick="addIndustryReportSubsection(${sectionIndex})" ${lockedAttr} class="w-8 h-8 rounded-lg bg-white border border-blue-100 hover:bg-blue-50 text-blue-600${lockedButtonClass}" title="新增二级标题">
                    <i class="fas fa-plus"></i>
                </button>
                <button onclick="removeIndustryReportSection(${sectionIndex})" ${lockedAttr} class="w-8 h-8 rounded-lg bg-white border border-gray-200 hover:bg-red-50 text-gray-500 hover:text-red-500${lockedButtonClass}" title="删除章节">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <div class="industry-report-outline-subsections divide-y divide-gray-100 bg-white">
                ${(section.subsections || []).map((sub, subIndex) => {
                    const outlineId = sub.outline_id || `${section.level1_id || `S${sectionIndex + 1}`}.${subIndex + 1}`;
                    const coordinated = isIndustryReportSubsectionCoordinated(outlineId);
                    return `
                    <div class="grid grid-cols-[28px_48px_minmax(0,1fr)_minmax(88px,auto)] items-center gap-2 px-4 py-2 transition-colors"
                         data-report-subsection="${subIndex}"
                         data-report-subsection-original-index="${subIndex}"
                         ondragleave="handleIndustryReportOutlineDragLeave(event)"
                         ondragover="handleIndustryReportOutlineDragOver(event)"
                         ondrop="handleIndustryReportOutlineDrop(event, ${sectionIndex})">
                        <span class="industry-report-outline-drag-handle text-center text-slate-300${lockedDragClass}"
                              ${lockedDragAttr}
                              ondragstart="handleIndustryReportOutlineDragStart(event, ${sectionIndex}, ${subIndex})"
                              ondragend="handleIndustryReportOutlineDragEnd()"
                              title="拖动调整本章二级标题顺序">
                            <i class="fas fa-grip-vertical"></i>
                        </span>
                        <span class="text-xs font-semibold text-slate-500">${sectionIndex + 1}.${subIndex + 1}</span>
                        <input class="report-subsection-title min-w-0 bg-transparent px-2 py-1 text-sm font-medium text-slate-700 outline-none focus:bg-blue-50 focus:ring-2 focus:ring-blue-100 rounded${lockedInputClass}"
                               oninput="handleIndustryReportOutlineInput()"
                               ${lockedAttr}
                               value="${escapeIndustryReportHtml(sub.title || "")}">
                        <div class="flex items-center justify-end gap-2">
                            ${coordinated ? '<span class="industry-report-outline-coordinated">已统筹</span>' : ""}
                            <button onclick="removeIndustryReportSubsection(${sectionIndex}, ${subIndex})" ${lockedAttr} class="w-8 h-8 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-500${lockedButtonClass}" title="删除二级标题">
                                <i class="fas fa-minus"></i>
                            </button>
                        </div>
                    </div>
                    `;
                }).join("")}
            </div>
        </div>
    `).join("");
    box.scrollTop = previousScrollTop;
    syncIndustryReportOutlineConfirmButton(outline);
    syncIndustryReportGenerateButton(outline);
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
}

function isIndustryReportSubsectionCoordinated(outlineId) {
    if (!outlineId) return false;
    const progress = industryReportWorkspace.coordinatorProgressById?.[outlineId];
    if (progress?.statusState === "done") return true;
    return (industryReportWorkspace.writingTasks || []).some(task => task?.outline_id === outlineId);
}

function updateIndustryReportOutlineSummary(outline = industryReportWorkspace.outline) {
    const summary = document.getElementById("industry-report-outline-summary");
    if (!summary) return;
    const level1Count = Array.isArray(outline) ? outline.length : 0;
    const level2Count = countIndustryReportSubsections(outline || []);
    summary.textContent = level1Count
        ? `已创建 ${level1Count} 个一级标题，${level2Count} 个二级标题`
        : "暂无大纲";
}

function toggleIndustryReportOutlineSection(sectionIndex) {
    const section = document.querySelector(`[data-report-section="${sectionIndex}"]`);
    if (!section) return;
    const body = section.querySelector(".industry-report-outline-subsections");
    const icon = section.querySelector(".industry-report-outline-toggle i");
    if (!body) return;
    const collapsed = body.classList.toggle("hidden");
    if (icon) {
        icon.classList.toggle("fa-chevron-down", !collapsed);
        icon.classList.toggle("fa-chevron-right", collapsed);
    }
}

function handleIndustryReportOutlineDragStart(event, sectionIndex, subIndex) {
    if (isIndustryReportOutlineLocked()) {
        event?.preventDefault?.();
        return;
    }
    const row = event.target?.closest?.("[data-report-subsection]");
    if (!row) return;
    row.classList.add("opacity-50", "bg-blue-50", "ring-2", "ring-blue-100");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", JSON.stringify({ sectionIndex, subIndex }));
}

function handleIndustryReportOutlineDragEnd() {
    clearIndustryReportOutlineDragStyles();
}

function handleIndustryReportOutlineDragOver(event) {
    if (isIndustryReportOutlineLocked()) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const row = event.target?.closest?.("[data-report-subsection]");
    if (!row) return;
    clearIndustryReportOutlineDropTargetStyles(row);
    const rect = row.getBoundingClientRect();
    const insertAfter = event.clientY > rect.top + rect.height / 2;
    row.classList.add("bg-blue-50/70");
    row.classList.add(insertAfter ? "border-b-2" : "border-t-2", "border-blue-400");
}

function handleIndustryReportOutlineDragLeave(event) {
    const row = event.target?.closest?.("[data-report-subsection]");
    if (!row || row.contains(event.relatedTarget)) return;
    clearIndustryReportOutlineDropTargetStyles(row);
}

function handleIndustryReportOutlineDrop(event, targetSectionIndex) {
    event.preventDefault();
    if (isIndustryReportOutlineLocked()) {
        clearIndustryReportOutlineDragStyles();
        return;
    }
    const targetRow = event.target?.closest?.("[data-report-subsection]");
    if (!targetRow) return;
    let payload = {};
    try {
        payload = JSON.parse(event.dataTransfer.getData("text/plain") || "{}");
    } catch (_err) {
        payload = {};
    }
    if (payload.sectionIndex !== targetSectionIndex) return;
    const section = targetRow.closest("[data-report-section]");
    const sourceRow = section?.querySelector(`[data-report-subsection="${payload.subIndex}"]`);
    if (!section || !sourceRow || sourceRow === targetRow) return;

    const rect = targetRow.getBoundingClientRect();
    const insertAfter = event.clientY > rect.top + rect.height / 2;
    targetRow.parentNode.insertBefore(sourceRow, insertAfter ? targetRow.nextSibling : targetRow);
    clearIndustryReportOutlineDragStyles();

    const outline = readIndustryReportOutlineFromDom();
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

function clearIndustryReportOutlineDragStyles() {
    document.querySelectorAll("[data-report-subsection]").forEach(row => {
        row.classList.remove(
            "opacity-50",
            "bg-blue-50",
            "ring-2",
            "ring-blue-100",
            "bg-blue-50/70",
            "border-t-2",
            "border-b-2",
            "border-blue-400",
        );
    });
}

function clearIndustryReportOutlineDropTargetStyles(exceptRow = null) {
    document.querySelectorAll("[data-report-subsection]").forEach(row => {
        if (row === exceptRow) return;
        row.classList.remove("bg-blue-50/70", "border-t-2", "border-b-2", "border-blue-400");
    });
}

function handleIndustryReportOutlineInput() {
    if (isIndustryReportOutlineLocked()) {
        renderIndustryReportOutline(industryReportWorkspace.outline);
        return;
    }
    const outline = readIndustryReportOutlineFromDom();
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    syncIndustryReportOutlineConfirmButton(outline);
    syncIndustryReportGenerateButton(outline);
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
}

function readIndustryReportOutlineFromDom() {
    const sections = [];
    document.querySelectorAll("[data-report-section]").forEach((sectionEl, sectionIndex) => {
        const previous = industryReportWorkspace.outline[sectionIndex] || {};
        const title = sectionEl.querySelector(".report-section-title")?.value.trim();
        if (!title) return;
        const level1Id = previous.level1_id || `S${sectionIndex + 1}`;
        const subsections = [];
        sectionEl.querySelectorAll("[data-report-subsection]").forEach((subEl, subIndex) => {
            const originalSubIndex = Number(subEl.getAttribute("data-report-subsection-original-index"));
            const previousSub = previous.subsections?.[
                Number.isInteger(originalSubIndex) ? originalSubIndex : subIndex
            ] || {};
            const subTitle = subEl.querySelector(".report-subsection-title")?.value.trim();
            if (!subTitle) return;
            subsections.push({
                outline_id: previousSub.outline_id || `${level1Id}.${subIndex + 1}`,
                title: subTitle,
                generation_instruction: previousSub.generation_instruction || "",
                expected_words: previousSub.expected_words || 800,
            });
        });
        sections.push({
            ...previous,
            level1_id: level1Id,
            level1_title: title,
            section_type: "body",
            subsections,
        });
    });
    return sections;
}

function addIndustryReportSection() {
    if (isIndustryReportOutlineLocked()) return;
    const outline = readIndustryReportOutlineFromDom();
    const index = Math.max(0, ...outline.map(section =>
        Number(section.level1_id?.match(/^S(\d+)$/)?.[1]) || 0,
    )) + 1;
    outline.push({
        level1_id: `S${index}`,
        level1_title: "新增章节",
        section_type: "body",
        subsections: [{ outline_id: `S${index}.1`, title: "新增二级标题", generation_instruction: "", expected_words: 800 }],
    });
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

function addIndustryReportSubsection(sectionIndex) {
    if (isIndustryReportOutlineLocked()) return;
    const outline = readIndustryReportOutlineFromDom();
    if (!outline[sectionIndex]) return;
    const next = Math.max(0, ...(outline[sectionIndex].subsections || []).map(subsection =>
        Number(subsection.outline_id?.match(/\.(\d+)$/)?.[1]) || 0,
    )) + 1;
    outline[sectionIndex].subsections.push({
        outline_id: `${outline[sectionIndex].level1_id}.${next}`,
        title: "新增二级标题",
        generation_instruction: "",
        expected_words: 800,
    });
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

function removeIndustryReportSection(sectionIndex) {
    if (isIndustryReportOutlineLocked()) return;
    const outline = readIndustryReportOutlineFromDom();
    outline.splice(sectionIndex, 1);
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

function removeIndustryReportSubsection(sectionIndex, subIndex) {
    if (isIndustryReportOutlineLocked()) return;
    const outline = readIndustryReportOutlineFromDom();
    if (!outline[sectionIndex]) return;
    outline[sectionIndex].subsections.splice(subIndex, 1);
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

async function startIndustryReportRun() {
    const coordinated = await prepareIndustryReportTasks();
    if (coordinated?.report_scope?.status === "incomplete") {
        setIndustryReportStatus("研究范围确认未完成，已保留检索资料，请查看具体原因。", "error");
        await saveIndustryReportHistory({silent: true});
        return;
    }
    if (coordinated?.status === "success") await startIndustryReportGeneration();
}

async function prepareIndustryReportTasks() {
    const formValues = getIndustryReportFormValues();
    const title = industryReportWorkspace.reportScope?.effective_title || industryReportWorkspace.taskCard?.selected_title || industryReportWorkspace.reportTitle || formValues.title;
    const effectivePrompt = industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || title;
    const reportIndustry = industryReportWorkspace.taskCard ? industryReportWorkspace.industry : formValues.industry;
    const useGraph = industryReportWorkspace.taskCard?.use_graph !== false;
    const useExternalRag = industryReportWorkspace.taskCard?.use_external_rag !== false;
    industryReportWorkspace.outline = readIndustryReportOutlineFromDom();
    if (!title) {
        setIndustryReportStatus("请先输入报告标题", "error");
        return null;
    }
    if (!countIndustryReportSubsections(industryReportWorkspace.outline)) {
        setIndustryReportStatus("请先生成或填写至少一个二级标题", "error");
        return null;
    }
    setIndustryReportBusy(true);
    clearIndustryReportStepDone(["coordinator", "body", "review"]);
    clearIndustryReportStepTiming(["coordinator", "body", "review"]);
    setIndustryReportStage("coordinator", "正在检索资料并生成写作任务");
    industryReportWorkspace.selectedAgentStep = "coordinator";
    startIndustryReportStepTiming("coordinator");
    industryReportWorkspace.outlineLocked = true;
    industryReportWorkspace.coordinatorProgressById = {};
    industryReportWorkspace.coordinatorTotal = countIndustryReportSubsections(industryReportWorkspace.outline);
    industryReportWorkspace.writingTasks = [];
    industryReportWorkspace.coordination = null;
    renderIndustryReportOutline(industryReportWorkspace.outline);
    try {
        const data = await streamIndustryReportCoordinator({
            user_prompt: effectivePrompt,
            report_title: title,
            industry: reportIndustry,
            outline: industryReportWorkspace.outline,
            top_k: getIndustryReportNumber("industry-report-top-k", 10),
            max_workers: getIndustryReportNumber("industry-report-coordinator-workers", 3),
            use_graph: useGraph,
            use_external_rag: useExternalRag,
        });
        industryReportWorkspace.userPrompt = effectivePrompt;
        industryReportWorkspace.reportTitle = data.report_scope?.effective_title || title;
        industryReportWorkspace.industry = reportIndustry;
        industryReportWorkspace.writingTasks = data.writing_tasks || [];
        industryReportWorkspace.coordination = data.coordination || null;
        if (Array.isArray(data.final_outline)) {
            industryReportWorkspace.outline = normalizeIndustryReportOutline(data.final_outline);
            renderIndustryReportOutline(industryReportWorkspace.outline);
        }
        industryReportWorkspace.adjustmentNotes = Array.isArray(data.adjustment_notes) ? data.adjustment_notes : [];
        industryReportWorkspace.references = Array.isArray(data.references) ? data.references : [];
        appendIndustryReportWarnings(data.warnings);
        renderIndustryReportOutline(industryReportWorkspace.outline);
        renderIndustryReportProgress([
            { key: "outline", title: "推荐大纲", status: "done", detail: `${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题` },
            { key: "coordinator", title: "写作任务", status: "done", detail: industryReportCoordinatorCompletionText(data) },
            { key: "body", title: "正文生成", status: "pending", detail: "等待开始" },
        ]);
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        markIndustryReportStepDone("coordinator");
        setIndustryReportStage("coordinator", industryReportCoordinatorCompletionText(data));
        setIndustryReportRequirementSubmittedStatus();
        return data;
    } catch (err) {
        setIndustryReportStage("error", "写作任务生成失败");
        setIndustryReportStatus(`写作任务生成失败：${err.message}`, "error");
        return null;
    } finally {
        setIndustryReportBusy(false);
    }
}

async function streamIndustryReportCoordinator(payload) {
    let completedPayload = null;
    await readIndustryReportSseStream("/api/report/coordinator/stream", payload, event => {
        const result = handleIndustryReportCoordinatorStreamEvent(event);
        if (event.event === "completed") completedPayload = result || event;
        if (event.event === "error") throw new Error(event.message || "写作任务生成失败");
    });
    if (!completedPayload) throw new Error("统筹任务流未返回完成事件");
    return completedPayload;
}

function handleIndustryReportCoordinatorStreamEvent(event) {
    const eventName = event?.event;
    if (eventName === "started") {
        industryReportWorkspace.coordinatorTotal = Math.max(
            getIndustryReportCoordinatorTotal(),
            Number(event.total) || 0,
        );
        setIndustryReportStage("coordinator", `统筹任务已启动：共 ${industryReportWorkspace.coordinatorTotal || 0} 个任务`);
        renderIndustryReportFlowSteps("coordinator");
        return event;
    }
    if (eventName === "retrieval_progress") {
        const labels = {planning: "正在规划检索问题", retrieving: "正在检索资料", assessing: "正在评估证据支持", follow_up: "正在针对证据缺口补查", retrieval_completed: "资料检索与评估已结束"};
        const text = labels[event.phase] || "正在处理章节资料";
        updateIndustryReportCoordinatorProgress(event, text, "active");
        setIndustryReportStage("coordinator", `${text}：${event.title || event.outline_id || "当前小节"}`);
        return event;
    }
    if (eventName === "task_started") {
        updateIndustryReportCoordinatorProgress(event, "检索统筹中", "active");
        setIndustryReportStage("coordinator", `正在统筹：${event.title || event.outline_id || "写作任务"}`);
        return event;
    }
    if (eventName === "task_completed" || eventName === "task_failed") {
        const isSuccess = eventName === "task_completed";
        upsertIndustryReportWritingTask(event, Number.isInteger(event.index) ? event.index : undefined);
        updateIndustryReportCoordinatorProgress(event, isSuccess ? "初稿任务已生成" : "失败", isSuccess ? "done" : "failed");
        setIndustryReportStage(
            "coordinator",
            `${isSuccess ? "初稿任务已生成" : "统筹失败"}：${event.title || event.outline_id || "写作任务"}`,
        );
        return event;
    }
    if (eventName === "coordination_started") {
        setIndustryReportStage("coordinator", "正在协调全报告小节分工");
        return event;
    }
    if (eventName === "coordination_completed") {
        industryReportWorkspace.coordination = event.coordination || null;
        appendIndustryReportWarnings(event.warnings);
        setIndustryReportStage("coordinator", industryReportCoordinationText(industryReportWorkspace.coordination));
        return event;
    }
    if (eventName === "completed") {
        industryReportWorkspace.writingTasks = event.writing_tasks || industryReportWorkspace.writingTasks || [];
        industryReportWorkspace.coordination = event.coordination || industryReportWorkspace.coordination || null;
        if (Array.isArray(event.final_outline)) {
            industryReportWorkspace.outline = normalizeIndustryReportOutline(event.final_outline);
            renderIndustryReportOutline(industryReportWorkspace.outline);
        }
        industryReportWorkspace.adjustmentNotes = Array.isArray(event.adjustment_notes) ? event.adjustment_notes : [];
        industryReportWorkspace.coordinatorTotal = Math.max(
            getIndustryReportCoordinatorTotal(),
            Number(event.total) || 0,
        );
        industryReportWorkspace.references = Array.isArray(event.references) ? event.references : [];
        appendIndustryReportWarnings(event.warnings);
        renderIndustryReportFlowSteps("coordinator");
        setIndustryReportStage("coordinator", industryReportCoordinatorCompletionText(event));
        return event;
    }
    return event;
}

async function startIndustryReportGeneration() {
    industryReportWorkspace.outline = readIndustryReportOutlineFromDom();
    if (!hasIndustryReportOutline(industryReportWorkspace.outline)) {
        syncIndustryReportGenerateButton(industryReportWorkspace.outline);
        setIndustryReportStatus("请先生成或填写至少一个二级标题", "error");
        return;
    }
    if (!hasConfirmedIndustryReportOutline()) {
        syncIndustryReportGenerateButton(industryReportWorkspace.outline);
        setIndustryReportStatus("请先确认大纲并生成写作任务", "error");
        return;
    }
    const formValues = getIndustryReportFormValues();
    const title = industryReportWorkspace.reportScope?.effective_title || industryReportWorkspace.taskCard?.selected_title || industryReportWorkspace.reportTitle || formValues.title;
    const effectivePrompt = industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || title;
    const reportIndustry = industryReportWorkspace.taskCard ? industryReportWorkspace.industry : formValues.industry;
    setIndustryReportBusy(true);
    clearIndustryReportStepDone(["body", "review"]);
    clearIndustryReportStepTiming(["body", "review"]);
    setIndustryReportStage("body", "正在生成正文");
    industryReportWorkspace.selectedAgentStep = "body";
    startIndustryReportStepTiming("body");
    industryReportWorkspace.bodyProgressById = {};
    industryReportWorkspace.bodyTotal = industryReportWorkspace.writingTasks.length;
    industryReportWorkspace.bodySections = [];
    renderIndustryReportProgress(buildIndustryReportTaskProgress("generating"));
    try {
        const data = await streamIndustryReportBody({
            user_prompt: effectivePrompt,
            report_title: title,
            industry: reportIndustry,
            writing_tasks: industryReportWorkspace.writingTasks,
            references: industryReportWorkspace.references || [],
            max_workers: getIndustryReportNumber("industry-report-workers", 3),
        });
        industryReportWorkspace.bodySections = normalizeIndustryReportBodySections(data.body_sections || []);
        industryReportWorkspace.references = mergeIndustryReportReferences(
            industryReportWorkspace.references,
            Array.isArray(data.references) ? data.references : [],
        );
        appendIndustryReportWarnings(data.warnings);
        try {
            setIndustryReportStage("body", "正文已生成，正在生成摘要");
            industryReportWorkspace.abstractText = await generateIndustryReportSummaryForWord(title, industryReportWorkspace.bodySections);
        } catch (summaryErr) {
            industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
            industryReportWorkspace.deliveryStatus = "incomplete";
            industryReportWorkspace.deliveryReasons = [];
            throw summaryErr;
        }
        await prepareIndustryReportDownload(title, industryReportWorkspace.bodySections);
        renderIndustryReportProgress(buildIndustryReportTaskProgress("generated", industryReportWorkspace.bodySections));
        renderIndustryReportPreview();
        void saveIndustryReportHistory({ silent: true });
        if (hasIncompleteIndustryReportBodySections(industryReportWorkspace.bodySections)) {
            setIndustryReportStage("body", "正文部分生成完成，但仍有空小节");
            setIndustryReportStatus("部分正文已生成，请补齐空小节后再导出 Word", "error");
            return;
        }
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        markIndustryReportStepDone("coordinator");
        markIndustryReportStepDone("body");
        industryReportWorkspace.selectedAgentStep = "review";
        setIndustryReportStage("done", industryReportWorkspace.deliveryStatus === "completed" ? "报告与 Word 已完成" : "报告已生成，仍有未完成项");
        setIndustryReportRequirementSubmittedStatus();
    } catch (err) {
        renderIndustryReportProgress(buildIndustryReportTaskProgress("failed"));
        setIndustryReportStage("error", "正文生成失败");
        setIndustryReportStatus(`正文生成失败：${err.message}`, "error");
    } finally {
        setIndustryReportBusy(false);
    }
}

async function streamIndustryReportBody(payload) {
    let completedPayload = null;
    await readIndustryReportSseStream("/api/report/body/stream", payload, event => {
        const result = handleIndustryReportBodyStreamEvent(event);
        if (event.event === "completed") completedPayload = result || event;
        if (event.event === "error") throw new Error(event.message || "正文生成失败");
    });
    if (!completedPayload) throw new Error("正文生成流未返回完成事件");
    return completedPayload;
}

async function readIndustryReportSseStream(path, payload, onEvent) {
    payload = withIndustryReportRuntime(payload);
    const resp = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
    });
    if (!resp.ok || !resp.body) {
        let data = {};
        try {
            data = await resp.json();
        } catch (_err) {
            data = {};
        }
        throw new Error(data.message || `HTTP ${resp.status}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
        const {value, done} = await reader.read();
        if (value) {
            buffer += decoder.decode(value, {stream: !done});
            const events = buffer.split("\n\n");
            buffer = events.pop() || "";
            for (const rawEvent of events) {
                const event = parseIndustryReportSseEvent(rawEvent);
                if (!event) continue;
                acceptIndustryReportRunResult(event);
                onEvent(event);
            }
        }
        if (done) break;
    }
    if (buffer.trim()) {
        const event = parseIndustryReportSseEvent(buffer);
        if (event) {
            acceptIndustryReportRunResult(event);
            onEvent(event);
        }
    }
}

function parseIndustryReportSseEvent(rawEvent) {
    const dataLines = String(rawEvent || "")
        .split(/\r?\n/)
        .filter(line => line.startsWith("data:"))
        .map(line => line.slice(5).trimStart());
    if (!dataLines.length) return null;
    try {
        return JSON.parse(dataLines.join("\n"));
    } catch (err) {
        return null;
    }
}

function handleIndustryReportBodyStreamEvent(event) {
    const eventName = event?.event;
    if (eventName === "started") {
        industryReportWorkspace.bodyTotal = Math.max(
            getIndustryReportBodyTotal(),
            Number(event.total) || 0,
        );
        setIndustryReportStage("body", `正文生成已启动：共 ${industryReportWorkspace.bodyTotal || 0} 个小节，并发 ${event.max_workers || 1}`);
        renderIndustryReportFlowSteps("body");
        return event;
    }
    if (eventName === "section_started") {
        updateIndustryReportBodyProgress(event, "生成中", "active");
        setIndustryReportStage("body", `正在生成：${event.title || event.outline_id || "正文小节"}`);
        return event;
    }
    if (eventName === "section_completed" || eventName === "section_failed") {
        const isSuccess = eventName === "section_completed" && event.status === "success";
        const section = normalizeIndustryReportBodySections([event])[0];
        upsertIndustryReportBodySection(section, Number.isInteger(event.index) ? event.index : undefined);
        appendIndustryReportWarnings(section.warnings);
        updateIndustryReportBodyProgress(event, isSuccess ? "已生成" : "失败", isSuccess ? "done" : "failed");
        renderIndustryReportProgress(buildIndustryReportTaskProgress("generating", industryReportWorkspace.bodySections));
        renderIndustryReportPreview();
        setIndustryReportStage(
            "body",
            `${isSuccess ? "已生成" : "生成失败"}：${event.title || event.outline_id || "正文小节"}`,
        );
        return event;
    }
    if (eventName === "review_started") {
        setIndustryReportStage("body", "正在核对关键事实、引用与重复内容");
        return event;
    }
    if (eventName === "review_checked") {
        setIndustryReportStage("body", `已检查重复内容，发现 ${event.issue_count || 0} 处需要处理`);
        return event;
    }
    if (eventName === "review_section_completed") {
        setIndustryReportStage("body", event.status === "success" ? "正在应用正文局部修正" : "部分正文精简未采用");
        return event;
    }
    if (eventName === "completed") {
        industryReportWorkspace.bodySections = normalizeIndustryReportBodySections(event.body_sections || industryReportWorkspace.bodySections || []);
        industryReportWorkspace.review = event.review || null;
        industryReportWorkspace.adjustmentNotes = [
            ...(industryReportWorkspace.adjustmentNotes || []).filter(note => note.kind !== "body_edit"),
            ...(Array.isArray(event.adjustment_notes) ? event.adjustment_notes : []),
        ];
        industryReportWorkspace.bodyTotal = Math.max(
            getIndustryReportBodyTotal(),
            Number(event.total) || 0,
        );
        appendIndustryReportWarnings(event.warnings);
        appendIndustryReportWarnings(industryReportWorkspace.bodySections.flatMap(section => section.warnings || []));
        renderIndustryReportProgress(buildIndustryReportTaskProgress("generated", industryReportWorkspace.bodySections));
        renderIndustryReportPreview();
        setIndustryReportStage("body", `正文生成完成：已生成 ${event.success_count || 0} / 共 ${industryReportWorkspace.bodyTotal || industryReportWorkspace.bodySections.length} 个小节`);
        return event;
    }
    return event;
}

function updateIndustryReportBodyProgress(event, status, statusState) {
    const key = event.outline_id || (Number.isInteger(event.index) ? `task_${event.index + 1}` : "");
    if (!key) return;
    industryReportWorkspace.bodyProgressById = industryReportWorkspace.bodyProgressById || {};
    industryReportWorkspace.bodyProgressById[key] = {
        status,
        statusState,
    };
    renderIndustryReportFlowSteps("body");
}

function updateIndustryReportCoordinatorProgress(event, status, statusState) {
    const key = event.outline_id || (Number.isInteger(event.index) ? `task_${event.index + 1}` : "");
    if (!key) return;
    industryReportWorkspace.coordinatorProgressById = industryReportWorkspace.coordinatorProgressById || {};
    industryReportWorkspace.coordinatorProgressById[key] = {
        status,
        statusState,
    };
    renderIndustryReportOutline(industryReportWorkspace.outline);
}

function upsertIndustryReportWritingTask(task, index) {
    if (!task || !task.outline_id) return;
    const tasks = Array.isArray(industryReportWorkspace.writingTasks)
        ? [...industryReportWorkspace.writingTasks]
        : [];
    const existingIndex = tasks.findIndex(item => item?.outline_id === task.outline_id);
    if (existingIndex >= 0) {
        tasks[existingIndex] = task;
    } else if (Number.isInteger(index) && index >= 0) {
        tasks[index] = task;
    } else {
        tasks.push(task);
    }
    industryReportWorkspace.writingTasks = tasks.filter(Boolean);
}

function upsertIndustryReportBodySection(section, index) {
    if (!section || !section.outline_id) return;
    const sections = Array.isArray(industryReportWorkspace.bodySections)
        ? [...industryReportWorkspace.bodySections]
        : [];
    const existingIndex = sections.findIndex(item => item?.outline_id === section.outline_id);
    if (existingIndex >= 0) {
        sections[existingIndex] = section;
    } else if (Number.isInteger(index) && index >= 0) {
        sections[index] = section;
    } else {
        sections.push(section);
    }
    industryReportWorkspace.bodySections = sections.filter(Boolean);
}

function cleanIndustryReportMalformedCitations(value) {
    const text = String(value || "");
    const markers = [...new Set(text.match(/\[citation:\d+\]/g) || [])];
    return { text: text.replace(/\[citation:\d+\]/g, ""), warnings: markers.length ? [{
        stage: "citation_validation",
        message: "已移除异常引用标记，未推定资料编号，请核对该句证据。",
        malformed_citation_markers: markers,
    }] : [] };
}

function normalizeIndustryReportBodySections(sections) {
    return (sections || []).map((section, index) => {
        const cleaned = cleanIndustryReportMalformedCitations(section.body_text || section.text || "");
        return {
            ...section,
            outline_id: section.outline_id || `section_${index + 1}`,
            status: section.status || "success",
            body_text: preserveIndustryReportVerifiedText(section, normalizeIndustryReportParagraphText(cleaned.text)),
            ...(section.claim_verification ? {claim_verification: currentIndustryReportVerification(section, preserveIndustryReportVerifiedText(section, normalizeIndustryReportParagraphText(cleaned.text)))} : {}),
            warnings: [...(section.warnings || []), ...cleaned.warnings],
            graph_evidence_blocks: section.graph_evidence_blocks || [],
            external_evidence_blocks: section.external_evidence_blocks || [],
            citation_ids: Array.isArray(section.citation_ids) ? section.citation_ids : [],
        };
    });
}

function hasIncompleteIndustryReportBodySections(sections) {
    return !Array.isArray(sections) || !sections.length
        || sections.some(section => !String(section?.body_text || "").trim());
}

function buildIndustryReportTaskProgress(status, sections = []) {
    const byId = new Map((sections || []).map(item => [item.outline_id, item]));
    const sourceTasks = (industryReportWorkspace.writingTasks || []).length
        ? industryReportWorkspace.writingTasks
        : (sections || []).map(section => ({
            outline_id: section.outline_id,
            title: section.title,
            parent_level1_title: section.parent_level1_title,
        }));
    return sourceTasks.map((task, index) => {
        const generated = byId.get(task.outline_id);
        const failed = generated && generated.status !== "success";
        return {
            key: task.outline_id || `task_${index + 1}`,
            title: task.title || `章节 ${index + 1}`,
            parent: task.parent_level1_title || "",
            status: failed ? "failed" : generated ? "done" : status,
            detail: failed ? (generated.message || "生成失败") : generated ? "已生成" : "生成中",
        };
    });
}

function renderIndustryReportProgress(items) {
    const box = document.getElementById("industry-report-progress");
    if (!box) return;
    if (!items || !items.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">生成大纲后显示流程进度</div>';
        return;
    }
    box.innerHTML = items.map(item => {
        const style = getIndustryReportProgressStyle(item.status);
        return `
            <div class="border ${style.border} ${style.bg} rounded-lg px-3 py-2">
                <div class="flex items-center gap-3">
                    <div class="w-7 h-7 rounded-full ${style.icon} flex items-center justify-center text-xs shrink-0">${style.html}</div>
                    <div class="min-w-0 flex-1">
                        <div class="font-medium text-gray-800 truncate">${escapeIndustryReportHtml(item.title || "")}</div>
                        <div class="text-xs ${style.text} truncate">${escapeIndustryReportHtml(item.detail || item.parent || "")}</div>
                    </div>
                    <span class="text-xs font-semibold ${style.text}">${style.label}</span>
                </div>
            </div>
        `;
    }).join("");
}

function getIndustryReportProgressStyle(status) {
    const map = {
        pending: { border: "border-gray-200", bg: "bg-gray-50", icon: "bg-gray-200 text-gray-500", text: "text-gray-500", label: "等待", html: '<i class="fas fa-clock"></i>' },
        generating: { border: "border-blue-200", bg: "bg-blue-50", icon: "bg-blue-500 text-white", text: "text-blue-700", label: "进行中", html: '<i class="fas fa-spinner fa-spin"></i>' },
        done: { border: "border-emerald-200", bg: "bg-emerald-50", icon: "bg-emerald-500 text-white", text: "text-emerald-700", label: "完成", html: '<i class="fas fa-check"></i>' },
        generated: { border: "border-emerald-200", bg: "bg-emerald-50", icon: "bg-emerald-500 text-white", text: "text-emerald-700", label: "完成", html: '<i class="fas fa-check"></i>' },
        failed: { border: "border-red-200", bg: "bg-red-50", icon: "bg-red-500 text-white", text: "text-red-700", label: "失败", html: '<i class="fas fa-exclamation"></i>' },
    };
    return map[status] || map.pending;
}

function renderIndustryReportPreview() {
    renderIndustryReportDeliveryDetails();
    const box = document.getElementById("industry-report-preview");
    if (!box) return;
    renderIndustryReportPreviewNav();
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    industryReportWorkspace.reportTitle = title;
    const target = industryReportWorkspace.previewTarget || { type: "all", key: "" };
    if (target.type === "abstract" && !industryReportWorkspace.bodySections.length) {
        box.innerHTML = `
            <div class="border-b border-gray-200 pb-4">
                <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
            </div>
            ${renderIndustryReportAbstractBlock() || '<div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">暂无摘要内容</div>'}
        `;
        return;
    }
    if (target.type === "references" && !industryReportWorkspace.bodySections.length) {
        box.innerHTML = `
            <div class="border-b border-gray-200 pb-4">
                <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
            </div>
            ${renderIndustryReportReferences({ standalone: true })}
        `;
        return;
    }
    if (!industryReportWorkspace.bodySections.length) {
        box.innerHTML = `
            <div class="border-b border-gray-200 pb-4">
                <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
            </div>
            <div class="text-gray-400">暂无正文内容</div>
        `;
        return;
    }
    if (target.type === "abstract") {
        box.innerHTML = `
            <div class="border-b border-gray-200 pb-4">
                <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
            </div>
            ${renderIndustryReportAbstractBlock() || '<div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">暂无摘要内容</div>'}
        `;
        return;
    }
    if (target.type === "references") {
        box.innerHTML = `
            <div class="border-b border-gray-200 pb-4">
                <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
            </div>
            ${renderIndustryReportReferences({ standalone: true })}
        `;
        return;
    }
    const groups = groupIndustryReportBodySections();
    const visibleGroups = filterIndustryReportPreviewGroups(groups);
    box.innerHTML = `
        <div class="border-b border-gray-200 pb-4">
            <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
        </div>
        ${target.type === "section" ? "" : renderIndustryReportAbstractBlock()}
        ${visibleGroups.length ? visibleGroups.map((group, groupIndex) => `
            <article class="border-b border-gray-200 pb-4 last:border-b-0">
                <h2 class="text-xl font-bold text-gray-900 mb-3">${escapeIndustryReportHtml(group.displayNumber || String(groupIndex + 1))}. ${escapeIndustryReportHtml(group.title)}</h2>
                <div class="space-y-4">
                    ${group.children.map((section, sectionIndex) => renderIndustryReportBodySection(section, group.displayNumber || groupIndex + 1, section.displayNumber || sectionIndex + 1)).join("")}
                </div>
            </article>
        `).join("") : '<div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">当前标题暂无正文内容。</div>'}
        ${target.type === "all" ? renderIndustryReportMethodNotes() : ""}
        ${renderIndustryReportReferences()}
    `;
}

function renderIndustryReportAdjustmentNotes() {
    const sections = industryReportWorkspace.bodySections || [];
    const notes = [...(industryReportWorkspace.adjustmentNotes || []), ...buildIndustryReportAgenticNotes(),
        ...(industryReportWorkspace.warnings || []).map(warning => ({reason: warning.message || ""}))];
    const reasons = [...new Set(notes.map(note => note.reason).filter(Boolean))];
    if (!sections.length && !reasons.length) return "";
    const completed = industryReportWorkspace.deliveryStatus === "completed";
    const pending = completed ? [] : (industryReportWorkspace.deliveryReasons || []);
    return `<aside class="rounded border ${completed ? "border-blue-200 bg-blue-50" : "border-amber-200 bg-amber-50"} p-4 text-sm">
        <h2 class="font-semibold">生成与交付核对</h2>
        <p class="mt-1">${completed ? "本次生成与核对已完成。" : "报告已生成，核对尚未全部完成。请查看待核对事项后再对外使用。"}</p>
        ${pending.length ? `<ul class="mt-2 list-disc pl-5">${pending.map(reason => `<li>${escapeIndustryReportHtml(reason)}</li>`).join("")}</ul>` : ""}
        <p class="mt-1 text-xs text-gray-600">以下为生成与核对记录，不写入正式报告。</p>
        ${reasons.length ? `<details class="mt-2"><summary class="cursor-pointer font-medium">查看待核对事项与生成记录</summary><ul class="mt-2 list-disc pl-5 space-y-1">${reasons.map(reason => `<li>${escapeIndustryReportHtml(reason)}</li>`).join("")}</ul></details>` : ""}
        <details class="mt-2"><summary class="cursor-pointer font-medium">查看逐节核对明细</summary>${sections.map(section => `<div data-report-agentic="${escapeIndustryReportHtml(section.outline_id)}"><h3 class="mt-3 font-medium">${escapeIndustryReportHtml(section.title || section.outline_id)}</h3>${renderIndustryReportAgenticDetails(section)}</div>`).join("")}</details>
    </aside>`;
}

function renderIndustryReportDeliveryDetails() {
    const box = document.getElementById("industry-report-delivery-details");
    if (box) box.innerHTML = renderIndustryReportAdjustmentNotes();
}

function buildIndustryReportMethodNotes() {
    const notes = [], scope = industryReportWorkspace.reportScope;
    const boundary = scope?.status === "completed" ? (scope.boundary || {}) : {};
    if (boundary.subjects?.length) notes.push(`研究范围：${boundary.subjects.join("；")}。`);
    if (boundary.period) notes.push(`观察时期：${boundary.period}。`);
    const usedIds = new Set((industryReportWorkspace.bodySections || []).flatMap(section => section.citation_ids || []));
    const dates = (industryReportWorkspace.references || []).filter(ref => usedIds.has(ref.citation_id))
        .map(ref => String(ref.retrieved_at || "").slice(0, 10)).filter(value => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value))).sort();
    notes.push(dates.length ? `资料检索截止日期：${dates[dates.length - 1]}。各来源的发布日期与检索时间见参考资料。`
        : "资料来源：依据本报告所引公开资料开展分析，来源信息见参考资料及对应正文。");
    notes.push("统计与判断口径：数据的统计对象、期间及测算条件以对应正文和引文为准；预测、计划与已实现情况分别标注，企业案例不直接代表行业整体。");
    return notes;
}

function renderIndustryReportMethodNotes() {
    return `<section class="border-t border-gray-200 pt-4"><h2 class="text-xl font-bold mb-3">资料与方法说明</h2>${buildIndustryReportMethodNotes().map(note => `<p class="mt-2">${escapeIndustryReportHtml(note)}</p>`).join("")}</section>`;
}

function filterIndustryReportPreviewGroups(groups) {
    const target = industryReportWorkspace.previewTarget || { type: "all", key: "" };
    return (groups || []).map((group, groupIndex) => {
        const groupKey = getIndustryReportPreviewGroupKey(group.title, groupIndex);
        const displayNumber = String(groupIndex + 1);
        const children = (group.children || []).map((section, sectionIndex) => ({
            ...section,
            displayNumber: sectionIndex + 1,
        }));
        return { ...group, key: groupKey, displayNumber, children };
    }).filter(group => {
        if (target.type === "all" || !target.key) return true;
        if (target.type === "group") return group.key === target.key;
        if (target.type === "section") {
            group.children = group.children.filter(section => section.outline_id === target.key);
            return group.children.length > 0;
        }
        return true;
    });
}

function renderIndustryReportPreviewNav() {
    const box = document.getElementById("industry-report-preview-nav");
    if (!box) return;
    const outline = Array.isArray(industryReportWorkspace.outline) ? industryReportWorkspace.outline : [];
    if (!outline.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">生成大纲后显示标题导航</div>';
        return;
    }
    const target = industryReportWorkspace.previewTarget || { type: "all", key: "" };
    const allActive = target.type === "all" || !target.type;
    const abstractActive = target.type === "abstract";
    const referencesActive = target.type === "references";
    const generatedSectionIds = new Set((industryReportWorkspace.bodySections || [])
        .filter(section => section?.outline_id && String(section.body_text || "").trim())
        .map(section => section.outline_id));
    box.innerHTML = `
        <button type="button"
                onclick="selectIndustryReportPreviewTarget('all', '')"
                class="w-full rounded-lg border ${allActive ? "border-blue-200 bg-white text-blue-700 font-semibold" : "border-blue-100 bg-white/70 text-slate-600 hover:bg-white hover:text-blue-700"} px-3 py-2 text-left text-sm">
            <i class="fas fa-file-lines mr-2"></i>整篇报告
        </button>
        <button type="button"
                onclick="selectIndustryReportPreviewTarget('abstract', '')"
                class="w-full rounded-lg border ${abstractActive ? "border-amber-200 bg-amber-50 text-amber-700 font-semibold" : "border-blue-100 bg-white/70 text-slate-600 hover:bg-white hover:text-amber-700"} px-3 py-2 text-left text-sm">
            <i class="fas fa-align-left mr-2"></i>摘要
        </button>
    ` + outline.map((section, sectionIndex) => {
        const children = Array.isArray(section.subsections) ? section.subsections : [];
        const groupKey = getIndustryReportPreviewGroupKey(section.level1_title || `章节 ${sectionIndex + 1}`, sectionIndex);
        const groupActive = target.type === "group" && target.key === groupKey;
        return `
            <div class="rounded-lg border border-blue-100 bg-white overflow-hidden">
                <button type="button"
                        onclick="selectIndustryReportPreviewTarget('group', '${escapeIndustryReportJs(groupKey)}')"
                        class="w-full flex items-center gap-2 px-3 py-2 text-left text-sm font-bold ${groupActive ? "bg-blue-100 text-blue-900" : "bg-blue-50 text-blue-900 hover:bg-blue-100"}">
                    <span class="inline-flex w-5 h-5 items-center justify-center rounded-full bg-blue-100 text-xs text-blue-700">${sectionIndex + 1}</span>
                    <span class="min-w-0 truncate">${escapeIndustryReportHtml(section.level1_title || `章节 ${sectionIndex + 1}`)}</span>
                </button>
                ${children.length ? `
                    <div class="space-y-1 px-3 py-2">
                        ${children.map((sub, subIndex) => {
                            const outlineId = sub.outline_id || `${section.level1_id || `S${sectionIndex + 1}`}.${subIndex + 1}`;
                            const active = target.type === "section" && target.key === outlineId;
                            const generated = generatedSectionIds.has(outlineId);
                            return `
                                <button type="button"
                                        onclick="selectIndustryReportPreviewTarget('section', '${escapeIndustryReportJs(outlineId)}')"
                                        class="w-full flex items-center gap-2 rounded px-2 py-1 text-left text-xs leading-5 transition ${active ? "bg-white text-blue-700 font-semibold shadow-sm" : "text-slate-500 hover:bg-white hover:text-blue-700"}">
                                    <span class="w-8 shrink-0 font-semibold">${sectionIndex + 1}.${subIndex + 1}</span>
                                    <span class="industry-report-preview-nav-title min-w-0 truncate ${generated ? "is-generated" : ""}">${escapeIndustryReportHtml(sub.title || `二级标题 ${subIndex + 1}`)}</span>
                                </button>
                            `;
                        }).join("")}
                    </div>
                ` : ""}
            </div>
        `;
    }).join("") + `
        <button type="button"
                onclick="selectIndustryReportPreviewTarget('references', '')"
                class="w-full rounded-lg border ${referencesActive ? "border-emerald-200 bg-emerald-50 text-emerald-700 font-semibold" : "border-blue-100 bg-white/70 text-slate-600 hover:bg-white hover:text-emerald-700"} px-3 py-2 text-left text-sm">
            <i class="fas fa-book-open mr-2"></i>参考资料
        </button>
    `;
}

function getIndustryReportPreviewGroupKey(title, index) {
    return `${index}:${String(title || "").trim()}`;
}

function selectIndustryReportPreviewTarget(type, key) {
    const nextType = type || "all";
    const nextKey = key || "";
    if (nextType === "section" && nextKey) {
        industryReportWorkspace.lastSectionPreviewKey = nextKey;
    }
    industryReportWorkspace.previewTarget = { type: nextType, key: nextKey };
    renderIndustryReportPreview();
}

function renderIndustryReportAbstractBlock() {
    const abstractText = (industryReportWorkspace.abstractText || "").trim();
    if (!abstractText) return "";
    return `
        <section class="rounded-lg border border-amber-100 bg-amber-50/60 p-4">
            <div class="flex items-center justify-between gap-3 mb-2">
                <h2 class="text-base font-bold text-gray-900">摘要</h2>
                <div class="flex items-center gap-2">
                    <span id="industry-report-abstract-count" class="text-xs text-amber-700">${countIndustryReportWords(abstractText)} 字</span>
                    <button onclick="refreshIndustryReportAbstract()" class="bg-white hover:bg-amber-50 text-amber-700 px-2.5 py-1.5 rounded-lg text-xs border border-amber-200 flex items-center gap-1.5">
                        <i class="fas fa-rotate"></i>
                        刷新摘要
                    </button>
                </div>
            </div>
            <div id="industry-report-abstract-editor"
                 contenteditable="true"
                 oninput="updateIndustryReportAbstractText(this)"
                 class="min-h-[72px] rounded-lg border border-transparent bg-white/70 px-4 py-3 text-sm leading-7 text-gray-800 focus:border-amber-300 focus:ring-2 focus:ring-amber-100 outline-none">
                ${renderIndustryReportParagraphs(abstractText)}
            </div>
        </section>
    `;
}

async function refreshIndustryReportAbstract() {
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
    industryReportWorkspace.deliveryStatus = "incomplete";
    industryReportWorkspace.deliveryReasons = [];
    syncIndustryReportBodySectionsFromDom();
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const bodySections = buildIndustryReportExportSections();
    if (!bodySections.length) {
        setIndustryReportStatus("请先生成正文后再刷新摘要", "error");
        return;
    }
    setIndustryReportStatus("正在根据当前正文刷新摘要...", "loading");
    try {
        industryReportWorkspace.abstractText = await generateIndustryReportSummaryForWord(title, bodySections);
        renderIndustryReportPreview();
        void saveIndustryReportHistory({ silent: true });
        setIndustryReportStatus("摘要已根据当前正文刷新", "success");
    } catch (err) {
        setIndustryReportStatus(`摘要刷新失败：${err.message}`, "error");
    }
}

function groupIndustryReportBodySections() {
    const groups = [];
    const groupByTitle = {};
    industryReportWorkspace.bodySections.forEach(section => {
        const title = section.parent_level1_title || "正文";
        if (!groupByTitle[title]) {
            groupByTitle[title] = { title, children: [] };
            groups.push(groupByTitle[title]);
        }
        groupByTitle[title].children.push(section);
    });
    return groups;
}

function renderIndustryReportBodySection(section, groupNumber, sectionNumber) {
    const graphCount = (section.graph_evidence_blocks || []).length;
    const externalCount = (section.external_evidence_blocks || []).length;
    const bodyText = normalizeIndustryReportParagraphText(section.body_text || "");
    return `
        <section class="group rounded-lg border border-transparent hover:border-blue-100 hover:bg-blue-50/30 p-2 -mx-2 transition" data-report-body-section="${escapeIndustryReportHtml(section.outline_id)}">
            <div class="flex items-start justify-between gap-3">
                <h3 class="text-base font-bold text-gray-900 leading-snug">${groupNumber}.${sectionNumber} ${escapeIndustryReportHtml(section.title || "")}</h3>
                <button onclick="openIndustryReportRewriteModal('${escapeIndustryReportJs(section.outline_id)}')" class="opacity-0 group-hover:opacity-100 w-8 h-8 rounded-lg border border-gray-200 bg-white text-gray-500 hover:text-blue-600 hover:border-blue-200 transition" title="重写此节">
                    <i class="fas fa-pen"></i>
                </button>
            </div>
            <div oninput="updateIndustryReportBodyText('${escapeIndustryReportJs(section.outline_id)}', getIndustryReportEditableText(this))"
                 contenteditable="true"
                 class="industry-report-body-editor mt-2 w-full min-h-[140px] leading-7 text-gray-800 bg-white border border-transparent hover:border-gray-200 focus:border-blue-300 focus:ring-2 focus:ring-blue-100 rounded-lg px-4 py-3 outline-none"
                 data-placeholder="可在这里手动修改正文内容">${renderIndustryReportParagraphs(bodyText, getIndustryReportSectionReferences(section))}</div>
            <div class="industry-report-section-count mt-1 text-right text-xs text-gray-400">${countIndustryReportWords(bodyText)} 字</div>
            <div class="mt-3 flex flex-wrap gap-2 text-xs">
                <span class="rounded-full bg-blue-50 text-blue-700 border border-blue-100 px-2 py-1">知识图谱资料 ${graphCount}</span>
                <span class="rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100 px-2 py-1">外部资料 ${externalCount}</span>
            </div>
            ${renderIndustryReportEvidenceDetails(section)}
        </section>
    `;
}

function updateIndustryReportBodyText(outlineId, value) {
    const cleaned = cleanIndustryReportMalformedCitations(value);
    const normalized = normalizeIndustryReportParagraphText(cleaned.text);
    appendIndustryReportWarnings(cleaned.warnings);
    showIndustryReportCitationValidationWarning(cleaned.warnings);
    industryReportWorkspace.bodySections = industryReportWorkspace.bodySections.map(section => {
        if (section.outline_id !== outlineId) return section;
        if (normalizeIndustryReportParagraphText(section.body_text) !== normalized) {
            industryReportWorkspace.abstractText = "";
            industryReportWorkspace.deliveryStatus = "incomplete";
            industryReportWorkspace.deliveryReasons = [];
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
            if (industryReportWorkspace.review) industryReportWorkspace.review = { ...industryReportWorkspace.review, status: "partial", claim_verification: {status: "needs_confirmation"} };
            const abstractEditor = document.getElementById("industry-report-abstract-editor");
            if (abstractEditor) abstractEditor.innerHTML = "";
        }
        return {
            ...section,
            claim_verification: currentIndustryReportVerification(section, preserveIndustryReportVerifiedText(section, normalized)),
            body_text: preserveIndustryReportVerifiedText(section, normalized),
            warnings: [...(section.warnings || []), ...cleaned.warnings],
            citation_ids: extractIndustryReportCitationIds(
                normalized,
                getIndustryReportSectionReferences(section),
            ),
        };
    });
    const sectionEl = Array.from(document.querySelectorAll("[data-report-body-section]"))
        .find(el => el.getAttribute("data-report-body-section") === outlineId);
    const countEl = sectionEl?.querySelector(".industry-report-section-count");
    if (countEl) countEl.textContent = `${countIndustryReportWords(normalized)} 字`;
    renderIndustryReportDeliveryDetails();
}

function updateIndustryReportAbstractText(el) {
    const value = normalizeIndustryReportParagraphText(getIndustryReportEditableText(el));
    industryReportWorkspace.abstractText = value;
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
    industryReportWorkspace.deliveryStatus = "incomplete";
    industryReportWorkspace.deliveryReasons = [];
    const countEl = document.getElementById("industry-report-abstract-count");
    if (countEl) countEl.textContent = `${countIndustryReportWords(value)} 字`;
    renderIndustryReportDeliveryDetails();
}

function getIndustryReportAgenticContext(section) {
    const task = (industryReportWorkspace.writingTasks || []).find(item => item.outline_id === section.outline_id) || {};
    const ownsPack = Object.prototype.hasOwnProperty.call(section, "evidence_pack");
    return {
        traces: [task.agentic_retrieval, ...(task.merged_agentic_retrievals || [])].filter(Boolean),
        packs: ownsPack
            ? [section.evidence_pack, ...(section.merged_evidence_packs || [])].filter(Boolean)
            : [task.evidence_pack, ...(task.merged_evidence_packs || [])].filter(Boolean),
        verification: currentIndustryReportVerification(section, section.body_text || ""),
    };
}

function preserveIndustryReportVerifiedText(section, text) {
    const original = section.claim_verification?.body_text;
    // Keep the checked original and offsets when only display whitespace differs.
    return typeof original === "string" && normalizeIndustryReportParagraphText(original) === normalizeIndustryReportParagraphText(text)
        ? original : text;
}

function currentIndustryReportVerification(section, bodyText) {
    const prior = section.claim_verification;
    if (prior && prior.body_text === bodyText) return prior;
    if (!prior) return null;
    return { status: "needs_confirmation", body_text: bodyText, claims: [], invalidated: true,
        reason: "正文已修改，原事实核对结果失效，需重新核对。" };
}

function buildIndustryReportExportSections() {
    return (industryReportWorkspace.bodySections || []).map(section => {
        const context = getIndustryReportAgenticContext(section);
        return { ...section, claim_verification: context.verification,
            evidence_pack: context.packs[0] || null, merged_evidence_packs: context.packs.slice(1) };
    });
}

function buildIndustryReportAgenticNotes() {
    const notes = [];
    const add = (section, kind, reason) => notes.push({kind, outline_ids: [section.outline_id], reason: `《${section.title || section.outline_id}》${reason}`});
    for (const section of industryReportWorkspace.bodySections || []) {
        const { packs, verification } = getIndustryReportAgenticContext(section);
        for (const pack of packs) {
            for (const requirement of pack.requirements || []) {
                if (requirement.status !== "supported") add(section, "agentic_evidence", `证据待确认：${requirement.requirement}；${requirement.reason || "尚无充分依据"}`);
            }
        }
        if (verification?.invalidated) add(section, "agentic_claim", verification.reason);
        else if (verification) {
            for (const claim of verification.claims || []) {
                if (!["supported", "not_factual"].includes(claim.status)) add(section, "agentic_claim", `事实待确认：${claim.quote}；${claim.reason || "核对未完成"}`);
            }
            if (verification.omitted_claim_count) add(section, "agentic_claim", `另有${verification.omitted_claim_count}项关键声明超出本次核对范围，仍需确认。`);
            if (verification.status === "needs_confirmation" && !(verification.claims || []).some(c => !["supported", "not_factual"].includes(c.status)) && !verification.omitted_claim_count) add(section, "agentic_claim", "事实核对仍需确认，不能视为已通过。");
        } else if (packs.length) add(section, "agentic_claim", "事实核对尚无结果，不能视为已通过。");
    }
    return notes.filter((note, index) => notes.findIndex(other => other.reason === note.reason) === index);
}

function renderIndustryReportAgenticDetails(section) {
    const { traces, packs, verification } = getIndustryReportAgenticContext(section);
    if (!traces.length && !packs.length && !verification) return "";
    const esc = escapeIndustryReportHtml;
    const labels = { not_factual: "研究方法或分析", supported: "有支持", insufficient: "支持不足", partial: "部分支持", unsupported: "不支持", conflicting: "存在冲突", unknown: "无法判断" };
    const gaps = packs.flatMap(pack => (pack.requirements || []).filter(r => r.status !== "supported"));
    const state = verification?.invalidated ? "正文已修改，需重新核对" : verification?.status === "completed" ? "关键事实核对已完成" : verification?.status === "not_needed" ? "未选出需核对的关键声明" : "关键事实待确认";
    const stops = {round_limit: "已达到一次补查上限", requirements_supported: "证据要求已获支持", no_new_evidence: "补查未获得新证据", no_new_query: "没有新的有效补查问题", retrieval_failed: "补查未完成", assessment_failed: "证据评估未完成", assessment_unavailable: "原文检索不可用", assessment_skipped: "未启用原文评估"};
    return `<aside class="mt-3 rounded-lg border border-amber-200 bg-amber-50/40 p-3 text-sm">
        <div class="font-semibold text-gray-800">资料与事实核对</div>
        <p class="mt-1 text-xs text-gray-600">${esc(state)}${gaps.length ? `；${gaps.length}项证据要求待确认` : ""}。核对仅针对本次提供的资料。</p>
        ${section.evidence_pack === null && section.original_body_text ? '<p class="mt-1 text-xs text-gray-600">本节已按重新选择的资料改写，原证据需求评估不再适用；以下查询为初始检索记录。</p>' : ""}
        ${traces.length ? `<details class="mt-2"><summary class="cursor-pointer font-medium">查看检索规划与补查记录</summary><div class="mt-2 space-y-2">${traces.map(trace => {
            const follow = trace.follow_up || {};
            const queries = [...(trace.plan?.sub_queries || []), ...(trace.follow_up_plan?.sub_queries || [])];
            return `<div class="rounded border border-gray-200 bg-white p-2">${trace.plan?.status === "fallback" ? '<p>规划未完成，使用章节查询。</p>' : ""}${["error", "partial"].includes(trace.status) ? '<p>部分资料检索未完成，保留已取得的资料。</p>' : ""}<ol class="list-decimal pl-5">${queries.map(q => `<li>${esc(q.question)}${q.reason ? `<span class="block text-xs text-gray-500">${esc(q.reason)}</span>` : ""}</li>`).join("")}</ol><p class="mt-2 text-xs">补查${Number(follow.rounds) || 0}轮、${Number(follow.query_count) || 0}个问题，新增${Number(follow.new_evidence_count) || 0}个片段。${esc(stops[follow.stop_reason] || "查询记录已保存")}</p></div>`;
        }).join("")}</div></details>` : ""}
        ${packs.length ? `<details class="mt-2" ${gaps.length ? "open" : ""}><summary class="cursor-pointer font-medium">证据要求与写作边界</summary><ul class="mt-2 space-y-2">${packs.flatMap(pack => (pack.requirements || []).map(r => `<li><strong>${esc(labels[r.status] || "无法判断")}：</strong>${esc(r.requirement)}<p class="text-xs text-gray-600">${esc(r.reason || "")}</p></li>`)).join("")}</ul>${packs.flatMap(p => p.writing_constraints || []).map(text => `<p class="mt-1 text-xs text-gray-600">${esc(text)}</p>`).join("")}</details>` : ""}
        ${verification ? `<details class="mt-2" ${verification.status === "needs_confirmation" ? "open" : ""}><summary class="cursor-pointer font-medium">关键事实核对明细</summary>${verification.invalidated ? `<p class="mt-2 text-amber-800">${esc(verification.reason)}</p>` : `<ul class="mt-2 space-y-3">${(verification.claims || []).map(claim => `<li><strong>${esc(labels[claim.status] || "无法判断")}</strong>：${esc(claim.quote)}<p class="text-xs text-gray-600">${esc(claim.reason || "")}</p>${(claim.supports || []).map(s => `<blockquote class="mt-1 border-l-2 border-gray-300 pl-2 text-xs text-gray-600">[${esc(s.citation_id || "")}] ${esc(s.quote || "")}</blockquote>`).join("")}</li>`).join("")}</ul>`}${verification.omitted_claim_count ? `<p class="mt-2">另有${Number(verification.omitted_claim_count)}项声明未覆盖，仍需确认。</p>` : ""}${verification.correction_status === "reverted" ? '<p class="mt-2 text-amber-800">局部修正未通过复核，已恢复原文并保留待确认项。</p>' : ""}</details>` : ""}
    </aside>`;
}

function renderIndustryReportEvidenceDetails(section) {
    const graphBlocks = section.graph_evidence_blocks || [];
    const externalBlocks = section.external_evidence_blocks || [];
    if (!graphBlocks.length && !externalBlocks.length) return "";
    const usedIds = new Set(section.citation_ids || []);
    const usedExternal = externalBlocks.filter(item => usedIds.has(item?.citation_id));
    const candidateExternal = externalBlocks.filter(item => !usedIds.has(item?.citation_id));
    return `
        <details class="mt-3 rounded-lg border border-gray-200 bg-white">
            <summary class="cursor-pointer px-3 py-2 text-xs font-semibold text-gray-600">查看本节资料依据</summary>
            <div class="p-3 space-y-3">
                ${graphBlocks.map((item, index) => renderIndustryReportEvidenceCard(item, `知识图谱 ${index + 1}`, "graph")).join("")}
                ${usedExternal.length ? `<div class="text-xs font-semibold text-emerald-700">本节已引用资料</div>${usedExternal.map((item, index) => renderIndustryReportEvidenceCard(item, `外部资料 ${index + 1}`, "external")).join("")}` : ""}
                ${candidateExternal.length ? `<div class="text-xs font-semibold text-gray-600">其他检索候选</div>${candidateExternal.map((item, index) => renderIndustryReportEvidenceCard(item, `外部资料 ${index + 1}`, "external")).join("")}` : ""}
            </div>
        </details>
    `;
}

function renderIndustryReportReferences(options = {}) {
    const sections = getIndustryReportReferenceSections(options);
    const usedIds = new Set((sections || [])
        .flatMap(section => Array.isArray(section?.citation_ids) ? section.citation_ids : []));
    const references = (industryReportWorkspace.references || [])
        .filter(item => usedIds.has(item?.citation_id));
    if (!references.length) {
        if (!options.standalone) return "";
        return `
            <section class="border-t border-gray-200 pt-5 mt-6" id="industry-report-references">
                <h2 class="text-lg font-bold text-gray-900 mb-3">参考资料</h2>
                <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500">当前视图暂无已引用参考资料。</div>
            </section>
        `;
    }
    return `
        <section class="border-t border-gray-200 pt-5 mt-6" id="industry-report-references">
            <h2 class="text-lg font-bold text-gray-900 mb-3">参考资料</h2>
            <div class="space-y-3">
                ${references.map(item => {
                    const citationId = String(item.citation_id || "");
                    const address = String(item.source_address || "").trim();
                    const date = item.publish_date ? `，发布日期：${escapeIndustryReportHtml(item.publish_date)}` : "";
                    const retrieved = item.retrieved_at ? `，检索时间：${escapeIndustryReportHtml(item.retrieved_at)}` : "";
                    const link = address ? `，<a class="text-blue-600 hover:underline" href="${escapeIndustryReportHtml(address)}" target="_blank" rel="noopener">打开原文</a>` : "";
                    return `<div id="report-reference-${escapeIndustryReportHtml(citationId)}" class="text-sm leading-6 text-gray-700"><span class="font-semibold">[${escapeIndustryReportHtml(citationId)}] ${escapeIndustryReportHtml(item.title || "未命名资料")}</span>${date}${retrieved}${link}<div class="text-xs text-gray-500 mt-1">${escapeIndustryReportHtml(item.evidence_excerpt || "")}</div></div>`;
                }).join("")}
            </div>
        </section>
    `;
}

function getIndustryReportReferenceSections(options = {}) {
    if (Array.isArray(options.sections)) return options.sections.filter(Boolean);
    const target = industryReportWorkspace.previewTarget || { type: "all", key: "" };
    const bodySections = industryReportWorkspace.bodySections || [];
    if (target.type === "section" && target.key) {
        return bodySections.filter(section => section?.outline_id === target.key);
    }
    if (target.type === "references") {
        const sectionKey = industryReportWorkspace.lastSectionPreviewKey || "";
        if (sectionKey) {
            const sections = bodySections.filter(section => section?.outline_id === sectionKey);
            if (sections.length) return sections;
        }
    }
    return bodySections;
}

function getIndustryReportSectionReferences(section) {
    const evidenceBlocks = Array.isArray(section?.external_evidence_blocks)
        ? section.external_evidence_blocks
        : [];
    if (evidenceBlocks.length) return evidenceBlocks;
    const knownIds = new Set(Array.isArray(section?.citation_ids) ? section.citation_ids : []);
    return (industryReportWorkspace.references || []).filter(item => knownIds.has(item?.citation_id));
}

function renderIndustryReportEvidenceCard(item, fallbackTitle, type = "external") {
    const title = getIndustryReportEvidenceTitle(item, fallbackTitle);
    const text = getIndustryReportEvidenceText(item);
    const nodeId = type === "graph" ? getIndustryReportGraphNodeId(item) : "";
    const graphLink = nodeId ? buildIndustryReportGraphLink(nodeId) : "";
    const citationId = type === "external" ? String(item?.citation_id || "") : "";
    const sourceAddress = type === "external" ? String(item?.source_address || "").trim() : "";
    const sourceLink = sourceAddress
        ? `<a href="${escapeIndustryReportHtml(sourceAddress)}" target="_blank" rel="noopener" class="text-blue-600 hover:underline">打开原文</a>`
        : "";
    const publishDate = type === "external" && item?.publish_date
        ? ` · 发布日期：${escapeIndustryReportHtml(item.publish_date)}`
        : "";
    const titleLabel = type === "graph" ? "图谱位置" : "文章标题";
    const textLabel = type === "graph" ? "具体形式" : "段落内容";
    return `
        <div class="rounded-lg bg-gray-50 border border-gray-200 p-3">
            <div class="text-xs font-semibold text-gray-700 flex items-center justify-between gap-2">
                <span class="min-w-0 truncate">${citationId ? `[${escapeIndustryReportHtml(citationId)}] ` : ""}${titleLabel}：${escapeIndustryReportHtml(title)}${publishDate}</span>
                ${graphLink ? `<a href="${escapeIndustryReportHtml(graphLink)}" data-graph-node-id="${escapeIndustryReportHtml(nodeId)}" onclick="return openIndustryReportGraph(this.dataset.graphNodeId)" class="text-blue-600 hover:text-blue-700 font-medium">打开图谱</a>` : sourceLink}
            </div>
            <div class="mt-1 text-xs leading-5 text-gray-500">${textLabel}：${escapeIndustryReportHtml(truncateIndustryReportText(text, 260))}</div>
        </div>
    `;
}

function getIndustryReportGraphNodeId(item) {
    return getIndustryReportGraphSegment(item)?.id ?? item?.node_id ?? item?.id ?? "";
}

function getIndustryReportGraphSegment(item) {
    // Existing saved reports use level3; newly generated evidence uses segment.
    return item?.segment || item?.level3 || null;
}

function buildIndustryReportGraphLink(nodeId) {
    const params = new URLSearchParams({
        view: "graph",
        subview: "graph",
        node: String(nodeId),
        industry: industryReportWorkspace.industry ?? getIndustryReportCurrentIndustry(),
    });
    return `${window.location.origin}${window.location.pathname}?${params.toString()}`;
}

function openIndustryReportGraph(nodeId) {
    const normalizedNodeId = String(nodeId ?? "").trim();
    if (!normalizedNodeId || typeof switchView !== "function") return true;

    const industry = industryReportWorkspace.industry || getIndustryReportCurrentIndustry();
    const previousIndustry = getIndustryReportCurrentIndustry();
    if (typeof setCurrentIndustryFromRoute === "function") {
        setCurrentIndustryFromRoute(industry);
    }
    if (industry !== previousIndustry && typeof loadIndustryData === "function") {
        loadIndustryData(industry);
    }
    window.pendingGraphSubView = "graph";
    window.pendingGraphFocusNodeId = normalizedNodeId;
    if (window.history && typeof window.history.replaceState === "function") {
        window.history.replaceState({}, "", buildIndustryReportGraphLink(normalizedNodeId));
    }
    switchView("graph");
    return false;
}

function openIndustryReportRewriteModal(outlineId) {
    const section = industryReportWorkspace.bodySections.find(item => item.outline_id === outlineId);
    if (!section) return;
    industryReportWorkspace.activeSectionId = outlineId;
    industryReportWorkspace.rewriteMaterials = null;
    const modal = document.getElementById("industry-report-rewrite-modal");
    const meta = document.getElementById("industry-report-rewrite-meta");
    const prompt = document.getElementById("industry-report-rewrite-prompt");
    const materials = document.getElementById("industry-report-materials");
    const preview = document.getElementById("industry-report-rewrite-preview");
    if (meta) meta.textContent = `${section.parent_level1_title || "正文"} · ${section.title || ""}`;
    if (prompt) prompt.value = "";
    if (materials) materials.innerHTML = "点击“推荐资料”后显示";
    if (preview) preview.innerHTML = '<div class="border border-gray-200 rounded-lg p-3 bg-gray-50 text-gray-500">重写成功后自动更新正文</div>';
    if (modal) modal.classList.remove("hidden");
}

function closeIndustryReportRewriteModal() {
    const modal = document.getElementById("industry-report-rewrite-modal");
    if (modal) modal.classList.add("hidden");
}

function getIndustryReportActiveSection() {
    return industryReportWorkspace.bodySections.find(item => item.outline_id === industryReportWorkspace.activeSectionId);
}

async function recommendIndustryReportMaterials() {
    const section = getIndustryReportActiveSection();
    const rewritePrompt = (document.getElementById("industry-report-rewrite-prompt")?.value || "").trim();
    if (!section) return;
    if (!rewritePrompt) {
        renderIndustryReportMaterialsMessage("请先输入重写要求", "error");
        return;
    }
    renderIndustryReportMaterialsMessage("正在推荐资料...", "loading");
    try {
        const data = await industryReportApi("/api/report/rewrite/materials", {
            method: "POST",
            body: JSON.stringify({
                rewrite_prompt: rewritePrompt,
                report_title: industryReportWorkspace.reportTitle,
                industry: industryReportWorkspace.industry ?? "ai",
                body_section: section,
                top_k: getIndustryReportNumber("industry-report-top-k", 10),
            }),
        });
        industryReportWorkspace.rewriteMaterials = data;
        renderIndustryReportMaterials(data);
    } catch (err) {
        renderIndustryReportMaterialsMessage(`资料推荐失败：${err.message}`, "error");
    }
}

function renderIndustryReportMaterials(data) {
    const box = document.getElementById("industry-report-materials");
    if (!box) return;
    const graphBlocks = data.graph_retrieval?.evidence_blocks || [];
    const externalBlocks = data.external_rag_retrieval?.evidence_blocks || [];
    box.innerHTML = `
        <div class="space-y-3">
            <div>
                <div class="text-xs font-semibold text-gray-500 mb-2">知识图谱资料（自动纳入）</div>
                ${graphBlocks.length ? graphBlocks.map((item, index) => renderIndustryReportMaterialRow(item, index, "graph", false)).join("") : '<div class="text-xs text-gray-400">暂无知识图谱资料</div>'}
            </div>
            <div>
                <div class="text-xs font-semibold text-gray-500 mb-2">外部资料（可勾选）</div>
                ${externalBlocks.length ? externalBlocks.map((item, index) => renderIndustryReportMaterialRow(item, index, "external", true)).join("") : '<div class="text-xs text-gray-400">暂无外部资料</div>'}
            </div>
        </div>
    `;
}

function renderIndustryReportMaterialRow(item, index, type, selectable) {
    const title = getIndustryReportEvidenceTitle(item, `${type === "graph" ? "知识图谱" : "外部资料"} ${index + 1}`);
    const text = getIndustryReportEvidenceText(item);
    const checkbox = selectable ? `<input type="checkbox" class="industry-report-material-checkbox mt-1" data-material-index="${index}" checked>` : '<i class="fas fa-link text-blue-500 mt-1"></i>';
    const nodeId = type === "graph" ? getIndustryReportGraphNodeId(item) : "";
    const graphLink = nodeId ? buildIndustryReportGraphLink(nodeId) : "";
    const titleLabel = type === "graph" ? "图谱位置" : "文章标题";
    const textLabel = type === "graph" ? "具体形式" : "段落内容";
    return `
        <label class="flex items-start gap-2 rounded-lg border border-gray-200 bg-white p-2 mb-2">
            ${checkbox}
            <span class="min-w-0">
                <span class="flex items-center justify-between gap-2 text-xs font-semibold text-gray-700">
                    <span class="min-w-0 truncate">${titleLabel}：${escapeIndustryReportHtml(title)}</span>
                    ${graphLink ? `<a href="${escapeIndustryReportHtml(graphLink)}" data-graph-node-id="${escapeIndustryReportHtml(nodeId)}" onclick="return openIndustryReportGraph(this.dataset.graphNodeId)" class="text-blue-600 hover:text-blue-700">打开图谱</a>` : ""}
                </span>
                <span class="block mt-1 text-xs leading-5 text-gray-500">${textLabel}：${escapeIndustryReportHtml(truncateIndustryReportText(text, 180))}</span>
            </span>
        </label>
    `;
}

function renderIndustryReportMaterialsMessage(message, type = "info") {
    const box = document.getElementById("industry-report-materials");
    if (!box) return;
    const color = type === "error" ? "text-red-600" : type === "loading" ? "text-blue-600" : "text-gray-500";
    box.innerHTML = `<div class="${color}">${escapeIndustryReportHtml(message)}</div>`;
}

async function rewriteIndustryReportSection() {
    const section = getIndustryReportActiveSection();
    const rewritePrompt = (document.getElementById("industry-report-rewrite-prompt")?.value || "").trim();
    if (!section || !rewritePrompt) return;
    if (!industryReportWorkspace.rewriteMaterials) {
        await recommendIndustryReportMaterials();
        if (!industryReportWorkspace.rewriteMaterials) return;
    }
    const externalBlocks = industryReportWorkspace.rewriteMaterials.external_rag_retrieval?.evidence_blocks || [];
    const selected = Array.from(document.querySelectorAll(".industry-report-material-checkbox"))
        .filter(input => input.checked)
        .map(input => externalBlocks[Number(input.dataset.materialIndex)])
        .filter(Boolean);
    const preview = document.getElementById("industry-report-rewrite-preview");
    if (preview) preview.innerHTML = '<div class="text-blue-600"><i class="fas fa-spinner fa-spin mr-2"></i>正在生成重写内容...</div>';
    try {
        const data = await industryReportApi("/api/report/rewrite", {
            method: "POST",
            body: JSON.stringify({
                rewrite_prompt: rewritePrompt,
                report_title: industryReportWorkspace.reportTitle,
                industry: industryReportWorkspace.industry ?? "ai",
                body_section: section,
                graph_retrieval: industryReportWorkspace.rewriteMaterials.graph_retrieval || {},
                selected_external_evidence_blocks: selected,
                references: industryReportWorkspace.references || [],
                previous_body_sections: (industryReportWorkspace.bodySections || [])
                    .filter(item => item && item.outline_id !== section.outline_id),
            }),
        });
        appendIndustryReportWarnings(data.warnings);
        showIndustryReportCitationValidationWarning(data.warnings);
        applyIndustryReportRewrite(data, section.outline_id);
    } catch (err) {
        if (preview) preview.innerHTML = `<div class="text-red-600">重写失败：${escapeIndustryReportHtml(err.message)}</div>`;
    }
}

function applyIndustryReportRewrite(rewritten, outlineId) {
    if (!rewritten || !outlineId) return;
    industryReportWorkspace.bodySections = industryReportWorkspace.bodySections.map(section => {
        if (section.outline_id !== outlineId) return section;
        return {
            ...section,
            body_text: rewritten.body_text || section.body_text,
            original_body_text: rewritten.original_body_text || section.body_text,
            claim_verification: rewritten.claim_verification || {status: "needs_confirmation", body_text: rewritten.body_text || section.body_text, claims: [], invalidated: true, reason: "重写后事实核对尚未完成。"},
            evidence_pack: null,
            merged_evidence_packs: [],
            repetition_focus_terms: Array.isArray(rewritten.repetition_focus_terms) ? rewritten.repetition_focus_terms.slice() : [],
            warnings: [...(section.warnings || []), ...(rewritten.warnings || [])],
            graph_evidence_blocks: rewritten.graph_evidence_blocks || section.graph_evidence_blocks || [],
            external_evidence_blocks: rewritten.selected_external_evidence_blocks || section.external_evidence_blocks || [],
            citation_ids: Array.isArray(rewritten.citation_ids)
                ? rewritten.citation_ids
                : extractIndustryReportCitationIds(
                    rewritten.body_text || section.body_text,
                    rewritten.selected_external_evidence_blocks || getIndustryReportSectionReferences(section),
                ),
        };
    });
    if (Array.isArray(rewritten.references)) {
        industryReportWorkspace.references = mergeIndustryReportReferences(
            industryReportWorkspace.references,
            rewritten.references,
        );
    }
    industryReportWorkspace.adjustmentNotes = [
        ...(industryReportWorkspace.adjustmentNotes || []).filter(note =>
            !(["body_edit", "review_warning"].includes(note.kind) && note.outline_ids?.length === 1 && note.outline_ids.includes(outlineId))),
        ...(Array.isArray(rewritten.adjustment_notes) ? rewritten.adjustment_notes : []),
    ];
    industryReportWorkspace.review = rewritten.review || industryReportWorkspace.review;
    industryReportWorkspace.abstractText = "";
    industryReportWorkspace.preparedDocxPath = "";
    industryReportWorkspace.summaryReview = null;
    renderIndustryReportPreview();
    void saveIndustryReportHistory({ silent: true });
    closeIndustryReportRewriteModal();
    setIndustryReportStatus("已采用重写内容", "success");
    showIndustryReportCitationValidationWarning(industryReportWorkspace.warnings);
}

function buildIndustryReportHistoryRecord() {
    syncIndustryReportBodySectionsFromDom();
    const title = (industryReportWorkspace.reportScope?.effective_title || industryReportWorkspace.taskCard?.selected_title || document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const prompt = (industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || document.getElementById("industry-report-prompt")?.value || "").trim();
    const now = new Date().toISOString();
    return {
        id: industryReportWorkspace.historyId || `local_report_${Date.now()}`,
        title,
        prompt,
        abstractText: industryReportWorkspace.abstractText || "",
        industry: industryReportWorkspace.industry ?? getIndustryReportCurrentIndustry(),
        pageIndustry: industryReportWorkspace.pageIndustry || getIndustryReportCurrentIndustry(),
        taskCard: industryReportWorkspace.taskCard ? { ...industryReportWorkspace.taskCard, outline_template: industryReportWorkspace.outlineTemplate?.confirmed ? { level1_titles: [...industryReportWorkspace.outlineTemplate.level1_titles] } : undefined } : null,
        outlineTemplate: industryReportWorkspace.outlineTemplate || null,
        outline: industryReportWorkspace.outline || [],
        writingTasks: industryReportWorkspace.writingTasks || [],
        coordination: industryReportWorkspace.coordination || null,
        review: industryReportWorkspace.review || null,
        runtimeBudget: industryReportWorkspace.runtimeBudget || null,
        reportScope: industryReportWorkspace.reportScope || null,
        summaryReview: industryReportWorkspace.summaryReview || null,
        deliveryStatus: industryReportWorkspace.deliveryStatus || "incomplete",
        deliveryReasons: industryReportWorkspace.deliveryReasons || [],
        preparedDocxPath: industryReportWorkspace.preparedDocxPath || "",
        adjustmentNotes: industryReportWorkspace.adjustmentNotes || [],
        bodySections: industryReportWorkspace.bodySections || [],
        references: industryReportWorkspace.references || [],
        warnings: industryReportWorkspace.warnings || [],
        createdAt: industryReportWorkspace.historyId ? undefined : now,
        updatedAt: now,
    };
}

async function saveIndustryReportHistory(options = {}) {
    if (industryReportWorkspace.busy && industryReportWorkspace.currentStage === "coordinator") {
        if (!options.silent) setIndustryReportStatus("正在统筹与协调小节分工，请完成后保存历史", "info");
        return;
    }
    const record = buildIndustryReportHistoryRecord();
    if (!record.bodySections.length && !record.outline.length && !record.taskCard) {
        if (!options.silent) setIndustryReportStatus("暂无可保存的报告内容", "error");
        return;
    }
    try {
        const data = await industryReportApi("/api/report/history", {
            method: "POST",
            body: JSON.stringify({ report: record }),
        });
        industryReportWorkspace.historyId = data.report?.id || record.id;
        industryReportHistoryIndex = Array.isArray(data.items) ? data.items : industryReportHistoryIndex;
        renderIndustryReportHistorySelect(industryReportWorkspace.historyId);
        if (!options.silent) setIndustryReportStatus("当前报告已保存到本机历史记录", "success");
    } catch (err) {
        if (!options.silent) setIndustryReportStatus(`历史保存失败：${err.message}`, "error");
    }
}

function renderIndustryReportHistorySelect(selectedId = "") {
    const select = document.getElementById("industry-report-history-select");
    if (!select) return;
    if (!industryReportHistoryIndex.length) {
        select.innerHTML = '<option value="">暂无历史报告</option>';
        return;
    }
    select.innerHTML = industryReportHistoryIndex.map(item => {
        const time = formatIndustryReportHistoryTime(item.updatedAt || item.createdAt);
        const selected = selectedId && item.id === selectedId ? "selected" : "";
        return `<option value="${escapeIndustryReportHtml(item.id)}" ${selected}>${escapeIndustryReportHtml(item.title || "未命名报告")} · ${escapeIndustryReportHtml(time)}</option>`;
    }).join("");
}

async function refreshIndustryReportHistorySelect(selectedId = "") {
    try {
        const data = await industryReportApi("/api/report/history");
        industryReportHistoryIndex = Array.isArray(data.items) ? data.items : [];
        renderIndustryReportHistorySelect(selectedId);
    } catch (err) {
        industryReportHistoryIndex = [];
        renderIndustryReportHistorySelect();
    }
}

async function loadSelectedIndustryReportHistory() {
    const select = document.getElementById("industry-report-history-select");
    const id = select?.value || "";
    if (!id) {
        setIndustryReportStatus("请先选择一份历史报告", "error");
        return;
    }
    let record;
    try {
        const data = await industryReportApi(`/api/report/history/${encodeURIComponent(id)}`);
        record = data.report;
    } catch (err) {
        setIndustryReportStatus(`读取历史报告失败：${err.message}`, "error");
        void refreshIndustryReportHistorySelect();
        return;
    }
    if (!record) return;
    const requirementRewriteSeq = nextIndustryReportRequirementRewriteSeq();
    industryReportWorkspace = {
        historyId: record.id,
        currentStage: getIndustryReportStageFromRecord(record),
        activeStep: getIndustryReportActiveStepKey(getIndustryReportStageFromRecord(record)),
        completedSteps: getIndustryReportCompletedStepsFromRecord(record),
        flowCollapsed: industryReportWorkspace.flowCollapsed || false,
        userPrompt: record.prompt || "",
        reportTitle: record.title || "产业报告",
        abstractText: record.abstractText || "",
        industry: record.industry || "ai",
        pageIndustry: record.pageIndustry || record.taskCard?.page_industry || record.industry || "ai",
        taskCard: record.taskCard || null,
        outlineTemplate: normalizeIndustryReportTemplate(record.outlineTemplate || record.taskCard?.outline_template),
        outline: record.outline || [],
        writingTasks: record.writingTasks || [],
        coordination: record.coordination || null,
        review: record.review || null,
        runtimeBudget: record.runtimeBudget || null,
        reportScope: record.reportScope || null,
        summaryReview: record.summaryReview || null,
        deliveryStatus: record.deliveryStatus || "incomplete",
        deliveryReasons: record.deliveryReasons || [],
        preparedDocxPath: record.preparedDocxPath || "",
        adjustmentNotes: Array.isArray(record.adjustmentNotes) ? record.adjustmentNotes : [],
        bodySections: normalizeIndustryReportBodySections(record.bodySections || []),
        references: Array.isArray(record.references) ? record.references : [],
        warnings: record.warnings || [],
        activeSectionId: "",
        rewriteMaterials: null,
        busy: false,
        exportState: "",
        selectedAgentStep: getIndustryReportActiveStepKey(getIndustryReportStageFromRecord(record)),
        bodyProgressById: {},
        coordinatorProgressById: {},
        executionLogTimeByKey: {},
        stepTimingByKey: {},
        bodyTotal: Array.isArray(record.writingTasks) ? record.writingTasks.length : 0,
        coordinatorTotal: countIndustryReportSubsections(record.outline || []),
        outlineLocked: Boolean(record.writingTasks?.length || record.bodySections?.length),
        requirementRewriteSeq,
        previewTarget: { type: "all", key: "" },
        lastSectionPreviewKey: "",
    };
    appendIndustryReportWarnings(industryReportWorkspace.bodySections.flatMap(section => section.warnings || []));
    const titleInput = document.getElementById("industry-report-title");
    const promptInput = document.getElementById("industry-report-prompt");
    if (titleInput) titleInput.value = industryReportWorkspace.reportTitle;
    if (promptInput) promptInput.value = industryReportWorkspace.userPrompt;
    renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
    if (industryReportWorkspace.outlineTemplate) {
        industryReportWorkspace.outlineTemplate.context = industryReportTemplateContext();
    }
    renderIndustryReportOutline(industryReportWorkspace.outline);
    renderIndustryReportProgress(industryReportWorkspace.bodySections.length
        ? buildIndustryReportTaskProgress("generated", industryReportWorkspace.bodySections)
        : []);
    renderIndustryReportPreview();
    syncIndustryReportHeader();
    renderIndustryReportHistorySelect(record.id);
    setIndustryReportStage(getIndustryReportStageFromRecord(record), "已载入历史报告");
    setIndustryReportCompletionStatus("历史报告已载入");
}

function getIndustryReportStageFromRecord(record) {
    if (record.bodySections?.length) return "done";
    if (record.writingTasks?.length) return "coordinator";
    if (record.outline?.length) return "outline";
    return "idle";
}

function getIndustryReportCompletedStepsFromRecord(record) {
    const steps = [];
    if (record.taskCard || record.prompt || record.outline?.length || record.writingTasks?.length || record.bodySections?.length) {
        steps.push("requirement");
    }
    if (record.outline?.length || record.writingTasks?.length || record.bodySections?.length) {
        steps.push("outline");
    }
    if (record.writingTasks?.length || record.bodySections?.length) {
        steps.push("coordinator");
    }
    if (record.bodySections?.length) {
        steps.push("body");
    }
    return steps;
}

async function deleteSelectedIndustryReportHistory() {
    const select = document.getElementById("industry-report-history-select");
    const id = select?.value || "";
    if (!id) return;
    try {
        const data = await industryReportApi("/api/report/history", {
            method: "DELETE",
            body: JSON.stringify({ id }),
        });
        industryReportHistoryIndex = Array.isArray(data.items) ? data.items : [];
        if (industryReportWorkspace.historyId === id) industryReportWorkspace.historyId = "";
        renderIndustryReportHistorySelect();
        setIndustryReportStatus("已删除本机历史报告", "success");
    } catch (err) {
        setIndustryReportStatus(`删除历史报告失败：${err.message}`, "error");
    }
}

function formatIndustryReportHistoryTime(value) {
    const date = new Date(value || "");
    if (Number.isNaN(date.getTime())) return "未知时间";
    const pad = num => String(num).padStart(2, "0");
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function exportIndustryReportMarkdown() {
    const markdown = buildIndustryReportMarkdown();
    if (!markdown.trim()) {
        setIndustryReportStatus("暂无可导出的报告内容", "error");
        return;
    }
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const title = (industryReportWorkspace.reportTitle || "产业报告").replace(/[\\/:*?"<>|]+/g, "_");
    link.href = url;
    link.download = `${title}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function prepareIndustryReportDownload(title, bodySections) {
    const data = await industryReportApi("/api/report/export/word", {
        method: "POST", body: JSON.stringify({
            report_title: industryReportWorkspace.reportScope?.effective_title || title,
            abstract_text: industryReportWorkspace.abstractText,
            industry: industryReportWorkspace.industry,
            body_sections: bodySections,
            references: industryReportWorkspace.references || [],
            adjustment_notes: industryReportWorkspace.adjustmentNotes || [],
            review: industryReportWorkspace.review,
            summary_review: industryReportWorkspace.summaryReview,
        }),
    });
    if (!data.docx_path) throw new Error("后端未返回 Word 文件路径");
    acceptIndustryReportRunResult(data);
    industryReportWorkspace.preparedDocxPath = data.docx_path;
    industryReportWorkspace.deliveryStatus = data.delivery_status || "incomplete";
    return data;
}

async function exportIndustryReportWord() {
    syncIndustryReportBodySectionsFromDom();
    if (industryReportWorkspace.preparedDocxPath) {
        await downloadIndustryReportWord(industryReportWorkspace.preparedDocxPath);
        return;
    }
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const bodySections = buildIndustryReportExportSections();
    if (!bodySections.length) {
        setIndustryReportStatus("请先生成正文后再导出 Word", "error");
        return;
    }
    let abstractText = (industryReportWorkspace.abstractText || "").trim();
    try {
        if (!abstractText) {
            setIndustryReportStatus("正在生成 Word 摘要...", "loading");
            abstractText = await generateIndustryReportSummaryForWord(title, bodySections);
            industryReportWorkspace.abstractText = abstractText;
        }
    } catch (err) {
        industryReportWorkspace.deliveryStatus = "incomplete";
        industryReportWorkspace.deliveryReasons = [];
        setIndustryReportStatus(`摘要未完成：${err.message}`, "error");
        return;
    }
    if (!abstractText) {
        setIndustryReportStatus("正文内容为空，无法导出 Word", "error");
        return;
    }

    industryReportWorkspace.exportState = "active";
    industryReportWorkspace.selectedAgentStep = "review";
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "done");
    setIndustryReportStatus("正在导出 Word...", "loading");
    try {
        const data = await industryReportApi("/api/report/export/word", {
            method: "POST",
            body: JSON.stringify({
                report_title: title,
                abstract_text: abstractText,
                industry: industryReportWorkspace.industry ?? getIndustryReportCurrentIndustry(),
                body_sections: bodySections,
                references: industryReportWorkspace.references || [],
                adjustment_notes: industryReportWorkspace.adjustmentNotes || [],
                review: industryReportWorkspace.review,
                summary_review: industryReportWorkspace.summaryReview,
            }),
        });
        if (!data.docx_path) {
            throw new Error("后端未返回 Word 文件路径");
        }
        industryReportWorkspace.preparedDocxPath = data.docx_path;
        acceptIndustryReportRunResult(data);
        renderIndustryReportDeliveryDetails();
        await downloadIndustryReportWord(data.docx_path);
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        markIndustryReportStepDone("coordinator");
        markIndustryReportStepDone("body");
        industryReportWorkspace.exportState = "done";
        if (industryReportWorkspace.deliveryStatus === "completed") markIndustryReportStepDone("review");
        setIndustryReportStage("done", industryReportWorkspace.deliveryStatus === "completed" ? "Word 已生成并下载" : "Word 已下载，仍有待核对事项");
        setIndustryReportStatus(industryReportWorkspace.deliveryStatus === "completed" ? "Word 已生成，正在下载" : "Word 已生成，请查看生成与交付核对", industryReportWorkspace.deliveryStatus === "completed" ? "success" : "info");
    } catch (err) {
        industryReportWorkspace.exportState = "failed";
        renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "done");
        setIndustryReportStatus(`Word 导出失败：${err.message}`, "error");
    }
}

async function generateIndustryReportSummaryForWord(title, bodySections) {
    const data = await industryReportApi("/api/report/summary", {
        method: "POST",
        body: JSON.stringify({
            report_title: title,
            industry: industryReportWorkspace.industry ?? getIndustryReportCurrentIndustry(),
            outline: industryReportWorkspace.outline || [],
            body_sections: bodySections,
        }),
    });
    industryReportWorkspace.adjustmentNotes = [
        ...(industryReportWorkspace.adjustmentNotes || []).filter(note => note.kind !== "summary_review"),
        ...(Array.isArray(data.adjustment_notes) ? data.adjustment_notes : []),
    ];
    return (data.abstract_text || "").trim();
}

function syncIndustryReportBodySectionsFromDom() {
    const abstractEl = document.getElementById("industry-report-abstract-editor");
    if (abstractEl) {
        industryReportWorkspace.abstractText = normalizeIndustryReportParagraphText(getIndustryReportEditableText(abstractEl));
    }
    document.querySelectorAll("[data-report-body-section]").forEach(sectionEl => {
        const outlineId = sectionEl.getAttribute("data-report-body-section");
        const editor = sectionEl.querySelector(".industry-report-body-editor");
        if (outlineId && editor) {
            updateIndustryReportBodyText(outlineId, getIndustryReportEditableText(editor));
        }
    });
}

function buildIndustryReportAbstractForWord(bodySections) {
    const abstractSection = bodySections.find(section => /摘要|概述|总结/.test(section.title || section.parent_level1_title || ""));
    const source = abstractSection || bodySections.find(section => (section.body_text || "").trim());
    const text = (source?.body_text || "").trim();
    if (!text) return "";
    const firstParagraph = text.split(/\n\s*\n/).find(item => item.trim()) || text;
    return firstParagraph.slice(0, 1200);
}

async function downloadIndustryReportWord(docxPath) {
    const url = `${API_BASE}/api/report/export/word/download?path=${encodeURIComponent(docxPath)}`;
    const resp = await fetch(url, { method: "GET" });
    if (!resp.ok) {
        let message = `下载失败：${resp.status}`;
        try {
            const data = await resp.json();
            message = data.message || message;
        } catch (err) {
            // ignore non-json response
        }
        throw new Error(message);
    }
    const blob = await resp.blob();
    const disposition = resp.headers.get("Content-Disposition") || "";
    const filename = parseIndustryReportDownloadFilename(disposition)
        || `${(industryReportWorkspace.reportTitle || "产业报告").replace(/[\\/:*?"<>|]+/g, "_")}.docx`;
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
}

function parseIndustryReportDownloadFilename(disposition) {
    const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    if (utf8Match) {
        try {
            return decodeURIComponent(utf8Match[1]);
        } catch (err) {
            return utf8Match[1];
        }
    }
    const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
    return plainMatch ? plainMatch[1] : "";
}

function buildIndustryReportMarkdown() {
    syncIndustryReportBodySectionsFromDom();
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const groups = groupIndustryReportBodySections();
    const lines = [`# ${title}`, ""];
    const abstractText = (industryReportWorkspace.abstractText || "").trim();
    if (abstractText) {
        lines.push("## 摘要", "", abstractText, "");
    }
    if (!groups.length && industryReportWorkspace.outline.length) {
        industryReportWorkspace.outline.forEach((section, sectionIndex) => {
            lines.push(`## ${sectionIndex + 1}. ${section.level1_title}`, "");
            (section.subsections || []).forEach((sub, subIndex) => {
                lines.push(`### ${sectionIndex + 1}.${subIndex + 1} ${sub.title}`, "");
            });
        });
        return lines.join("\n");
    }
    groups.forEach((group, groupIndex) => {
        lines.push(`## ${groupIndex + 1}. ${group.title}`, "");
        group.children.forEach((section, sectionIndex) => {
            lines.push(`### ${groupIndex + 1}.${sectionIndex + 1} ${section.title}`, "");
            lines.push(section.body_text || "", "");
        });
    });
    lines.push("## 资料与方法说明", "", ...buildIndustryReportMethodNotes().flatMap(note => [note, ""]));
    const usedIds = new Set((industryReportWorkspace.bodySections || [])
        .flatMap(section => Array.isArray(section.citation_ids) ? section.citation_ids : []));
    const usedReferences = (industryReportWorkspace.references || [])
        .filter(item => usedIds.has(item?.citation_id));
    if (usedReferences.length) {
        lines.push("## 参考资料", "");
        usedReferences.forEach(item => {
            const published = item.publish_date ? `，发布于 ${item.publish_date}` : "";
            const retrieved = item.retrieved_at ? `，检索于 ${item.retrieved_at}` : "";
            const address = item.source_address ? `，${item.source_address}` : "";
            lines.push(`[${item.citation_id}] ${item.title || "未命名资料"}${published}${retrieved}${address}`);
        });
        lines.push("");
    }
    return lines.join("\n");
}

function getIndustryReportNumber(id, fallback) {
    const value = Number(document.getElementById(id)?.value);
    return Number.isFinite(value) && value > 0 ? value : fallback;
}

function normalizeIndustryReportParagraphText(value) {
    const normalized = String(value || "")
        .replace(/\r\n/g, "\n")
        .replace(/\u00a0/g, " ")
        .split(/\n+/)
        .map(line => line.trim())
        .filter(Boolean)
        .join("\n");
    return normalized === "可在这里手动修改内容" ? "" : normalized;
}

function renderIndustryReportParagraphs(value, references = []) {
    const paragraphs = normalizeIndustryReportParagraphText(value).split("\n").filter(Boolean);
    if (!paragraphs.length) {
        return '<p data-industry-report-placeholder="true" class="indent-8 min-h-[1.75rem] m-0 text-gray-400">可在这里手动修改内容</p>';
    }
    return paragraphs
        .map(paragraph => `<p class="indent-8 m-0">${renderIndustryReportCitationMarkers(escapeIndustryReportHtml(paragraph), references)}</p>`)
        .join("");
}

function renderIndustryReportCitationMarkers(escapedText, references = []) {
    const allowed = new Set((references || []).map(item => item?.citation_id));
    return String(escapedText || "").replace(/\[(C[1-9]\d*)\]/g, (marker, citationId) => {
        if (!allowed.has(citationId)) return marker;
        return `<a href="#report-reference-${escapeIndustryReportHtml(citationId)}" contenteditable="false" class="text-blue-600 font-semibold hover:underline">${marker}</a>`;
    });
}

function extractIndustryReportCitationIds(text, references = []) {
    const allowed = new Set((references || []).map(item => item?.citation_id));
    const ids = [];
    for (const match of String(text || "").matchAll(/\[(C[1-9]\d*)\]/g)) {
        const citationId = match[1];
        if (allowed.has(citationId) && !ids.includes(citationId)) ids.push(citationId);
    }
    return ids;
}

function mergeIndustryReportReferences(existing = [], incoming = []) {
    const merged = [];
    const byId = new Map();
    [...(Array.isArray(existing) ? existing : []), ...(Array.isArray(incoming) ? incoming : [])]
        .forEach(item => {
            const citationId = String(item?.citation_id || "").trim();
            if (!citationId) return;
            if (!byId.has(citationId)) {
                const copy = { ...item, citation_id: citationId };
                byId.set(citationId, copy);
                merged.push(copy);
            } else {
                byId.set(citationId, { ...byId.get(citationId), ...item, citation_id: citationId });
                const index = merged.findIndex(row => row.citation_id === citationId);
                if (index >= 0) merged[index] = byId.get(citationId);
            }
        });
    return merged;
}

function getIndustryReportEditableText(el) {
    if (el?.querySelector?.("[data-industry-report-placeholder='true']")) return "";
    return String(el?.innerText || "")
        .replace(/\n{3,}/g, "\n")
        .trim();
}

function getIndustryReportEvidenceTitle(item, fallbackTitle) {
    const segment = getIndustryReportGraphSegment(item);
    return item?.source_title
        || item?.article_title
        || item?.document_title
        || item?.doc_title
        || item?.title
        || segment?.name
        || item?.chain_path
        || fallbackTitle
        || "未命名资料";
}

function getIndustryReportEvidenceText(item) {
    return item?.paragraph_text
        || item?.paragraph
        || item?.context_text
        || item?.evidence_excerpt
        || item?.summary
        || item?.content
        || item?.rag_context_text
        || item?.text
        || "";
}

function truncateIndustryReportText(value, limit = 220) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text) return "暂无段落内容";
    if (text.length <= limit) return text;
    return `${text.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function countIndustryReportWords(value) {
    const text = String(value || "").trim();
    if (!text) return 0;
    const chineseChars = (text.match(/[\u4e00-\u9fff]/g) || []).length;
    const nonChineseWords = text
        .replace(/[\u4e00-\u9fff]/g, " ")
        .trim()
        .split(/\s+/)
        .filter(Boolean).length;
    return chineseChars + nonChineseWords;
}

function escapeIndustryReportHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeIndustryReportJs(value) {
    return String(value ?? "")
        .replace(/\\/g, "\\\\")
        .replace(/'/g, "\\'")
        .replace(/\n/g, "\\n")
        .replace(/\r/g, "");
}

document.addEventListener("industryChanged", () => {
    const template = industryReportWorkspace.outlineTemplate;
    resetIndustryReportWorkspace();
    industryReportWorkspace.outlineTemplate = template;
    markIndustryReportTemplateForReview();
});

window.addEventListener("load", () => {
    syncIndustryReportTitlePlaceholder();
    syncIndustryReportHeader();
    void refreshIndustryReportHistorySelect();
    renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
    renderIndustryReportOutline(industryReportWorkspace.outline);
    renderIndustryReportFlowSteps("idle");
    renderIndustryReportPreview();
});

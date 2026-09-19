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
    outline: [],
    writingTasks: [],
    bodySections: [],
    warnings: [],
    activeSectionId: "",
    rewriteMaterials: null,
    pendingRewrite: null,
    busy: false,
    requirementRewriteSeq: 0,
};

let industryReportHistoryIndex = [];

const INDUSTRY_REPORT_STAGE_LABELS = {
    idle: "未开始",
    outline: "生成大纲",
    coordinator: "统筹任务",
    body: "生成正文",
    done: "已完成",
    error: "失败",
};

const INDUSTRY_REPORT_FLOW_STEPS = [
    { key: "requirement", title: "需求输入", detail: "填写主题、标题和参数" },
    { key: "outline", title: "任务卡与大纲", detail: "确认任务卡并生成章节" },
    { key: "coordinator", title: "统筹任务", detail: "检索资料并拆分写作任务" },
    { key: "body", title: "生成正文", detail: "按章节生成报告内容" },
    { key: "review", title: "预览导出", detail: "查看、重写、保存或导出" },
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

function setIndustryReportCompletionStatus(successText) {
    const ragWarning = getIndustryReportRagWarning();
    setIndustryReportStatus(ragWarning?.message || successText, ragWarning ? "info" : "success");
}

function setIndustryReportBusy(isBusy, text = "") {
    industryReportWorkspace.busy = Boolean(isBusy);
    ["report-outline-btn", "report-task-card-confirm-btn", "report-outline-confirm-btn", "report-generate-btn"].forEach(id => {
        const btn = document.getElementById(id);
        const shouldDisable = Boolean(isBusy)
            || (id === "report-task-card-confirm-btn" && !industryReportWorkspace.taskCard)
            || (id === "report-outline-confirm-btn" && !hasIndustryReportOutline());
        if (btn) btn.disabled = shouldDisable;
        if (btn) btn.classList.toggle("opacity-60", shouldDisable);
        if (btn) btn.classList.toggle("cursor-not-allowed", shouldDisable);
    });
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

function setIndustryReportStage(stage, detail = "") {
    const meta = document.getElementById("report-flow-meta");
    const stageEl = document.getElementById("report-flow-stage");
    const label = INDUSTRY_REPORT_STAGE_LABELS[stage] || stage || "未开始";
    industryReportWorkspace.currentStage = stage || "idle";
    industryReportWorkspace.activeStep = getIndustryReportActiveStepKey(stage);
    if (meta) meta.textContent = detail || label;
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage);
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
}

function clearIndustryReportStepDone(stepKeys) {
    const remove = new Set(stepKeys || []);
    industryReportWorkspace.completedSteps = (industryReportWorkspace.completedSteps || []).filter(key => !remove.has(key));
}

function getIndustryReportStepState(stepKey, stage) {
    if (stage === "error" && industryReportWorkspace.activeStep === stepKey) return "failed";
    if ((industryReportWorkspace.completedSteps || []).includes(stepKey)) return "done";
    if (industryReportWorkspace.activeStep === stepKey) return "active";
    return "pending";
}

function renderIndustryReportFlowSteps(stage = "idle") {
    const box = document.getElementById("industry-report-stepper");
    if (!box) return;
    const styleMap = {
        done: {
            item: "border-emerald-300 bg-emerald-50",
            badge: "bg-emerald-500 text-white",
            title: "text-emerald-800",
            detail: "text-emerald-700",
            icon: '<i class="fas fa-check"></i>',
            label: "已完成",
            panel: "border-emerald-200 bg-emerald-50/60",
        },
        active: {
            item: "border-blue-500 bg-blue-50 shadow-sm",
            badge: "bg-blue-600 text-white",
            title: "text-blue-900",
            detail: "text-blue-700",
            icon: '<i class="fas fa-spinner fa-spin"></i>',
            label: "当前步骤",
            panel: "border-blue-200 bg-blue-50/70",
        },
        pending: {
            item: "border-gray-200 bg-gray-50",
            badge: "bg-gray-200 text-gray-500",
            title: "text-gray-700",
            detail: "text-gray-500",
            icon: "",
            label: "待开始",
            panel: "border-gray-200 bg-gray-50",
        },
        failed: {
            item: "border-red-200 bg-red-50",
            badge: "bg-red-500 text-white",
            title: "text-red-800",
            detail: "text-red-700",
            icon: '<i class="fas fa-exclamation"></i>',
            label: "失败",
            panel: "border-red-200 bg-red-50",
        },
    };
    const activeStep = INDUSTRY_REPORT_FLOW_STEPS.find(step => step.key === industryReportWorkspace.activeStep) || INDUSTRY_REPORT_FLOW_STEPS[0];
    const activeState = getIndustryReportStepState(activeStep.key, stage);
    const activeStyle = styleMap[activeState] || styleMap.pending;
    const stepsHtml = INDUSTRY_REPORT_FLOW_STEPS.map((step, index) => {
        const state = getIndustryReportStepState(step.key, stage);
        const style = styleMap[state];
        const number = style.icon || String(index + 1);
        const isActive = step.key === activeStep.key;
        return `
            <div class="relative border ${style.item} ${isActive ? "rounded-t-lg rounded-b-none border-b-white" : "rounded-lg"} px-3 py-2 min-w-0">
                <div class="flex items-start gap-3">
                    <div class="w-7 h-7 rounded-full ${style.badge} flex items-center justify-center text-xs font-bold shrink-0">${number}</div>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center justify-between gap-2">
                            <div class="text-sm font-semibold ${style.title} truncate">${index + 1}. ${escapeIndustryReportHtml(step.title)}</div>
                            <span class="hidden xl:inline text-[11px] font-medium ${style.detail} whitespace-nowrap">${style.label}</span>
                        </div>
                        <div class="text-xs ${style.detail} mt-0.5 truncate">${escapeIndustryReportHtml(step.detail)}</div>
                    </div>
                </div>
                ${isActive ? '<div class="absolute left-0 right-0 -bottom-px h-px bg-white"></div>' : ""}
            </div>
        `;
    }).join("");
    box.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-5 gap-2 items-end">${stepsHtml}</div>
    `;
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
        const tasks = hasTasks
            ? industryReportWorkspace.writingTasks.map((task, index) => ({
                key: task.outline_id || `task_${index + 1}`,
                title: task.title || `写作任务 ${index + 1}`,
                parent: task.parent_level1_title || "",
                indexLabel: task.outline_id || String(index + 1),
                status: "已统筹",
                statusState: "done",
            }))
            : flattenIndustryReportOutlineSubsections().map(item => ({
                ...item,
                status: "待统筹",
                statusState: "pending",
            }));
        if (!hasTasks && industryReportWorkspace.currentStage === "coordinator" && tasks.length) {
            tasks.forEach(item => {
                item.status = "进行中";
                item.statusState = "active";
            });
        }
        return tasks;
    }
    if (stepKey === "body") {
        const generatedById = new Map((industryReportWorkspace.bodySections || []).map(section => [section.outline_id, section]));
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
            const failed = generated && generated.status !== "success";
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
    return [];
}

function renderIndustryReportActiveStepPanel(step, style) {
    const items = getIndustryReportStepSubitems(step.key);
    const groups = groupIndustryReportStepItems(items);
    const emptyText = getIndustryReportStepEmptyText(step.key);
    return `
        <div class="border ${style.panel} rounded-b-lg rounded-tr-lg px-4 py-3 min-h-[86px]">
            <div class="flex items-center justify-between gap-3 mb-2">
                <div class="font-semibold ${style.title}">${escapeIndustryReportHtml(step.title)}任务明细</div>
                <div class="text-xs ${style.detail}">${escapeIndustryReportHtml(style.label)}</div>
            </div>
            ${groups.length ? `
                <div class="space-y-3 max-h-64 overflow-y-auto pr-1">
                    ${groups.map(group => renderIndustryReportStepGroup(group)).join("")}
                </div>
            ` : `<div class="text-sm ${style.detail}">${escapeIndustryReportHtml(emptyText)}</div>`}
        </div>
    `;
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
        requirement: "填写左侧报告需求后，点击生成大纲开始。",
        outline: "大纲生成后，这里会列出二级小标题。",
        coordinator: "确认大纲后，这里会列出统筹拆分出的写作任务。",
        body: "开始生成正文后，这里会显示每个二级标题的生成状态。",
        review: "正文生成完成后，可以在下方预览、重写、保存或导出。",
    };
    return map[stepKey] || "等待任务开始。";
}

async function industryReportApi(path, options = {}) {
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
    const industry = getIndustryReportCurrentIndustry();
    const defaultTitle = getIndustryReportDefaultTitle(industry);
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
        outline: [],
        writingTasks: [],
        bodySections: [],
        warnings: [],
        activeSectionId: "",
        rewriteMaterials: null,
        pendingRewrite: null,
        busy: false,
        requirementRewriteSeq: 0,
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
    setIndustryReportStage("idle", "等待输入报告需求");
    setIndustryReportStatus("等待输入需求", "info");
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
    const { prompt, title, industry } = getIndustryReportFormValues();
    if (!prompt) {
        setIndustryReportStatus("请先输入报告需求", "error");
        return;
    }
    if (!title) {
        setIndustryReportStatus("请先输入报告标题", "error");
        return;
    }
    industryReportWorkspace.requirementRewriteSeq = (industryReportWorkspace.requirementRewriteSeq || 0) + 1;
    setIndustryReportBusy(true, "正在理解题目与需求并生成写作任务卡...");
    clearIndustryReportStepDone(["requirement", "outline", "coordinator", "body", "review"]);
    setIndustryReportStage("idle", "正在生成写作任务卡");
    try {
        const data = await industryReportApi("/api/report/task-card", {
            method: "POST",
            body: JSON.stringify({ title, user_requirement: prompt, page_industry: industry }),
        });
        industryReportWorkspace.historyId = "";
        industryReportWorkspace.userPrompt = prompt;
        industryReportWorkspace.reportTitle = title;
        industryReportWorkspace.pageIndustry = industry;
        industryReportWorkspace.industry = data.task_card?.selected_industry || "";
        industryReportWorkspace.taskCard = data.task_card || null;
        industryReportWorkspace.outline = [];
        industryReportWorkspace.writingTasks = [];
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.abstractText = "";
        industryReportWorkspace.warnings = [];
        appendIndustryReportWarnings(data.warnings);
        renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
        renderIndustryReportOutline([]);
        renderIndustryReportProgress([]);
        renderIndustryReportPreview();
        setIndustryReportStage("idle", "写作任务卡已生成，等待确认");
        const fallback = getIndustryReportRequirementFallbackWarning(data.warnings);
        setIndustryReportStatus(
            fallback?.message || "请检查并编辑写作任务卡，然后生成大纲",
            fallback ? "info" : "success",
        );
    } catch (err) {
        setIndustryReportStage("error", "写作任务卡生成失败");
        setIndustryReportStatus(`写作任务卡生成失败：${err.message}`, "error");
    } finally {
        setIndustryReportBusy(false);
    }
}

function renderIndustryReportTaskCard(taskCard) {
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
        if (recognizedIndustry) recognizedIndustry.textContent = "待生成";
        if (selectedIndustry) {
            selectedIndustry.innerHTML = `<option value="${escapeIndustryReportHtml(industry)}">${escapeIndustryReportHtml(getIndustryReportIndustryName(industry))}</option>`;
            selectedIndustry.value = industry;
        }
        if (suggestionBox) suggestionBox.classList.add("hidden");
        if (suggestionOptions) suggestionOptions.innerHTML = "";
        if (resultBox) resultBox.innerHTML = '<div>提交题目与需求后，系统会生成可编辑的写作任务卡、参考标题和产业匹配结果。</div>';
        if (state) state.textContent = "待生成";
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.classList.add("opacity-60", "cursor-not-allowed");
    }
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
                <label class="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
                    <input type="radio" name="industry-report-title-suggestion" value="${escapeIndustryReportHtml(title)}"
                           onchange="selectIndustryReportSuggestedTitle(this.value)" class="mt-1 text-blue-600"${checked}>
                    <span class="leading-5">${escapeIndustryReportHtml(title)}</span>
                </label>
            `;
        }).join("");
    }

    if (selectedIndustry) {
        const matches = Array.isArray(taskCard.industry_matches) ? taskCard.industry_matches : [];
        selectedIndustry.innerHTML = [
            '<option value="">不使用产业图谱</option>',
            ...matches.map(item => `<option value="${escapeIndustryReportHtml(item.key || "")}">${escapeIndustryReportHtml(item.name || item.key || "未知产业")}${item.graph_available ? "（图谱可用）" : "（无可用图谱）"}</option>`),
        ].join("");
        selectedIndustry.value = taskCard.selected_industry || "";
    }
    updateIndustryReportTaskCardMatch();
}

function selectIndustryReportSuggestedTitle(title) {
    const input = document.getElementById("industry-report-task-title");
    if (input) input.value = title || "";
}

async function handleIndustryReportSelectedIndustryChange() {
    updateIndustryReportTaskCardMatch();
    const taskCard = industryReportWorkspace.taskCard;
    if (!taskCard) return;
    const rewriteSeq = (industryReportWorkspace.requirementRewriteSeq || 0) + 1;
    industryReportWorkspace.requirementRewriteSeq = rewriteSeq;
    const selectedIndustry = document.getElementById("industry-report-selected-industry")?.value || "";
    const requirementInput = document.getElementById("industry-report-task-requirement");
    const confirmBtn = document.getElementById("report-task-card-confirm-btn");
    if (!selectedIndustry) {
        if (requirementInput) {
            requirementInput.disabled = false;
            requirementInput.value = taskCard.report_requirement || requirementInput.value;
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
            graph_match: {
                status: match.graph_available ? "matched" : "unavailable",
                industry: selectedIndustry,
                industry_name: match.name || "",
                graph_available: Boolean(match.graph_available),
            },
        };
        industryReportWorkspace.userPrompt = rewrittenRequirement;
        industryReportWorkspace.industry = selectedIndustry;
        if (requirementInput) requirementInput.value = rewrittenRequirement;
        appendIndustryReportWarnings(data.warnings);
        const fallback = getIndustryReportRequirementFallbackWarning(data.warnings);
        setIndustryReportStatus(
            fallback?.message || "报告需求已根据新的最终产业方向更新",
            fallback ? "info" : "success",
        );
    } catch (err) {
        if (industryReportWorkspace.requirementRewriteSeq !== rewriteSeq) return;
        if (requirementInput) requirementInput.value = taskCard.report_requirement || "";
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
    const selectedKey = document.getElementById("industry-report-selected-industry")?.value || "";
    const match = (taskCard.industry_matches || []).find(item => item.key === selectedKey);
    const conflict = taskCard.industry_conflict
        ? `<div class="mb-2 text-amber-700">当前页面产业与模型识别结果不同，请确认最终产业方向。</div>`
        : "";
    if (!match) {
        resultBox.innerHTML = `${conflict}<div>未选择产业图谱。系统将基于已有资料和大模型能力继续生成，后续不会使用特定产业图谱作为证据源。</div>`;
        return;
    }
    const graphText = match.graph_available
        ? "已匹配可用产业图谱，后续生成将调用该图谱。"
        : "该产业暂无可用图谱，将自动使用已有资料和大模型能力继续生成。";
    const reasonText = String(match.reason || "").trim() || "系统支持";
    const reason = `<div class="mt-1"><span class="font-semibold text-gray-700">依据：</span>${escapeIndustryReportHtml(reasonText)}</div>`;
    resultBox.innerHTML = `${conflict}<div><span class="font-semibold text-gray-700">当前选择产业：</span>${escapeIndustryReportHtml(match.name || match.key)}</div>${reason}<div class="mt-1"><span class="font-semibold text-gray-700">图谱匹配：</span>${graphText}</div><div class="mt-1 text-xs text-gray-500">最终产业方向会决定后续知识图谱、外部资料库和正文生成的产业上下文。</div>`;
}

function readIndustryReportTaskCardFromDom() {
    const taskCard = industryReportWorkspace.taskCard;
    if (!taskCard) return null;
    const selectedIndustry = document.getElementById("industry-report-selected-industry")?.value || "";
    const match = (taskCard.industry_matches || []).find(item => item.key === selectedIndustry);
    return {
        ...taskCard,
        selected_title: (document.getElementById("industry-report-task-title")?.value || "").trim(),
        report_requirement: (document.getElementById("industry-report-task-requirement")?.value || "").trim(),
        selected_industry: selectedIndustry,
        selected_industry_name: match?.name || "",
        selection_source: "user",
        graph_match: {
            status: match?.graph_available ? "matched" : "unavailable",
            industry: selectedIndustry,
            industry_name: match?.name || "",
            graph_available: Boolean(match?.graph_available),
        },
    };
}

async function generateIndustryReportOutline() {
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
    setIndustryReportBusy(true, "正在根据确认任务卡生成大纲...");
    clearIndustryReportStepDone(["outline", "coordinator", "body", "review"]);
    markIndustryReportStepDone("requirement");
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
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.abstractText = "";
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
        setIndustryReportCompletionStatus("推荐大纲已生成，可继续编辑");
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

function hasIndustryReportOutline(outline = industryReportWorkspace.outline) {
    return Array.isArray(outline) && outline.length > 0;
}

function syncIndustryReportOutlineConfirmButton(outline = industryReportWorkspace.outline) {
    const btn = document.getElementById("report-outline-confirm-btn");
    if (!btn) return;
    const disabled = industryReportWorkspace.busy || !hasIndustryReportOutline(outline);
    btn.disabled = disabled;
    btn.classList.toggle("opacity-60", disabled);
    btn.classList.toggle("cursor-not-allowed", disabled);
}

function renderIndustryReportOutline(outline) {
    const box = document.getElementById("industry-report-outline");
    if (!box) return;
    if (!outline || !outline.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">生成推荐大纲后可编辑</div>';
        syncIndustryReportOutlineConfirmButton([]);
        renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
        return;
    }
    box.innerHTML = outline.map((section, sectionIndex) => `
        <div class="border border-gray-200 rounded-lg p-4 bg-gray-50" data-report-section="${sectionIndex}">
            <div class="flex items-center gap-2">
                <span class="text-xs font-bold text-indigo-600 w-6">${sectionIndex + 1}</span>
                <input class="report-section-title flex-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium"
                       value="${escapeIndustryReportHtml(section.level1_title || "")}">
                <button onclick="addIndustryReportSubsection(${sectionIndex})" class="w-8 h-8 rounded-lg bg-white border border-gray-300 hover:bg-gray-100 text-gray-600" title="新增二级标题">
                    <i class="fas fa-plus"></i>
                </button>
                <button onclick="removeIndustryReportSection(${sectionIndex})" class="w-8 h-8 rounded-lg bg-white border border-gray-300 hover:bg-red-50 text-red-500" title="删除章节">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <div class="mt-3 space-y-2">
                ${(section.subsections || []).map((sub, subIndex) => `
                    <div class="rounded-lg bg-white border border-gray-200 p-2" data-report-subsection="${subIndex}">
                        <div class="flex items-center gap-2">
                            <span class="text-xs text-gray-400 w-8">${sectionIndex + 1}.${subIndex + 1}</span>
                            <input class="report-subsection-title flex-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm"
                                   value="${escapeIndustryReportHtml(sub.title || "")}">
                            <button onclick="removeIndustryReportSubsection(${sectionIndex}, ${subIndex})" class="w-8 h-8 rounded-lg bg-white border border-gray-300 hover:bg-red-50 text-red-500" title="删除二级标题">
                                <i class="fas fa-minus"></i>
                            </button>
                        </div>
                    </div>
                `).join("")}
            </div>
        </div>
    `).join("");
    syncIndustryReportOutlineConfirmButton(outline);
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
            const previousSub = previous.subsections?.[subIndex] || {};
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
    const outline = readIndustryReportOutlineFromDom();
    const index = outline.length + 1;
    outline.push({
        level1_id: `S${index}`,
        level1_title: "新增章节",
        section_type: "body",
        subsections: [{ outline_id: `S${index}.1`, title: "新增二级标题", generation_instruction: "", expected_words: 800 }],
    });
    industryReportWorkspace.outline = outline;
    renderIndustryReportOutline(outline);
}

function addIndustryReportSubsection(sectionIndex) {
    const outline = readIndustryReportOutlineFromDom();
    if (!outline[sectionIndex]) return;
    const next = (outline[sectionIndex].subsections || []).length + 1;
    outline[sectionIndex].subsections.push({
        outline_id: `${outline[sectionIndex].level1_id}.${next}`,
        title: "新增二级标题",
        generation_instruction: "",
        expected_words: 800,
    });
    industryReportWorkspace.outline = outline;
    renderIndustryReportOutline(outline);
}

function removeIndustryReportSection(sectionIndex) {
    const outline = readIndustryReportOutlineFromDom();
    outline.splice(sectionIndex, 1);
    industryReportWorkspace.outline = outline;
    renderIndustryReportOutline(outline);
}

function removeIndustryReportSubsection(sectionIndex, subIndex) {
    const outline = readIndustryReportOutlineFromDom();
    if (!outline[sectionIndex]) return;
    outline[sectionIndex].subsections.splice(subIndex, 1);
    industryReportWorkspace.outline = outline;
    renderIndustryReportOutline(outline);
}

async function prepareIndustryReportTasks() {
    const formValues = getIndustryReportFormValues();
    const title = industryReportWorkspace.taskCard?.selected_title || industryReportWorkspace.reportTitle || formValues.title;
    const effectivePrompt = industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || title;
    const reportIndustry = industryReportWorkspace.taskCard ? industryReportWorkspace.industry : formValues.industry;
    industryReportWorkspace.outline = readIndustryReportOutlineFromDom();
    if (!title) {
        setIndustryReportStatus("请先输入报告标题", "error");
        return null;
    }
    if (!countIndustryReportSubsections(industryReportWorkspace.outline)) {
        setIndustryReportStatus("请先生成或填写至少一个二级标题", "error");
        return null;
    }
    setIndustryReportBusy(true, "正在统筹写作任务...");
    clearIndustryReportStepDone(["coordinator", "body", "review"]);
    setIndustryReportStage("coordinator", "正在检索资料并生成写作任务");
    try {
        const data = await industryReportApi("/api/report/coordinator", {
            method: "POST",
            body: JSON.stringify({
                user_prompt: effectivePrompt,
                report_title: title,
                industry: reportIndustry,
                outline: industryReportWorkspace.outline,
                top_k: getIndustryReportNumber("industry-report-top-k", 10),
            }),
        });
        industryReportWorkspace.userPrompt = effectivePrompt;
        industryReportWorkspace.reportTitle = title;
        industryReportWorkspace.industry = reportIndustry;
        industryReportWorkspace.writingTasks = data.writing_tasks || [];
        appendIndustryReportWarnings(data.warnings);
        renderIndustryReportProgress([
            { key: "outline", title: "推荐大纲", status: "done", detail: `${countIndustryReportSubsections(industryReportWorkspace.outline)} 个二级标题` },
            { key: "coordinator", title: "写作任务", status: "done", detail: `${industryReportWorkspace.writingTasks.length} 个任务` },
            { key: "body", title: "正文生成", status: "pending", detail: "等待开始" },
        ]);
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        markIndustryReportStepDone("coordinator");
        setIndustryReportStage("coordinator", "写作任务已生成");
        setIndustryReportCompletionStatus("大纲已确认，写作任务已生成");
        return data;
    } catch (err) {
        setIndustryReportStage("error", "写作任务生成失败");
        setIndustryReportStatus(`写作任务生成失败：${err.message}`, "error");
        return null;
    } finally {
        setIndustryReportBusy(false);
    }
}

async function startIndustryReportGeneration() {
    if (!industryReportWorkspace.writingTasks.length) {
        const prepared = await prepareIndustryReportTasks();
        if (!prepared) return;
    }
    const formValues = getIndustryReportFormValues();
    const title = industryReportWorkspace.taskCard?.selected_title || industryReportWorkspace.reportTitle || formValues.title;
    const effectivePrompt = industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || title;
    const reportIndustry = industryReportWorkspace.taskCard ? industryReportWorkspace.industry : formValues.industry;
    setIndustryReportBusy(true, "正在生成正文，这一步可能需要较长时间...");
    clearIndustryReportStepDone(["body", "review"]);
    setIndustryReportStage("body", "正在生成正文");
    renderIndustryReportProgress(buildIndustryReportTaskProgress("generating"));
    try {
        const data = await industryReportApi("/api/report/body", {
            method: "POST",
            body: JSON.stringify({
                user_prompt: effectivePrompt,
                report_title: title,
                industry: reportIndustry,
                writing_tasks: industryReportWorkspace.writingTasks,
                max_workers: getIndustryReportNumber("industry-report-workers", 3),
            }),
        });
        industryReportWorkspace.bodySections = normalizeIndustryReportBodySections(data.body_sections || []);
        appendIndustryReportWarnings(data.warnings);
        try {
            setIndustryReportStatus("正文已生成，正在生成摘要...", "loading");
            industryReportWorkspace.abstractText = await generateIndustryReportSummaryForWord(title, industryReportWorkspace.bodySections);
        } catch (summaryErr) {
            industryReportWorkspace.abstractText = buildIndustryReportAbstractForWord(industryReportWorkspace.bodySections);
        }
        renderIndustryReportProgress(buildIndustryReportTaskProgress("generated", industryReportWorkspace.bodySections));
        renderIndustryReportPreview();
        void saveIndustryReportHistory({ silent: true });
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        markIndustryReportStepDone("coordinator");
        markIndustryReportStepDone("body");
        setIndustryReportStage("done", "报告正文已生成");
        setIndustryReportCompletionStatus("报告正文已生成");
    } catch (err) {
        renderIndustryReportProgress(buildIndustryReportTaskProgress("failed"));
        setIndustryReportStage("error", "正文生成失败");
        setIndustryReportStatus(`正文生成失败：${err.message}`, "error");
    } finally {
        setIndustryReportBusy(false);
    }
}

function normalizeIndustryReportBodySections(sections) {
    return (sections || []).map((section, index) => ({
        ...section,
        outline_id: section.outline_id || `section_${index + 1}`,
        status: section.status || "success",
        body_text: normalizeIndustryReportParagraphText(section.body_text || section.text || ""),
        graph_evidence_blocks: section.graph_evidence_blocks || [],
        external_evidence_blocks: section.external_evidence_blocks || [],
    }));
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
    const box = document.getElementById("industry-report-preview");
    if (!box) return;
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    industryReportWorkspace.reportTitle = title;
    if (!industryReportWorkspace.bodySections.length) {
        box.innerHTML = `
            <div class="border-b border-gray-200 pb-4">
                <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
            </div>
            <div class="text-gray-400">暂无正文内容</div>
        `;
        return;
    }
    const groups = groupIndustryReportBodySections();
    box.innerHTML = `
        <div class="border-b border-gray-200 pb-4">
            <h1 class="text-2xl font-bold text-gray-900 leading-tight">${escapeIndustryReportHtml(title)}</h1>
        </div>
        ${renderIndustryReportAbstractBlock()}
        ${groups.map((group, groupIndex) => `
            <article class="border-b border-gray-200 pb-4 last:border-b-0">
                <h2 class="text-xl font-bold text-gray-900 mb-3">${groupIndex + 1}. ${escapeIndustryReportHtml(group.title)}</h2>
                <div class="space-y-4">
                    ${group.children.map((section, sectionIndex) => renderIndustryReportBodySection(section, groupIndex + 1, sectionIndex + 1)).join("")}
                </div>
            </article>
        `).join("")}
    `;
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
    syncIndustryReportBodySectionsFromDom();
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const bodySections = industryReportWorkspace.bodySections || [];
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
                 data-placeholder="可在这里手动修改正文内容">${renderIndustryReportParagraphs(bodyText)}</div>
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
    const normalized = normalizeIndustryReportParagraphText(value);
    industryReportWorkspace.bodySections = industryReportWorkspace.bodySections.map(section => {
        if (section.outline_id !== outlineId) return section;
        return { ...section, body_text: normalized };
    });
    const sectionEl = Array.from(document.querySelectorAll("[data-report-body-section]"))
        .find(el => el.getAttribute("data-report-body-section") === outlineId);
    const countEl = sectionEl?.querySelector(".industry-report-section-count");
    if (countEl) countEl.textContent = `${countIndustryReportWords(normalized)} 字`;
}

function updateIndustryReportAbstractText(el) {
    const value = normalizeIndustryReportParagraphText(getIndustryReportEditableText(el));
    industryReportWorkspace.abstractText = value;
    const countEl = document.getElementById("industry-report-abstract-count");
    if (countEl) countEl.textContent = `${countIndustryReportWords(value)} 字`;
}

function renderIndustryReportEvidenceDetails(section) {
    const graphBlocks = section.graph_evidence_blocks || [];
    const externalBlocks = section.external_evidence_blocks || [];
    if (!graphBlocks.length && !externalBlocks.length) return "";
    return `
        <details class="mt-3 rounded-lg border border-gray-200 bg-white">
            <summary class="cursor-pointer px-3 py-2 text-xs font-semibold text-gray-600">查看本节资料依据</summary>
            <div class="p-3 space-y-3">
                ${graphBlocks.map((item, index) => renderIndustryReportEvidenceCard(item, `知识图谱 ${index + 1}`, "graph")).join("")}
                ${externalBlocks.map((item, index) => renderIndustryReportEvidenceCard(item, `外部资料 ${index + 1}`, "external")).join("")}
            </div>
        </details>
    `;
}

function renderIndustryReportEvidenceCard(item, fallbackTitle, type = "external") {
    const title = getIndustryReportEvidenceTitle(item, fallbackTitle);
    const text = getIndustryReportEvidenceText(item);
    const nodeId = type === "graph" ? getIndustryReportGraphNodeId(item) : "";
    const graphLink = nodeId ? buildIndustryReportGraphLink(nodeId) : "";
    const titleLabel = type === "graph" ? "图谱位置" : "文章标题";
    const textLabel = type === "graph" ? "具体形式" : "段落内容";
    return `
        <div class="rounded-lg bg-gray-50 border border-gray-200 p-3">
            <div class="text-xs font-semibold text-gray-700 flex items-center justify-between gap-2">
                <span class="min-w-0 truncate">${titleLabel}：${escapeIndustryReportHtml(title)}</span>
                ${graphLink ? `<a href="${escapeIndustryReportHtml(graphLink)}" data-graph-node-id="${escapeIndustryReportHtml(nodeId)}" onclick="return openIndustryReportGraph(this.dataset.graphNodeId)" class="text-blue-600 hover:text-blue-700 font-medium">打开图谱</a>` : ""}
            </div>
            <div class="mt-1 text-xs leading-5 text-gray-500">${textLabel}：${escapeIndustryReportHtml(truncateIndustryReportText(text, 260))}</div>
        </div>
    `;
}

function getIndustryReportGraphNodeId(item) {
    return item?.level3?.id ?? item?.node_id ?? item?.id ?? "";
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
    industryReportWorkspace.pendingRewrite = null;
    const modal = document.getElementById("industry-report-rewrite-modal");
    const meta = document.getElementById("industry-report-rewrite-meta");
    const prompt = document.getElementById("industry-report-rewrite-prompt");
    const materials = document.getElementById("industry-report-materials");
    const preview = document.getElementById("industry-report-rewrite-preview");
    if (meta) meta.textContent = `${section.parent_level1_title || "正文"} · ${section.title || ""}`;
    if (prompt) prompt.value = "";
    if (materials) materials.innerHTML = "点击“推荐资料”后显示";
    if (preview) preview.innerHTML = '<div class="border border-gray-200 rounded-lg p-3 bg-gray-50 text-gray-500">生成后显示对比</div>';
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
            }),
        });
        industryReportWorkspace.pendingRewrite = data;
        renderIndustryReportRewritePreview(section, data);
    } catch (err) {
        if (preview) preview.innerHTML = `<div class="text-red-600">重写失败：${escapeIndustryReportHtml(err.message)}</div>`;
    }
}

function renderIndustryReportRewritePreview(original, rewritten) {
    const box = document.getElementById("industry-report-rewrite-preview");
    if (!box) return;
    const originalText = original.body_text || "";
    const rewrittenText = rewritten.body_text || "";
    box.innerHTML = `
        <div class="grid grid-cols-2 gap-3">
            <div class="rounded-lg border border-gray-200 bg-gray-50 p-3 min-w-0">
                <div class="flex items-center justify-between gap-2 mb-2">
                    <div class="text-xs font-semibold text-gray-500">原正文</div>
                    <div class="text-xs text-gray-400">${countIndustryReportWords(originalText)} 字</div>
                </div>
                <div class="text-sm leading-6 text-gray-700 whitespace-pre-wrap max-h-[520px] overflow-y-auto">${escapeIndustryReportHtml(originalText)}</div>
            </div>
            <div class="rounded-lg border border-emerald-200 bg-emerald-50 p-3 min-w-0">
                <div class="flex items-center justify-between gap-2 mb-2">
                    <div class="text-xs font-semibold text-emerald-700">重写后</div>
                    <div id="industry-report-rewrite-word-count" class="text-xs text-emerald-700">${countIndustryReportWords(rewrittenText)} 字</div>
                </div>
                <textarea oninput="updateIndustryReportPendingRewriteText(this.value)"
                          class="w-full min-h-[520px] text-sm leading-6 text-gray-800 bg-white/80 border border-emerald-100 rounded-lg p-3 resize-y focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100"
                          placeholder="可在采用前微调重写内容">${escapeIndustryReportHtml(rewrittenText)}</textarea>
            </div>
        </div>
    `;
}

function updateIndustryReportPendingRewriteText(value) {
    if (industryReportWorkspace.pendingRewrite) {
        industryReportWorkspace.pendingRewrite.body_text = value;
    }
    const countEl = document.getElementById("industry-report-rewrite-word-count");
    if (countEl) countEl.textContent = `${countIndustryReportWords(value)} 字`;
}

function acceptIndustryReportRewrite() {
    const rewritten = industryReportWorkspace.pendingRewrite;
    if (!rewritten || !industryReportWorkspace.activeSectionId) return;
    industryReportWorkspace.bodySections = industryReportWorkspace.bodySections.map(section => {
        if (section.outline_id !== industryReportWorkspace.activeSectionId) return section;
        return {
            ...section,
            body_text: rewritten.body_text || section.body_text,
            graph_evidence_blocks: rewritten.graph_evidence_blocks || section.graph_evidence_blocks || [],
            external_evidence_blocks: rewritten.selected_external_evidence_blocks || section.external_evidence_blocks || [],
        };
    });
    renderIndustryReportPreview();
    void saveIndustryReportHistory({ silent: true });
    closeIndustryReportRewriteModal();
    setIndustryReportStatus("已采用重写内容", "success");
}

function buildIndustryReportHistoryRecord() {
    syncIndustryReportBodySectionsFromDom();
    const title = (industryReportWorkspace.taskCard?.selected_title || document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const prompt = (industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || document.getElementById("industry-report-prompt")?.value || "").trim();
    const now = new Date().toISOString();
    return {
        id: industryReportWorkspace.historyId || `local_report_${Date.now()}`,
        title,
        prompt,
        abstractText: industryReportWorkspace.abstractText || "",
        industry: industryReportWorkspace.industry ?? getIndustryReportCurrentIndustry(),
        pageIndustry: industryReportWorkspace.pageIndustry || getIndustryReportCurrentIndustry(),
        taskCard: industryReportWorkspace.taskCard || null,
        outline: industryReportWorkspace.outline || [],
        writingTasks: industryReportWorkspace.writingTasks || [],
        bodySections: industryReportWorkspace.bodySections || [],
        warnings: industryReportWorkspace.warnings || [],
        createdAt: industryReportWorkspace.historyId ? undefined : now,
        updatedAt: now,
    };
}

async function saveIndustryReportHistory(options = {}) {
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
        outline: record.outline || [],
        writingTasks: record.writingTasks || [],
        bodySections: record.bodySections || [],
        warnings: record.warnings || [],
        activeSectionId: "",
        rewriteMaterials: null,
        pendingRewrite: null,
        busy: false,
        requirementRewriteSeq: 0,
    };
    const titleInput = document.getElementById("industry-report-title");
    const promptInput = document.getElementById("industry-report-prompt");
    if (titleInput) titleInput.value = industryReportWorkspace.reportTitle;
    if (promptInput) promptInput.value = industryReportWorkspace.userPrompt;
    renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
    renderIndustryReportOutline(industryReportWorkspace.outline);
    renderIndustryReportProgress(industryReportWorkspace.bodySections.length
        ? buildIndustryReportTaskProgress("generated", industryReportWorkspace.bodySections)
        : []);
    renderIndustryReportPreview();
    syncIndustryReportHeader();
    renderIndustryReportHistorySelect(record.id);
    setIndustryReportStage(getIndustryReportStageFromRecord(record), "已载入历史报告");
    setIndustryReportStatus("历史报告已载入", "success");
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

async function exportIndustryReportWord() {
    syncIndustryReportBodySectionsFromDom();
    const title = (document.getElementById("industry-report-title")?.value || industryReportWorkspace.reportTitle || "产业报告").trim();
    const bodySections = industryReportWorkspace.bodySections || [];
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
        abstractText = buildIndustryReportAbstractForWord(bodySections);
        industryReportWorkspace.abstractText = abstractText;
    }
    if (!abstractText) {
        setIndustryReportStatus("正文内容为空，无法导出 Word", "error");
        return;
    }

    setIndustryReportStatus("正在导出 Word...", "loading");
    try {
        const data = await industryReportApi("/api/report/export/word", {
            method: "POST",
            body: JSON.stringify({
                report_title: title,
                abstract_text: abstractText,
                industry: industryReportWorkspace.industry ?? getIndustryReportCurrentIndustry(),
                body_sections: bodySections,
            }),
        });
        if (!data.docx_path) {
            throw new Error("后端未返回 Word 文件路径");
        }
        await downloadIndustryReportWord(data.docx_path);
        markIndustryReportStepDone("requirement");
        markIndustryReportStepDone("outline");
        markIndustryReportStepDone("coordinator");
        markIndustryReportStepDone("body");
        markIndustryReportStepDone("review");
        setIndustryReportStage("done", "Word 已生成并下载");
        setIndustryReportStatus("Word 已生成，正在下载", "success");
    } catch (err) {
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
    return lines.join("\n");
}

function getIndustryReportNumber(id, fallback) {
    const value = Number(document.getElementById(id)?.value);
    return Number.isFinite(value) && value > 0 ? value : fallback;
}

function normalizeIndustryReportParagraphText(value) {
    return String(value || "")
        .replace(/\r\n/g, "\n")
        .replace(/\u00a0/g, " ")
        .split(/\n+/)
        .map(line => line.trim())
        .filter(Boolean)
        .join("\n");
}

function renderIndustryReportParagraphs(value) {
    const paragraphs = normalizeIndustryReportParagraphText(value).split("\n").filter(Boolean);
    if (!paragraphs.length) {
        return '<p class="indent-8 min-h-[1.75rem] m-0 text-gray-400">可在这里手动修改内容</p>';
    }
    return paragraphs
        .map(paragraph => `<p class="indent-8 m-0">${escapeIndustryReportHtml(paragraph)}</p>`)
        .join("");
}

function getIndustryReportEditableText(el) {
    return String(el?.innerText || "")
        .replace(/\n{3,}/g, "\n")
        .trim();
}

function getIndustryReportEvidenceTitle(item, fallbackTitle) {
    return item?.source_title
        || item?.article_title
        || item?.document_title
        || item?.doc_title
        || item?.title
        || item?.level3?.name
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
    resetIndustryReportWorkspace();
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

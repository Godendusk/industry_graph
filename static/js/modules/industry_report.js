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
    references: [],
    warnings: [],
    activeSectionId: "",
    rewriteMaterials: null,
    pendingRewrite: null,
    busy: false,
    selectedAgentStep: "requirement",
    bodyProgressById: {},
    coordinatorProgressById: {},
    bodyTotal: 0,
    coordinatorTotal: 0,
    requirementRewriteSeq: 0,
};

let industryReportHistoryIndex = [];
let industryReportRequirementRewriteSeq = 0;

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
    { key: "review", title: "报告导出", detail: "摘要、预览、导出", tone: "green" },
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
        item?.stage === "citation_validation"
        && Array.isArray(item?.invalid_citation_ids)
        && item.invalid_citation_ids.length
    );
}

function showIndustryReportCitationValidationWarning(items) {
    const warning = getIndustryReportCitationValidationWarning(items);
    if (!warning) return;
    setIndustryReportStatus(
        `已移除 ${warning.invalid_citation_ids.length} 个不在本节资料中的引用编号：${warning.invalid_citation_ids.join("、")}`,
        "info",
    );
}

function setIndustryReportCompletionStatus(successText) {
    const ragWarning = getIndustryReportRagWarning();
    const citationWarning = getIndustryReportCitationValidationWarning(industryReportWorkspace.warnings);
    if (citationWarning) {
        setIndustryReportStatus(
            `已移除 ${citationWarning.invalid_citation_ids.length} 个不在本节资料中的引用编号：${citationWarning.invalid_citation_ids.join("、")}`,
            "info",
        );
        return;
    }
    setIndustryReportStatus(ragWarning?.message || successText, ragWarning ? "info" : "success");
}

function setIndustryReportBusy(isBusy, text = "") {
    industryReportWorkspace.busy = Boolean(isBusy);
    ["report-outline-btn", "report-task-card-confirm-btn", "report-outline-confirm-btn", "report-generate-btn"].forEach(id => {
        const btn = document.getElementById(id);
        const shouldDisable = Boolean(isBusy)
            || (id === "report-task-card-confirm-btn" && !industryReportWorkspace.taskCard)
            || (id === "report-outline-confirm-btn" && !hasIndustryReportOutline())
            || (id === "report-generate-btn" && !hasConfirmedIndustryReportOutline());
        if (btn) btn.disabled = shouldDisable;
        if (btn) btn.classList.toggle("opacity-60", shouldDisable);
        if (btn) btn.classList.toggle("cursor-not-allowed", shouldDisable);
    });
    syncIndustryReportGenerateButton();
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

function setIndustryReportRequirementSubmittedStatus() {
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
    box.innerHTML = `
        <div class="flex items-stretch gap-4 overflow-x-auto pb-2">${stepsHtml}</div>
        ${activeStep ? renderIndustryReportActiveStepPanel(activeStep, activeStyle) : ""}
    `;
}

function renderIndustryReportAgentCard(step, index, style, state, selected) {
    const summary = getIndustryReportAgentSummary(step.key);
    const cardShape = selected ? "ring-2 ring-blue-300" : "";
    const robotHtml = step.key === "body"
        ? renderIndustryReportBodyRobots(state)
        : `<div class="mx-auto w-16 h-16 rounded-xl ${style.robot} flex items-center justify-center text-2xl shadow-sm ${state === "active" ? "animate-pulse" : ""}"><i class="fas fa-robot"></i></div>`;
    const connector = index < INDUSTRY_REPORT_FLOW_STEPS.length - 1
        ? '<div class="hidden xl:flex items-center text-blue-300 px-1"><i class="fas fa-arrow-right-long"></i></div>'
        : "";
    return `
        <button type="button"
                onclick="selectIndustryReportAgentStep('${escapeIndustryReportJs(step.key)}')"
                class="text-center border ${style.item} ${cardShape} rounded-lg px-4 py-4 min-w-[190px] flex-1 transition hover:shadow-sm">
            <div class="space-y-4">
                <div class="mx-auto w-full max-w-[150px] rounded-lg border border-blue-700 bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm">
                    ${escapeIndustryReportHtml(step.title)}
                </div>
                ${robotHtml}
                <div>
                    <div class="text-xs font-medium ${style.detail}">${escapeIndustryReportHtml(style.label)}</div>
                    <div class="mt-1 text-sm font-semibold ${style.title} leading-5 min-h-[2.5rem] flex items-center justify-center">${escapeIndustryReportHtml(summary)}</div>
                </div>
            </div>
        </button>
        ${connector}
    `;
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
        const tasks = hasTasks
            ? industryReportWorkspace.writingTasks.map((task, index) => ({
                key: task.outline_id || `task_${index + 1}`,
                title: task.title || `写作任务 ${index + 1}`,
                parent: task.parent_level1_title || "",
                indexLabel: task.outline_id || String(index + 1),
                status: progressById[task.outline_id]?.status || "已统筹",
                statusState: progressById[task.outline_id]?.statusState || "done",
            }))
            : flattenIndustryReportOutlineSubsections().map(item => ({
                ...item,
                status: progressById[item.key]?.status || "待统筹",
                statusState: progressById[item.key]?.statusState || "pending",
            }));
        if (!hasTasks && industryReportWorkspace.currentStage === "coordinator" && tasks.length && !Object.keys(progressById).length) {
            tasks.forEach(item => {
                item.status = "进行中";
                item.statusState = "active";
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
        <div class="border ${style.panel} rounded-b-lg rounded-tr-lg px-4 py-3 min-h-[86px]">
            <div class="flex items-center justify-between gap-3 mb-2">
                <div class="font-semibold ${style.title}">${escapeIndustryReportHtml(step.title)}任务明细</div>
                <div class="text-xs ${style.detail}">${escapeIndustryReportHtml(summary || style.label)}</div>
            </div>
            ${groups.length ? `
                <div class="space-y-3 max-h-64 overflow-y-auto pr-1">
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
        outline: [],
        writingTasks: [],
        bodySections: [],
        references: [],
        warnings: [],
        activeSectionId: "",
        rewriteMaterials: null,
        pendingRewrite: null,
        busy: false,
        selectedAgentStep: "requirement",
        bodyProgressById: {},
        coordinatorProgressById: {},
        bodyTotal: 0,
        coordinatorTotal: 0,
        requirementRewriteSeq,
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
    const { prompt, title, industry } = getIndustryReportFormValues();
    if (!title) {
        setIndustryReportStatus("请先输入报告标题", "error");
        return;
    }
    const taskCardSeq = nextIndustryReportRequirementRewriteSeq();
    setIndustryReportBusy(true, "正在理解题目与需求并生成写作任务卡...");
    clearIndustryReportStepDone(["requirement", "outline", "coordinator", "body", "review"]);
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
        industryReportWorkspace.bodySections = [];
        industryReportWorkspace.references = [];
        industryReportWorkspace.abstractText = "";
        industryReportWorkspace.warnings = [];
        appendIndustryReportWarnings(data.warnings);
        renderIndustryReportTaskCard(industryReportWorkspace.taskCard);
        renderIndustryReportOutline([]);
        renderIndustryReportProgress([]);
        renderIndustryReportPreview();
        setIndustryReportStage("idle", "写作任务卡已生成，等待确认");
        setIndustryReportRequirementSubmittedStatus();
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
        selectedIndustry.innerHTML = matches.map(item => {
            const graphText = item.graph_available ? "图谱可用" : "图谱不可用";
            const ragText = item.external_rag_available ? "外部资料库可用" : "外部资料库不可用";
            const label = `${item.name || item.key || "未知产业"}（${graphText}，${ragText}）`;
            return `<option value="${escapeIndustryReportHtml(item.key || "")}">${escapeIndustryReportHtml(label)}</option>`;
        }).join("");
        selectedIndustry.value = taskCard.selected_industry || "";
    }
    updateIndustryReportTaskCardMatch();
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
    const input = document.getElementById("industry-report-task-title");
    if (input) input.value = title || "";
}

async function handleIndustryReportSelectedIndustryChange() {
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

function invalidateIndustryReportConfirmedOutline() {
    industryReportWorkspace.writingTasks = [];
    industryReportWorkspace.bodySections = [];
    industryReportWorkspace.bodyProgressById = {};
    industryReportWorkspace.coordinatorProgressById = {};
    industryReportWorkspace.bodyTotal = 0;
    industryReportWorkspace.coordinatorTotal = countIndustryReportSubsections(industryReportWorkspace.outline);
    clearIndustryReportStepDone(["coordinator", "body", "review"]);
}

function syncIndustryReportOutlineConfirmButton(outline = industryReportWorkspace.outline) {
    const btn = document.getElementById("report-outline-confirm-btn");
    if (!btn) return;
    const disabled = industryReportWorkspace.busy || !hasIndustryReportOutline(outline);
    btn.disabled = disabled;
    btn.classList.toggle("opacity-60", disabled);
    btn.classList.toggle("cursor-not-allowed", disabled);
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
}

function renderIndustryReportOutline(outline) {
    const box = document.getElementById("industry-report-outline");
    if (!box) return;
    if (!outline || !outline.length) {
        box.innerHTML = '<div class="text-gray-400 text-sm">生成推荐大纲后可编辑</div>';
        syncIndustryReportOutlineConfirmButton([]);
        syncIndustryReportGenerateButton([]);
        renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
        return;
    }
    box.innerHTML = outline.map((section, sectionIndex) => `
        <div class="border border-gray-200 rounded-lg p-4 bg-gray-50" data-report-section="${sectionIndex}">
            <div class="flex items-center gap-2">
                <span class="text-xs font-bold text-indigo-600 w-6">${sectionIndex + 1}</span>
                <input class="report-section-title flex-1 bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium"
                       oninput="handleIndustryReportOutlineInput()"
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
                                   oninput="handleIndustryReportOutlineInput()"
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
    syncIndustryReportGenerateButton(outline);
    renderIndustryReportFlowSteps(industryReportWorkspace.currentStage || "idle");
}

function handleIndustryReportOutlineInput() {
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
    invalidateIndustryReportConfirmedOutline();
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
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

function removeIndustryReportSection(sectionIndex) {
    const outline = readIndustryReportOutlineFromDom();
    outline.splice(sectionIndex, 1);
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

function removeIndustryReportSubsection(sectionIndex, subIndex) {
    const outline = readIndustryReportOutlineFromDom();
    if (!outline[sectionIndex]) return;
    outline[sectionIndex].subsections.splice(subIndex, 1);
    industryReportWorkspace.outline = outline;
    invalidateIndustryReportConfirmedOutline();
    renderIndustryReportOutline(outline);
}

async function prepareIndustryReportTasks() {
    const formValues = getIndustryReportFormValues();
    const title = industryReportWorkspace.taskCard?.selected_title || industryReportWorkspace.reportTitle || formValues.title;
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
    setIndustryReportStage("coordinator", "正在检索资料并生成写作任务");
    industryReportWorkspace.selectedAgentStep = "coordinator";
    industryReportWorkspace.coordinatorProgressById = {};
    industryReportWorkspace.coordinatorTotal = countIndustryReportSubsections(industryReportWorkspace.outline);
    industryReportWorkspace.writingTasks = [];
    try {
        const data = await streamIndustryReportCoordinator({
            user_prompt: effectivePrompt,
            report_title: title,
            industry: reportIndustry,
            outline: industryReportWorkspace.outline,
            top_k: getIndustryReportNumber("industry-report-top-k", 10),
            use_graph: useGraph,
            use_external_rag: useExternalRag,
        });
        industryReportWorkspace.userPrompt = effectivePrompt;
        industryReportWorkspace.reportTitle = title;
        industryReportWorkspace.industry = reportIndustry;
        industryReportWorkspace.writingTasks = data.writing_tasks || [];
        industryReportWorkspace.references = Array.isArray(data.references) ? data.references : [];
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
    if (eventName === "task_started") {
        updateIndustryReportCoordinatorProgress(event, "检索统筹中", "active");
        setIndustryReportStage("coordinator", `正在统筹：${event.title || event.outline_id || "写作任务"}`);
        return event;
    }
    if (eventName === "task_completed" || eventName === "task_failed") {
        const isSuccess = eventName === "task_completed";
        upsertIndustryReportWritingTask(event, Number.isInteger(event.index) ? event.index : undefined);
        updateIndustryReportCoordinatorProgress(event, isSuccess ? "已统筹" : "失败", isSuccess ? "done" : "failed");
        setIndustryReportStage(
            "coordinator",
            `${isSuccess ? "已统筹" : "统筹失败"}：${event.title || event.outline_id || "写作任务"}`,
        );
        return event;
    }
    if (eventName === "completed") {
        industryReportWorkspace.writingTasks = event.writing_tasks || industryReportWorkspace.writingTasks || [];
        industryReportWorkspace.coordinatorTotal = Math.max(
            getIndustryReportCoordinatorTotal(),
            Number(event.total) || 0,
        );
        industryReportWorkspace.references = Array.isArray(event.references) ? event.references : [];
        appendIndustryReportWarnings(event.warnings);
        renderIndustryReportFlowSteps("coordinator");
        setIndustryReportStage("coordinator", `统筹任务完成：已统筹 ${event.success_count || 0} / 共 ${industryReportWorkspace.coordinatorTotal || industryReportWorkspace.writingTasks.length} 个任务`);
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
    const title = industryReportWorkspace.taskCard?.selected_title || industryReportWorkspace.reportTitle || formValues.title;
    const effectivePrompt = industryReportWorkspace.taskCard?.report_requirement || industryReportWorkspace.userPrompt || title;
    const reportIndustry = industryReportWorkspace.taskCard ? industryReportWorkspace.industry : formValues.industry;
    setIndustryReportBusy(true);
    clearIndustryReportStepDone(["body", "review"]);
    setIndustryReportStage("body", "正在生成正文");
    industryReportWorkspace.selectedAgentStep = "body";
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
            industryReportWorkspace.abstractText = buildIndustryReportAbstractForWord(industryReportWorkspace.bodySections);
        }
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
        setIndustryReportStage("done", "报告正文已生成");
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
                onEvent(event);
            }
        }
        if (done) break;
    }
    if (buffer.trim()) {
        const event = parseIndustryReportSseEvent(buffer);
        if (event) {
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
        updateIndustryReportBodyProgress(event, isSuccess ? "已生成" : "失败", isSuccess ? "done" : "failed");
        renderIndustryReportProgress(buildIndustryReportTaskProgress("generating", industryReportWorkspace.bodySections));
        renderIndustryReportPreview();
        setIndustryReportStage(
            "body",
            `${isSuccess ? "已生成" : "生成失败"}：${event.title || event.outline_id || "正文小节"}`,
        );
        return event;
    }
    if (eventName === "completed") {
        industryReportWorkspace.bodySections = normalizeIndustryReportBodySections(event.body_sections || industryReportWorkspace.bodySections || []);
        industryReportWorkspace.bodyTotal = Math.max(
            getIndustryReportBodyTotal(),
            Number(event.total) || 0,
        );
        appendIndustryReportWarnings(event.warnings);
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
    renderIndustryReportFlowSteps("coordinator");
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

function normalizeIndustryReportBodySections(sections) {
    return (sections || []).map((section, index) => ({
        ...section,
        outline_id: section.outline_id || `section_${index + 1}`,
        status: section.status || "success",
        body_text: normalizeIndustryReportParagraphText(section.body_text || section.text || ""),
        graph_evidence_blocks: section.graph_evidence_blocks || [],
        external_evidence_blocks: section.external_evidence_blocks || [],
        citation_ids: Array.isArray(section.citation_ids) ? section.citation_ids : [],
    }));
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
        ${renderIndustryReportReferences()}
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
    const normalized = normalizeIndustryReportParagraphText(value);
    industryReportWorkspace.bodySections = industryReportWorkspace.bodySections.map(section => {
        if (section.outline_id !== outlineId) return section;
        return {
            ...section,
            body_text: normalized,
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

function renderIndustryReportReferences() {
    const usedIds = new Set((industryReportWorkspace.bodySections || [])
        .flatMap(section => Array.isArray(section.citation_ids) ? section.citation_ids : []));
    const references = (industryReportWorkspace.references || [])
        .filter(item => usedIds.has(item?.citation_id));
    if (!references.length) return "";
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
                references: industryReportWorkspace.references || [],
            }),
        });
        appendIndustryReportWarnings(data.warnings);
        showIndustryReportCitationValidationWarning(data.warnings);
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
        industryReportWorkspace.pendingRewrite.citation_ids = extractIndustryReportCitationIds(
            value,
            industryReportWorkspace.pendingRewrite.selected_external_evidence_blocks
                || industryReportWorkspace.references,
        );
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
    renderIndustryReportPreview();
    void saveIndustryReportHistory({ silent: true });
    closeIndustryReportRewriteModal();
    setIndustryReportStatus("已采用重写内容", "success");
    showIndustryReportCitationValidationWarning(industryReportWorkspace.warnings);
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
        references: industryReportWorkspace.references || [],
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
        outline: record.outline || [],
        writingTasks: record.writingTasks || [],
        bodySections: record.bodySections || [],
        references: Array.isArray(record.references) ? record.references : [],
        warnings: record.warnings || [],
        activeSectionId: "",
        rewriteMaterials: null,
        pendingRewrite: null,
        busy: false,
        selectedAgentStep: getIndustryReportActiveStepKey(getIndustryReportStageFromRecord(record)),
        bodyProgressById: {},
        coordinatorProgressById: {},
        bodyTotal: Array.isArray(record.writingTasks) ? record.writingTasks.length : 0,
        coordinatorTotal: countIndustryReportSubsections(record.outline || []),
        requirementRewriteSeq,
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
                references: industryReportWorkspace.references || [],
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

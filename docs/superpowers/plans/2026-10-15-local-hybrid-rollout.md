# 本机混合检索正式接入与报告验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:executing-plans，在当前会话逐项执行；步骤用复选框记录。用户已授权执行；2026-10-15 已完成七产业正式接入和八产业检索验收，报告生成已完成；bundled LibreOffice 中文字体缺失导致视觉渲染验收未完成，实际结果见本轮 acceptance.md。

**Goal:** 让八个产业的日常报告流程使用现有混合检索，并完成七产业正式索引就绪、八产业真实检索和两份完整报告的验收。

**Architecture:** 人工智能继续使用既有 report_v2；其他七产业复用原 Chroma 向量和各自的 FTS5 关键词索引，沿现有召回、RRF 融合、BGE 重排与引用链路运行。优先复用正式目录中可用的索引，将缺失项从验证目录同盘移动，不重新嵌入或新增索引管理框架。

**Tech Stack:** Python / kunlun、Chroma、SQLite FTS5、jieba、BGE embedding/reranker、Flask、现有报告生成与 Word 导出模块。

---

## 一、已确认的基础与本次边界

项目根目录：`/Users/livictor/Desktop/industry/industry_graph`。以下相对路径和命令均以此为工作目录。

- 七产业验证索引：`report_generation/outputs/hybrid-local-validation/<industry>/`，产业依次为 biology、quantum、brain、material、sea、low_altitude、embodied。
- 正式关键词索引：`RAG/indexes/report_v2_news/<industry>/`；AI 为 `RAG/indexes/report_v2/`。
- 2026-10-14 构建记录：七产业合计 2,148,648 块、324,921 篇文章，关键词文件约 15.432 GiB；真实混合检索与单小节写作已通过。该记录不是当前正式服务验收。
- 2026-10-15 编写计划时，正式目录已经存在 embodied 的 READY、约 10.35 GiB lexical.sqlite3，另有约 8 GiB lexical.staging.sqlite3 和 BUILD.lock。来源及当前有效性尚未核实，不能覆盖或直接删除。
- 当前存在报告审阅、图谱、摘要、前端等未提交改动。本次不合并旧 worktree 方案，不重置、提交或清理他人的文件。
- 这是一轮部署与验收，预期无需修改产品代码。若暴露代码缺陷，记录具体触发条件，先增加针对该失败的测试，再做最小修复；不借机重构。
- 不要求所有产业生成完整报告，也不将本轮结果解释成“混合检索质量已经全面优于旧版”。

## 二、涉及文件及职责

| 路径 | 用途与处理 |
| --- | --- |
| `report_generation/external_rag/news_index.py` | 使用 check_news_index / build_news_index 的现有就绪与同步逻辑，默认不修改 |
| `scripts/build_news_hybrid_index.py` | 正式路径就绪检查；仅对实际失效产业执行 sync |
| `scripts/verify_industry_hybrid_rag.py` | 八产业真实召回与重排验收，不启用 writing-tasks |
| `backend_server.py` | 确认实际服务及报告入口；默认不修改 |
| `report_generation/outputs/hybrid-local-validation/` | 已构建索引及历史证据，保留历史验证结果 |
| `report_generation/outputs/hybrid-rollout-20261015/` | 执行时新建；保存迁移记录、就绪结果、检索结果、报告与验收说明 |
| `docs/industry-hybrid-retrieval.md` | 验收完成后补充 macOS 本机运行命令、路径与实际状态 |

输出目录中的文件按现有 Git 忽略规则存放，不上传索引、模型或生成报告。文档只记录配置名称，不记录令牌。

## 三、执行步骤

### 任务 1：确认运行基线，决定哪些索引需要接入

**检查目的：** 发现正式索引已存在、源资料已更新、服务仍有任务或工作区发生变化。分别决定复用、同步、延后切换或记录新的验收基线。

- [x] 记录 `git rev-parse HEAD`、`git status --short`，保存到本轮输出目录；不改动列出的其他工作。
- [x] 使用 `/opt/miniconda3/envs/kunlun/bin/python`；若该环境不可用，查找现有后端实际使用的解释器，不创建或升级环境。
- [x] 查看当前后端进程、启动目录和端口，以及前端是否有生成中的报告。只操作本项目对应实例；不批量结束 Python 进程。
- [x] 对七产业的正式和验证目录分别调用现有检查，保存 JSON。此步只检查 READY 与源数据关系，不重复全量内容扫描：

```bash
/opt/miniconda3/envs/kunlun/bin/python - <<'PY'
import json
from pathlib import Path
from report_generation.external_rag.news_index import check_news_index
root = Path('report_generation/outputs/hybrid-local-validation')
out = Path('report_generation/outputs/hybrid-rollout-20261015')
out.mkdir(parents=True, exist_ok=True)
rows = []
for industry in ['biology','quantum','brain','material','sea','low_altitude','embodied']:
    rows.append({'industry': industry,
                 'formal': check_news_index(industry),
                 'validation': check_news_index(industry, root=root / industry)})
(out / 'preflight.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
print(json.dumps(rows, ensure_ascii=False, indent=2))
PY
```

- [x] 按结果作决定：正式 ready 就复用；正式缺失且验证 ready 就移动；正式存在但 not_ready 则先记录原因、保留原目录，再选有效验证副本或执行对应产业 sync；两处均失效时先修复该产业，不继续将它计为成功。

**完成条件：** 七产业各有明确处理决定，确认实际服务和当前任务状态。

### 任务 2：接入缺失索引并保留可恢复路径

**检查目的：** 防止覆盖已有可用索引、移动仍在使用的构建目录，或同盘移动被误做成大文件复制。发现这些情况时复用已有项、等现有任务结束或重新安排路径。

- [x] 核实相关 BUILD.lock 对应构建进程是否仍活跃；活动构建结束前不移动其目录。
- [x] 记录每个待移动目录的来源、目标、原目标是否存在和处理结果，保存 `publication-log.json`。使用普通操作记录，不增加哈希或指纹。
- [x] 创建正式父目录。对正式缺失项使用 Python `Path.rename` 同盘移动整个产业目录；目标已存在则不执行 rename。对已有失效目录先改名保留为本轮备份，再移入已通过检查的验证目录。
- [x] 若需要 sync，只对明确失效的产业使用现有命令，例如：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/build_news_hybrid_index.py --industry biology --action sync --workers 1
```

同步会产生 staging 文件；执行前按该产业索引规模确认可用空间。低空和具身依次处理，不并行运行两个大库同步。不因有文件存在就直接改 READY。

- [x] 发布后从默认正式路径执行一次检查并保存输出：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/build_news_hybrid_index.py --industry all --action check > report_generation/outputs/hybrid-rollout-20261015/formal-ready.jsonl
```

**完成条件：** 退出码为 0，七个结果都是 ready。AI 索引不移动。历史背景任务记录保留原样，本轮状态另行记录。

### 任务 3：八产业正式路径真实检索验收

**检查目的：** 发现正式路径加载错误、只有一路召回、重排失败、跨产业结果或隐藏回退。失败时根据该产业诊断定位，不通过切回 legacy 来标记验收成功。

- [x] 用新进程运行现有脚本，禁用回退，不注入验证目录、不 mock 模型：

```bash
REPORT_RETRIEVAL_MODE=hybrid_v2 REPORT_RETRIEVAL_ALLOW_LEGACY_FALLBACK=0 /opt/miniconda3/envs/kunlun/bin/python scripts/verify_industry_hybrid_rag.py --industry all --output report_generation/outputs/hybrid-rollout-20261015/eight-industry-retrieval.json
```

- [x] 要求八产业 status 均 success，full_hybrid、both_recall_routes、real_rerank、industry_isolated、evidence_with_source 均为 true；保存耗时和候选数量作为后续比较依据，不把候选数量当质量评分。
- [x] 不使用 `--writing-tasks` 作为本次门槛：该辅助路径传入空大纲，之前已出现无效承接小节。多小节写作由真实报告流程验证，无须在本轮修辅助脚本。

**完成条件：** 八产业真实检索全部通过；失败项保留原始报错，不反复重跑已通过产业。

### 任务 4：让日常后端使用正式索引

**检查目的：** 发现命令行验证成功但后端仍使用旧模式、旧进程状态或其他 checkout。发现后调整正确实例的启动环境并重新加载。

- [ ] 基于任务 1 识别的实例，保留其端口、启动方式及其他配置；在无进行中报告的窗口重启该实例，启动环境设为 `REPORT_RETRIEVAL_MODE=hybrid_v2`，验收期间设 `REPORT_RETRIEVAL_ALLOW_LEGACY_FALLBACK=0`。不更改全局 shell 配置，不同时启动重复服务。
- [ ] 通过现有登录后的产业报告页面发起真实请求，确认请求到达该实例。接口为 `/api/report/coordinator` 或 `/api/report/coordinator/stream`，请求包含正确 industry 和 `use_external_rag=true`。
- [ ] 保存实际协调器响应或服务诊断，证明报告阶段使用 hybrid_v2 且无回退。只有命令行结果不能满足此项。
- [ ] 验收后恢复服务原有的 fallback 策略，保留 hybrid_v2 模式；记录最终生效配置。若原来允许回退，后续回退仍按现有告警标识，不隐瞒降级。

**完成条件：** 正式后端实际请求使用正式目录中的混合检索。

### 任务 5：两份完整短报告验收

**检查目的：** 发现检索可用但多小节协调、引用传递、摘要或 Word 导出失败。依据失败阶段处理，不默认归因于索引。

- [ ] 使用同一正式后端，依次生成生物制造、具身智能报告。保留正常图谱设置并记录；本轮不将图谱增强的效果归因于关键词索引。
- [ ] 统一要求：面向产业研究读者，每小节约 400—600 字；只陈述资料支持的事实，区分规划、预测与已发生事实；保留引用；资料不足处说明不足。两份均走需求、大纲、协调器、正文、摘要、Word 导出的正常流程，不能只调用单小节函数。
- [ ] 生物制造标题：**生物制造产业发展与应用进展报告**。确认大纲包含两章四小节：技术与产业现状（合成生物与发酵技术、代表性企业与产品）；应用与发展约束（应用场景与产业化案例、技术与商业化约束）。
- [ ] 具身智能标题：**具身智能产业发展与应用进展报告**。确认大纲包含两章四小节：技术与产业现状（核心零部件与感知控制、整机企业与产品）；应用与发展约束（实际应用场景、技术与商业化约束）。
- [ ] 通过页面正常操作执行；必要时使用已登录页面发出的同一 API 调试，不绕过认证。保存请求参数和各阶段 JSON，凭证不写入验收文件。两份报告顺序运行。
- [ ] 每个产业产物置于输出目录自己的子目录：需求与大纲、协调器结果、正文、摘要、导出结果、DOCX、耗时记录和 `acceptance.md`。
- [ ] 阅读全部八个正文小节，记录无依据断言、明显重复或跨产业内容；核对所有引用编号能找到对应参考文献。每小节选至少一条关键事实与原始证据核对，并核对所有核心数量、企业产品和量产状态主张；不把抽样核对写成全文事实已验证。
- [ ] 打开并按文档技能渲染两份导出 DOCX，确认标题、章节、摘要、正文和参考文献均存在，中文可读且无截断、空白异常；如果只能生成但无法打开/渲染，明确标记导出展示验收未完成。

**完成条件：** 两份报告各阶段成功；全部计划小节存在且非占位正文；引用无悬空、检索无隐藏回退；导出可读。质量问题逐条记录证据与所属阶段；阻碍事实可信度的问题修复后再验收受影响阶段。

### 任务 6：收尾、空间清理与使用说明

**检查目的：** 找出已不再需要的 staging/重复副本，以及误被纳入 Git 的大文件；仅在其不承担回退或续建用途时安排清理。

- [ ] 汇总 `acceptance.md`：正式路径、八产业结果、两份报告路径、实际耗时、最终服务配置、未解决问题，分别列明已验证与未验证范围。
- [ ] 核实 embodied 正式目录残留 staging 的构建进程已退出、正式索引已通过验收且不需要续建后，将其列为可清理项。重复验证索引和本轮备份先列出路径与可释放空间，再执行明确授权的删除；不因发布成功自动删除所有验证资料。
- [ ] 用 `git check-ignore` 检查本轮实际产物是否被忽略；若未忽略，补充精准规则，避免把生成物纳入提交。索引不上传 GitHub。
- [ ] 在 `docs/industry-hybrid-retrieval.md` 补充本机 Python 路径、check/sync/verify 命令、后端生效说明以及新增资料后只同步对应产业的操作。
- [ ] 如需提交，仅暂存本计划、实际修改的运行说明及本任务必要修复；先检查暂存 diff，不夹带当前工作区其他修改。

## 四、失败处理与恢复

- 移动后就绪检查失败：停止该项发布；根据 publication-log 将移动目录退回，恢复保留的原正式目录。不要删除任何一份资料以尝试修复。
- 正式目录已 ready：复用它，不以验证目录较新或较大为理由覆盖。
- 源数据确实更新：只同步受影响产业；源路径没有变时无需重建全部向量。
- 模型加载或重排错误：保留诊断，处理本机运行依赖；未完成重排的结果不能作为 full hybrid 验收。
- LLM 超时或限流：保留已完成阶段，只重试失败阶段；不重复构建索引。
- 报告或导出失败：区分协调器、正文、摘要、引用和导出，保留当前其他改动的背景；不盲目回退用户合并的代码。
- 运行恢复优先沿原有启动方式恢复服务。必要时临时使用已有 legacy 模式恢复可用性，并明确记录本轮混合检索尚未通过，不能当作完成。

## 五、交付与实施节奏

顺序为：基线与复用决定 → 缺失索引接入 → 八产业真实检索 → 正式后端生效 → 生物制造完整报告 → 具身智能完整报告 → 汇总与空间整理。

发布属于已有文件移动，正常情况下不需要再次花费整夜构建；主要时间来自模型加载、真实生成与人工证据阅读。若发现源数据变化，则单独报告需要同步的产业和空间，不承诺固定完成时间。

最终交付：七产业正式 READY 结果、八产业真实检索 JSON、两份完整报告及 DOCX、可读验收说明、更新后的本机操作文档。正式服务可用和报告效果分别给出结论。

## 2026-10-15 执行结果

任务 1—3 已完成。任务 4 已重载实际后端并恢复原回退策略，实际协调器响应待模型恢复后验证。任务 5 已完成两份完整报告、引用检查和 DOCX 生成；bundled LibreOffice 无法显示中文，视觉排版验收保留为未完成。任务 6 已完成运行文档、忽略规则核实和清理候选记录，未删除文件、未提交代码。详见 `report_generation/outputs/hybrid-rollout-20261015/acceptance.md`。

# 产业报告审查 Agent 与内容分工实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 仅在用户明确选择并行代理执行时使用 superpowers:subagent-driven-development。

**Goal:** 在既有证据检索、分配、写作分工基础上增加一次全篇重复检查与自动定点修改，保留有用证据和合理复用，输出与实际改动一致的调整说明。

**Architecture:** 统筹负责证据用途、全篇分工和限额内的大纲调整；正文负责初稿；新增 review_agent 负责检查实际重复并修改命中小节；引用校验和前文规则继续共享。普通与流式正文入口均返回审查后的最终正文，摘要和导出使用最终版本；局部重写仅允许修改当前节。

**Tech Stack:** Python、现有 LLMClient/query_result、Flask/SSE、原生 JavaScript、pytest（conda kunlun）、node:test、python-docx。

---

## 0. 工作位置、授权与证据

工作目录：`/Users/livictor/Desktop/industry/industry_graph-fact-reuse`。本文中代码路径均相对此目录。计划只描述实施，不表示代码已经完成。

用户已经同意本方案及自动应用修改，不增加审查结果逐条确认、不新增原稿对比界面。此次请求只编写计划，不运行真实模型、不修改业务代码、不提交已有未提交代码。

依据：

- `docs/superpowers/specs/2026-10-07-report-fact-reuse-control-design.md`
- `docs/superpowers/specs/2026-10-09-report-writing-decisions-design.md`
- `/Users/livictor/Desktop/industry/report-validation-20261013-after-merge/合并后真实生成测试结论.md`
- 本次对话已确认的需求（与旧设计“不增加审稿、不调整大纲”冲突处，以本计划为准）。

最新已知失败：18/19具身决策因紧凑JSON超过1000字符而备用；协调返回大量完整决策导致截断；联盟及500余AI场景重复；专题资料接入问题导致低空/量子外部证据为空。检索失败不能解释为行业没有证据。

实施前重新读取工作树状态。目前 graph_retriever.py 及动态图谱相关测试也有进行中的修改，不能覆盖或将其误计为本任务成果。不要 checkout/reset/stash 全工作树，不迁移向量库，不提交ZIP、原始资料、真实调用日志。

## 1. 已确认的行为边界

1. 允许同篇资料、同一事实跨节复用；仅无新增用途的完整重复介绍需要精简。
2. 完整介绍留在最适合的位置，不默认保留首次出现。
3. 一级章节不变。二级小节减少上限为 `min(2, ceil(original_count * 0.1))`；删除和合并共同计数，以原大纲为基数，一次统筹内统一执行。不删除一级章节的最后一个二级小节。
4. 保留用户明确要求回答的问题；缺证据可以缩短并说明，不能悄悄删掉需求。无法确认删除不影响要求时，保留。
5. 全篇协调阶段可以合并/删除；正文审查阶段只能修改内容，不再改变标题、顺序或小节数量。
6. 小节长短不一，总字数是目标。不能靠重复或无依据推论补篇幅。
7. 一次全篇检查，命中小节各修改一次；无问题小节不调用修改。不追加第二轮语义检查，不自动模型重试（现有SDK网络行为不在范围内）。
8. 修改自动应用；失败保留原正文。内部运行期间允许留存原始对象用于失败回退，不新增用户可见版本管理。
9. 局部重写比较全篇，但只改当前小节；遵从用户明确要求保留背景的指令。
10. 摘要在最终正文形成后生成。最终提示记录实际采用的大纲调整、内容精简、内容不足和处理失败，随历史、Markdown、Word保存。
11. 检查器不承担全面事实审计；程序不声称验证了语义完整性。禁止“已完全消除重复”的保证性状态文字。

## 2. 文件职责

保留：`material_allocator.py`（资料分配）、`repetition_context.py`（前文选择/公共复用规则）、`citations.py`（公共引用校验）、检索模块和向量库配置。

修改：

- `report_generation/writing_decisions.py`：可用决策保留、具体证据用途、方向明确的分工文字。
- `report_generation/task_coordination.py`：紧凑分工调整与一次限额内大纲操作。
- `report_generation/coordinator_agent.py`：最终大纲/任务/引用一致，普通与SSE一致。
- `report_generation/body_agent.py`：初稿结束后接入审查，完成事件延后。
- `report_generation/rewrite_agent.py`：重写后受限审查。
- `backend_server.py`：透传新增结果及历史、导出参数，不在路由重复调用审查。
- `static/js/modules/industry_report.js`、`templates/components/industry_report.html`：进度、自动采用、调整说明、摘要失效与刷新。
- `report_generation/word_export_agent.py`：正文外的调整说明。

新增：

- `report_generation/outline_adjustments.py`：大纲操作纯函数与数量/归属约束。
- `report_generation/review_contracts.py`：段落索引、检查结果解析和确定性验证。
- `report_generation/review_agent.py`：检查/定点修改调用及结果汇总。
- `tests/test_report_outline_adjustments.py`
- `tests/test_report_review_contracts.py`
- `tests/test_report_review_agent.py`
- `tests/test_report_review_flow.py`
- `tests/js/test_industry_report_review.test.js`

不新增通用工作流框架、特征开关、哈希、相似度评分器、事实数据库或旧报告迁移。真实报告超过一次检查容量时明确报告未完成检查，不静默截断全文或暗中分批增加调用。

## 3. 统一数据约定

沿用 `outline_id`、`body_text`、`external_evidence_blocks`、`citation_ids`、`writing_decision`；正文和引用身份不重新编号。

统筹结果新增 `final_outline` 和 `adjustment_notes`。大纲操作格式：

```json
{"kind":"merge","source_ids":["S3.2"],"target_id":"S3.1","reason":"两个小节依赖同一布局事实，保留目标节并吸收独有内容"}
```

删除使用 `kind=delete, source_ids=[...], target_id=null`。初版合并只允许同一一级章节内，目标标题保持原值；跨一级标题的职责重叠使用内容分工处理，不自动搬动章节。一次操作不能引用另一操作已删除/合并的ID，不允许链式、循环或重复消费。超限操作拒绝而非偷偷截断操作列表。所有有效操作先计算再整体应用，保持大纲和任务一致。

审查调用接口（新增）：

```python
def review_report_bodies(*, body_sections, writing_tasks, report_title,
                         user_prompt, references, target_outline_id=None,
                         on_event=None):
    """Return body_sections, references, review, adjustment_notes, warnings."""
```

段落索引在一次检查输入上建立：`S3.1:P1`，按现有段落切分保持顺序，不写入用户正文。检查输出：

```json
{"issues":[{"reason":"成员名单和三项任务被重复完整介绍",
 "keep_paragraph_ids":["S3.1:P2"],
 "edits":[{"outline_id":"S4.4","paragraph_ids":["S4.4:P1"],
 "instruction":"压缩联盟背景，保留后文机制分析",
 "preserve_paragraph_ids":["S4.4:P2"]}]}]}
```

这里的保留段落列表表达模型意图，不等于程序证明语义保留。所有段落ID必须存在；同一段不能同时要求删除和完整保留；冲突组不应用并记录原因。按小节合并所有有效修改要求，一节一次调用。作为其他节保留依据的小节若也需修改，先完成该保留小节；它失败时，依赖它的删减不执行。若依赖成环，保留该冲突组原文并提示，不反复协调。

修改输出仅含当前ID和完整新正文：

```json
{"outline_id":"S4.4","body_text":"该联盟……[C14]"}
```

应用时只替换 `body_text`，重新计算引用信息；不让模型替换标题、证据或其他元数据。

结果状态：

```json
{"review":{"status":"completed","checked_outline_ids":["S3.1","S4.4"],
 "changed_outline_ids":["S4.4"],"failed_outline_ids":[],"issue_count":1},
 "adjustment_notes":[{"kind":"body_edit","outline_ids":["S4.4"],
 "reason":"压缩重复联盟背景，完整介绍保留于央企布局现状"}],"warnings":[]}
```

`status` 为 `completed|partial|failed|skipped_budget`；completed 表示本轮处理完成，不代表无重复。合法空issues为completed且无改动说明。仅实际正文变化产生body_edit记录。用户文案由这些结构化记录组装，不额外调用模型总结处理成绩。

## 4. 实施任务

### Task 1：保存真实失败样本并建立基线

Files: 新建 `tests/fixtures/report_review_cases.json`，读取现有决策fixture和真实运行目录；不复制整份日志。

- [ ] 读取 `git status --short` 和实际函数签名，记录本次可改文件及进行中图谱改动；目的为避免覆盖并行修改，发现重叠先整合实际差异。
- [ ] 从最新运行提取：1019/1083/1235字符合法决策、截断协调响应、联盟重复段落、合理复用段落、同节重复段落。fixture仅保留业务所需文本，不保存凭据。
- [ ] 为fixture写明预期语义：应保留事实、应压缩位置、不能推断的内容。包含同源不同C编号、同C不同事实两类。
- [ ] 在kunlun运行既有核心测试作为基线：

```bash
conda run --no-capture-output -n kunlun python -m pytest -q tests/test_report_writing_decisions.py tests/test_report_task_coordination.py tests/test_report_decision_flow.py tests/test_report_rewrite_citations.py
```

失败时记录具体失败与本任务关系，不把未知失败写成“既有”。这组测试发现旧决策/协调契约问题，将影响下一任务的修改与回归范围。

### Task 2：修复有效决策丢失及分工方向

Files: 修改 `writing_decisions.py`、`task_coordination.py`；测试 `test_report_writing_decisions.py`、`test_report_task_coordination.py`。

- [ ] 先增加真实长决策回归，现实现应在1000字符限制失败：

```python
def test_complete_real_decisions_keep_evidence_uses(real_decision_cases):
    for case in real_decision_cases:
        result = validate_decision(case['decision'], case['task'], case['outline_ids'])
        assert result['evidence_uses'] == case['decision']['evidence_uses']
```

- [ ] 运行该测试确认失败来自整份长度限制。
- [ ] 去掉1000字符整份拒绝；继续使用已有字段长度和条目数量约束限制输出。不用更大任意总字符数再次丢弃合法决策。单个证据用途无效时只去掉该项并warning；section_question或整体结构不可解析时才整体备用。相应修改函数返回诊断并更新全部调用方。
- [ ] 输出仍以简洁为要求，topic写具体事实，不只写企业/主题名；不要新增强制结论。将“承接某节”改为方向中立的“该背景由某节完整介绍，本节仅用于……”，避免把后节称为前文。
- [ ] 协调输出改为字段级调整：`outline_id, reason, set`，set只允许四个既有决策字段；与原决策合并后做一次语义结构/引用验证。未改字段不重复返回。测试空变更、局部错误、截断保留逐节决策。
- [ ] 运行本任务两份测试及 `test_report_decision_flow.py`，确认合法信息保留、无效信息不会变成可用证据。

### Task 3：限额内大纲调整与证据归属

Files: 新建 `outline_adjustments.py`、`test_report_outline_adjustments.py`；修改统筹及协调。

- [ ] 首先覆盖额度边界：

```python
@pytest.mark.parametrize('count,expected', [(0,0),(1,1),(8,1),(10,1),(19,2),(30,2)])
def test_reduction_limit(count, expected):
    assert reduction_limit(count) == expected
```

- [ ] 最小实现：

```python
def reduction_limit(original_count):
    return min(2, (original_count + 9) // 10)
```

- [ ] 测试合并加删除累计、超限、跨一级、最后子节、未知ID、循环、受保护用户需求、检索失败导致的删除提议。实现 `apply_outline_adjustments(outline, tasks, operations, protected_outline_ids)` 返回final_outline/final_tasks/applied_notes/warnings。
- [ ] 将可追溯的用户要求带入协调；不能确认需求已覆盖时拒绝删除。正常无命中与检索error分开，error节不得因“无资料”自动删除。拒绝超限时保留原大纲操作集合，内容分工仍可独立应用。
- [ ] 合并前将源节独有证据并入目标节证据集合，沿用引用编号、按现有资料/片段身份去重，不运行再次分配删掉必要证据；模型调整后的目标决策只可引用合并后合法证据。图谱信息保留其实际状态及来源，不把失败拼成成功。
- [ ] 修正所有分工中的已移除ID：合并指向目标；删除对象的分工条目移除并记录。目标标题和一级结构不变，显示编号可连续，内部ID稳定。
- [ ] 普通与SSE统筹的最终事件同时提供final_outline、writing_tasks、references、adjustment_notes。前端使用final_outline生成后续任务；旧历史缺字段时沿用已有大纲，不自动迁移。
- [ ] 运行新测试和 `test_report_coordinator_citations.py`、`test_report_decision_flow.py`；发现证据丢失或任务ID不一致时不能进入正文任务。

### Task 4：审查输入与检查契约

Files: 新建 `review_contracts.py`、`test_report_review_contracts.py`。

- [ ] 写段落定位、无效段落ID、同源不同编号、局部修改越界的测试；合法“同C不同用途”fixture允许无issues。
- [ ] 实现 `index_paragraphs(body_sections)` 生成一次请求内稳定索引；保留原文段落和小节ID。不用散列或相似度阈值。
- [ ] 实现 `validate_review_issues(response, paragraph_index, target_outline_id=None)`；校验引用的段落存在、段落属于指定节、局部模式只编辑目标节、保留/删改指令不冲突。无效组记录warning，不让其进入修改。
- [ ] 输入包含完整成功正文、标题、最终分工、用户要求；不把所有原始资料放入检查输入。正文缺节时标记覆盖不完整，不能展示全篇检查完成。
- [ ] 一次输入初始上限60000字符，按完整JSON计数；超过则skipped_budget，不截取前半报告。此为显式运行边界，真实19节样本应能容纳；若实测不能容纳，应在验收前重新设计容量，不宣称功能已覆盖该报告。
- [ ] 测试超限不调用模型、空issues有效、含未知ID不进入修改、同节内部重复可表达。

### Task 5：审查 Agent 与自动修改

Files: 新建 `review_agent.py`、`test_report_review_agent.py`；复用 `citations.py`、`repetition_context.py`。

- [ ] 使用mock计数验证调用上限：

```python
def test_no_issues_uses_only_one_call(review_fixture, mock_llm):
    mock_llm.return_json({'issues': []})
    result = review_report_bodies(**review_fixture)
    assert mock_llm.call_count == 1
    assert result['body_sections'] == review_fixture['body_sections']
    assert result['review']['changed_outline_ids'] == []
```

- [ ] 实现检查调用：使用query_result、直接输出参数沿用现有决策调用；5000输出token，检查error/empty/length/JSON。输出只列具体冲突，不返回正文。失败不解析截断JSON为局部成功。
- [ ] 按节合并有效指令；按保留位置依赖排序，使用同一份初稿段落索引，不因前一节修改重编号。每个目标节调用一次，max_tokens沿用正文5000，不自动重试。
- [ ] 修改输入包含原小节、相关重复段落、统一安排、本节实际证据和用户要求。输出仅outline_id/body_text，强调保留独有内容、不补造结论、不追逐字数。
- [ ] 拒绝空正文、length、错误ID、未知引用；先检测非法引用再调用现有清洗，不能通过删除非法标记把失败伪装成成功。合法引用清洗后重新汇总本节citation_ids和报告已用references。
- [ ] 每节应用原子化；保留位置失败则跳过依赖它的删减。失败节保留原始对象。结果body_text与原文相同时不记录改动。
- [ ] 测试：同节多问题只修改一次；合理复用不改；修改失败原文保留；依赖失败不误删；局部模式其他节对象不变；材料和标题不变；模型调用恰好1+k，k为实际尝试修改的节数。

### Task 6：普通/SSE正文流程与摘要顺序

Files: `body_agent.py`、`backend_server.py`、`industry_report.js`；新增 `test_report_review_flow.py`。

- [ ] 写普通/SSE一致性测试：两种入口收到相同初稿和模型返回，最终body_sections/review/notes一致；摘要不得收到初稿。
- [ ] 普通generate_report_bodies在初稿汇总后调用review_report_bodies；SSE在初稿结束后同样调用，通过回调发送review_started、review_checked、review_section_completed、review_completed；completed只在审查结束后发送。
- [ ] 失败/跳过也必须发送终态和可用正文，不挂起SSE。没有成功正文时不调用审查；缺节时仅审查可用内容并明确partial覆盖。
- [ ] 后端路由只透传结果，不再第二次审查。新增字段沿既有history保存链路落盘，不创建新数据库。
- [ ] 前端收到最终completed时整体替换bodySections，不能保留流式初稿片段；审查期间禁用编辑、重写、导出以避免支持的用户操作覆盖正在返回的正文。失败终态恢复操作。
- [ ] 只在最终正文形成后生成/刷新摘要；正文自动修改、手动编辑或局部重写采用后清空旧摘要状态，导出前按已有入口重新生成。审查失败但有正文仍可生成摘要，说明未完成审查。
- [ ] 测试正常、审查模型错误、部分正文失败、连接终止不显示成功、历史重新加载不自动再次调用审查。用现有SSE消费函数测试，不新建通用调度器。

### Task 7：局部重写自动采用

Files: `rewrite_agent.py`、`backend_server.py`、`industry_report.js`；`test_report_rewrite_citations.py`、新JS测试。

- [ ] mock重写→检查→修改，断言只替换当前ID；用户指定保留背景传入检查和修改提示。
- [ ] 重写Agent得到候选正文后，与previous_body_sections组成检查输入，target_outline_id限定当前节；本节引用资格来自本次用户选中的资料，不因审查增加其他节资料。
- [ ] 检查或精简失败时保留本次有效重写候选；重写本身失败才保留之前正文。分别记录失败阶段。
- [ ] 前端rewriteIndustryReportSection成功后直接复用采用逻辑更新正文/引用/说明并保存；移除本流程pendingRewrite及原稿对比确认步骤，保留材料选择和用户重写要求。没有新增第二套采用逻辑。
- [ ] 使用普通单节结果视图显示最终内容，其他节不改；使摘要失效。测试不需要点击“采用”、错误不覆盖原节、其他小节不变。

### Task 8：调整说明、历史与导出

Files: `industry_report.js`、`industry_report.html`、`backend_server.py`、`word_export_agent.py`；JS新测试、`test_word_export_citations.py`。

- [ ] adjustment_notes由实际应用结果产生，kind使用outline_merge/outline_delete/body_edit/content_limit；失败和跳过使用warnings。未采用建议不写成已完成改动。
- [ ] 以当前报告状态保存说明；重复打开/导出不重复追加。用户再次生成统筹或正文时替换该阶段旧说明，局部重写替换当前节对应说明，不累积失效成绩。
- [ ] 页面提供简短“本次报告调整说明”，无说明不显示空面板；不增加对比界面。正文不出现内部error、token等诊断词，详细技术原因保留日志。
- [ ] 历史保存/加载保留final_outline、review、adjustment_notes；缺新字段的旧历史照常显示，不自动审查或生成摘要。
- [ ] Markdown和Word在正文之外附“报告调整说明”；导出参数增加可选adjustment_notes，旧调用缺省为空。Word仍从最终正文收集实际使用引用。
- [ ] 测试只有采用的调整出现、失败提示准确、说明不进入正文引用统计、旧历史可加载、摘要来自最终正文。
- [ ] 如修改Word布局，按pdf/documents相关技能渲染一份有说明与一份无说明样例，检查分页、正文与附录分隔；发现溢出修模板，不据XML测试宣称排版合格。

### Task 9：定向回归与真实质量验收

Files: 新建 `docs/superpowers/report-review-agent-validation-2026-10-13.md`；必要的测试驱动脚本放独立验证目录，不放业务模块。

- [ ] 先处理证据接入前置条件：核对低空/量子当前是否仍走旧集合。若尚未整合，单独整合已存在的专题接入改动，运行对应路由测试；不得在零外部证据状态宣称跨产业质量验收通过。动态图谱并行工作按实际提交整合，不复制覆盖。
- [ ] 运行以下定向回归，发现失败回到对应任务，不盲目扩大为全库修复：

```bash
conda run --no-capture-output -n kunlun python -m pytest -q tests/test_report_outline_adjustments.py tests/test_report_review_contracts.py tests/test_report_review_agent.py tests/test_report_review_flow.py tests/test_report_writing_decisions.py tests/test_report_task_coordination.py tests/test_report_decision_flow.py tests/test_report_coordinator_citations.py tests/test_report_body_citations.py tests/test_report_rewrite_citations.py tests/test_report_repetition_context.py tests/test_material_allocator.py tests/test_report_citations.py tests/test_word_export_citations.py
node --test tests/js/test_industry_report_review.test.js tests/js/test_industry_report_citations.test.js
node --check static/js/modules/industry_report.js
git diff --check
```

这些检查分别检测分工/额度错误、引用越界、重复调用、普通/SSE差异、自动采用和格式错误；任何失败都必须修改对应实现或准确更新与新契约冲突的旧测试。

- [ ] 真实调用仅在执行阶段获得运行授权后启动。第一轮固定现有具身智能初稿、分工和证据，仅调用审查Agent；不用重新检索混淆效果。内部验证目录保存输入输出便于评估，不建立用户版本界面。
- [ ] 人工对照联盟成员/三项任务、500余AI场景、融资比例、矿山/家用等重复位置；逐项记录保留位置、精简位置、独有事实是否保留、是否新增无依据推断。不能用引用次数或模型自评代替内容判断。
- [ ] 再运行完整19节流程，验证分工有效率、实际大纲减少数、审查1+k调用、最终摘要/引用/导出一致。记录各阶段耗时与真实调用量，不承诺固定时间提升。
- [ ] 验收至少包含：不重复时零修改调用；同节重复；跨节重复；同源不同编号；合理复用；缺证据但独立问题；检索失败不能删节；局部重写；检查截断；修改失败；历史与导出。
- [ ] 若独有信息丢失、产生新无依据结论、重复仍完整保留，将其记录为未达质量验收并定位提示/分工/应用问题，不自动增加第二轮审稿，也不以单元测试通过结项。

## 5. 提交与完成条件

计划阶段不提交业务改动。实施时按“决策修复”“大纲调整”“审查Agent”“流程与局部重写”“展示导出”分阶段提交；仅显式暂存本阶段文件/差异。因为现有文件包含前两轮未提交实现，先辨认其来源并保留，不能声称所有diff都是本轮新增。不要使用git add .。

完成必须同时满足：定向自动化通过、代表性真实内容验收通过、普通/SSE/局部重写及历史导出接通、最终调整说明准确。若尚未授权真实调用，应报告“代码与离线流程完成，真实质量待验收”，不能称重复问题已解决。

## 6. 范围外与独立故障

不重建向量库、不自动按标题合并全库资料、不引入全文事实核验或通用多Agent平台、不为旧报告自动执行付费审查。摘要空输出、动态图谱截断分别沿其模块处理；本任务必须保证摘要使用最终正文、失败提示准确，但不把摘要模型行为修复混入审查Agent。真实验收如被这些故障阻断，应明确对应阶段，不能归因于重复检查或跳过后声称端到端成功。

# 新生成产业报告质量与十五分钟交付实施规划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 本规划不自动授权拆分多个聊天或向其他聊天发送消息。

**Goal:** 在现有数据渠道内，使新生成报告更稳定地回答核心研究问题，减少明显事实、口径、重复和引用问题，并在正式生成启动后十五分钟内返回可下载结果或明确的未完成状态。

**Architecture:** 复用 Agentic 检索评估、GraphRAG、全篇协调和审查 Agent。把章节证据判断接入整篇范围决策与材料分配，拆开容易超载的审查输出，并让同一运行预算贯穿协调、正文、审查、摘要和导出。按真实失败修改现有环节，不新增通用 Agent 平台。

**Tech Stack:** Python、现有后端路由与 LLM 客户端、Hybrid 检索及图谱关联原文、现有 Word 导出、原生 JavaScript、pytest 与现有 JS 测试。

## 一、已确认的产品约束

- 优先保证新报告；旧四份报告用于定位和验证，不建设旧稿自动修复平台。
- 允许修改三个新增模块以外的代码；范围由问题决定。
- 沿用已经接通的数据渠道，不建设新资料库或新网络搜索服务。
- 材料不足时先整合已召回证据，再定向补查；仍不足则收缩覆盖面，保留核心问题与分析深度。
- 允许调整已确认的报告标题、一级章节和二级小节，并简洁说明原因；不得悄悄换研究对象或主题。
- 没有最低字数、固定章数要求；不能通过空洞扩写或过度删减掩盖研究不足。
- 有依据的条件性分析可以原创；事实、推断、预测必须区分。
- 无支持的关键断言删除或收窄，不能仅加“可能”保留原结论；重要缺口集中说明。
- 核心问题无法形成完整研究时可交付有实质内容的简报；检索服务故障不能被解释为行业没有资料。
- 十五分钟从确认大纲后首次启动正式协调/生成计算，包含系统实际执行的协调、正文、审查、摘要和导出；用户主动等待不计。全自动连续运行墙钟时间不得超过 900 秒。
- 外部服务故障时仍应在时限内返回明确状态。十五分钟是完成或结束的上限，不承诺任何资料条件下都能生成合格长报告。

## 二、已核对的实现与证据边界

1. `report_generation/agentic_rag/chapter.py` 已有逐节初查、评估、最多一轮两项补查与无新增停止。不要重新实现同名闭环。
2. `coordinator_agent.py` 在检索后分配材料、登记引用、串行生成写作决策，再调用全篇协调。应在正文之前统一范围，不能只在末端修标题。
3. `task_coordination.py` 只传简短决策及允许引用，缺少完整的需求支持状态；`outline_adjustments.py` 保持一级章节、最多减少两个小节，与新授权不一致。
4. `material_allocator.py` 有来源复用控制，但主要在各节原有候选内分配；不等于跨节按需求共享证据。
5. `review_agent.py` 已有局部修改和复核。失败瓶颈是单次全文检查同时输出重复定位与声明核对，输出上限 16000 token；不是整篇改写协议。
6. `static/js/modules/industry_report.js` 与 `backend_server.py` 将协调、正文、摘要、Word 分为多次请求；正文成功后仍需用户导出。预算必须跨请求且最终 Word 自动准备好，下载点击本身不计生成。
7. `llm_client.py` 现有超时约 300 秒；只在外层检查剩余时间不能中止正在阻塞的调用，线程池退出也可能等待未完成任务。
8. 已有双产业固定五节验收，Agentic 约 467/421 秒；协调约 240/96 秒，正文含审查约 158/165 秒，摘要约 69/160 秒。该样例跳过任务卡和大纲，不证明二十余小节满足十五分钟。
9. 当前大量 GraphRAG/Agentic 改动尚未提交。实施必须基于当前工作区内容；不得重置、清理或用旧 HEAD 替换。若隔离执行，明确携带所需当前改动，不复制密钥和无关大文件。
10. 四份旧报告的准确代码版本尚未完整对应。不得声称它们全部验证过最新模块。任务 0 只恢复能证明的功能执行记录，无法还原的标为未知。

## 三、实现边界与最小数据约定

新增小模块只承载现有文件不适合继续堆叠的职责：

| 文件 | 职责 |
|---|---|
| `report_generation/report_scope.py` | 整篇研究范围、覆盖关系及调整结果校验；不实现新检索器 |
| `report_generation/runtime_budget.py` | 剩余运行时间、阶段预留及调用超时计算；使用可注入时钟 |
| `report_generation/review_batches.py` | 事实核对批次、重复检查候选分组与结果汇总；复用原有核对和修正 |

范围决策保存到协调结果并沿后续请求、历史及导出传递：

```python
report_scope = {
    "original_title": "原始标题",
    "effective_title": "证据支持的标题",
    "deliverable_type": "report",  # report / brief
    "core_question": "用户要求回答的主要问题",
    "boundary": {"subjects": [], "period": "", "classification": ""},
    "coverage": [
        {"requirement": "具体研究要求", "status": "supported",
         "section_ids": ["S1.1"], "reason": "具体支持依据或缺口"}
    ],
    "adjustments": [],
    "remaining_gaps": [],
}
```

`coverage.status` 使用 `supported/partial/insufficient/unknown/unavailable`，保留现有证据包的逐片段身份，不用来源数量换算支持度。范围对象不是事实证据，不能被正文作为引用。

运行结果将研究类型和执行状态分开：`deliverable_type=report/brief`；`delivery_status=completed/incomplete/failed`。只有必须正文、审查执行、摘要一致性和最终文件处理结束后才为 completed；不表示外部世界的所有事实已经核实。unknown 必须记录“资料不足”或“核对未执行/失败”等具体原因。

## 四、任务与实施顺序

### 任务 0：固定验证输入并核对实际运行链路

**Files:** 读取 `backend_server.py`、`llm_client.py`、`static/js/modules/industry_report.js`、已有历史/日志与 `evaluation/agentic_report/`；创建 `evaluation/report_quality/README.md` 和 `cases.json`。

- [x] 记录当前改动列表，确认执行基线包括新增模块；不自动提交别人的改动。
- [x] 对旧四份报告记录题目、报告规模、可对应的运行时间、Agentic 执行字段、审查结果与失败日志。没有版本证据的写 unknown，不从文件日期猜版本。
- [x] 追踪确认大纲到 Word 下载的生产请求，记录每一步携带的标题、大纲、引用、证据包和审查结果。找出历史恢复及同步入口的对应路径。
- [x] 固定三类内容回归：前十名单缺失、时间序列不足、已有企业财务材料分配错误；另固定长报告审查截断与引用悬空案例。
- [x] 写明每项失败会导致的具体实现动作。此阶段不重跑四份长报告，不扫描全部外部事实。

**验收：** 入口、当前基线与旧报告证据边界有记录；后续用例能复现具体问题，不把未知版本当成最新版本失败。

### 任务 1：先建立跨阶段时间预算

**Files:** 新增 `runtime_budget.py`、`tests/test_report_runtime_budget.py`；修改 `llm_client.py`、`backend_server.py`、协调/正文/摘要调用入口及前端运行状态；复用 `tests/test_llm_client_configuration.py`。

- [x] 用假时钟测试：累计运行时间不因进入正文/摘要而重置；用户等待不消耗执行预算；失败调用和重试消耗预算。
- [x] LLM 调用增加可选的本次超时参数，报告调用传入剩余阶段时间；其他业务默认行为保持原样。明确底层重试总时长不超过传入预算。
- [x] 初始工程分配为协调与检索 300 秒、正文 300 秒、审查 210 秒、摘要与导出 90 秒。允许后阶段使用前面未消耗时间；这些是待实跑校准的起始分配，不是已测量性能结论。
- [x] 所有网络检索、模型调用与重试前检查预算；不再启动超过剩余阶段时间的补查。已有章节内一次补查上限继续保留。
- [x] 处理协调线程池和正文后台线程的截止：超时后不等待超长任务退出才能返回；底层调用也设超时，迟到结果不能修改已经结束的报告。
- [x] 预算在协调、正文、摘要和导出请求间传递累计消耗，后端计算本次耗时；不新建任务队列、分布式调度或认证框架。
- [x] 前端准备自动连续生成并在末尾生成 Word；保留手动阶段操作，但复用同次运行的预算。刷新/恢复不能把已消耗时间清零。

关键行为测试示意（在新增模块中提供 `RuntimeBudget` 接口）：

```python
def test_budget_survives_stage_transition():
    now = [0.0]
    budget = RuntimeBudget(total_seconds=900, consumed_seconds=120,
                           clock=lambda: now[0])
    now[0] = 80.0
    assert budget.remaining_seconds() == 700
    assert budget.snapshot()["consumed_seconds"] == 200
```

运行：`/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_runtime_budget.py tests/test_llm_client_configuration.py -q`。先确认新增时间用例能暴露旧流程无总预算的问题，再完成实现。失败时修调用传播或阻塞处理，不用提高总时限解决。

### 任务 2：让 Agentic 证据判断决定整篇范围

**Files:** 新增 `report_scope.py`、`tests/test_report_scope.py`；修改 `coordinator_agent.py`、`task_coordination.py`、`outline_adjustments.py`、`agentic_rag/chapter.py`；覆盖现有 `test_agentic_report_outline.py`、`test_report_outline_adjustments.py`。

- [x] 给全篇协调输入加入各需求的支持状态、重要缺口、证据身份和简短摘录；不把全部原文重复塞入模型。
- [x] 复用现有全篇协调调用输出 report_scope 和大纲调整，避免增加多个逐节规划轮次。核心问题、样本及时间范围全篇只保留一份有效定义。
- [x] 对企业比较要求固定比较对象与指标；历史演变要求对应时期的节点/可比数据；区域比较要求明确区域与比较维度。不存在资料时不捏造空表或排名。
- [x] 在章节补查前优先检查当前已汇总材料是否能覆盖缺口；预算不足时优先核心要求，不把所有小节同等扩展查询。
- [x] 放开一级标题不变、最多减少两节等旧产品限制，支持改名、合并、删除和收窄范围；保留稳定小节 ID 或显式映射，避免引用、事件、历史悬空。
- [x] title/outline/report_scope 必须原子采用。若返回无效决策，保留已有材料并明确未完成范围校验，不按原题目冒充已完成；不能因服务失败大幅缩题。
- [x] 对证据很少的输入：能回答核心问题的局部内容组成 brief；仅有不相关背景时返回 incomplete，不能靠两段背景满足交付。

测试具体场景：无前十名单时不能保留“前十排名”标题；有四家可比较企业时保留比较而不是改写行业科普；五年数据不足但节点可靠时保留节点分析；用户研究对象不变；无独立内容章节可跨一级合并；检索 error 不触发“无资料”的结论。

运行：`/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_scope.py tests/test_report_outline_adjustments.py tests/test_agentic_report_outline.py tests/test_report_task_coordination.py -q`。出现空泛缩题或数据丢失就修范围决策/应用，不加最低字数。

### 任务 3：共享证据并形成真正的比较分析

**Files:** 修改 `material_allocator.py`、`coordinator_agent.py`、`writing_decisions.py`、`body_agent.py`、`agentic_rag/assessment.py`；新增 `tests/test_report_evidence_sharing.py`，复用 `test_report_writing_decisions.py`、`test_body_agent.py`。

- [x] 汇总本次报告已召回证据，以现有 material/chunk 身份去重；按具体需求把相关片段分配到目标小节，不把整篇材料无差别复制到每节。
- [x] 保留需求到片段的对应关系；跨节移用后更新证据包与统一引用。不能让来自另一节的 supported 状态替代目标需求的判断。
- [x] 复用当前关键片段保护逻辑；来源多样性只能在满足需求之后发挥作用，不能为了降低复用率挤掉唯一财务或历史依据。
- [x] 明确各节独立回答，背景完整介绍放到最适合的位置；其他位置承接并分析不同含义。允许同一事实用于不同分析，不设置机械引用次数上限。
- [x] 正文接收 report_scope；提示区分公司总收入/相关业务收入、预测/实绩、静态名单/历史变化、传统专用产品/通用具身能力。
- [x] 去掉要求资料直接给出情景或建议的过度约束；条件分析必须说明事实依据、假设和适用边界。禁止以“未检索到”推出“尚未商业化”。
- [ ] 以信息任务决定自然篇幅，不引入每节最低长度；比较适合表格时允许生成结构化比较，缺项如实标明。
  - 已移除硬性篇幅；本批先保留段落对照，Word 表格输出尚未实现。

验证场景：营收片段从估值节转供经营节后，引用仍可追溯；只支持单年收入不能支持五年增长；有事实依据时能够形成条件情景；跨节使用不丢掉“计划投产”限定。

运行：`/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_evidence_sharing.py tests/test_report_writing_decisions.py tests/test_body_agent.py tests/test_agentic_report_assessment.py tests/test_report_coordinator_citations.py -q`。

### 任务 4：拆解长报告审查的输出负担

**Files:** 新增 `review_batches.py`、`tests/test_report_review_batches.py`；修改 `review_agent.py`、`agentic_rag/verification.py`；复用 `test_report_review_agent.py`、`test_agentic_report_verification.py`。

- [x] 用多节高声明数样例复现一次输出截断导致全部检查失效。另测后部小节不会因证据预算顺序耗尽而永远未核对。
- [x] 将事实核对按现有候选声明和证据预算组批，每批初始最多三节且每节最多八项高影响声明；超额声明继续排批，不能默默丢弃。优先摘要依据、关键数字、年份、排名、监管与企业状态。预算不足的项明确标未覆盖。
- [x] 从重复检查调用移除逐条事实核对输出。短文沿用全文定位；长文先用各节紧凑主题/事实索引找跨节重复组，再只带相关原文定位最小修改片段。索引只作线索，修改仍以原文为准。
- [x] 批次分别解析和保存；单批截断允许在剩余预算内拆成更小批一次，不扩大 token 上限或无限重试。其他已完成批次不回滚。
- [ ] 复用已有最小片段修改、冲突合并和改后复核。事实修改与去重修改针对同一处时统一处理，禁止两个补丁覆盖。
  - 已保留最小修改及复核；重叠事实修改当前会明确延后并保持未完成，未实现全部重叠片段的统一修正。
- [x] 语义支持不足时收窄或删除断言；核对服务失败不等于事实错误，不据此删除全文。关键检查未完成时 delivery_status 不得为 completed。
- [x] 批次并发上限初始为 2，共享审查剩余时间，避免与正文阶段叠加无限并发。

验证：一个批次失败时其他修正保留；跨节重复仍能发现；独有事实与计划状态保留；截断不产生全篇零修正的静默成功；未覆盖声明的原因可见。

运行：`/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_review_batches.py tests/test_report_review_agent.py tests/test_agentic_report_verification.py tests/test_report_review_flow.py -q`。

### 任务 5：统一引用、摘要和交付状态

**Files:** 修改 `citations.py`、`summary_agent.py`、`word_export_agent.py`、`backend_server.py`、`static/js/modules/industry_report.js`；新增 `tests/test_report_delivery_state.py`，复用引用、摘要、Word 和前端测试。

- [x] 正文裸写 C 编号仅在能对应当前真实来源时规范化；找不到来源的编号不能虚构参考条目，必须修正文断言或标记未解决。
- [x] 摘要只依据最终正文和有效范围生成，不复活已删除的排名、结论、年份或原标题承诺。摘要失败不再静默用未经一致性检查的拼接文本冒充正式摘要。
- [x] Word 正式正文保留简洁参考资料；长命中片段和调试信息不默认混入成稿。重要研究限制集中呈现；具体审查执行失败不得通过隐藏提示消失。
- [x] 完成生成时自动准备 Word 并显示可下载状态，不再等待用户点击导出才开始模型摘要调用。下载已有文件不重复审查和生成。
- [x] 部分正文、审查未完成、预算耗尽分别显示真实状态；允许取回明确标记的部分结果，不能按完整正式稿展示。
- [x] 历史保存/恢复保留有效标题、范围、状态和预算。旧历史缺新字段时正常只读展示为原有记录，不迁移或重跑旧稿。
- [x] 同步与流式入口使用相同语义；前端未收到 completed 不得把逐节到达当成整篇完成。

运行：`/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_delivery_state.py tests/test_word_export_citations.py tests/test_report_body_citations.py tests/test_summary_agent.py tests/test_word_export_agent.py tests/test_agentic_report_export.py -q`。

前端运行：`node --test tests/js/test_industry_report_agentic.test.js tests/js/test_industry_report_review.test.js`。实施时按仓库已有 Node 环境执行，不新建前端框架。生成最终 Word 样例后按 documents 技能渲染检查标题、比较表、参考资料和状态说明；只在布局错误时重渲染。

### 任务 6：新报告验证与交付决定

**Files:** 复用 `scripts/evaluate_agentic_report.py`，扩展 `evaluation/report_quality/` 记录；不得为测试恢复旧生产检索开关。

- [x] 用旧四份的具体失败构造离线回归：名单缺失、时间漂移、跨节证据错配、引用悬空、长审查截断和部分导出。测试目标是系统行为，不手工改这四份文稿。
- [x] 完成一次受影响测试集合；除新失败或新增改动外不反复全仓测试。
- [x] 生成至少三份新题目报告：低空代表企业比较、海洋近年结构变化、生物制造技术路线与应用比较。题目覆盖不同研究类型，不使用样例中特定企业数字硬编码。
- [x] 在修改完成前固定一份未用于提示词调优的题目作为保留验收题。使用正常任务卡/大纲流程，再从确认大纲启动计时；不能仅用固定五节跳过关键范围调整。
- [x] 至少一次输入 17—23 小节原始大纲，允许系统按证据合理调整；检查不是靠删空内容满足耗时。记录调整前后标题、章节和核心回答。
- [x] 每份记录：累计执行时间、各阶段耗时、调用/重试、补查新增有效依据、范围变化、审查实际覆盖与采用修正、最终交付类型。不要用 unknown 数量计算准确率。
- [ ] 对主要结论逐条比对实际引用片段；对决定结论的日期/状态，优先使用现有渠道原始披露。来源只有二手内容时如实保留来源属性，不能声称完成独立真实性验证。
- [ ] 任一新报告出现核心问题没回答、显著重复、对象/时间漂移、关键无据断言、引用悬空、未完成伪装成完成或超过时限，记录具体位置并回到对应任务修复。仅重跑受影响场景，必要时再跑保留题。
- [x] 人工评估明确“可接受/不可接受及原因”，不用综合分数代替判断；测试通过不等于业务通过。

## 五、验收依据与失败后的动作

| 具体失败 | 验证方法 | 失败后动作 |
|---|---|---|
| 题目承诺未兑现 | 对照原需求、有效标题、主要结论和比较内容 | 修全篇范围决策及摘要传播 |
| 少写掩盖无内容 | 查看缩题后是否仍回答核心问题，有无实质比较/分析 | 修范围和材料分配；必要时明确 incomplete |
| 同一背景反复完整展开 | 阅读旧样例高重复主题及新报告跨节内容 | 修写作分工或重复检查定位 |
| 引用存在但范围不支持 | 核对主体、年份、口径、预测状态与原文 | 修证据使用、声明核对和正文 |
| 长报告审查未执行 | 看批次执行、截断、实际修正与未覆盖记录 | 修分批及预算，禁止靠状态字段粉饰 |
| Word 部分稿伪装成稿 | 用不完整生成和审查失败输入导出 | 修交付状态和前端/导出行为 |
| 超过 900 秒或线程仍阻塞返回 | 假时钟/慢调用故障注入及真实运行 | 修底层超时、重试、调度和预算分配 |

## 六、实施节奏及不做事项

依赖顺序：0 → 1 → 2 → 3 → 4 → 5 → 6。任务 1 的预算接口先建立，随后每个环节接入；不是等内容开发结束才追加超时。

建议第一天完成基线、预算、范围/证据协调及审查拆分的最小闭环；第二天完成交付整合与新题真实验证。此为工作顺序建议，不是完成时间承诺。若时间不足，停止扩大功能，优先处理验收发现的具体失败，明确未完成项，不降低验收标准。

不做：新增数据渠道、图谱大改造、五库标签扩建、通用评分平台、无限研究循环、任意最低字数、旧稿批量修复、迁移框架、无实质用途的哈希与指纹、无关重构。

每个任务先写对应失败行为的测试，确认失败原因与任务一致，再最小实现并跑指定集合。阶段提交只包含本任务新增变化；不得将当前其他未提交改动一并提交。实施结束报告代码变更、实际测试和真实报告结果，分别说明功能完成与内容验收，不宣称“任意报告零错误”。

## 七、规划自审与实施前注意

本规划覆盖已确认的范围调整、内容深度、资料渠道、十五分钟、历史样例验证及跨模块授权。首次实施时确认同时进行的其他聊天没有覆盖这些文件；遇到同文件更新先读差异并合并，不重置工作区。

尚不能从历史记录确定的版本归属在任务 0 核对；不能核对也不阻塞改进，保持未知并以当前基线复现为准。阶段时间分配及审查批次大小是明确的初始实现值，真实运行若表明不适用，在同一 900 秒上限内调整，记录依据，不扩成配置平台。

## 当前执行检查点（2026-10-17）

代码已按差量合入原工作目录，受影响测试通过。真实新题低空9节、生物制造15节完成连续生产；海洋19→17节经过保存协调结果重放完成。三份最终均为 incomplete，内容验收不通过，详见 evaluation/report_quality/acceptance-summary.md。不得将计划的实现勾选等同于系统已经达到稳定交付标准；任务6的新一轮最终版本内容验收仍未完成。比较表格保持未实现。

# 新报告内容可靠性第二轮实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 默认在当前任务内顺序执行，不自动创建新聊天或派发子代理。

**Goal:** 修复本轮新报告中跨章节事实矛盾、审查漏项及修正未落地、证据适用范围越界和无独立内容章节保留的问题，使证据足够的新题能形成可接受成稿，证据不足时仍提供有实质内容且范围诚实的结果，并保持正式执行不超过 900 秒。

**Architecture:** 保留上一轮已实现的预算、证据共享、范围调整、分批审查和交付状态。先用真实请求与响应定位失败，再将报告关键事实的适用边界贯穿范围决策、写作和复核；把重叠修改合成一次局部修正，最后用最终正文而非模型自报字段判断问题是否消除。复用现有模块，不建设新的通用 Agent 平台。

**Tech Stack:** Python、现有 LLM 客户端、Agentic RAG、GraphRAG、pytest、现有 JavaScript 测试、Word 导出和真实报告评估脚本。

---

## 1. 本轮定位与约束

本计划接续 `2026-10-16-report-quality-delivery.md`，不替代其已完成记录。事实基线为 `evaluation/report_quality/acceptance-summary.md` 和 `verification.json`。

| 已观察到的失败 | 已有证据 | 本轮动作 |
|---|---|---|
| 同一企业证照状态前后不同 | 低空 9 节，424.07 秒，102 次调用无截断，0 节修正采用；存在峰飞已取得 TC 与待验证口径差异 | 先区分对象/型号/时间，再核查跨节一致性与补丁回滚原因 |
| 核对漏项、合理分析误判、修正回滚 | 低空与生物制造均为 partial；无截断仍可能缺核对行 | 请求级留证、逐声明结果对账、有限缺项补核、语义反例验证 |
| 申报要求被推广为路线的一般条件 | 生物制造 15 节，518.05 秒，7 节修改采用，仍内容不通过 | 从评估与正文之前限制证据适用范围；末端修正必须消除越界前提 |
| 证据不足仍保留许多独立章节 | 生物制造 15→15，重复方法和边界；海洋 19→17 仍重复 | 明确各节实际回答和独立作用，再决策合并，不按章数裁剪 |
| 事实修正和去重互相阻塞 | `verification.merge_edits` 遇到 edit/keep_span 重叠即 deferred | 同一原文位置合并修改意图，保留位置也接受事实核对 |
| 长报告最终版本未连续验收 | 海洋 550.69 秒为原协调加后续重放的累计值 | 最终版本从确认大纲到 Word 做一次连续验收 |

不能从以上结果直接推出“模型一定不行”“所有 unknown 都是错事实”或“增加 token 就能修好”。同样，修改采用数量不是质量指标：正确原文可以零修改；本次零修改的问题在于明确矛盾仍在。

沿用产品约束：优先新报告；不手修样例；不新增资料渠道；不设最低字数/章数；允许有依据的原创比较与条件分析；资料不足先共享、再定向补查、再收窄；保留核心问题与实质分析；检索失败不能解释为没有资料；确认大纲后的正式连续执行包含协调、正文、审查、摘要和 Word，总计不超过 900 秒。

本轮不新增表格导出、图谱扩库、通用评分系统、迁移层或模型路由平台。上一计划的 Word 比较表功能继续保留为待办，不阻塞内容修复。预算、前端和引用链只在本轮发现具体回归时修改。

## 2. 文件与职责

以下路径均相对于 `/Users/livictor/Desktop/industry/industry_graph`；实施可复用已有隔离工作树 `/Users/livictor/.config/superpowers/worktrees/industry_graph/codex-report-quality-delivery`，先确认与主目录本任务差量一致，保留其他未提交改动。

| 文件 | 本轮职责 |
|---|---|
| `scripts/evaluate_agentic_report.py`、`scripts/evaluate_report_quality.py`、`scripts/replay_report_quality_review.py` | 保存失败调用的输入输出及修正去向；复用真实生产入口 |
| `report_generation/review_batches.py` | 核对结果完整性、缺项有限补核、预算内汇总 |
| `report_generation/agentic_rag/verification.py` | 声明级证据充分性、事实/分析边界、补丁意图合并 |
| `report_generation/review_agent.py` | 来源冲突定位、一次局部修正、最终内容复核和采用/回滚原因 |
| 新增 `report_generation/report_facts.py` | 本次报告关键事实及来源的紧凑表示、引用绑定校验和相关事实选取；不新增检索器或持久知识库 |
| `report_generation/agentic_rag/assessment.py`、`task_coordination.py`、`report_scope.py` | 证据适用性、章节独立作用与有效范围 |
| `report_generation/coordinator_agent.py`、`writing_decisions.py`、`body_agent.py` | 将已校验关键事实与边界传到写作；决定每节回答什么 |
| `evaluation/report_quality/round2/` | 本轮诊断、固定反例、最终运行及人工内容结论；与上一轮证据分开 |

不复制密钥、数据库或所有调用的无关大对象。诊断只保存本次报告实际输入模型的报告材料、响应正文和必要运行元数据；不保存认证头、环境变量或客户端配置。

## 3. 任务 0：先解释为什么“发现了问题却没有改成”

**修改：** 上表三个评估脚本；新增 `tests/test_report_quality_trace.py`、`evaluation/report_quality/round2/diagnosis.md` 和 `fixtures/`。

- [x] 从现有 low_altitude、biology、sea 的 body/coordination/calls 记录提取具体失败位置。逐个关联声明 ID、段落 ID、证据、检查结果、修改指令、候选补丁和回滚原因；已有记录不能说明原因的明确记为待捕获，不推断模型响应。
- [x] 在评估入口增加可选的本地调用记录；记录调用序号、阶段、耗时、finish_reason、输入、原始响应及解析失败原因。修正过程另记录修改目标、采用或拒绝以及具体原因。只启用在评估运行，不给正常用户增加调试操作。
- [x] 用假响应分别制造“有效 JSON 漏声明”“引用校验失败”“补丁定位失败”“信息保留复核回滚”，验证记录能区分这四种失败，且模型调用和报告内容不被记录逻辑改变。
- [x] 对无法从现有证据解释的低空失败调用做局部生产重放，携带原始证据及预算；不先重跑三份全文。保留成功和失败响应，不只截取支持假设的例子。
- [x] 写出每条可修根因对应的真实请求/响应路径；把语义误判、协议漏项、确定性校验拒绝和预算未执行分开。后续每项修复引用这里的案例。

运行：`LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_quality_trace.py -q`。

**检查目的与动作：** 若四类失败被混成“unknown”，修记录和结果归因；若输入或调用行为被改变，撤回记录侵入。真实重放只用于补足缺失的因果证据，不计作最终连续验收。

## 4. 任务 1：补齐核对结果，避免不相关证据影响当前声明

**修改：** `review_batches.py`、`agentic_rag/verification.py`；测试 `tests/test_report_review_batches.py`、`tests/test_agentic_report_verification.py`。

- [x] 加失败测试：输入声明 A/B，模型只返回 A；A 结果保留，B 被识别为缺项。返回重复 A 或未知 C 不能让 B 被算作已核对。
- [x] 加失败测试：B 所需引用完整，但另一条 A 的证据被截断，不能仅因整节 `incomplete_evidence=True` 将 B 的有效判断一律降为 unknown。反例是 B 自己的来源缺失，此时必须 unknown。
- [x] 在 `prepare_section` 和 `validate_checks` 中把证据缺失/截断关联到具体引用及声明。保留当前显式错误引用不能借其他来源通过的约束，不将“未找到支持”自动等同于现实世界为假。
- [x] 在 `check_claim_batches` 中对本批提交的 ID 和有效返回的 ID 对账。首次解析失败、截断或结果缺项共享一次补核机会，只重发缺失/无效项；不能“截断重试一次”后再叠加无限缺项重试。已完成声明不重复调用。
- [x] 补核前沿用 `call_remaining` 和现有超时。无时间、二次缺项或失败时返回具体未核对原因，保留其他成功结果，并保持 incomplete。
- [x] 保存逐声明有效结果；禁止以“有一个 claim_checks 数组”或“模型声称 completed”代替完整性判断。

可直接加入分批测试的核心断言（沿用测试文件现有 prepared-section fixture 与假 query）：

```python
rows, failures, losses = check_claim_batches(prepared_sections, query, prompt)
returned = [row['claim_id'] for row in rows['S1.1']]
assert sorted(returned) == sorted(c['claim_id'] for c in prepared_sections[0]['claims'])
assert len(returned) == len(set(returned))
```

运行：`LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_review_batches.py tests/test_agentic_report_verification.py -q`。

**验收：** 无截断漏项能有限补全；失败不污染成功结果；不能靠把 unknown 全部改成 supported 提高通过率。若重放仍缺项，定位原始响应及校验规则，不直接提高全局 token 上限。

## 5. 任务 2：统一关键事实的对象、时间与适用范围

**新增：** `report_generation/report_facts.py`、`tests/test_report_facts.py`。**修改：** `coordinator_agent.py`、`task_coordination.py`、`writing_decisions.py`、`body_agent.py`、`review_agent.py`。

先解决决定结论的状态和数字：证照、实际/计划投产或交付、营收归属、统计时期与分类、项目要求的适用对象。不抽取所有实体，不建立全行业事实库。

关键事实使用以下紧凑结构；字段只表达来源确实能支持的内容，不知道的保持空值：

```json
{
  "subject": "企业甲的产品A",
  "attribute": "型号合格证",
  "value": "已取得",
  "event_time": "2025年3月",
  "published_at": "2025-04-01",
  "modality": "actual",
  "applicability": "仅适用于产品A，不代表企业其他产品",
  "supports": [{"evidence_id": "已有片段ID", "citation_id": "C19", "quote": "来源逐字原文"}]
}
```

- [ ] 加失败测试：同一公司不同型号不能被合成一个证照状态；发布时间不等于事件时间；后发布的历史回顾不能仅凭日期覆盖较早的实际事件；计划投产不能升级为已投产。
- [ ] 加适用性反例：项目申报指南支持“该项目的申报要求”，不支持“整个食品路线必须达到此要求”；图谱列出关联只支持该记录关系；公司总营收不支持相关业务收入。
- [ ] 在既有协调输入与结果中加入关键事实候选，先验证支持片段身份及逐字引文，再采用。来源不足时保留未决边界，不能选“日期最新的一条”自动消解冲突。优先复用现有协调调用的输出预算；不按每节增加事实抽取调用。
- [ ] 若真实长输入证明同次协调不能容纳这些内容，再只为存在冲突的关键事实安排一个有预算上限的小批判断；记录新增耗时。没有冲突的报告不得固定增加一轮全篇调用。
- [ ] 通过写作任务传递相关关键事实与来源，不能把全部原文复制进每节。事实表是检索原文的索引，正文引用仍指向原文，不能引用协调结论自身。
- [ ] 复用审查的跨节候选定位，检查同一对象/指标/时期是否出现互不相容的陈述。不能只检查初始候选声明，因为正文可能新增了错误归纳。
- [ ] 来源冲突修正后复核冲突组中的最终段落，要求给出被修正/仍保留的实际句子与支持。`consistency_resolved:true` 只有与有效原文位置和依据一致时才可采用；不能靠该布尔值清除警告。

运行：`LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_facts.py tests/test_report_task_coordination.py tests/test_report_coordinator_citations.py tests/test_body_agent.py tests/test_report_review_agent.py -q`。

**验收：** 对已确认是同一对象同一状态的冲突，最终正文统一；对实际属于不同产品/时期的状态，正文解释差异，不能强行统一。低空 TC 案例须先读源文确认对象，不能把案例描述直接当已确定外部事实。

## 6. 任务 3：一次完成重叠事实修正与去重

**修改：** `agentic_rag/verification.py::merge_edits`、`review_agent.py::_apply_patches` 和改后复核；测试 `tests/test_agentic_report_verification.py`、`tests/test_report_review_agent.py`、`tests/test_report_review_flow.py`。

- [ ] 加失败测试：同一段既有重复背景又有错误状态，不能只删重复后把事实修正 deferred；同时测试错误状态出现在原 `keep_spans` 中。
- [ ] 将同一原文位置的重叠修改意图合并，区分必须修正的事实、可压缩的重复内容、必须保留的独有事实及目标保留位置。先按原始正文确定区间，再一次生成补丁，禁止修改一次后沿用旧偏移继续修改。
- [ ] `keep_spans` 只保护有据且需要保留的信息，不能保护已经证伪的措辞；若保留位置本身有问题，将该位置纳入修正组，或把有据内容放到有效保留位置。不能因此把整个小节放开重写。
- [ ] 局部修正后同时验证：已定位事实问题是否消除、重复内容是否按分工减少、独有事实和正确引文是否保留、是否新增无据断言或重复前导句。
- [ ] 候选修正被拒绝时，只在预算允许下对该组携带具体拒绝原因修复一次；补核与修补计入原审查阶段，不能各自独立无限重试。仍失败就保留原文、未完成状态和具体原因。
- [ ] 对任务 0 捕获的回滚案例逐一重放，不能为了增加采用率删除信息保留复核、引用校验或语法检查。

运行：`LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_agentic_report_verification.py tests/test_report_review_agent.py tests/test_report_review_flow.py -q`。

**验收：** 可兼容的重叠问题不再仅因位置重叠被推迟；不兼容的真实冲突仍明确保留。成功标准是最终段落正确且不丢有效内容，不是采用修改数增长。

## 7. 任务 4：让章节保留依据“回答了什么”

**修改：** `agentic_rag/assessment.py`、`task_coordination.py`、`report_scope.py`、`writing_decisions.py`、`body_agent.py`；测试 `tests/test_agentic_report_assessment.py`、`tests/test_report_task_coordination.py`、`tests/test_report_scope.py`、`tests/test_report_writing_decisions.py`、`tests/test_body_agent.py`。

- [ ] 将生物制造已观察到的证据越界和独立用途不足固定为回归；该题从本轮开始仅作开发回归，不能继续称为未见保留题。
- [ ] 加一组正反例：两个产品各自有路线/阶段事实，可以形成原创比较，不要求来源已写好对照结论；只有一个项目申报指南，则不能推导两条路线普遍成本、成熟度或监管门槛。
- [ ] 在现有 writing_decision 的 `section_question`、`evidence_uses`、`content_scope` 中明确本节实质回答、依据和与其他节不同的用途。优先复用现有字段，不另建评分表。
- [ ] 全篇协调保留有实质回答或独立分析作用的小节；只重复方法/资料缺口的小节并入对应内容或集中限制说明。两个小节使用同一事实但回答不同问题，可以保留。
- [ ] 章节必须依靠不适用证据才成立时，删除越界前提，重写具体回答或合并；不能只在结尾加“仅供参考”后保留原结论。
- [ ] 合并后重新校验覆盖映射、有效标题与核心问题；检查有据比较是否一同保留。证据不足优先减少承诺维度，不自动把比较题改成科普题，不用只剩几段通用背景的短稿冒充 brief。
- [ ] 若核心问题仍无实质回答，返回明确 incomplete；若仍有可用比较/节点分析，按其真实范围输出 report 或 brief，并集中说明缺口。

运行：`LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_agentic_report_assessment.py tests/test_report_task_coordination.py tests/test_report_scope.py tests/test_report_writing_decisions.py tests/test_body_agent.py -q`。

**验收：** 生物制造不再用申报指南替代产业路线依据，也不因缺少现成“比较文章”取消有据比较；章节数可以不减少，但每节必须有可说明的独立作用。不以“15 节必须压到 8 节”作为测试。

## 8. 任务 5：分层验证，最后才运行新题全文

**修改：** `scripts/evaluate_report_quality.py`、`evaluation/report_quality/round2/cases.json`、`acceptance.md`、`verification.json`；必要时修改 `tests/test_report_delivery_state.py`。

- [ ] 在任何本轮语义提示词修改前，固定一个新保留题与原始用户要求：在现有资料库支持的行业中，选定此前未调优的具体比较问题，记录选题及冻结时间。优先采用“低空经济运营场景的商业化条件比较：载人出行、物流运输与巡检服务，区分试点、获批、实际运营和规模化”。不能将缺少资料的场景补写为已成熟。
- [ ] 另固定“资料稀少但仍有局部有效依据”和“只有不相关背景”两种离线输入，分别验证有内容的收窄与诚实 incomplete。不能用模型虚构事实补足测试资料。
- [ ] 每个任务先跑明确失败测试，再最小修改、再跑受影响集合；测试响应只能验证程序契约，语义质量另用真实模型和保存的原文判断。
- [ ] 对任务 0 的真实失败分别重放，输出修改前后段落和引用。明显问题尚在时留在局部定位，不反复生成所有全文。
- [ ] 局部通过后，生成低空和生物制造新稿验证整个链路；再运行 17—23 节候选大纲的海洋连续流程和新保留题。均从正常任务卡/大纲进入，不手工填正文，不绕过协调，不把重放累计耗时当连续耗时。
- [ ] 每份记录原需求、有效范围、最终正文、关键结论来源、真实耗时、漏核项、修改采用/回滚原因和交付状态；检查最终 Word 的标题、状态、摘要、引用与正文是否一致。只有导出布局发生变化或新样例暴露问题时扩大渲染检查。
- [ ] 完成一次受影响 Python 集合；前端未改动时不重复 JS 全集，若交付字段/前端改动才跑对应 JS 测试。测试数量与内容验收分别记录。
- [ ] 对新保留题给出可接受/不可接受及具体原因；若失败并据此调优，该题转为开发回归，再冻结另一新题，不继续宣称独立保留验收。

完整连续实跑命令示例（在实施目录执行，输出到新的目录）：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/evaluate_report_quality.py --case low_altitude --source /Users/livictor/Desktop/industry/industry_graph --output report_generation/outputs/report-quality-round2/low_altitude
/opt/miniconda3/envs/kunlun/bin/python scripts/evaluate_report_quality.py --case biology --source /Users/livictor/Desktop/industry/industry_graph --output report_generation/outputs/report-quality-round2/biology
/opt/miniconda3/envs/kunlun/bin/python scripts/evaluate_report_quality.py --case sea --source /Users/livictor/Desktop/industry/industry_graph --output report_generation/outputs/report-quality-round2/sea
```

新保留题沿用同一个 `run_case` 生产流程；在脚本 `CASES` 中增加 `holdout_round2` 键，内容与冻结文件一致，再用 `--case holdout_round2` 执行。不为保留题增加专用生成分支或企业/数字硬编码。

受影响 Python 总集合沿用上一轮命令，并加入新增的三个测试文件：

```bash
LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_agentic_report*.py tests/test_report*.py tests/test_coordinator_stability.py tests/test_body_agent.py tests/test_summary_agent.py tests/test_word_export*.py tests/test_llm_client_configuration.py tests/test_direct_outline_json_recovery.py tests/test_outline_template.py -q
```

其中 `test_report*.py` 自动覆盖新增文件，不重复列名。

## 9. 内容验收与停止条件

每份报告直接做以下判断，不算综合分数：

1. 有效标题和主体内容回答核心问题；收窄后的比较或分析有实质内容，重要缺口可见。
2. 主要结论与决定结论的数字、对象、状态和时间能对应来源；项目/样本边界不能被推广成行业普遍事实。
3. 不存在未解释的关键跨节矛盾；原创分析有事实基础，假设明确，没有把推断写成事实。
4. 不存在明显重复堆叠、破句、重复前导句或有据独有内容被误删；摘要不重新引入正文已删的结论。
5. 必需核对和文件处理实际完成才标 completed；程序成功不替代内容判断。资料不足或执行失败返回明确状态，不通过降低校验标准制造成稿。
6. 从确认大纲启动到文件准备好的连续执行不超过 900 秒。新增诊断重放、开发等待与离线测试不能混入或抵扣该指标。

证据足够的场景应能输出内容可接受的 completed 报告；证据不足的场景允许 brief 或 incomplete，但不能让所有场景都以 incomplete 结束而宣布系统质量目标达成。有限样例验收用于说明当前改进效果，不承诺任意题目零错误。

若连续局部修复仍被同一语义误判阻塞，停止叠加提示词：整理真实输入、正确判断依据、模型输出和确定性拒绝原因。在同一批固定正反例上比较当前模式与已有可用模式的判断和耗时；只有结果支持且能保持整体 900 秒才提议模型模式调整。单次探针成功或 token 增长不构成切换依据。

## 10. 实施顺序与交付记录

顺序：**任务 0 → 冻结新保留题 → 任务 1 → 任务 2 → 任务 3 → 任务 4 → 任务 5 完整验收**。

第一个检查点是低空具体失败从检查到修正形成可解释闭环；第二个检查点是生物制造的证据适用性与章节用途；第三个检查点是长报告及新保留题的最终连续结果。时间紧张时停止扩充功能，先完成这三个检查点，不跳过最后业务验收。

每个任务结束记录修改文件、失败用例、实际验证结果和未解决问题；只同步本任务差量，保留其他未提交工作。本计划本身不要求自动提交、推送或部署。上一轮的 468 个 Python 测试、80 个子测试及 81 个 JS 测试是历史基线，不写成下一轮已通过结果。

本计划的完成条件是上述内容验收与运行约束有实际证据；写完代码、提高修改采用数或把更多状态改为 completed 都不构成完成。

## 执行记录：第二轮开发检查点

任务0与任务1已完成程序实现及针对性验证。诊断重放发现整节声明漏返、重叠补丁拒绝及语义复核回滚，原始证据见 `evaluation/report_quality/round2/diagnosis.md`。任务2—4已接入关键事实、适用范围、重叠修正及一次局部修补，业务效果待完整新稿验证，暂不整体勾选。新保留题已在语义修改前冻结。上一轮基线未被覆盖。

### 实跑后的追加结论

- 真实低空去重8条中7条被同段preserve冲突拒绝，已归一为保留待改片段之外的实质正文；整段冲突及只剩引用仍拒绝。另一次原文摘录不准确导致全部去重未采用，已保留原始调用与具体拒绝原因，尚未解决模型长摘录定位的可靠性。
- 海洋真实20节输出的显式合并与标题数组矛盾，重问仍无效。已采用显式操作作为结构来源、标题数组提供保留章节名称/顺序；真实决策确定性归一20→17，不把它当正文验收。
- 协调阶段累计上限从300秒校准至360秒，总900秒不变，正文600/审查810/摘要导出900累计截止不变；单独海洋在旧上限下272秒已完成协调，之前并行评估曾到300秒结束。新的阶段校准有假时钟、网络截止与迟到结果测试，真实进程版本边界另记。
- 低空8节460.41秒、生物制造16节642.71秒、新保留题12节641.85秒均跑完摘要/Word但仍incomplete，内容不通过。独立保留题已曝光；后续若据其内容调优，改列开发回归并另冻新题。
- 全批切换思考模式的探针截断，小批改善也不稳定；未切换生产模式。下一步应重新评估章节实质回答、审查判断与定位职责，不继续仅叠加提示词。
- 具体业务失败见 `evaluation/report_quality/round2/acceptance.md`。计划任务5以及任务2/4中与实质判断有关的验收保持未完成，不以代码与测试完成代替内容达标。


## 继续实施记录：现有模型下减少歧义任务

用户确认仅当前模型可用，不以换模型为前提。真实失败支持两处调整：重复审查以程序生成片段编号定位，绑定原文位置后沿修改链传递；范围协调增加同调用的紧凑section_answers，为每个保留小节明确实际拟回答及引用，正文必须面对该回答，而非只重复任务名称。它复用原有分工、合并、来源和事实索引，不增加模型调用或通用评分类系统。原计划优先复用writing_decision，但该决策先于全篇范围、合并和关键事实产生，且changes仅修少量冲突，不能表达每个最终小节的实际回答，因此采用这组紧凑安排而不输出逐节完整决策。

程序回归和独立代码审查已覆盖定位、位置合并、共享原文和安排缺项。真实编号回放有改善但内容仍不通过；新全流程遇到SSL连接中断，section_answers生产语义效果尚未实测。任务4与任务5继续保持未完成。完整证据见round2/acceptance.md和verification.json。


### 声明上下文的追加根因与动作

继续执行中，从保存的真实请求发现初始声明批次删除完整正文且未给原段上下文，导致跨段批次把“公司”误解成上一企业。初查现传本批声明的对应原段（长段只保留段首与声明邻域且标截断），实际分批容量计入新增上下文；不把正文当作外部证据。另修复“包括与甲、乙等达成合作”中的名单介词误提取，保留缺失实体的拦截。两处均有修前失败/修后通过回归及原真实响应离线证据，未手改报告正文。

截至2026-10-17 21:07，最小模型请求仍TLS失败，普通HTTPS也无法访问；尚无最终新版本连续运行证据，内容验收仍未完成。不得因离线输入容量通过或真实旧响应重新校验通过而勾选全文验收。


## 2026-10-18 最终代码实测与未完成项

连接已恢复，不能继续以网络阻塞解释当前验收。继续实现了全篇已有来源接入section_answers目标任务、同片段排名元数据差异去重、审批/准入/商业化关键声明覆盖、动作列表不误认实体名单，并将协调累计截止校准为420秒；总900秒及后续累计截止不变。每项有具体真实失败、修前失败测试及修后验证，代码独立审查无未处理发现。主目录受影响集合521项、80个子测试通过（8.13秒）。

生物制造新稿679.86秒、海洋长稿746.64秒均走完正文/摘要/Word但内容不通过；二者启动于最后去重/覆盖/预算修改之前，不当最终版本验收。低空来源共享重放407.14秒为累计，不能替代连续运行。

包含全部最终代码的新保留题在654.78秒连续完成14节、摘要与Word，协调396.20秒。实际内容仍不通过：物流C30已有具名客户正式上岗、持续优化五个多月、24小时作业记录，但部署分层与摘要仍称没有持续运行证据；Figure直播“2025年5月”与2026年来源“今年5月”不一致却被复核supported；若干部署/验证章节重复案例且漏综合更直接的证据。本体/供应商分工总体守住条件推断，但未充分完成比较。详见round2/acceptance.md。

这证明本次最终版本流程能在900秒内结束，不证明交付质量达标。根据第9节停止条件，不继续仅叠加提示词。任务2、任务4及任务5的业务验收保持未完成；如果据新保留题调优，必须将其转开发回归并再冻结独立新题。低空最终代码连续回归仍在执行，结果另追加。


### 低空最终连续回归：402外部阻塞

2026-10-18 00:41，最新代码的低空8节报告在358.49秒结束。协调与8节正文成功，开始审查后第64—71次请求连续返回`402 Payment Required`，摘要第72次请求同样返回402，故review partial、summary error、没有Word。该次已用量599323输入token、76854输出token，9次失败请求无usage。不是900秒耗尽，也不能算完成连续验收；未再发模型探针或重试整份报告。返回体未给出更具体计费原因，不能断言一定余额为零。

证据在runs/low_altitude_final和fixtures/final-low-402-failures.json。当前外部阻碍已从此前恢复的TLS切换为模型接口402；但这不解释此前新保留题已经查实的内容错误。最新代码低空的完整质量验证仍待接口恢复。

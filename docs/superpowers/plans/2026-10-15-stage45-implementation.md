# 阶段 4 与阶段 5 GraphRAG 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在具身智能新映射和证据限定已经接入写作上下文的基础上，完成一份可追溯的具身智能完整报告验收，并把已验证的证据约束与产业配置抽取为可供第二个产业试点复用的最小接口。

**Architecture:** 阶段 4 先沿现有报告入口运行 `embodied` 的真实检索、图谱证据增强、章节分配、正文、摘要、引用注册和 Word 导出；验收同时检查“证据支持范围”和最终写作表述，发现越界后回到阶段 3 修复。阶段 5 只抽取已验证的 sidecar 证据格式、审核状态、上下文约束和产业路径配置，先在一个小规模产业试点上验证，不修改现有八产业数据，也不引入新数据库、社区摘要或全局迁移框架。

**Tech Stack:** Python 3、现有 `report_generation` 协调器、具身智能 Chroma SQLite、现有 lexical index、GraphRAG sidecar、pytest、现有 Word 导出器、JSON/Markdown 验收产物。

---

## 范围与前置条件

- 阶段 4 的行业固定为 `embodied`，报告主题固定为“具身智能产业发展报告”。
- 阶段 4 使用当前正式映射 `static/data/embodied/graph_evidence_links.json`，不使用候选文件直接检索。
- 阶段 4 必须使用当前 `embodied_news` 数据库和 `hybrid_v2` 链路；如果发生 `legacy_news` 回退，结果只能记录为失败或受限运行。
- 阶段 3 已把 `review_method`、`review_note`、`evidence_scope` 传到证据上下文；阶段 4 需要验证写作是否遵守这些字段。
- 阶段 5 只在阶段 4 达到“可运行且证据边界无系统性越界”后开始。
- 报道事实仍需保留来源限定；AI 辅助审核不等于人工或外部事实认证。

## 文件地图

- Create: `evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.json` — 阶段 4 机器可读结果。
- Create: `evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.md` — 阶段 4 人工可读审阅记录。
- Create: `evaluation/graph_evidence/embodied_stage4_outputs/` — 报告、正文、摘要、导出结果和运行日志。
- Modify: `scripts/run_graph_evidence_acceptance.py` — 增加新映射校验、证据限定检查和阶段 4 输出摘要；保留原三路对比行为。
- Test: `tests/test_graph_evidence_report_acceptance.py` — 阶段 4 的确定性校验函数。
- Modify: `report_generation/external_rag/report_adapter.py` — 仅在阶段 4 暴露出字段传递缺失时继续修复，不改变已通过的上下文格式。
- Modify: `report_generation/review_agent.py` 或 `report_generation/body_agent.py` — 仅在真实报告发现证据范围越界且可由写作约束修复时修改。
- Create: `report_generation/graph_evidence_contract.py` — 阶段 5 抽取出的 sidecar 审核字段和产业配置契约。
- Create: `tests/test_graph_evidence_contract.py` — 通用契约的结构和状态测试。
- Create: `evaluation/graph_evidence/stage5_pilot_biology_2026-10-15.json` — 第二产业小范围试点结果。
- Create: `evaluation/graph_evidence/stage5_pilot_biology_2026-10-15.md` — 第二产业试点审阅记录。
- Modify: `docs/graph-evidence-links.md` — 记录阶段 4 验收与阶段 5 复制边界。
- Modify: `docs/superpowers/plans/2026-10-15-embodied-graph-evidence-and-query-expansion.md` — 更新阶段 3、4、5 进度。

## 阶段 4：具身智能完整报告验收

### Task 1: 固化阶段 4 的运行入口和验收问题

**Files:**
- Modify: `scripts/run_graph_evidence_acceptance.py`
- Create: `tests/test_graph_evidence_report_acceptance.py`

- [x] **Step 1: 写失败测试，固定五个检索问题的报告验收输入。**

测试至少固定以下问题和检查字段：

```python
QUESTIONS = [
    "人形机器人伺服电机和无框力矩电机有哪些企业参与？请给出产品证据。",
    "人形机器人控制器与驱动器有哪些企业，分别提供什么产品？",
    "触觉传感器与六维力传感器环节有哪些企业及其产品或检测服务？",
    "人形机器人动力电池的配套企业有哪些？",
    "人形机器人整机有哪些企业及应用案例？",
]
REQUIRED_DIAGNOSTICS = {
    "retrieval_version",
    "retrieval_fallback",
    "hybrid_error",
    "graph_diagnostics",
    "selected_chunk_ids",
}
```

验收函数必须把 `legacy_news` 回退、`hybrid_error`、图谱身份告警和缺少审核限定分别报告为不同失败原因。

- [x] **Step 2: 运行定向测试确认验收函数尚未实现。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_graph_evidence_report_acceptance.py -q
```

预期：新增测试失败，提示阶段 4 校验函数尚未存在。

- [x] **Step 3: 实现最小验收函数。**

函数输入为一条检索结果和一组正式 sidecar 链接，输出 JSON 安全结果：

```python
{
    "retrieval_ok": True,
    "version": "hybrid_v2",
    "fallback": None,
    "hybrid_error": None,
    "identity_warning_count": 0,
    "curation_note_count": 3,
    "failure_reasons": [],
}
```

函数只判断实际结果，不根据候选数量推断质量。

- [x] **Step 4: 运行定向测试。**

预期：所有阶段 4 运行状态和失败原因测试通过。

## Task 2: 运行阶段 4 前的真实链路预检

**Files:**
- Create: `evaluation/graph_evidence/embodied_stage4_preflight_2026-10-15.json`
- Test: `tests/test_graph_evidence_report_acceptance.py`

- [x] **Step 1: 检查具身智能 collection 和当前索引状态。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python - <<'PY'
from report_generation.industry_config import get_industry_config
from report_generation.external_rag.news_index import check_news_index
cfg = get_industry_config("embodied")
print(cfg["collection_name"])
print(check_news_index("embodied"))
PY
```

必须确认 collection 为 `embodied_news`、状态为 READY、向量数量非零；不满足时停止报告生成并记录具体缺失项。

- [x] **Step 2: 运行五个真实检索问题，并保存实际诊断。**

使用：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
/opt/miniconda3/envs/kunlun/bin/python -u \
scripts/run_graph_evidence_acceptance.py \
  --stage compare-three-way \
  --output-dir evaluation/graph_evidence/embodied_stage4_preflight_2026-10-15
```

记录五个问题的基线版本、回退状态、图谱新增 chunk、关键词新增 chunk、身份告警和审核备注数量。

- [x] **Step 3: 写入预检结论。**

只有五个问题都满足 `hybrid_v2`、无 `hybrid_error`、无无法解释的身份告警，才进入完整报告生成。关键词候选可以包含噪声，但必须在后续报告审阅中标记其是否进入最终材料。

## Task 3: 生成具身智能完整报告

**Files:**
- Create: `evaluation/graph_evidence/embodied_stage4_outputs/`
- Modify: `scripts/run_graph_evidence_acceptance.py`（仅补充输出摘要字段）

- [x] **Step 1: 固定报告需求。**

使用：

```
生成一份具身智能产业发展报告，重点分析人形机器人技术进展、产业链结构、政策环境、主要企业、典型应用、商业化趋势及风险挑战，并尽量引用近期可靠资讯。
```

- [x] **Step 2: 通过现有报告入口依次执行大纲、章节检索、正文、摘要、引用注册和 Word 导出。**

必须保存：

- 最终大纲；
- 每个章节的检索问题和 evidence blocks；
- 正文和摘要；
- 引用注册结果；
- Word 导出 JSON 和绝对路径；
- 完整运行日志。

如果 LLM 凭据或服务不可用，保存本地检索和上下文结果，报告状态标记为 `blocked_external_model`，不得伪造完整报告成功。

- [x] **Step 3: 检查报告路由。**

从运行产物确认所有章节使用 `industry="embodied"`、资料库为 `embodied_news`，图谱文件为 `static/data/embodied/graph_data.json`。发现 `ai`、其他产业 collection 或 `legacy_news` 混入时，停止验收并记录章节和证据块。

## Task 4: 审阅证据边界与引用完整性

**Files:**
- Create: `evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.json`
- Create: `evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.md`
- Test: `tests/test_graph_evidence_report_acceptance.py`

- [x] **Step 1: 建立逐事实检查表。**

从正文和摘要抽取企业、产品、数字、日期、订单、部署、合作、产能和政策断言，逐条关联引用 ID。每条记录使用：

```json
{
  "section_id": "S1.2",
  "claim": "某企业在园区进行了人形机器人巡检示范",
  "citation_ids": ["C3"],
  "support_level": "direct|qualified|insufficient",
  "curation_note_obeyed": true,
  "boundary_issue": "",
  "review_method": "ai_assisted_source_review"
}
```

- [x] **Step 2: 强制检查四类高风险改写。**

至少检查：

1. “参展/演示/测试”是否被写成“已部署/已量产”；
2. “战略合作/意向协议”是否被写成“已经供货/采购完成”；
3. “规划产能/未来目标”是否被写成“当前产能/已交付”；
4. “小批量订单/送样/检测服务”是否被写成“规模化供货/成熟产品”。

发现一次越界就标记 `boundary_issue`，该条报告不能进入通过状态，必须回到阶段 3 修正写作约束或改写正文。

- [x] **Step 3: 检查引用完整性和来源分布。**

验证：

- 正文和摘要中的每个引用 ID 都存在于 references；
- references 中的 chunk/document/material/library 身份可回查；
- 主要章节至少包含一条外部资料引用或明确记录“无直接证据”；
- 同一资料不会无理由垄断所有章节；
- 图谱实体提及与关系支持在 diagnostics 中保持区分。

- [x] **Step 4: 检查 Word 导出。**

运行现有导出器和引用校验测试。记录 DOCX 文件路径、状态、引用警告和视觉检查结果。中文视觉显示异常时，状态写为 `exported_visual_qa_limited`，不能写成视觉验收通过。

- [x] **Step 5: 形成阶段 4 结论。**

结论只能是以下三种之一：

- `passed`：检索、报告、引用、边界和导出均满足标准；
- `runnable_quality_followup`：链路运行成功，但存在可控的相关性、重复或来源多样性问题；
- `blocked`：存在回退、身份错误、引用断裂、系统性证据越界或外部服务阻断。

## Task 5: 阶段 4 回归与退出门

**Files:**
- Modify: `docs/graph-evidence-links.md`
- Modify: `docs/superpowers/plans/2026-10-15-embodied-graph-evidence-and-query-expansion.md`

- [x] **Step 1: 运行阶段 4 相关测试。**

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest \
  tests/test_graph_evidence_report_acceptance.py \
  tests/test_graph_evidence_retrieval.py \
  tests/test_graph_evidence_links.py \
  tests/test_graph_query_expansion.py \
  tests/test_graph_retriever_dynamic_hierarchy.py \
  tests/test_report_rag_adapter.py \
  tests/test_report_body_citations.py \
  tests/test_summary_agent.py \
  tests/test_word_export_citations.py -q
```

预期：所有测试通过，且阶段 4 产物记录真实报告状态。

- [x] **Step 2: 更新阶段 4 结论。**

只有达到 `passed` 或明确的 `runnable_quality_followup`，才允许开始阶段 5；`blocked` 必须停留在具身智能链路修复。

## 阶段 5：多产业复制的最小试点

### Task 6: 抽取通用 GraphRAG 证据契约

**Files:**
- Create: `report_generation/graph_evidence_contract.py`
- Create: `tests/test_graph_evidence_contract.py`

- [x] **Step 1: 写契约测试。**

契约至少支持以下字段：

```python
{
    "element_type": "node|relationship",
    "id": 101,
    "source": 101,
    "target": 205,
    "type": "参与环节",
    "evidence_kind": "entity_mention|relationship_support",
    "evidence_refs": [{
        "material_id": "biology-material-001",
        "document_id": "biology-material-001",
        "chunk_id": "biology-material-001:0",
        "library": "biology_news",
        "verification_status": "approved",
        "review_method": "ai_assisted_source_review",
        "review_note": "仅支持原文明确的产品展示表述",
        "evidence_scope": "展示或案例描述，不外推为量产交付"
    }]
}
```

测试要求：

- `pending`、`rejected` 引用不会被加载；
- `entity_mention` 不自动升级为 `relationship_support`；
- relationship 的 source、target、type 必须完整；
- 同一个 element 和 chunk 只出现一次；
- 审核字段可以为空，但不能伪造为 approved。

- [x] **Step 2: 实现纯数据校验和规范化函数。**

实现以下纯函数，避免把产业选择、数据库读取和写作提示词混在契约层：

```python
normalize_evidence_link(link: Mapping[str, Any]) -> dict[str, Any]
validate_evidence_sidecar(payload: Mapping[str, Any]) -> list[str]
filter_approved_evidence_refs(refs: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]
```

函数只做字段、状态、去重和关系类型校验；不做评分、不联网、不复制原文。

- [x] **Step 3: 运行契约测试。**

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_graph_evidence_contract.py -q
```

## Task 7: 抽取产业配置并选择试点

**Files:**
- Modify: `report_generation/industry_config.py`
- Create: `evaluation/graph_evidence/stage5_pilot_biology_2026-10-15.json`

- [x] **Step 1: 选择已有图谱、资料库和行业配置的“生物制造（biology）”作为试点。**

选择标准：

- 已有 `graph_data.json`；
- 已有对应资料库和稳定 chunk ID；
- 至少有一个可核对的终端环节；
- 不要求先建设新向量库。

生物制造已经有 `static/data/biology/graph_data.json`、`report_generation/vector_db/biology` 和 `biology_news` 配置；如果运行时任一项缺失，记录 `pilot_blocked_missing_graph_or_index`，不新建数据。

- [x] **Step 2: 抽取最小产业配置。**

配置只包含：

```python
{
    "industry": "biology",
    "graph_path": "static/data/biology/graph_data.json",
    "evidence_sidecar_path": "static/data/biology/graph_evidence_links.json",
    "collection_name": "biology_news",
    "rag_type": "news",
    "terminal_segments_source": "graph_data.json 中没有下级‘从属于’节点的环节节点",
}
```

不复制具身智能企业名、产品名或主题词到试点配置。

- [x] **Step 3: 验证试点配置指向真实文件和资料库。**

运行只读检查，输出图谱节点/边数量、sidecar approved 数量、可定位 chunk 数量和身份告警。发现资料库缺失、身份不匹配或 chunk 无法读取时停止试点。

## Task 8: 在生物制造产业运行小规模复制验收

**Files:**
- Create: `evaluation/graph_evidence/stage5_pilot_biology_2026-10-15.md`
- Test: `tests/test_graph_evidence_contract.py`
- Modify: `docs/graph-evidence-links.md`

- [x] **Step 1: 只绑定一个终端环节的少量证据。**

试点最多使用 10 个 approved element–chunk 绑定；每条都记录 `entity_mention` 或 `relationship_support`，不扫描全库，不批量审核全部企业。

- [x] **Step 2: 运行三个小规模查询。**

查询分别覆盖：

1. 一个企业/实体事实；
2. 一个产品或环节事实；
3. 一个应用或政策事实。

保存原始 Hybrid、GraphRAG 证据和最终合并结果，确认原始 Hybrid 可独立工作。

- [x] **Step 3: 检查复制边界。**

验证：

- 试点没有读取 `embodied` 的图谱或 sidecar；
- 试点没有混用 `embodied_news`；
- pending/rejected 引用没有进入检索；
- 节点提及和关系支持仍保持分离；
- 审核备注能够进入上下文；
- 失败时只影响试点，不改变其他产业运行。

- [x] **Step 4: 保存阶段 5 结论。**

阶段 5 只允许得到：

- `pilot_passed`：契约和一个产业试点通过；
- `pilot_quality_followup`：链路可运行，但证据覆盖不足；
- `pilot_blocked`：配置、资料库或身份校验失败。

不得因为一个试点通过就宣称所有产业已经完成迁移。

## 统一验证命令

阶段 4：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest \
  tests/test_graph_evidence_report_acceptance.py \
  tests/test_graph_evidence_retrieval.py \
  tests/test_graph_evidence_links.py \
  tests/test_graph_query_expansion.py \
  tests/test_graph_retriever_dynamic_hierarchy.py \
  tests/test_report_rag_adapter.py \
  tests/test_report_body_citations.py \
  tests/test_summary_agent.py \
  tests/test_word_export_citations.py -q
```

阶段 5：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest \
  tests/test_graph_evidence_contract.py \
  tests/test_graph_evidence_links.py \
  tests/test_graph_evidence_retrieval.py -q
```

## 退出标准

阶段 4 完成需要：

1. 新映射下的具身智能完整报告确实运行；
2. 五个主题检索保持 `hybrid_v2` 或有明确质量跟进结论；
3. 主要事实有引用，引用可回查；
4. 证据限定没有系统性越界；
5. Word 文件生成并记录视觉 QA 限制；
6. 阶段 4 相关回归通过。

阶段 5 完成需要：

1. 通用证据契约测试通过；
2. 生物制造这一非具身产业完成小范围试点；
3. sidecar、图谱和资料库完全按产业隔离；
4. 节点提及、关系支持和审核限定保持原语义；
5. 试点结果明确记录为通过、质量跟进或阻断；
6. 没有把一个产业试点的结果扩展成全行业完成。

## 当前不处理

- 不在阶段 4 重建具身智能向量库；
- 不在阶段 4 修改 chunk 大小、embedding 或 reranker 权重；
- 不在阶段 5 全行业批量生成候选；
- 不迁移历史 sidecar，不新增数据库；
- 不引入哈希、校验和、feature flag 或兼容层；
- 不将 AI 辅助审核写成“人工认证”；
- 不将 Word 导出成功写成中文视觉 QA 已通过。



## 实际执行结论（2026-10-15）

阶段四：`runnable_quality_followup`。按真实大纲智能体生成三章六节并完成统筹、正文、摘要、引用和Word导出；保留运行日志与原始产物，来源审阅后做12条定点修订并复审。原始版本有局部证据外推，结论针对修订版本；技术评测/政策原始文件不足和跨章重复仍需跟进。Word为`exported_visual_qa_limited`，不能声称视觉排版通过。

阶段五：`pilot_passed`。契约抽取后由原GraphEvidenceIndex复用；产业配置已经通用，因此Task7复用industry_config及图旁sidecar发现，不额外添加重复字段包装。biology单终端47、凯赛生物节点266，3个approved实体–chunk绑定、1条pending参与边。三个真实问题全hybrid_v2、行业隔离及限定传递正常，相对基线新增0，不宣称质量提升或全行业迁移完成。

实现中修复了两项真实缺口：审核限定从sidecar实际加载时及重复chunk合并时丢失；验收器错误要求未选中图谱关联的备注。通用契约另补完整sidecar与chunk-only inline引用的兼容身份合并，显式冲突仍交解析器报错。

最终相关回归153 passed、32 subtests passed。记录见`evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.json`、`evaluation/graph_evidence/stage5_pilot_biology_2026-10-15.json`。Task4逐事实审阅为AI辅助来源审核，不是外部真实性认证；原稿和逐条修改均保留。上述步骤勾选表示已执行并记录实际结论，不表示所有质量/视觉限制消失。


## 复查修正记录

本次复查补正S2.2段首：未来市场预测不再写作当前部署增长，也不扩展到商业服务部署现状；正文修改累计13条（E13），A026覆盖段首预测限定。A034的审阅引用字段由C2修为C12，与正文及原chunk一致。修订前产物保留为`*.before_review_fixes.*`，最初模型原稿仍保留。

代码已限制graph_matches只使用本次实际通过身份校验且在40条读取上限内的引用；同chunk有效实体引用不会恢复被拒绝的关系标注，下行与祖先路径均有回归覆盖。

`--stage report`现调用大纲智能体，按三章报告模板执行大纲、统筹、正文、摘要和Word导出并保存各阶段产物；`--stage export-report`只导出已保存的正文/摘要，不调用生成模型。原始验收报告确实运行过；本次未重新运行完整在线生成，新入口用离线编排测试验证，已真实执行export-report并重新渲染。Word中文仍不可见，视觉验收状态保持受限。

# 具身智能 GraphRAG 证据覆盖与关键词增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 扩大具身智能知识图谱到原文 chunk 的高价值证据覆盖，并让图谱实体、产品和环节信息以独立 lexical 查询参与 Hybrid RAG，同时保留现有 GraphRAG 证据增强链路。

**Architecture:** 阶段一继续使用现有 `graph_evidence_links.json` sidecar，通过候选扫描、人工审核和 approved 映射扩展证据覆盖。阶段二在图谱检索成功后生成受控的 `graph_query_terms`，对当前产业原文执行额外 lexical 检索；原始 Hybrid 候选、图谱关键词候选和已绑定图谱证据候选统一去重并交给同一个 reranker，最终结果仍进入现有章节材料分配和引用流程。关键词扩展只增加候选来源，不改变原始查询和现有回退语义。

**Tech Stack:** Python 3、现有 Chroma SQLite、现有 SQLite lexical index、`jieba`、`retrieval_core`、现有 reranker、pytest、JSON/Markdown 审核产物。

---

## 范围与验收边界

- 只处理 `embodied`，不扩展其他产业。
- 只扩展高价值主题：电机、控制器与驱动器、力觉与触觉传感器、动力电池、人形机器人整机和应用案例。
- 实体名称出现只生成 `entity_mention`；只有原文明确表达企业与产品、环节、供应或应用关系时，才允许 `relationship_support`。
- `pending`、缺少 `chunk_id`、身份不匹配或无法在当前原库定位的映射不得进入检索。
- 不新建数据库，不引入社区摘要，不重写现有 Hybrid pipeline，不增加 feature flag、迁移框架或哈希校验。
- 关键词扩展必须保留原始 Hybrid 查询，并在诊断中区分原始候选、图谱证据候选和图谱关键词候选。

## 文件地图

- Modify: `static/data/embodied/graph_evidence_links.json` — 保存人工审核后的 approved 证据映射。
- Create: `evaluation/graph_evidence/embodied_stage1_candidates_2026-10-15.json` — 阶段一待审核候选，禁止覆盖已有 sidecar。
- Create: `evaluation/graph_evidence/embodied_stage1_candidates_2026-10-15.md` — 候选原文和审核依据。
- Create: `evaluation/graph_evidence/embodied_stage1_review.json` — 已审核记录和覆盖统计。
- Modify: `scripts/build_graph_evidence_links.py` — 支持按主题、扫描范围和已有映射去重生成候选（若现有参数已经满足，则只补测试，不改行为）。
- Modify: `report_generation/graph_retriever.py` — 从选中的图谱证据块生成受控关键词和来源诊断。
- Create: `report_generation/external_rag/graph_query_expansion.py` — 生成关键词、执行 lexical 查询并返回带来源的候选。
- Modify: `report_generation/external_rag/graph_evidence_retrieval.py` — 合并原始 Hybrid、图谱证据和关键词候选，保留来源类别和统一重排。
- Modify: `report_generation/coordinator_agent.py` — 在现有章节检索入口接入关键词候选，并把诊断告警传入任务结果。
- Create: `tests/test_graph_query_expansion.py` — 关键词生成、清洗、上限和 lexical 候选测试。
- Modify: `tests/test_graph_evidence_candidates.py` — 候选不覆盖 approved 映射、主题筛选和审核字段测试。
- Modify: `tests/test_graph_evidence_retrieval.py` — 三路候选合并、去重、来源诊断和失败回退测试。
- Create: `evaluation/graph_evidence/embodied_stage2_comparison_2026-10-15.json` — 三路检索离线对比结果。
- Create: `evaluation/graph_evidence/embodied_stage2_comparison_2026-10-15.md` — 可读对比报告。

## 阶段一：扩大具身智能高价值证据映射

### Task 1: 固化主题范围和审核格式

**Files:**
- Modify: `scripts/build_graph_evidence_links.py`
- Test: `tests/test_graph_evidence_candidates.py`
- Create: `evaluation/graph_evidence/embodied_stage1_review.json`

- [ ] **Step 1: 写失败测试，确认候选扫描支持主题过滤并保留审核字段。**

测试应验证候选包含 `topic`、`evidence_kind`、`verification_status`、`evidence_refs`、`evidence_excerpt`、`review_note`，并且主题不在六个允许主题内时不会进入输出。

- [ ] **Step 2: 运行定向测试确认当前实现缺少主题过滤或字段时失败。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_graph_evidence_candidates.py -q
```

预期：新增测试在实现前失败；不要修改已有审核 sidecar。

- [ ] **Step 3: 以最小改动实现主题规范化和候选字段保留。**

允许主题集合固定为：`motor`、`controller_driver`、`force_tactile_sensor`、`battery`、`humanoid_robot`、`application_case`。已有命令行默认行为保持不变，主题过滤通过显式参数启用。

- [ ] **Step 4: 运行候选工具测试。**

预期：候选结构测试全部通过，已有 `approved` 映射不会被覆盖。

### Task 2: 扫描并生成具身智能待审核候选

**Files:**
- Create: `evaluation/graph_evidence/embodied_stage1_candidates_2026-10-15.json`
- Create: `evaluation/graph_evidence/embodied_stage1_candidates_2026-10-15.md`
- Test: `tests/test_graph_evidence_candidates.py`

- [ ] **Step 1: 运行候选生成器，覆盖六个主题。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/build_graph_evidence_links.py \
  --industry embodied \
  --scan-limit 20000 \
  --output evaluation/graph_evidence/embodied_stage1_candidates_2026-10-15.json \
  --markdown-output evaluation/graph_evidence/embodied_stage1_candidates_2026-10-15.md
```

输出路径必须不存在；如果路径已存在，改用新的日期后缀，不覆盖已有审核材料。

- [ ] **Step 2: 对候选做身份和文本完整性检查。**

逐条确认 `chunk_id` 可以在当前 `embodied_news` Chroma SQLite 定位，`material_id`、`document_id`、`library` 与实际记录一致，原文非空，候选状态为 `pending`。

- [ ] **Step 3: 人工审核六个主题的高价值候选。**

审核记录必须明确：

```text
approved / rejected
entity_mention / relationship_support
原文支持范围
不能推出的更强结论
```

涉及“检测、参展、计划、战略合作、产业交流”的原文，只保留原文实际表达，不改写成生产、供应或量产。

### Task 3: 合并 approved 映射并生成覆盖报告

**Files:**
- Modify: `static/data/embodied/graph_evidence_links.json`
- Create: `evaluation/graph_evidence/embodied_stage1_review.json`
- Test: `tests/test_graph_evidence_links.py`

- [ ] **Step 1: 为合并逻辑写测试。**

测试覆盖：已有 approved link 保留；重复的 `element_type + node/relationship identity + chunk_id` 只保留一条；`pending` 和 `rejected` 不进入 sidecar；实体提及不能自动变成关系支持。

- [ ] **Step 2: 生成新的 sidecar 临时文件并做结构校验。**

合并顺序为“已有 approved → 新审核 approved”，不直接修改原文件；校验通过后再替换 sidecar 内容。保留 `version=1` 和 `industry=embodied`。

- [ ] **Step 3: 记录阶段一覆盖统计。**

`embodied_stage1_review.json` 至少记录：节点链接数、关系链接数、六个主题各自的 approved 数量、pending/rejected 数量、唯一 chunk 数量和无法定位的候选数量。

- [ ] **Step 4: 运行图谱链接测试。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_graph_evidence_links.py tests/test_graph_evidence_candidates.py -q
```

### Task 4: 阶段一真实证据回归

**Files:**
- Modify: `evaluation/graph_evidence/hybrid_acceptance_20261014/acceptance_notes.md`
- Create: `evaluation/graph_evidence/embodied_stage1_retrieval_smoke_2026-10-15.json`

- [ ] **Step 1: 用六个主题各准备至少一个真实问题。**

问题必须覆盖企业、产品或应用事实，不能只测试环节名称命中。

- [ ] **Step 2: 运行现有 GraphRAG + Hybrid 检索入口。**

验证所有 `approved` 映射可精确取回，身份不匹配为零，`graph_matches` 正确区分实体提及和关系支持，原始 Hybrid 候选仍存在。

- [ ] **Step 3: 保存 smoke 结果和阶段一结论。**

记录每个问题的 `requested`、`resolved`、`added_chunk_ids`、`selected_chunk_ids`、`dropped_linked_chunk_ids` 和告警列表。任何无法解释的身份错误都阻止进入阶段二。

## 阶段二：图谱关键词显式增强

### Task 5: 定义 `graph_query_terms` 数据契约

**Files:**
- Create: `report_generation/external_rag/graph_query_expansion.py`
- Modify: `report_generation/graph_retriever.py`
- Test: `tests/test_graph_query_expansion.py`

- [ ] **Step 1: 写关键词契约测试。**

输入一个图谱证据块，输出结构固定为：

```python
{
    "terms": ["控制器", "驱动器", "禾川科技"],
    "groups": {
        "segments": [...],
        "entities": [...],
        "products": [...],
        "relationship_types": [...],
        "aliases": [...],
    },
    "source_graph_block_ids": [...],
    "diagnostics": {
        "input_count": 0,
        "term_count": 0,
        "dropped_terms": [],
    },
}
```

测试要求：去重、去空白、过滤通用词、限制每组和总词数、保留来源 block ID，不产生未出现在图谱或显式别名表中的新事实。

- [ ] **Step 2: 运行测试确认契约尚未实现。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_graph_query_expansion.py -q
```

- [ ] **Step 3: 从图谱结果生成关键词。**

关键词来源仅包括：

1. 命中的末级环节名称及路径中的具体环节名；
2. `downward_entities` 中的企业/实体名称；
3. 图谱节点中已有的产品字段；
4. 关系类型；
5. 明确配置的别名表。

不把任意原文词语反向加入图谱关键词，也不把“参与环节”改写成“供应商”或“已量产”。

### Task 6: 实现图谱关键词 lexical 检索

**Files:**
- Modify: `report_generation/external_rag/graph_query_expansion.py`
- Modify: `report_generation/external_rag/news_index.py` or the existing lexical adapter used by `retrieve_external_rag`
- Test: `tests/test_graph_query_expansion.py`

- [ ] **Step 1: 写 lexical 检索测试。**

使用临时 SQLite lexical index，验证：关键词查询只返回当前 `industry` 和当前 `library` 的记录；返回记录带 `retrieval_source="graph_keyword"`、关键词命中信息和原始 metadata；空关键词不访问索引。

- [ ] **Step 2: 实现查询入口。**

新增函数签名：

```python
def retrieve_graph_keyword_candidates(
    query: str,
    graph_result: dict,
    industry: str,
    limit: int,
) -> dict:
    """Return lexical candidates selected by approved graph terms."""
```

资讯产业使用当前 `embodied_news` Chroma SQLite 对应的词法索引，索引 READY 检查失败时返回结构化告警，不静默读取旧 sidecar。AI 产业路径保持现有 report v2 lexical index 行为。

- [ ] **Step 3: 设置保守查询边界。**

每次最多使用 20 个关键词、最多返回 20 个候选；优先组合“企业 + 环节”和“产品 + 环节”，再使用单个实体词。只把关键词作为 lexical 召回条件，不直接把 lexical rank 当最终 rank。

- [ ] **Step 4: 运行词法检索测试。**

预期：命中、空词、跨行业、索引缺失和当前索引 READY 检查场景全部通过。

### Task 7: 将三路候选合并到现有 GraphRAG 检索链路

**Files:**
- Modify: `report_generation/external_rag/graph_evidence_retrieval.py`
- Modify: `report_generation/coordinator_agent.py`
- Test: `tests/test_graph_evidence_retrieval.py`

- [ ] **Step 1: 写三路合并失败测试。**

验证以下行为：原始 Hybrid 候选保留；图谱证据候选标记 `retrieval_source="graph_evidence"`；关键词候选标记 `retrieval_source="graph_keyword"`；同一 chunk 只出现一次；统一 reranker 失败时保留原始顺序并产生 `graph_rerank_fallback` 告警。

- [ ] **Step 2: 扩展合并函数。**

将现有 `augment_with_graph_evidence` 扩展为接收可选的 `keyword_candidates`，保持原有调用兼容：

```python
augment_with_graph_evidence(
    query,
    graph,
    retrieval,
    industry,
    top_k,
    keyword_candidates=None,
    scorer=None,
)
```

合并优先级只用于诊断和去重，不直接给图谱候选加分；最终排序仍由相同 query 的 reranker 决定。

- [ ] **Step 3: 接入 coordinator。**

在章节检索中按以下顺序执行：图谱检索 → 生成关键词 → lexical 关键词候选 → 原始外部 Hybrid → 三路合并重排。图谱检索失败或没有 approved 证据时，原始 Hybrid 仍按现有路径执行。

- [ ] **Step 4: 记录可解释诊断。**

至少记录：`graph_keyword_terms`、`keyword_candidate_count`、`graph_evidence_candidate_count`、`original_candidate_count`、`deduped_candidate_count`、`selected_chunk_ids`、各候选 `retrieval_source` 和告警。

- [ ] **Step 5: 运行 GraphRAG 相关测试。**

运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest \
  tests/test_graph_query_expansion.py \
  tests/test_graph_evidence_retrieval.py \
  tests/test_graph_evidence_links.py \
  tests/test_graph_selection_focus.py -q
```

### Task 8: 三路检索对比与阶段二验收

**Files:**
- Create: `evaluation/graph_evidence/embodied_stage2_comparison_2026-10-15.json`
- Create: `evaluation/graph_evidence/embodied_stage2_comparison_2026-10-15.md`
- Modify: `scripts/run_graph_evidence_acceptance.py`

- [ ] **Step 1: 扩展验收脚本记录三种结果。**

对同一组具身智能问题分别保存：

1. 纯 Hybrid；
2. Hybrid + approved graph evidence；
3. Hybrid + approved graph evidence + graph keyword lexical candidates。

每组记录检索版本、回退、候选来源、耗时、新增/替换/丢弃 chunk 和诊断。

- [ ] **Step 2: 运行真实对比。**

运行：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
/opt/miniconda3/envs/kunlun/bin/python -u \
scripts/run_graph_evidence_acceptance.py \
  --stage compare-three-way \
  --output-dir evaluation/graph_evidence
```

五个已有问题必须保持 `hybrid_v2`、无回退、无 `hybrid_error`；新增关键词候选的跨行业和身份告警必须为零。

- [ ] **Step 3: 人工阅读新增关键词候选。**

只对进入最终前 10 的新增候选做人工判断，记录是否补充了企业、产品、关系或应用证据；不能以新增数量单独判断提升。

- [ ] **Step 4: 保存阶段二验收结论。**

结论至少回答：关键词是否召回了原始 Hybrid 漏掉的有效证据；是否引入名称共现噪声；是否需要调整词数上限、查询组合或候选权重；是否影响原有报告引用流程。

## 统一验证命令

每个任务完成后先运行其定向测试，阶段二完成后运行完整相关回归：

```bash
/opt/miniconda3/envs/kunlun/bin/python -m pytest \
  tests/test_graph_evidence_retrieval.py \
  tests/test_graph_evidence_candidates.py \
  tests/test_graph_evidence_links.py \
  tests/test_graph_query_expansion.py \
  tests/test_graph_retriever_dynamic_hierarchy.py \
  tests/test_graph_selection_focus.py \
  tests/test_report_coordinator_citations.py \
  tests/test_report_rag_adapter.py \
  tests/test_report_rag_modes.py \
  tests/test_report_citations.py \
  tests/test_report_body_citations.py \
  tests/test_word_export_citations.py \
  tests/test_news_hybrid_rag.py -q
```

阶段二的完成标准是：

1. 具身智能六个主题都有可追踪的审核统计；
2. 所有启用映射均能精确取回原文，身份告警为零；
3. 图谱关键词候选与原始 Hybrid、图谱证据候选可以稳定合并去重；
4. 三路检索中原始 Hybrid 仍可独立工作并且无回退变化；
5. 关键词来源、候选来源和最终选择都可诊断；
6. 相关回归测试通过；
7. 三路真实对比结果已经人工阅读并形成验收记录。

本计划不包含完整报告重新生成；报告端到端验收属于下一阶段，使用本计划完成后的固定实现和三路对比结果。

## 当前执行进度（2026-10-15）

- [x] Task 1：候选工具已支持六个主题字段和显式主题过滤。
- [x] Task 2：已扫描具身智能 20,000 个片段，生成 137 个 pending 实体候选和 250 条引用；审核材料未覆盖已有 sidecar。
- [x] Task 3（本轮审核）：按用户授权完成 AI 辅助候选筛选与重点正文审核；250 条引用中 47 条通过、164 条不纳入本轮、34 条待补充来源、5 条沿用已有结果。59 条读完整 chunk，其余为摘要筛选。已选择性合并，正式映射为 49 个节点、42 条关系，原有 25 条链接保留。34 条待定未启用，不代表全部候选均完成正文认证。
- [x] Task 4（本地映射 smoke）：六主题均通过真实加载器到原库取文检查，力觉/触觉分别验证；101 条正式引用对应 60 个 chunk，身份告警为零；定向回归 30 项通过。不含 LLM 选环节、Hybrid 重排或报告生成。
- [x] Task 5：已实现 `graph_query_terms` 生成、分组、去重、限额和来源追踪。
- [x] Task 6：已实现具身智能 graph keyword lexical 检索，并保留候选来源和命中词诊断。
- [x] Task 7：已接入 coordinator，原始 Hybrid、图谱证据和关键词候选统一去重重排。
- [x] Task 8：已完成五个真实问题三路对比；结果见 `evaluation/graph_evidence/embodied_stage2_20261015_retry/three_way_acceptance_notes.md`。

本轮新增审核记录：`evaluation/graph_evidence/embodied_stage1_ai_review_2026-10-15.md`；结构化逐条结论为 `embodied_stage1_review.json`；验证为 `embodied_stage1_ai_review_validation_2026-10-15.json`。此前三路对比基于旧映射，不能当作本次扩充后的质量验收。候选主题误分类和审核限定未传入写作链路是已记录的后续问题；当前不能宣布阶段二质量验收或整篇报告端到端验收全部完成。

阶段 3 已开始：`resolve_refs`、证据 block 和 RAG 上下文现在会保留 AI 审核方法与 `review_note`，写作模型可以看到“仅支持展演表述”等限定。定向测试为 70 passed、25 subtests passed。阶段 4（新映射下的完整报告验收）和阶段 5（多产业复制试点）尚未宣称完成。


### 阶段三、四、五后续执行记录

2026-10-15 已补齐真实sidecar加载路径、多节点/关系及已有Hybrid重复chunk的审核限定合并。父link仅补ref缺失字段，未选中关联不会混入上下文。此前阶段三局部字段测试不能替代真实加载验证，现已由集成测试和真实报告材料核对覆盖。

阶段四完成真实大纲、六节检索、正文、摘要与Word导出，结论`runnable_quality_followup`：原始生成结果经12条来源修订及独立复审，无未解决的来源边界问题；Word中文视觉检查受限。阶段五通过单终端生物制造小试点，结论`pilot_passed`，3条实体绑定启用、1条关系pending，三问实际路由与限定传递通过，相对原Hybrid新增均0。仅代表有限复制，不代表全产业质量提升。

详细产物：`evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.json`、`stage5_pilot_biology_2026-10-15.json`。共享契约接入后的相关回归153 passed、32 subtests passed。

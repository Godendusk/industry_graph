# 产业报告跨小节重复控制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不禁止关键资料复用的前提下，分散各小节的外部资料，并让正文和局部重写看到整篇报告已经写过的事实，减少跨小节重复论点。

**Architecture:** 先并行取得各小节的外部资料候选，再由一个纯材料分配器按大纲顺序为每节选择候选、登记报告级引用并重建上下文。写作任务书在材料分配后生成；正文改为按大纲顺序生成，把已完成小节的短事实提示传给后续小节。局部重写继续使用用户选中的材料，同时接收当前小节之外的已写事实提示。保留现有引用校验和流式事件协议。

**Tech Stack:** Python 3、现有 Flask 报告 API、`unittest`/pytest、Node `node:test`、现有 Chroma/Hybrid RAG 和原生 JavaScript 前端。

---

## 文件结构与职责

- Create: `report_generation/material_allocator.py` — 纯函数，按小节顺序从候选中分配外部资料；不调用模型、不访问数据库。
- Modify: `report_generation/coordinator_agent.py` — 将检索、材料分配、写作任务书生成拆成两个阶段；普通和流式入口使用同一分配逻辑。
- Modify: `report_generation/body_agent.py` — 由按一级标题分组并行改为按大纲顺序生成；构造短的全报告已写事实提示。
- Modify: `report_generation/rewrite_agent.py` — 重写提示增加其他小节的已写事实，排除当前小节。
- Modify: `backend_server.py` — 重写接口读取并校验 `previous_body_sections`，传给重写智能体。
- Modify: `static/js/modules/industry_report.js` — 重写请求携带当前报告其他正文小节；保持已有引用选择与预览行为。
- Create: `tests/test_material_allocator.py` — 材料分配、资料复用和候选不足测试。
- Modify: `tests/test_report_coordinator_citations.py` — 两阶段统筹、普通/流式结果和补充候选测试。
- Modify: `tests/test_report_body_citations.py` — 跨一级标题的顺序生成和已写事实提示测试。
- Modify: `tests/test_report_rewrite_citations.py` — 重写避重上下文和引用约束测试。
- Create: `tests/test_report_repetition_replay.py` — 使用历史报告结构做离线分配回放和指标检查，不调用模型或向量库。
- Modify: `tests/js/test_industry_report_citations.test.js` — 重写请求的其他小节字段和序列化测试；需要时把纯请求字段构造函数导出给 Node 测试，不改变浏览器行为。

## Task 1: 实现纯材料分配器

**Files:**
- Create: `report_generation/material_allocator.py`
- Create: `tests/test_material_allocator.py`

- [ ] **Step 1: 写失败测试，覆盖不同资料优先、关键资料复用和候选不足**

```python
import unittest

from report_generation.material_allocator import allocate_evidence_blocks


def block(material_id, vector_id, rank, title="资料"):
    return {
        "library": "policy",
        "material_id": material_id,
        "vector_id": vector_id,
        "rank": rank,
        "title": title,
        "text": f"{title}-{vector_id}",
    }


class MaterialAllocatorTest(unittest.TestCase):
    def test_prefers_unassigned_materials_but_keeps_best_candidate(self):
        sections = [
            {"outline_id": "S1.1", "candidates": [
                block("m1", "v11", 1, "甲"), block("m2", "v12", 2, "乙")
            ]},
            {"outline_id": "S2.1", "candidates": [
                block("m1", "v21", 1, "甲"), block("m3", "v22", 2, "丙")
            ]},
        ]

        allocated = allocate_evidence_blocks(sections, target_per_section=2)

        self.assertEqual(
            [row["material_id"] for row in allocated[0]["evidence_blocks"]],
            ["m1", "m2"],
        )
        self.assertEqual(
            [row["material_id"] for row in allocated[1]["evidence_blocks"]],
            ["m3", "m1"],
        )

    def test_deduplicates_same_material_within_section_and_allows_second_chunk_only_after_distinct_sources(self):
        sections = [{"outline_id": "S1.1", "candidates": [
            block("m1", "v1", 1), block("m1", "v2", 2), block("m2", "v3", 3)
        ]}]

        allocated = allocate_evidence_blocks(sections, target_per_section=3)

        self.assertEqual([row["vector_id"] for row in allocated[0]["evidence_blocks"]], ["v1", "v3", "v2"])

    def test_returns_available_candidates_without_filling_with_duplicates(self):
        sections = [{"outline_id": "S1.1", "candidates": [block("m1", "v1", 1)]}]

        allocated = allocate_evidence_blocks(sections, target_per_section=3)

        self.assertEqual(len(allocated[0]["evidence_blocks"]), 1)
        self.assertEqual(allocated[0]["diagnostics"]["distinct_material_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认纯函数尚不存在**

Run: `python -m pytest tests/test_material_allocator.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'report_generation.material_allocator'`.

- [ ] **Step 3: 实现分配函数和身份回退**

实现 `allocate_evidence_blocks(section_candidates, target_per_section)`，要求：

1. 按输入小节顺序处理；每个候选按原检索顺序稳定处理。
2. 资料身份使用 `library + material_id`；`material_id` 为空时使用 `library + vector_id`。
3. 第一轮每个小节最多取每个身份的一个片段，先选本报告尚未出现的身份，再选已出现次数较少的身份；每节第一名有效候选必须保留。
4. 第一轮不足目标数量时，按原排名补入同一资料的第二个片段，最多两个；不重复同一 `vector_id`。
5. 绝不伪造候选或复制片段。返回深拷贝，保留原字段，并附 `diagnostics`：`candidate_count`、`distinct_material_count`、`reused_material_ids`。

```python
def _material_key(block):
    library = str(block.get("library") or "").strip()
    material_id = str(block.get("material_id") or "").strip()
    vector_id = str(block.get("vector_id") or "").strip()
    identity = material_id or vector_id
    return f"{library}:{identity}" if identity else ""
```

- [ ] **Step 4: 运行纯函数测试**

Run: `python -m pytest tests/test_material_allocator.py -v`

Expected: all allocator tests PASS.

- [ ] **Step 5: 提交独立变更**

```bash
git add report_generation/material_allocator.py tests/test_material_allocator.py
git commit -m "feat: add report material allocation"
```

## Task 2: 将统筹改为“候选检索后分配，再生成任务书”

**Files:**
- Modify: `report_generation/coordinator_agent.py:26-360`
- Modify: `report_generation/external_rag/retriever.py:27-215`
- Modify: `tests/test_report_coordinator_citations.py`

- [ ] **Step 1: 写失败测试，验证分配发生在任务书生成前**

在 `tests/test_report_coordinator_citations.py` 增加测试：mock 每节检索返回 20 条候选，mock 写作任务书 LLM，断言任务书的 `rag_context_text` 只包含分配后的候选；第二小节优先获得未在第一小节使用的材料；同一材料在第一名候选中仍可复用。另加测试断言普通 `generate_writing_tasks` 与 `stream_writing_tasks` 的完成事件返回相同的 `writing_tasks` 和 `references` 结构。

```python
def test_task_prompt_uses_allocated_materials_before_prompt_generation(self):
    with patch.object(coordinator_agent, "_retrieve_candidates_for_subsection") as retrieve:
        retrieve.side_effect = [_retrieval_for_s1(), _retrieval_for_s2()]
        with patch.object(coordinator_agent, "_generate_writing_system_prompt") as prompt:
            prompt.return_value = {"status": "success", "writing_system_prompt": "prompt"}
            result = coordinator_agent.generate_writing_tasks(
                user_prompt="生成报告", report_title="测试报告",
                outline=_outline(), industry="embodied"
            )
    self.assertIn("m3", _material_ids(result["writing_tasks"][1]))
    self.assertNotIn("m4", _material_ids(result["writing_tasks"][1]))
```

测试文件中定义 `_outline()`、`_retrieval_for_s1()`、`_retrieval_for_s2()` 和 `_material_ids()` 四个小型 fixture/helper；测试不得启动真实模型或 Chroma。

- [ ] **Step 2: 运行测试，确认当前统筹顺序导致失败**

Run: `python -m pytest tests/test_report_coordinator_citations.py -v`

Expected: the new allocation-order assertion FAILS because `_generate_writing_task_for_subsection` currently generates each task, including its prompt, inside the retrieval worker.

- [ ] **Step 3: 拆出候选检索和任务书构造函数**

在 `coordinator_agent.py` 增加两个内部函数：

```python
def _retrieve_candidates_for_subsection(
    subsection: dict,
    user_prompt: str,
    report_title: str,
    top_k: int,
    industry: str,
    use_graph: bool,
    use_external_rag: bool,
) -> tuple[dict, list[dict]]:
    """只完成图谱/外部资料检索，不调用写作任务书 LLM。"""

def _build_writing_task_from_retrieval(
    subsection: dict,
    graph_retrieval: dict,
    external_rag_retrieval: dict,
    user_prompt: str,
    report_title: str,
    warnings: list[dict],
) -> tuple[dict, list[dict]]:
    """使用最终分配后的上下文生成一个写作任务书。"""
```

保留现有错误响应格式和 `use_graph`/`use_external_rag` 开关。外部检索第一次调用使用 `candidate_top_k = max(normalized_top_k, min(normalized_top_k * 2, 20))`；返回候选少于 3 个不同资料时，用当前一级标题和二级标题构造一次聚焦查询，第二次调用同样的候选上限，并将两次结果按材料身份合并。补充失败只写 warning，保留第一次候选。

- [ ] **Step 4: 在普通统筹入口中加入两阶段流程**

`generate_writing_tasks` 先用现有线程池完成所有 `_retrieve_candidates_for_subsection`，按 `final_subsections` 顺序组成候选数组；调用 `allocate_evidence_blocks`；对每节注册引用、重建 `rag_context_text`，再调用 `_build_writing_task_from_retrieval`。`references` 的编号顺序仍按大纲顺序。任务书生成失败时使用现有 fallback，不影响其他小节。

- [ ] **Step 5: 同步改造流式统筹入口**

流式入口保留 `task_started` 表示检索开始，但不要在单节检索完成时发送最终 `task_completed`。候选检索全部完成后统一分配材料，再按大纲顺序生成任务书；每个任务书完成后发送 `task_completed`，最后发送现有 `completed` 事件。事件中的 `writing_task`、`references` 和普通入口保持一致。

- [ ] **Step 6: 运行统筹相关测试**

Run: `python -m pytest tests/test_report_coordinator_citations.py tests/test_report_retrieval_evaluation.py tests/test_report_rag_modes.py -v`

Expected: all tests PASS; no test expects a task-completed event before report-level citation registration.

- [ ] **Step 7: 提交统筹变更**

```bash
git add report_generation/coordinator_agent.py report_generation/external_rag/retriever.py tests/test_report_coordinator_citations.py
git commit -m "feat: allocate report evidence across subsections"
```

## Task 3: 让正文生成看到全报告已写事实

**Files:**
- Modify: `report_generation/body_agent.py:144-475`
- Modify: `tests/test_report_body_citations.py`

- [ ] **Step 1: 写失败测试，验证跨一级标题顺序和提示内容**

增加一个 `max_workers=3` 的测试，给三个不同一级标题的小节提供 mock LLM 响应。断言调用顺序严格按 `writing_tasks` 顺序；第二个请求的用户提示包含第一个小节标题和第一句正文，第三个请求包含前两个已完成小节的提示。另加失败小节测试：失败小节不进入后续事实上下文。

```python
def test_body_generation_passes_prior_sections_across_level1_groups(self):
    prompts = []
    def query_result(**kwargs):
        prompts.append(kwargs["user_prompt"])
        return LLMQueryResult(content="本节正文。", finish_reason="stop")
    with patch.object(body_agent.llm, "query_result", side_effect=query_result):
        result = body_agent.generate_report_bodies(
            user_prompt="生成报告", report_title="测试报告",
            writing_tasks=_three_level1_tasks(), max_workers=3, references=[]
        )
    self.assertEqual(result["status"], "success")
    self.assertIn("S1.1", prompts[1])
    self.assertIn("本节正文", prompts[1])
    self.assertIn("S2.1", prompts[2])
```

- [ ] **Step 2: 运行测试，确认当前按一级标题并行时失败**

Run: `python -m pytest tests/test_report_body_citations.py -v`

Expected: the new cross-level prompt assertion FAILS because `_generate_body_group` only passes prior sections inside one level-1 group.

- [ ] **Step 3: 实现短事实提示构造**

在 `body_agent.py` 增加 `_format_prior_report_facts(previous_sections, current_task)`：

1. 按已完成小节顺序遍历成功正文。
2. 每节输出标题和正文首个完整句，句子最长 160 字。
3. 若正文包含当前小节候选中的 `[C数字]`，再输出最多两句含该编号的完整句，每句最长 160 字。
4. 不调用 LLM，不改变 `body_text` 和 `citation_ids`，只生成提示文本；没有已完成正文时返回“暂无整篇报告已生成正文”。

- [ ] **Step 4: 用单一有序生成器替换分组并行**

让 `generate_report_bodies` 和 `stream_report_bodies` 按 `writing_tasks` 原顺序调用 `generate_body_section`，每次把已成功的小节追加到 `previous_success_sections`。保留 `max_workers` 请求字段以兼容前端，但实际报告生成阶段设置并返回 `max_workers=1`，流式事件仍逐节发送。保留现有引用校验、失败状态和 `collect_used_references`。

- [ ] **Step 5: 将短事实提示加入正文用户提示**

在 `_build_body_user_prompt` 增加 `【整篇报告已写事实（仅用于避重）】` 区块，明确：它不是当前小节的可引用证据；当前小节只能使用自己的 `external_rag_retrieval.evidence_blocks` 中的 `[C数字]`。把原有“同一一级标题下已生成正文”改为兼容字段名，避免旧调用崩溃。

- [ ] **Step 6: 运行正文测试**

Run: `python -m pytest tests/test_report_body_citations.py tests/test_report_coordinator_citations.py tests/test_report_rewrite_citations.py -v`

Expected: all citation and ordering tests PASS; valid citation markers remain unchanged and invalid markers are still removed.

- [ ] **Step 7: 提交正文变更**

```bash
git add report_generation/body_agent.py tests/test_report_body_citations.py
git commit -m "feat: generate report sections with prior-fact context"
```

## Task 4: 让局部重写遵守跨小节避重规则

**Files:**
- Modify: `report_generation/rewrite_agent.py:99-205, 285-360`
- Modify: `backend_server.py:730-765`
- Modify: `static/js/modules/industry_report.js:2500-2605`
- Modify: `tests/test_report_rewrite_citations.py`
- Modify: `tests/js/test_industry_report_citations.test.js`

- [ ] **Step 1: 写失败测试，验证重写上下文排除当前小节**

在重写测试中传入当前小节和两个其他小节，mock `rewrite_agent.llm.query`，断言 user prompt 包含其他小节标题和短事实，不包含当前小节正文的“已写事实”条目；断言重写结果仍只接受用户选择材料中的 `[C数字]`。

```python
def test_rewrite_prompt_contains_other_sections_only(self):
    with patch.object(rewrite_agent.llm, "query", return_value="改写正文[C1]。") as query:
        result = rewrite_agent.rewrite_body_section(
            rewrite_prompt="补充材料", report_title="测试报告",
            body_section=_current_section(), graph_retrieval={"graph_context_text": ""},
            selected_external_evidence_blocks=[_evidence("C1")], references=[],
            industry="embodied", previous_body_sections=[_current_section(), _other_section()]
        )
    prompt = query.call_args.kwargs["user_prompt"]
    self.assertIn("其他小节", prompt)
    self.assertNotIn("当前小节的旧正文", prompt)
    self.assertEqual(result["citation_ids"], ["C1"])
```

- [ ] **Step 2: 运行重写测试，确认新字段尚未生效**

Run: `python -m pytest tests/test_report_rewrite_citations.py -v`

Expected: FAIL because `rewrite_body_section` currently has no `previous_body_sections` parameter and no cross-section context.

- [ ] **Step 3: 扩展重写智能体接口和提示**

给 `rewrite_body_section` 增加可选 `previous_body_sections: list = None`。调用 `body_agent._format_prior_report_facts` 或提取同等的无 LLM 纯函数，过滤当前 `outline_id` 后加入 `_build_rewrite_user_prompt`。材料推荐接口不接收正文，避免在用户还未选择材料时扩大请求。系统提示明确：避重上下文只用于改变叙述角度；外部引用仍只能来自 `selected_external_evidence_blocks`；用户明确要求重复背景时按用户要求执行。

- [ ] **Step 4: 传递后端请求字段**

在 `backend_server.py` 的重写路由读取 `previous_body_sections = data.get("previous_body_sections", [])`，要求它是数组，否则返回已有风格的 400；把字段传给 `rewrite_body_section`。材料推荐接口不需要完整正文，只在实际重写请求使用已写事实，避免无关检索调用扩大请求体。

- [ ] **Step 5: 修改前端重写请求**

在 `rewriteIndustryReportSection` 构造请求时，从 `industryReportWorkspace.bodySections` 取出除当前 `outline_id` 外的小节，发送 `previous_body_sections`；不改变用户勾选的外部资料和现有预览/采用流程。增加一个 Node 测试验证序列化请求不包含当前小节、包含其他小节。

- [ ] **Step 6: 运行重写测试**

Run: `python -m pytest tests/test_report_rewrite_citations.py tests/test_report_body_citations.py -v && node --test tests/js/test_industry_report_citations.test.js`

Expected: all tests PASS; rewrite references reuse existing IDs, append new IDs, and reject markers outside selected evidence.

- [ ] **Step 7: 提交重写变更**

```bash
git add report_generation/rewrite_agent.py backend_server.py static/js/modules/industry_report.js tests/test_report_rewrite_citations.py tests/js/test_industry_report_citations.test.js
git commit -m "feat: provide cross-section context to report rewrites"
```

## Task 5: 历史报告回放与端到端验证

**Files:**
- Create: `tests/test_report_repetition_replay.py`
- Modify: `evaluation/report_retrieval/README.md` only if the final command or metric description changes.

- [ ] **Step 1: 写回放测试和具体指标**

从 `report_generation/history/report_history.json` 读取前两份报告的 `writingTasks`、`bodySections` 和 `references`，只对保存的候选和正文做离线统计。测试断言：材料分配不会增加空候选小节；同一小节不出现同一 `vector_id` 两次；关键资料在候选不足时仍可复用；回放输出每份报告的资料使用次数、跨一级标题使用次数和每节不同资料数。

```python
def test_historical_reports_have_replayable_material_stats(self):
    records = _load_first_two_history_records()
    for record in records:
        sections = _candidate_sections_from_history(record)
        allocated = allocate_evidence_blocks(sections, target_per_section=10)
        for before, after in zip(sections, allocated):
            if before["candidates"]:
                self.assertTrue(after["evidence_blocks"])
                vector_ids = [row.get("vector_id") for row in after["evidence_blocks"]]
                self.assertEqual(len(vector_ids), len(set(vector_ids)))
```

- [ ] **Step 2: 运行回放测试**

Run: `python -m pytest tests/test_report_repetition_replay.py -v`

Expected: PASS without model, embedding model or Chroma initialization.

- [ ] **Step 3: 运行针对性 Python 测试集**

Run: `python -m pytest tests/test_material_allocator.py tests/test_report_coordinator_citations.py tests/test_report_body_citations.py tests/test_report_rewrite_citations.py tests/test_report_rag_modes.py tests/test_report_rag_adapter.py -v`

Expected: PASS.

- [ ] **Step 4: 运行 JavaScript 测试和语法检查**

Run: `node --test tests/js/test_industry_report_citations.test.js tests/js/test_industry_report_navigation.test.js`

Expected: PASS.

- [ ] **Step 5: 做一次离线人工检查**

运行回放输出，检查历史报告中已经观察到的三组高频事实（核心部件依赖进口、全链条标准体系、国家大基金入场布局）在新正文提示策略下会被标记为已写事实；确认没有把相同引用次数误报成内容重复。记录正文总耗时变化和空证据小节数。

- [ ] **Step 6: 运行完整现有测试集**

Run: `python -m pytest -q && node --test tests/js/*.test.js`

Expected: all existing tests PASS. If a test requires unavailable external credentials or local stores, report the exact skipped/failing test and do not change production behavior to hide it.

- [ ] **Step 7: 提交验证和文档变更**

```bash
git add tests/test_report_repetition_replay.py evaluation/report_retrieval/README.md
git commit -m "test: validate cross-section repetition control"
```

## 完成标准

- 普通和流式统筹都先完成候选分配，再生成任务书；两种入口的引用编号和材料语义一致。
- 同一小节优先不同资料，资料不足时不伪造候选；关键资料可跨小节复用。
- 正文后续小节能看到跨一级标题的已写事实；正文引用仍只允许当前小节证据。
- 局部重写能看到其他小节事实，仍只能使用用户选择的资料编号。
- 历史报告回放没有新增空证据小节，且输出资料复用和重复事实的诊断数据。
- 相关 Python/JavaScript 测试通过，完整测试结果已记录。

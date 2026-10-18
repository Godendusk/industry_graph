# Report Source Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为产业报告首次生成与局部重写建立报告级外部资料引用，使正文中的 `[C1]` 能稳定对应到真实检索材料，并在网页、历史记录、Markdown 和 Word 中保持可追溯。

**Architecture:** 在现有 Hybrid-RAG `evidence_blocks` 之上增加一个纯函数引用层：按 `library + material_id`（缺失时退回 `vector_id`）去重并分配报告级 `C1...Cn`，正文生成后只接受当前小节证据集合中存在的引用。`body_sections` 保存实际使用的 `citation_ids`，报告工作区保存去重后的 `references`；前端和导出器只根据这两个结构展示引用，不把“检索候选”误当成“已引用资料”。该机制保证引用编号可追溯到本节检索材料，但不等同于对句子事实正确性或材料蕴含关系的自动核查。知识图谱本期仍只显示节点定位，不宣称具有原始文章溯源能力。

**Tech Stack:** Python 3、Flask、现有 LLM/RAG 编排、原生 JavaScript、Node `node:test`、`unittest`/pytest、python-docx

---

## 一、范围与数据约定

本期包含：

- 人工智能和具身智能报告已有外部 RAG 证据的统一编号。
- 首次正文生成和局部重写中的外部资料引用。
- 引用合法性校验、实际引用集合计算。
- 网页正文引用跳转、已引用资料与检索候选区分。
- 历史记录、Markdown、Word 保留引用。

本期不包含：

- 不给知识图谱节点补造原始来源；图谱仍使用现有“打开图谱”定位。
- 不增加事实核查模型或第二次 LLM 审稿。
- 不保证模型写出的每个普通常识句都逐句引用；强制规则聚焦数字、政策、讲话、专家观点和企业案例。
- 不重建 RAG、不新增数据库、不增加哈希、迁移框架或 feature flag。
- 不引入第二个模型或逐句事实核查；`[C数字]` 只表示该材料是可回溯的写作依据，不自动证明其完整支持相邻结论。

统一字段：

```json
{
  "references": [
    {
      "citation_id": "C1",
      "library": "policy",
      "classification_name": "政策法规",
      "material_id": "153233267315903692926062900000034",
      "title": "国务院关于印发某规划的通知",
      "publish_date": "2026-06-29",
      "retrieved_at": "2026-09-21T14:30:00+08:00",
      "source_address": "https://www.gov.cn/...",
      "vector_ids": ["chunk-a", "chunk-b"],
      "evidence_excerpt": "检索命中的首个正文片段"
    }
  ],
  "body_sections": [
    {
      "outline_id": "S1.1",
      "body_text": "相关规划提出……[C1]。",
      "citation_ids": ["C1"],
      "external_evidence_blocks": []
    }
  ]
}
```

编号规则：

1. 初次统筹按照大纲顺序、每节检索结果顺序分配编号。
2. 同一 `library + material_id` 只生成一个引用；同一材料命中的多个 chunk 合并进 `vector_ids`。
3. 旧数据缺少 `material_id` 时使用 `library + vector_id`，不做标题模糊去重。
4. 局部重写复用已有引用编号，新材料从当前最大编号继续追加。
5. 正文出现顺序不改变编号，避免保存、重写后已有编号漂移。
6. `retrieved_at` 记录材料本次进入报告引用表的本地时间；原文地址后续失效或网页内容更新时，仍可说明该报告引用的检索时点。
7. 合法编号只证明“编号来自本节外部证据集合”，不证明该证据必然蕴含正文结论；人工验收需重点核查数字、政策、讲话、专家观点和企业案例的对应关系。

## 二、文件结构

- Create `report_generation/citations.py`：证据去重、编号注册、正文引用校验、已用参考资料筛选。
- Create `tests/test_report_citations.py`：引用纯函数的单元测试。
- Modify `report_generation/coordinator_agent.py`：完成所有章节检索后分配报告级引用，并统一写作约束。
- Create `tests/test_report_coordinator_citations.py`：统筹结果和提示词测试。
- Modify `report_generation/body_agent.py`：验证 LLM 引用并输出 `citation_ids`、`references`。
- Create `tests/test_report_body_citations.py`：正文引用与错误编号测试。
- Modify `report_generation/rewrite_agent.py`、`backend_server.py`：重写时注册新材料并返回更新后的引用表。
- Create `tests/test_report_rewrite_citations.py`：重写复用/追加编号测试。
- Modify `static/js/modules/industry_report.js`：保存引用表、正文引用链接、资料分组、Markdown 输出。
- Create `tests/js/test_industry_report_citations.test.js`：浏览器无关的引用渲染和序列化测试。
- Modify `report_generation/word_export_agent.py`、`backend_server.py`：Word 参考资料章节及请求字段。
- Create `tests/test_word_export_citations.py`：DOCX 引用保留测试。
- Modify `README.md`、`MODULES.md`：接口字段和行为说明。

### Task 1: 建立纯函数引用模型

**Files:**
- Create: `report_generation/citations.py`
- Create: `tests/test_report_citations.py`

- [ ] **Step 1: 写引用注册失败测试**

```python
import unittest

from report_generation.citations import register_evidence_blocks


class ReportCitationRegistryTests(unittest.TestCase):
    def test_registers_sources_in_order_and_merges_chunks_from_same_material(self):
        blocks = [
            {"library": "policy", "material_id": "m1", "vector_id": "v1", "title": "政策甲", "text": "片段一", "retrieved_at": "2026-09-21T14:30:00+08:00"},
            {"library": "policy", "material_id": "m1", "vector_id": "v2", "title": "政策甲", "text": "片段二"},
            {"library": "company_case", "material_id": "m2", "vector_id": "v3", "title": "案例乙", "text": "片段三"},
        ]

        mapped, references = register_evidence_blocks(blocks, [])

        self.assertEqual([row["citation_id"] for row in mapped], ["C1", "C1", "C2"])
        self.assertEqual(references[0]["vector_ids"], ["v1", "v2"])
        self.assertEqual(references[0]["evidence_excerpt"], "片段一")
        self.assertEqual(references[0]["retrieved_at"], "2026-09-21T14:30:00+08:00")
        self.assertEqual(references[1]["title"], "案例乙")

    def test_reuses_existing_ids_and_appends_after_highest_id(self):
        existing = [{"citation_id": "C4", "library": "policy", "material_id": "m1", "vector_ids": ["v1"]}]
        blocks = [
            {"library": "policy", "material_id": "m1", "vector_id": "v2"},
            {"library": "speech", "material_id": "m2", "vector_id": "v3"},
        ]

        mapped, references = register_evidence_blocks(blocks, existing)

        self.assertEqual([row["citation_id"] for row in mapped], ["C4", "C5"])
        self.assertEqual(references[0]["vector_ids"], ["v1", "v2"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `python -m pytest tests/test_report_citations.py -v`

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'report_generation.citations'`。

- [ ] **Step 3: 实现证据注册**

在 `report_generation/citations.py` 实现以下公开接口：

```python
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Iterable

_CITATION_PATTERN = re.compile(r"\[(C[1-9]\d*)\]")


def register_evidence_blocks(blocks: list, references: list) -> tuple[list[dict], list[dict]]:
    mapped = copy.deepcopy(blocks if isinstance(blocks, list) else [])
    registry = copy.deepcopy(references if isinstance(references, list) else [])
    by_key = {_reference_key(row): row for row in registry if _reference_key(row)}
    next_number = max((_citation_number(row.get("citation_id")) for row in registry), default=0) + 1

    for block in mapped:
        if not isinstance(block, dict):
            continue
        key = _reference_key(block)
        if not key:
            continue
        reference = by_key.get(key)
        if reference is None:
            reference = _new_reference(block, f"C{next_number}")
            next_number += 1
            registry.append(reference)
            by_key[key] = reference
        _append_vector_id(reference, block.get("vector_id"))
        block["citation_id"] = reference["citation_id"]
    return mapped, registry


def _reference_key(row: dict) -> str:
    if not isinstance(row, dict):
        return ""
    library = _text(row.get("library"))
    material_id = _text(row.get("material_id"))
    vector_id = _text(row.get("vector_id"))
    if not vector_id and isinstance(row.get("vector_ids"), list) and row["vector_ids"]:
        vector_id = _text(row["vector_ids"][0])
    identity = material_id or vector_id
    return f"{library}:{identity}" if identity else ""


def _new_reference(block: dict, citation_id: str) -> dict:
    return {
        "citation_id": citation_id,
        "library": _text(block.get("library")),
        "classification_name": _text(block.get("classification_name")),
        "material_id": _text(block.get("material_id")),
        "title": _text(block.get("title")),
        "publish_date": _text(block.get("publish_date")),
        "retrieved_at": _text(block.get("retrieved_at")) or datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_address": _text(block.get("source_address")),
        "vector_ids": [],
        "evidence_excerpt": _text(block.get("text")),
    }


def _append_vector_id(reference: dict, value: Any) -> None:
    vector_id = _text(value)
    if vector_id and vector_id not in reference["vector_ids"]:
        reference["vector_ids"].append(vector_id)


def _citation_number(value: Any) -> int:
    match = re.fullmatch(r"C([1-9]\d*)", _text(value))
    return int(match.group(1)) if match else 0


def _text(value: Any) -> str:
    return str(value or "").strip()
```

- [ ] **Step 4: 增加正文校验和已用引用筛选测试**

```python
from report_generation.citations import collect_used_references, validate_body_citations


class ReportCitationValidationTests(unittest.TestCase):
    def test_keeps_allowed_ids_in_first_occurrence_order_and_removes_unknown_marker(self):
        text, citation_ids, warnings = validate_body_citations(
            "政策已发布[C2]，随后落地[C1]，重复说明[C2]，错误引用[C9]。",
            [{"citation_id": "C1"}, {"citation_id": "C2"}],
        )
        self.assertEqual(text, "政策已发布[C2]，随后落地[C1]，重复说明[C2]，错误引用。")
        self.assertEqual(citation_ids, ["C2", "C1"])
        self.assertEqual(warnings[0]["invalid_citation_ids"], ["C9"])

    def test_collects_only_references_used_by_successful_sections(self):
        references = [{"citation_id": "C1"}, {"citation_id": "C2"}, {"citation_id": "C3"}]
        sections = [
            {"status": "success", "citation_ids": ["C2", "C1"]},
            {"status": "error", "citation_ids": ["C3"]},
        ]
        self.assertEqual(
            [row["citation_id"] for row in collect_used_references(sections, references)],
            ["C1", "C2"],
        )
```

- [ ] **Step 5: 实现两个纯函数并运行测试**

```python
def validate_body_citations(body_text: Any, evidence_blocks: list) -> tuple[str, list[str], list[dict]]:
    text = _text(body_text)
    allowed = {
        _text(row.get("citation_id"))
        for row in evidence_blocks
        if isinstance(row, dict) and _text(row.get("citation_id"))
    }
    used: list[str] = []
    invalid: list[str] = []

    def replace(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        if citation_id not in allowed:
            if citation_id not in invalid:
                invalid.append(citation_id)
            return ""
        if citation_id not in used:
            used.append(citation_id)
        return match.group(0)

    cleaned = _CITATION_PATTERN.sub(replace, text)
    warnings = []
    if invalid:
        warnings.append({
            "stage": "citation_validation",
            "message": "removed citation markers not present in section evidence",
            "invalid_citation_ids": invalid,
        })
    return cleaned, used, warnings


def collect_used_references(body_sections: list, references: list) -> list[dict]:
    used = {
        citation_id
        for section in body_sections
        if isinstance(section, dict) and section.get("status") == "success"
        for citation_id in section.get("citation_ids", [])
    }
    return [copy.deepcopy(row) for row in references if row.get("citation_id") in used]
```

Run: `python -m pytest tests/test_report_citations.py -v`

Expected: PASS。

- [ ] **Step 6: 提交引用模型**

```bash
git add report_generation/citations.py tests/test_report_citations.py
git commit -m "feat: add report citation registry"
```

### Task 2: 在统筹阶段分配报告级引用

**Files:**
- Modify: `report_generation/coordinator_agent.py:24-100`
- Modify: `report_generation/coordinator_agent.py:358-474`
- Create: `tests/test_report_coordinator_citations.py`

- [ ] **Step 1: 写统筹编号测试**

测试通过 patch `_generate_writing_task_for_subsection` 返回两个固定任务：第一节含材料 `m1`，第二节含 `m1` 和 `m2`。断言：

```python
self.assertEqual(result["writing_tasks"][0]["external_rag_retrieval"]["evidence_blocks"][0]["citation_id"], "C1")
self.assertEqual(
    [row["citation_id"] for row in result["writing_tasks"][1]["external_rag_retrieval"]["evidence_blocks"]],
    ["C1", "C2"],
)
self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C2"])
self.assertIn("[C1]", result["writing_tasks"][0]["external_rag_retrieval"]["rag_context_text"])
```

- [ ] **Step 2: 运行并确认缺少 `references` 而失败**

Run: `python -m pytest tests/test_report_coordinator_citations.py -v`

Expected: FAIL，错误为 `KeyError: 'references'` 或 evidence 仍为旧编号。

- [ ] **Step 3: 在全部并发任务按原顺序收齐后注册引用**

在 `generate_writing_tasks()` 的 warning 汇总之后，依次处理 `writing_tasks`：

```python
references = []
for task in writing_tasks:
    retrieval = task.get("external_rag_retrieval") or {}
    mapped, references = register_evidence_blocks(
        retrieval.get("evidence_blocks") or [], references
    )
    retrieval["evidence_blocks"] = mapped
    retrieval["rag_context_text"] = build_rag_context_text(mapped)
```

循环完成后，直接在 `generate_writing_tasks()` 的最终返回对象中增加 `"references": references`，并从 `report_generation.citations` 导入 `register_evidence_blocks`、从 `report_adapter` 导入 `build_rag_context_text`。

- [ ] **Step 4: 统一统筹提示词中的引用规则**

删除这些互相冲突的硬规则：

```text
不得标注 [知识图谱1]、[外部资料1] 等引用编号。
不得输出引用列表、参考文献或资料来源说明。
```

将 `_ensure_writing_prompt_constraints()` 的规则改为：

```python
hard_rules = [
    "不得把 [知识图谱1] 等知识图谱节点编号当作文章来源。",
    "使用数字、政策、领导讲话、专家观点或企业案例时，必须在对应句末使用外部资料上下文提供的 [C数字] 引用编号。",
    "只能使用外部资料上下文中真实存在的引用编号，不得编造引用编号、资料标题或网址。",
    "只输出当前二级标题正文，不输出独立参考文献列表、摘要、标题页、目录或 Word 导出说明。",
]
```

同时修改 `_generate_writing_system_prompt()` 的 system/user prompt 和 fallback 文本，使其不再生成旧的禁止引用约束。

- [ ] **Step 5: 运行统筹和现有 RAG 测试**

Run: `python -m pytest tests/test_report_coordinator_citations.py tests/test_report_rag_adapter.py tests/test_report_rag_modes.py -v`

Expected: PASS；现有 adapter 的 legacy/v2 evidence 字段兼容性保持不变。

- [ ] **Step 6: 提交统筹接入**

```bash
git add report_generation/coordinator_agent.py tests/test_report_coordinator_citations.py
git commit -m "feat: assign report-level citation ids"
```

### Task 3: 校验首次正文的实际引用

**Files:**
- Modify: `report_generation/body_agent.py:21-89`
- Modify: `report_generation/body_agent.py:176-184`
- Modify: `report_generation/body_agent.py:274-369`
- Modify: `backend_server.py:285-312`
- Create: `tests/test_report_body_citations.py`

- [ ] **Step 1: 写正文引用测试**

patch `llm.query` 返回：

```text
政策提出扩大应用范围[C1]，市场规模达到百亿元[C8]。
```

写作任务只允许 `C1`，断言结果为：

```python
self.assertEqual(section["body_text"], "政策提出扩大应用范围[C1]，市场规模达到百亿元。")
self.assertEqual(section["citation_ids"], ["C1"])
self.assertEqual(section["warnings"][-1]["invalid_citation_ids"], ["C8"])
```

另写报告级测试：调用 `generate_report_bodies(..., references=[C1, C2, C3])`，两个小节分别引用 `C2` 和 `C1`，断言返回的 `references` 仍按 `C1、C2` 顺序，未使用的 `C3` 不返回。

- [ ] **Step 2: 运行并确认缺少 `citation_ids` 而失败**

Run: `python -m pytest tests/test_report_body_citations.py -v`

Expected: FAIL，错误包含 `KeyError: 'citation_ids'`。

- [ ] **Step 3: 调整正文 prompt**

将 `_build_body_user_prompt()` 的引用要求统一为：

```text
不得把 [知识图谱1] 等知识图谱编号当作文章来源。
凡使用外部资料中的数字、政策、领导讲话、专家观点或企业案例，必须在对应句末保留该资料的 [C数字] 编号。
只能使用“外部资料库上下文”中真实出现的编号，不得编造编号、标题或网址。
正文不输出独立参考文献列表，参考资料列表由系统生成。
```

- [ ] **Step 4: 在正文清理后执行确定性校验**

在 `generate_body_section()` 中，用本节 `external_evidence_blocks` 调用：

```python
body_text, citation_ids, citation_warnings = validate_body_citations(
    body_text, _external_evidence_blocks(writing_task)
)
section_warnings.extend(citation_warnings)
```

结果增加 `"citation_ids": citation_ids`。错误响应也固定返回空数组，保持响应结构一致。

- [ ] **Step 5: 从请求接收完整引用表，并只返回实际使用项**

给 `generate_report_bodies()` 增加 `references: list | None = None` 参数，并验证传入值是数组。调用：

```python
used_references = collect_used_references(body_sections, references or [])
```

`generate_report_bodies()` 顶层返回 `"references": used_references`。`/api/report/body` 同步接收和校验 `references`，原样传给该函数。完整引用表只能来自 coordinator 响应，不允许正文阶段从 evidence blocks 重新编号。

- [ ] **Step 6: 运行正文测试**

Run: `python -m pytest tests/test_report_body_citations.py tests/test_report_citations.py -v`

Expected: PASS。

- [ ] **Step 7: 提交正文校验**

```bash
git add report_generation/body_agent.py backend_server.py tests/test_report_body_citations.py
git commit -m "feat: validate generated report citations"
```

### Task 4: 保持局部重写后的引用一致性

**Files:**
- Modify: `report_generation/rewrite_agent.py:101-187`
- Modify: `report_generation/rewrite_agent.py:275-398`
- Modify: `backend_server.py:497-529`
- Create: `tests/test_report_rewrite_citations.py`

- [ ] **Step 1: 写重写复用和追加编号测试**

请求包含已有 `references=[C1, C4]`，选择一条属于 `C1` 的旧材料和一条新材料。断言传给 LLM 的上下文分别为 `[C1]`、`[C5]`，返回正文校验后包含：

```python
self.assertEqual(result["citation_ids"], ["C5", "C1"])
self.assertEqual([row["citation_id"] for row in result["references"]], ["C1", "C4", "C5"])
```

- [ ] **Step 2: 运行并确认函数签名不接受 `references` 而失败**

Run: `python -m pytest tests/test_report_rewrite_citations.py -v`

Expected: FAIL，错误包含 `unexpected keyword argument 'references'`。

- [ ] **Step 3: 在调用 LLM 前注册用户选择的材料**

给 `rewrite_body_section()` 增加 `references: list` 参数。先调用：

```python
mapped_blocks, updated_references = register_evidence_blocks(
    selected_external_evidence_blocks, references
)
```

`_build_rewrite_user_prompt()` 使用 `mapped_blocks`。重写提示词采用 Task 3 的同一引用规则，不再要求 `[外部资料标题]`。

- [ ] **Step 4: 校验重写正文并返回引用信息**

清理正文后调用 `validate_body_citations(body_text, mapped_blocks)`，返回：

```python
{
    "body_text": body_text,
    "citation_ids": citation_ids,
    "selected_external_evidence_blocks": mapped_blocks,
    "references": updated_references,
    "warnings": cleanup_warnings + citation_warnings,
}
```

- [ ] **Step 5: 扩充 Flask 和前端请求契约**

`/api/report/rewrite` 接收 `references`，必须为数组；前端调用重写接口时发送 `industryReportWorkspace.references || []`。采用重写结果时，同时替换当前小节 `citation_ids` 并更新工作区 `references`。

- [ ] **Step 6: 运行重写测试**

Run: `python -m pytest tests/test_report_rewrite_citations.py -v`

Expected: PASS。

- [ ] **Step 7: 提交重写引用接入**

```bash
git add report_generation/rewrite_agent.py backend_server.py static/js/modules/industry_report.js tests/test_report_rewrite_citations.py
git commit -m "feat: preserve citations during section rewrite"
```

### Task 5: 网页预览、历史记录和 Markdown 输出引用

**Files:**
- Modify: `static/js/modules/industry_report.js:1-25`
- Modify: `static/js/modules/industry_report.js:708-763`
- Modify: `static/js/modules/industry_report.js:823-988`
- Modify: `static/js/modules/industry_report.js:1214-1231`
- Modify: `static/js/modules/industry_report.js:1279-1324`
- Modify: `static/js/modules/industry_report.js:1524-1549`
- Create: `tests/js/test_industry_report_citations.test.js`

- [ ] **Step 1: 写前端引用测试**

沿用 `tests/js/test_industry_report_navigation.test.js` 的 VM 加载方式，测试以下纯函数：

```javascript
test("citation marker links to its report reference", () => {
    const html = context.renderIndustryReportParagraphs("规划已经发布[C2]。", [{ citation_id: "C2" }]);
    assert.match(html, /href="#report-reference-C2"/);
    assert.match(html, />\[C2\]<\/a>/);
});

test("history and markdown keep only actually used references", () => {
    context.industryReportWorkspace.references = [
        { citation_id: "C1", title: "政策甲", source_address: "https://example.test/a" },
        { citation_id: "C2", title: "案例乙", source_address: "https://example.test/b" },
    ];
    context.industryReportWorkspace.bodySections = [
        { parent_level1_title: "现状", title: "政策", body_text: "正文[C2]。", citation_ids: ["C2"] },
    ];
    const markdown = context.buildIndustryReportMarkdown();
    assert.match(markdown, /\[C2\] 案例乙/);
    assert.doesNotMatch(markdown, /\[C1\] 政策甲/);
});
```

- [ ] **Step 2: 运行并确认引用链接或参考资料章节缺失**

Run: `node --test tests/js/test_industry_report_citations.test.js`

Expected: FAIL。

- [ ] **Step 3: 扩充工作区和接口响应接收**

在默认、重置、历史加载结构中增加 `references: []`。统筹成功后接收候选引用表，正文成功后用 `data.references || []` 替换为实际引用表：

```javascript
industryReportWorkspace.references = data.references || [];
```

调用 `/api/report/body` 时必须发送统筹阶段保存在工作区的完整引用表：

```javascript
references: industryReportWorkspace.references || []
```

历史记录增加 `references`，旧历史记录缺失该字段时读取为空数组，不需要单独迁移文件。

- [ ] **Step 3.1: 将无效引用清理 warning 显示给用户**

新增并测试以下纯函数；在正文生成和局部重写成功、`appendIndustryReportWarnings(data.warnings)` 之后调用它。只有后端实际返回 `citation_validation` warning 时才显示，正常生成不新增提示：

```javascript
function getIndustryReportCitationValidationWarning(items) {
    return (Array.isArray(items) ? items : []).find(item =>
        item?.stage === "citation_validation"
        && Array.isArray(item?.invalid_citation_ids)
        && item.invalid_citation_ids.length
    );
}

const citationWarning = getIndustryReportCitationValidationWarning(data.warnings);
if (citationWarning) {
    setIndustryReportStatus(
        `已移除 ${citationWarning.invalid_citation_ids.length} 个不在本节资料中的引用编号：${citationWarning.invalid_citation_ids.join("、")}`,
        "info",
    );
}
```

在 `tests/js/test_industry_report_citations.test.js` 增加断言：输入 `{ stage: "citation_validation", invalid_citation_ids: ["C9"] }` 时返回该 warning；空数组或其他 warning 时返回 `undefined`。前端不得静默吞掉这类 warning。

- [ ] **Step 4: 渲染可点击正文引用和报告参考资料区**

给 `renderIndustryReportParagraphs(value, references = [])` 增加引用替换：先 HTML escape，再只将已存在的 `C数字` 标记替换为锚点：

```javascript
function renderIndustryReportCitationMarkers(escapedText, references) {
    const allowed = new Set((references || []).map(item => item.citation_id));
    return escapedText.replace(/\[(C[1-9]\d*)\]/g, (marker, citationId) => {
        if (!allowed.has(citationId)) return marker;
        return `<a href="#report-reference-${citationId}" contenteditable="false" class="text-blue-600 font-semibold hover:underline">${marker}</a>`;
    });
}
```

正文编辑器调用时传 `industryReportWorkspace.references`。报告末尾渲染 `renderIndustryReportReferences()`，每条使用 `id="report-reference-C1"`，展示编号、标题、资料类型、发布日期、检索时间、命中片段和经过 HTML escaping 的原文链接。`retrieved_at` 缺失时不渲染空标签，保证旧历史记录可正常阅读。

- [ ] **Step 5: 区分已引用资料与其他检索候选**

`renderIndustryReportEvidenceDetails(section)` 使用 `section.citation_ids` 分组：

- `citation_id` 位于该集合中的卡片放入“本节已引用资料”。
- 其余卡片放入“其他检索候选”。
- 外部卡片增加发布日期、资料类型和“打开原文”；空 `source_address` 不渲染链接。
- 图谱卡片继续显示“打开图谱”，标题明确为“图谱辅助依据”，不进入参考资料列表。

- [ ] **Step 6: 手工编辑后同步 `citation_ids`**

`updateIndustryReportBodyText()` 从正文解析引用，且只保留报告引用表中存在的 ID：

```javascript
function extractIndustryReportCitationIds(text, references) {
    const allowed = new Set((references || []).map(item => item.citation_id));
    return [...String(text || "").matchAll(/\[(C[1-9]\d*)\]/g)]
        .map(match => match[1])
        .filter((id, index, ids) => allowed.has(id) && ids.indexOf(id) === index);
}
```

正文更新时同时写 `citation_ids`，确保用户删除标记后历史和导出不会保留未使用来源。

- [ ] **Step 7: Markdown 增加参考资料章节**

`buildIndustryReportMarkdown()` 在正文后追加：

```markdown
## 参考资料

[C2] 案例乙，发布于 2026-07-06，检索于 2026-09-21T14:30:00+08:00，https://example.test/b
```

只输出当前 `bodySections[].citation_ids` 实际使用的引用，并按报告级编号排序。

- [ ] **Step 8: 运行全部前端测试**

Run: `node --test tests/js/test_industry_report_navigation.test.js tests/js/test_industry_report_citations.test.js`

Expected: PASS。

- [ ] **Step 9: 提交网页闭环**

```bash
git add static/js/modules/industry_report.js tests/js/test_industry_report_citations.test.js
git commit -m "feat: render and persist report citations"
```

### Task 6: 在 Word 中输出正文标记和参考资料

**Files:**
- Modify: `report_generation/word_export_agent.py:19-193`
- Modify: `report_generation/word_export_agent.py:467-489`
- Modify: `backend_server.py:415-439`
- Modify: `static/js/modules/industry_report.js:1397-1431`
- Create: `tests/test_word_export_citations.py`

- [ ] **Step 1: 写 DOCX 内容测试**

使用临时目录调用 `export_report_docx()`：

```python
result = export_report_docx(
    report_title="测试报告",
    abstract_text="摘要正文",
    body_sections=[{
        "parent_level1_id": "S1",
        "parent_level1_title": "现状",
        "title": "政策",
        "body_text": "规划提出扩大应用[C1]。",
        "citation_ids": ["C1"],
    }],
    references=[{
        "citation_id": "C1",
        "title": "政策甲",
        "publish_date": "2026-06-29",
        "retrieved_at": "2026-09-21T14:30:00+08:00",
        "source_address": "https://example.test/policy",
    }],
    output_dir=temp_dir,
)
document = Document(result["docx_path"])
text = "\n".join(p.text for p in document.paragraphs)
self.assertIn("规划提出扩大应用[C1]。", text)
self.assertIn("参考资料", text)
self.assertIn("[C1] 政策甲", text)
self.assertIn("检索于 2026-09-21T14:30:00+08:00", text)
self.assertIn("https://example.test/policy", text)
```

再测试正文含 `[C9]` 而 references 只有 `C1` 时，导出文本不包含 `[C9]`，warnings 含 `word_export_citation_validation`。

- [ ] **Step 2: 运行并确认函数不接受 `references` 而失败**

Run: `python -m pytest tests/test_word_export_citations.py -v`

Expected: FAIL，错误包含 `unexpected keyword argument 'references'`。

- [ ] **Step 3: 扩充导出函数和路由参数**

`export_report_docx()` 增加 `references: list | None = None`。旧历史报告没有引用时仍可导出正文，但不生成空“参考资料”章节。Flask 路由校验 `references` 必须为数组；前端发送：

```javascript
references: industryReportWorkspace.references || []
```

- [ ] **Step 4: 导出前校验正文标记**

按 references 构造允许 ID，清理不存在的 `[C数字]`，记录结构化 warning。保留合法 `[C1]`，不再由 `_clean_report_text()` 删除合法引用。

- [ ] **Step 5: 写入参考资料章节**

正文完成后，仅筛选 `body_sections[].citation_ids` 实际使用的 references，增加一级标题“参考资料”，逐条写入：

```text
[C1] 政策甲，发布于 2026-06-29，检索于 2026-09-21T14:30:00+08:00，https://example.test/policy
```

本期使用普通文本方括号编号，不实现 Word 脚注/尾注 XML，避免引入超出需求的文档结构复杂度。

- [ ] **Step 6: 运行 Word 与接口相关测试**

Run: `python -m pytest tests/test_word_export_citations.py tests/test_report_body_citations.py tests/test_report_rewrite_citations.py -v`

Expected: PASS。

- [ ] **Step 7: 提交 Word 导出**

```bash
git add report_generation/word_export_agent.py backend_server.py static/js/modules/industry_report.js tests/test_word_export_citations.py
git commit -m "feat: export report references to Word"
```

### Task 7: 文档、全量回归与人工验收

**Files:**
- Modify: `README.md`
- Modify: `MODULES.md`

- [ ] **Step 1: 更新接口文档**

在报告 coordinator/body/rewrite/export 接口说明中记录：

- coordinator 返回候选 `references` 和带报告级 `citation_id` 的 evidence blocks。
- body 返回各节 `citation_ids` 与实际使用的 `references`。
- rewrite 请求/响应携带 `references`，新材料追加编号。
- Word 请求接收 `references`。
- 图谱依据仅可定位图谱节点，当前不等价于原始文章来源。

- [ ] **Step 2: 运行引用专项测试**

Run:

```bash
python -m pytest \
  tests/test_report_citations.py \
  tests/test_report_coordinator_citations.py \
  tests/test_report_body_citations.py \
  tests/test_report_rewrite_citations.py \
  tests/test_word_export_citations.py -v
node --test \
  tests/js/test_industry_report_navigation.test.js \
  tests/js/test_industry_report_citations.test.js
```

Expected: 全部 PASS。

- [ ] **Step 3: 运行项目现有自动化回归**

Run: `python -m pytest tests -v`

Expected: 全部通过；只允许项目已有、明确标记的可选依赖 skip，不接受新失败。

- [ ] **Step 4: 本地人工生成一份双来源报告**

使用包含“政策 + 企业案例”的报告需求，确认：

1. 至少一个正文小节同时出现两个合法引用标记。
2. 点击标记能定位到报告末尾相应参考资料。
3. “本节已引用资料”不包含未被正文采用的候选。
4. 原文地址能打开；无地址的材料不显示虚假链接。
5. 图谱依据只显示“打开图谱”，不出现在参考资料列表。
6. 参考资料同时显示发布日期与检索时间；旧历史记录没有检索时间时，界面不显示空字段。
7. 对报告中的市场规模、融资比例、政策表述和企业案例各抽查一处：对应句末存在合法 `[C数字]`，且链接、标题和命中片段与该结论主题一致。该抽查用于发现明显错配，不宣称自动完成事实核查。

- [ ] **Step 5: 验证历史与重写**

保存报告、重新载入，再重写其中一节并选择一条旧材料和一条新材料。确认旧编号不变、新编号递增、删除的引用不会继续出现在该节的 `citation_ids` 中。

- [ ] **Step 6: 验证两种导出**

导出 Markdown 和 Word，确认正文编号、文末参考资料、标题、日期、URL 一致，且不存在正文未使用的参考资料。

- [ ] **Step 7: 提交文档和最终回归结果**

```bash
git add README.md MODULES.md
git commit -m "docs: document report source citations"
```

## 三、完成定义

以下条件全部满足才算一期完成：

- 所有首次生成和局部重写的合法外部引用都使用报告级 `C数字`。
- 同一材料跨章节不重复编号，重写后已有编号不漂移。
- 编造或越权引用编号不会进入最终保存和导出结果，并产生可见 warning。
- 网页能区分“已引用资料”“其他检索候选”“图谱辅助依据”。
- 历史加载、Markdown 和 Word 均保持引用关系。
- legacy、hybrid_v2 和具身智能专题资讯返回的现有 evidence 字段均可注册引用。
- 图谱缺少原始来源的事实在界面和文档中被准确表达，没有伪造文章来源。
- 参考资料保留发布日期与本次检索时间；旧历史记录缺少检索时间时可正常加载和导出。
- 当后端移除越权或编造的引用编号时，前端向用户显示具体的清理提示，而不是静默删除。
- 文档和界面明确该功能保证材料可追溯，不替代对引用是否充分支持具体结论的人工判断。

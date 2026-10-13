# 产业报告事实复用与小节分工实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已于2026-10-07明确要求开始执行。

**Goal:** 修复已发生的分配与引用缺陷，在不增加模型调用、不牺牲本节证据的前提下，通过小节分工和选择性已写事实提示减少重复展开。

**Architecture:** 保持候选检索、报告级分配、任务书、顺序正文生成的现有流程。现有任务书调用接收全篇大纲并返回具体关注词；共享纯函数从实际正文记录完整引用句，按同资料及具体对象选择避重提示，正文与重写共同使用。引用清洗独立修复。

**Tech Stack:** Python、现有Flask API、OpenAI兼容LLMClient、pytest/unittest、原生JavaScript和Node test；测试统一使用本机conda的kunlun环境。

## 设计依据及执行约束

先读 `docs/superpowers/specs/2026-10-07-report-fact-reuse-control-design.md`。用户确认允许小节变短、选择性传递事实、区分事实/推断/待验证条件。自动同源合并、重复摘要清理、图谱调用修复、任务书并行和全文审稿都不在范围内。

执行前再次检查 `git status --short`。调查时已有修改：`RAG/build_vector_db.py`、`report_generation/external_rag/retriever.py`；还有向量库、压缩包、测试、tools等未跟踪文件。不要覆盖它们，不用 `git add .`。本计划不修改这两个已有改动文件，也不提交向量库或压缩包。若执行时出现新的相关改动，先读差异再调整任务。

只在用户明确要求提交时按任务列出的文件提交，不自动推送。代码实施已获授权；在独立工作树实施，未授权提交或推送。

每次检查先说明具体失败及它会改变什么：下文已列出测试目的。所有模型测试使用mock；离线回放不重新检索向量库。

## 文件职责

- Modify `report_generation/material_allocator.py`：不同资料第一轮、最多两段、检索前十优先。
- Create `report_generation/repetition_context.py`：完整引用句记录、关注词校验、提示选择和共同写作规则，纯函数，不调用模型。
- Modify `report_generation/coordinator_agent.py`：大纲传入、单次任务书调用、关注词与备用状态。
- Modify `report_generation/body_agent.py`：调用共享提示函数、系统规则、保留关注词。
- Modify `report_generation/rewrite_agent.py`：同一选择器、重写规则、保留关注词。
- Modify `report_generation/citations.py`：清理实际出现的异常标记。
- Modify `static/js/modules/industry_report.js`：保留关注词，异常标记警告。
- Modify现有分配、统筹、正文、重写、引用、Word及JS引用测试；Create `tests/test_report_repetition_context.py`。
- Create `tests/fixtures/report_repetition_20261002.json`：从实际记录裁取的事实与证据，不含未保存候选的伪造回放。
- Modify `tests/test_report_repetition_replay.py`：实际记录上下文回放，保留有意义的构造分配测试。

## Task 1：修正资料分配

**Files:** `report_generation/material_allocator.py`、`tests/test_material_allocator.py`。

- [x] 加入已复现的失败测试：非首资料连续多段会挤掉独立资料。另测前十名有可用资料时不能为降低使用次数提前选第十一名；跨节唯一来源继续可用。

```python
def test_nonfirst_material_does_not_consume_distinct_slots():
    candidates = [block("a", "a1", 1), block("b", "b1", 2),
                  block("b", "b2", 3), block("b", "b3", 4),
                  block("c", "c1", 5)]
    result = allocate_evidence_blocks([{"candidates": candidates}], 4)[0]
    assert [b["vector_id"] for b in result["evidence_blocks"]] == ["a1", "b1", "c1", "b2"]
```

- [x] Run `conda run --no-capture-output -n kunlun python -m pytest -q tests/test_material_allocator.py`。上述测试应先失败；若未失败，检查工作区是否已有人修复，不重复改。
- [x] 第一轮分为输入前十与后续两个候选组；每组内按此前小节使用数、输入位置稳定排序。循环内重新检查 selected_keys 和已选vector身份。同资料第二段只能在两组不同资料均选择后补入。核心循环替换为：

```python
seen_vectors = set()
if target and first is not None:
    selected.append(first)
    selected_keys.add(first[2])
    seen_vectors.add((first[1].get("library"), first[1].get("vector_id")))
    for pool in ([r for r in valid if r[0] < 10],
                 [r for r in valid if r[0] >= 10]):
        for row in sorted(pool, key=lambda r: (prior_usage[r[2]], r[0])):
            if len(selected) >= target:
                break
            vector = (row[1].get("library"), row[1].get("vector_id"))
            if row[2] in selected_keys or (vector[1] and vector in seen_vectors):
                continue
            selected.append(row)
            selected_keys.add(row[2])
            if vector[1]:
                seen_vectors.add(vector)
    selected.sort(key=lambda r: (r[0] >= 10, prior_usage[r[2]], r[0]))
    per_material = defaultdict(int)
    for row in selected:
        per_material[row[2]] += 1
    for row in valid:
        if len(selected) >= target:
            break
        vector = (row[1].get("library"), row[1].get("vector_id"))
        if row[2] not in selected_keys or per_material[row[2]] >= 2:
            continue
        if not vector[1] or vector in seen_vectors:
            continue
        selected.append(row)
        per_material[row[2]] += 1
        seen_vectors.add(vector)
```

该片段替换现有选择与补段部分，继续使用原有深拷贝、诊断和prior_usage更新。相同资料缺少vector_id时不追加第二段，首段仍可提供证据。

- [x] Run上述分配测试及 `tests/test_report_coordinator_citations.py`。检查第一名候选保留、B两段以内、不同资料优先及引用顺序没有意外变化。

## Task 2：建立完整事实记录与具体对象词项

**Files:** Create `report_generation/repetition_context.py`、`tests/test_report_repetition_context.py`。

- [x] 写失败测试：第三个引用事实不丢、不同编号同对象能匹配、行业泛词不能触发、失败正文不入记录、引用标记在句号后也归前句，手动编辑后末段无句号的引用表述仍记录。下面是必要的最小数据：

```python
prior = [{"outline_id": "S1.1", "title": "布局", "status": "success",
          "body_text": "背景。政策[C1]。成本[C2]。中国移动牵头成立具身智能产业联盟[C14]。",
          "external_evidence_blocks": [
              {"citation_id": "C14", "library": "news", "material_id": "old"}]}]
current = {"repetition_focus_terms": ["中国移动", "具身智能产业联盟"],
           "external_rag_retrieval": {"evidence_blocks": [
               {"citation_id": "C17", "library": "news", "material_id": "new",
                "text": "中国移动牵头成立具身智能产业联盟。"}]}}
records = build_fact_records(prior)
assert records[-1]["sentence"].endswith("[C14]。")
context = build_prior_context(prior, current)
assert "中国移动牵头成立" in context["text"]
assert "[C14]" in context["text"]  # 只用于避重，不能授权当前引用C14
```

- [x] Run `conda run --no-capture-output -n kunlun python -m pytest -q tests/test_report_repetition_context.py`，新模块缺失时失败。
- [x] 添加以下公共基础函数，不调用模型，不做同源合并。词项只与当前二级标题和当前外部材料核对，不使用全篇需求和报告标题作为grounding池。

```python
import re
from collections import defaultdict, deque

CITATIONS = re.compile(r"\[(C[1-9]\d*)\]")
MAX_FOCUS_TERMS = 8
MAX_PRIOR_FACT_CHARS = 6000
MAX_TOPIC_CHARS = 2400
GENERIC_TERMS = {"场景", "协同", "产业链", "具身智能", "人工智能",
                 "商业化", "技术创新", "产业发展", "产业协同"}

def _blocks(task):
    retrieval = task.get("external_rag_retrieval") or {}
    return retrieval.get("evidence_blocks") or task.get("external_evidence_blocks") or []

def _material_key(block):
    identity = str(block.get("material_id") or block.get("vector_id") or "").strip()
    return f"{block.get('library') or ''}:{identity}" if identity else ""

def _grounding(task):
    return "\n".join([str(task.get("title") or "")] +
        [str(b.get("title") or "") + "\n" + str(b.get("text") or "")
         for b in _blocks(task)])

def normalize_focus_terms(values, grounding):
    terms = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, str):
            continue
        term = value.strip()
        if not 4 <= len(term) <= 60 or term in GENERIC_TERMS or term not in grounding:
            continue
        if re.fullmatch(r"[\d\s.%％万亿年月个家至—-]+", term):
            continue
        if term not in terms:
            terms.append(term)
        if len(terms) == MAX_FOCUS_TERMS:
            break
    return terms

def focus_terms_for_task(task):
    grounding = _grounding(task)
    terms = normalize_focus_terms(task.get("repetition_focus_terms", []), grounding)
    quoted = [a or b or c for a, b, c in
              re.findall(r"《([^》\n]{4,60})》|“([^”\n]{4,60})”|\"([^\"\n]{4,60})\"", grounding)]
    return normalize_focus_terms(terms + quoted, grounding)

def complete_sentences(text):
    return [m.group(0).strip() for m in re.finditer(
        r"[^\n]+?(?:(?:[。！？!?；;]|\.(?=\s|$))(?:\[C[1-9]\d*\])*|(?=\n|$))",
        text or "") if m.group(0).strip()]

def build_fact_records(sections):
    records = []
    for section in sections or []:
        if section.get("status") not in (None, "", "success"):
            continue
        by_id = {b.get("citation_id"): _material_key(b)
                 for b in section.get("external_evidence_blocks", [])}
        for sentence in complete_sentences(section.get("body_text", "")):
            ids = list(dict.fromkeys(CITATIONS.findall(sentence)))
            if ids:
                records.append({"outline_id": section.get("outline_id", ""),
                    "title": section.get("title", ""), "sentence": sentence,
                    "citation_ids": ids,
                    "material_keys": [by_id[x] for x in ids if by_id.get(x)]})
    return records
```

- [x] 补充有对象的数字短语测试：`500个人工智能应用场景`可以在grounding原样存在时被接受；单独 `500个` 不接受。`80%`与“八成”不会被自动判定同义，测试不得要求不存在的语义转换。
- [x] Run新纯函数测试。只有实际引用句入记录；不将提取结果称为事实校验结论。

## Task 3：有预算地选择前文

**Files:** 同Task 2的模块和测试。

- [x] 写测试：多个资料轮流获得窗口、完整句不截断、超预算计数、精确同句只展示一次、主题提示有独立预算。预算测试传入小预算，不创建巨量数据。
- [x] 实现 `build_prior_context(sections, current_task, fact_budget=6000, topic_budget=2400)`。同资料优先，其次具体对象；空material_key不能互相匹配。记录始终完整，只有展示受预算约束。

```python
def build_prior_context(sections, current_task, fact_budget=MAX_PRIOR_FACT_CHARS,
                        topic_budget=MAX_TOPIC_CHARS):
    records = build_fact_records(sections)
    terms = focus_terms_for_task(current_task)
    current_ids = {b.get("citation_id") for b in _blocks(current_task) if b.get("citation_id")}
    current_keys = {_material_key(b) for b in _blocks(current_task) if _material_key(b)}
    buckets = [defaultdict(deque), defaultdict(deque)]
    matching = []
    for row in records:
        keys = [k for k in row["material_keys"] if k in current_keys]
        ids = [x for x in row["citation_ids"] if x in current_ids]
        matches = [t for t in terms if t in row["sentence"]]
        if keys or ids:
            bucket, group = 0, (keys or ids)[0]
        elif matches:
            bucket, group = 1, matches[0]
        else:
            continue
        buckets[bucket][group].append(row)
        matching.append(row)
    facts, shown, omitted = [], set(), 0
    used = 0
    for groups in buckets:
        while any(groups.values()):
            for queue in groups.values():
                if not queue:
                    continue
                row = queue.popleft()
                key = re.sub(r"\s+", "", CITATIONS.sub("", row["sentence"]))
                if key in shown:
                    continue
                line = f"- [{row['outline_id']}] {row['title']}：{row['sentence']}"
                if used + len(line) + 1 > fact_budget:
                    omitted += 1
                    continue
                facts.append(line)
                shown.add(key)
                used += len(line) + 1
    topic_rows = []
    for section in sections or []:
        if section.get("status") not in (None, "", "success") or not section.get("body_text"):
            continue
        sentences = complete_sentences(section["body_text"])
        title = f"- [{section.get('outline_id', '')}] {section.get('title', '')}"
        first = sentences[0][:120] if sentences else ""
        topic_rows.append((title, first))
    topics = []
    # 先为所有标题预留预算，不能让前几节摘要挤掉后几节标题。
    remaining = topic_budget - sum(len(title) + 1 for title, _ in topic_rows)
    for title, first in topic_rows:
        addition = "：" + first if first else ""
        if remaining >= len(addition):
            topics.append(title + addition)
            remaining -= len(addition)
        else:
            topics.append(title)
    text = "【相关已写表述，未经事实审阅】\n" + ("\n".join(facts) or "暂无匹配引用句")
    text += "\n\n【前文主题】\n" + ("\n".join(topics) or "暂无已生成正文")
    if omitted:
        text += f"\n受提示预算限制，有{omitted}条相关表述未展示；不能视为此前未写。"
    return {"text": text, "record_count": len(records),
            "matched_fact_count": len(matching), "omitted_fact_count": omitted}
```

此实现先保留全部标题，再分配首句摘要预算。若标题本身超过2400字符，允许主题提示仅由标题构成并超过该初值，不用裁掉小节来制造“完整覆盖”的假象；该初值不是无限大纲的硬请求上限。预算和泛词集为普通模块常量，不新增feature flag。精确同句只留首次位置；需要查看其他位置时仍从完整records读取。

- [x] Run纯函数测试；检查不同来源而同对象的事实不会因C编号不同被漏掉，也不会授权当前正文使用前文C编号。

## Task 4：任务书获得分工且不默默截断

**Files:** `report_generation/coordinator_agent.py`、`tests/test_report_coordinator_citations.py`、`static/js/modules/industry_report.js`、`tests/js/test_industry_report_citations.test.js`。

- [x] 写mock失败测试：普通与流式调用均包含全篇大纲；仅调用一次任务书模型；`length`、空输出、不完整JSON进入备用；关注词经过grounding；备用有分工和证据规则。
- [x] 在普通与流式入口 `_flatten_body_subsections` 之后，把同一简短大纲附在每个subsection的 `report_outline_context` 中：

```python
outline_context = "\n".join(
    f"{s['outline_id']} | {s['parent_level1_title']} | {s['title']}"
    for s in final_subsections)
for subsection in final_subsections:
    subsection["report_outline_context"] = outline_context
```

- [x] `_generate_writing_system_prompt` 与 `_fallback_writing_system_prompt` 增加参数 `report_outline_context: str = ""`； `_build_writing_task_from_retrieval` 从subsection传入。任务书模型输出合同改为下面两字段，关注词缺失不让有效任务书失败：

```json
{"writing_system_prompt":"含本节职责、其他小节展开边界及证据的任务书",
 "repetition_focus_terms":["中国移动","具身智能产业联盟"]}
```

把大纲区块与以下规则加入现有任务书提示；更新原“JSON只能包含一个字段”要求：

```text
【整篇正文大纲】
{report_outline_context}
任务书中写清楚本节回答的问题，以及哪些背景更适合由其他小节完整介绍。
同一事实可用于不同分析用途，必要背景通常用一句承接，不重新介绍完整案例。
没有新增事实或分析时允许正文更短，不为凑篇幅重复前文。
不能把材料的改进建议反推为已发生问题；区分事实、推导及待验证条件。
任务书简洁，不超过约1600字，不复述全部材料。
repetition_focus_terms最多8项，只取当前二级标题或当前外部材料原样存在的具体名称、
有对象的数字短语或具体判断短语；不得输出场景、协同、产业链等泛词。
```

- [x] 将任务书单次 `llm.query` 调用替换为如下调用和结果检查；继续使用现有JSON解析函数，不另加重试：

```python
result = llm.query_result(user_prompt=user_prompt_text, system_prompt=system_prompt,
    max_tokens=5000, reasoning_effort=None,
    extra_body={"thinking": {"type": "disabled"}},
    extra_log_info=f"report_generation.coordinator_agent outline={subsection_title}")
if result.error_message:
    return {"status": "error", "message": f"writing prompt LLM call failed: {result.error_message}"}
if result.finish_reason == "length":
    return {"status": "error", "message": "writing prompt LLM output was truncated"}
content = result.content
if not content:
    return {"status": "error", "message": "writing prompt LLM returned empty output"}
```

成功解析后把词项返回给任务构造函数；用 `normalize_focus_terms(values, _grounding(task))` 校验，再保存 `repetition_focus_terms`。备用任务同样用 `focus_terms_for_task` 取引号名称；任务新增 `writing_prompt_status`，正常为 `generated`，备用为 `fallback`。错误的warning继续使用现有 `writing_prompt_generation`，保留备用可继续生成正文的语义。

普通结果与流式completed事件新增 `fallback_count`，值为 `sum(t.get("writing_prompt_status") == "fallback" for t in writing_tasks if isinstance(t, dict))`。前端在现有统筹完成状态文字中、且仅在非零时显示“其中N节使用备用任务书”，不新增提示面板。已存在的warning保留，测试不能把生成出dict当成任务书完整成功。

- [x] 更新mock为 `LLMQueryResult`，不要为迁就测试保留第二条模型调用路径。Run统筹与纯函数测试；断言19节就是19次任务书调用，不增加模型请求。

## Task 5：正文及重写共用分工规则

**Files:** `report_generation/repetition_context.py`、`report_generation/body_agent.py`、`report_generation/rewrite_agent.py`、相关正文/重写测试、`static/js/modules/industry_report.js`和JS引用测试。

- [x] 写失败测试：系统提示包含承接、允许缩短、事实与条件边界；C14前文通过同对象进入C17任务但仍不能引用C14；当前重写节排除；用户明确重复背景仍遵从；历史正文无新字段仍能重写。
- [x] 在纯模块定义共同字符串，两智能体导入：

```python
REUSE_RULES = """整篇报告避重与证据规则：
前文已完整展开的背景通常只用一句承接，再围绕当前小节问题分析。
同一资料可用于不同事实或分析用途，不因前文引用过就禁用当前证据。
任务书中的背景示例可以压缩，不能为了凑篇幅重复案例、数字和结论。
没有新增事实或分析时允许小节变短，保留支撑本节结论的必要证据。
区分材料直接支持的事实、基于材料的分析判断和待验证条件；不能把改进建议反推为已发生问题。
不得扩大材料的研究对象或状态：行业总体数据不能直接代表细分领域数据，布局不能改写为已落地。
已写表述只用于避重，未经自动事实审阅；当前事实依据和引用只能来自当前材料。
用户明确要求重复背景时遵从用户要求。"""
```

- [x] 正文系统提示在原任务书之后追加 `REUSE_RULES`；用户提示去掉两处“同一一级标题”限定，改为全报告承接规则。 `_format_prior_report_facts` 改调用 `build_prior_context(...)["text"]`；不要保留旧前两句截取逻辑。
- [x] `generate_body_section` 用选择结果构建提示，同时将非零 `omitted_fact_count` 写入现有warnings，stage为 `repetition_context`。结果保存 `repetition_focus_terms=focus_terms_for_task(writing_task)`。普通和流式入口继续共用该函数，不改变生成并发。
- [x] 重写在过滤当前节之后，用以下current_task调用同一选择器；对旧正文或新选材料重新校验词项：

```python
current_task = {"title": current_section.get("title", ""),
    "repetition_focus_terms": current_section.get("repetition_focus_terms", []),
    "external_rag_retrieval": {"evidence_blocks": selected_external_evidence_blocks}}
context = build_prior_context(prior_sections, current_task)
```

把context传到原重写用户提示，系统提示追加 `REUSE_RULES`；结果保留 `focus_terms_for_task(current_task)`，非零遗漏计数同样写warning。选中材料不删，引用校验仍只允许选中证据。

- [x] 网页 `normalizeIndustryReportBodySections` 已通过 `...section` 保留字段，不为此重复修改。只在 `acceptIndustryReportRewrite` 的结果对象中补入重写后的关注词；手动修改正文不需更新台账缓存，因为选择器重新读取正文。字段表达式为：

```javascript
repetition_focus_terms: Array.isArray(rewritten.repetition_focus_terms)
    ? rewritten.repetition_focus_terms.slice() : [],
```

- [x] Run `conda run --no-capture-output -n kunlun python -m pytest -q tests/test_report_body_citations.py tests/test_report_rewrite_citations.py tests/test_report_repetition_context.py` 与 `node --test tests/js/test_industry_report_citations.test.js`。验证生成顺序、用户材料和历史保存未受影响。

## Task 6：独立清理异常引用

**Files:** `report_generation/citations.py`、`static/js/modules/industry_report.js`、引用/正文/重写/Word/JS引用测试。

- [x] 加入失败测试：允许C4也不能把 `[citation:4]` 自动变成C4；正文文字保留、异常标记删除、有warning，正确C4不受影响。

```python
text, used, warnings = validate_body_citations(
    "场景定义价值[citation:4]。另一事实[C4]。", [{"citation_id": "C4"}])
assert text == "场景定义价值。另一事实[C4]。"
assert used == ["C4"]
assert any(w["stage"] == "citation_validation" for w in warnings)
```

- [x] 在 `validate_body_citations` 初始化warnings并在标准C校验前清理已发生格式：

```python
malformed = re.findall(r"\[citation:\d+\]", text)
warnings = []
if malformed:
    text = re.sub(r"\[citation:\d+\]", "", text)
    warnings.append({"stage": "citation_validation",
        "message": "removed malformed citation markers without assigning source ids",
        "malformed_citation_markers": list(dict.fromkeys(malformed))})
```

移除该函数末尾重新初始化warnings的语句，避免丢警告。Word导出已有调用无需另建清洗器；测试确认它会保留该警告。

- [x] 网页正文接收、历史加载和手动编辑使用一个小型清洗函数；调用方把warning并入该小节现有warnings，不能静默删除：

```javascript
function cleanIndustryReportMalformedCitations(value) {
    const text = String(value || "");
    const markers = [...new Set(text.match(/\[citation:\d+\]/g) || [])];
    return { text: text.replace(/\[citation:\d+\]/g, ""), warnings: markers.length ? [{
        stage: "citation_validation",
        message: "已移除异常引用标记，未推定资料编号，请核对该句证据。",
        malformed_citation_markers: markers,
    }] : [] };
}
```

具体接入点是 `normalizeIndustryReportBodySections`、`updateIndustryReportBodyText` 和 `updateIndustryReportPendingRewriteText`。历史加载现有 `bodySections: record.bodySections || []` 改为经过normalize，再把小节warning汇总到现有workspace警告中；不能只在新生成入口清理。`getIndustryReportCitationValidationWarning` 当前只识别 `invalid_citation_ids`，必须同时接受 `malformed_citation_markers`；两个显示函数分别按warning实际字段生成消息，不读取不存在的数组。Node测试覆盖历史加载、手动编辑和两类警告共存的情况。

- [x] Run引用、正文、重写、Word测试及JS引用测试。检查warning显示路径是否支持新警告；若现有界面只显示未知C编号，扩展该已有提示分支，不新建审稿界面。

## Task 7：实际记录回放与人工验收准备

**Files:** `tests/fixtures/report_repetition_20261002.json`、`tests/test_report_repetition_replay.py`。

- [x] 从已核对的实际记录裁取fixture；不把分配后的10段称为原始20段候选。保存任务的title、outline_id、evidence_blocks和正文及其external_evidence_blocks；不保存raw_output、完整图谱、API配置或时间无关的其他报告。

```python
import json
from pathlib import Path
records = json.loads(Path("report_generation/history/report_history.json").read_text())
record = next(r for r in records if r["id"] == "local_report_1790923136987")
keep = {"S1.1", "S1.2", "S3.1", "S3.2", "S3.4", "S4.2", "S5.2", "S5.3"}
fixture = {
    "source_record_id": record["id"], "candidate_pool_available": False,
    "writing_tasks": [{"outline_id": t["outline_id"], "title": t["title"],
        "external_rag_retrieval": {"evidence_blocks": t["external_rag_retrieval"]["evidence_blocks"]}}
        for t in record["writingTasks"] if t["outline_id"] in keep],
    "body_sections": [{k: s[k] for k in ("outline_id", "title", "status", "body_text", "external_evidence_blocks")}
        for s in record["bodySections"] if s["outline_id"] in keep],
}
Path("tests/fixtures").mkdir(exist_ok=True)
Path("tests/fixtures/report_repetition_20261002.json").write_text(
    json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [x] 添加历史回放测试：S1.1融资完整引用句进入records，并因S1.2当前C4进入提示；以明确对象词将S3.1的联盟句选给S5.2，即使测试current_task只保留C17；真实S4.2异常标记被移除但正文事实保留。fixture只代表生成前已有数据，不代表新模型正文。
- [x] Run `conda run --no-capture-output -n kunlun python -m pytest -q tests/test_material_allocator.py tests/test_report_coordinator_citations.py tests/test_report_body_citations.py tests/test_report_rewrite_citations.py tests/test_report_citations.py tests/test_report_repetition_context.py tests/test_report_repetition_replay.py tests/test_word_export_citations.py` 与 `node --test tests/js/test_industry_report_citations.test.js tests/js/test_industry_report_navigation.test.js`。这些检查具体检测分配、上下文、引用及页面保存回归；通过后不无理由重复或扩大运行。
- [ ] 准备一次用户选择运行的真实正文对照：使用相同需求和大纲，记录实际新候选与模型配置、任务书备用数、生成时间和证据覆盖。若候选不同，明确不是严格修改前后实验。不得自动启动真实模型或新增全文审稿调用。
- [ ] 人工对照五组段落：联盟成员/任务只在适合的小节完整介绍；500场景不扩成具身智能已落地；矿山/家用在建议节用于明确切入顺序；融资比例在后节承接而非重铺；回本周期在成本节用于新推导。正文可以变短，但必要证据不能丢。不要把引用次数下降当成质量验收。
- [ ] 若人工仍发现重复，指出它属于匹配遗漏、预算遗漏、分工冲突还是模型复述；只调整对应步骤。若事实仍无证据，收回该表述，不引入无关材料补足。不自动开展方案C。

## 完成报告

实施后列出改动、上述定向检查及真实质量验收是否实际运行；未运行真实模型时明确“流程验证完成，实际正文效果尚未验收”。不得宣称已经达到不重复目标。当前仅文档阶段，所有实施步骤保持未勾选。

## 执行记录（2026-10-07）

实施位置：`/Users/livictor/Desktop/industry/industry_graph-fact-reuse`，分支 `codex/report-fact-reuse`，基于 `e8131b5`。原目录中的已有代码、向量库和压缩包保持不动；未提交、未推送。

完成Task 1—7及Task 8离线回放。关键回归先复现后修复：不同资料循环身份遗漏、前十候选被后续低复用候选提前替代、任务书截断未显式识别、真实融资句按分号切分丢失引用归属、历史加载覆盖异常引用警告、检索异常备用任务书漏计。分号连接的内容保留为完整句；按句号、问号、感叹号或段末切分。

最终Python命令（kunlun）：

```bash
conda run --no-capture-output -n kunlun python -m pytest -q -p no:cacheprovider tests/test_material_allocator.py tests/test_report_coordinator_citations.py tests/test_report_body_citations.py tests/test_report_rewrite_citations.py tests/test_report_citations.py tests/test_report_repetition_context.py tests/test_report_repetition_replay.py tests/test_word_export_citations.py tests/test_coordinator_stability.py tests/test_body_agent.py
```

59项通过。JavaScript引用测试10项通过；`node --check static/js/modules/industry_report.js`、`git diff --check`通过。

计划要求的JavaScript引用与导航合并检查初次为39通过、2失败。导航测试中的两个失败在修改前HEAD的脚本与测试上完整复现：`embodied report coordinator request keeps the selected industry`仍预期非流式统筹接口；`task-card fallback remains editable and tells the user to confirm it`的需求备用提示与实现不一致。这两项未在本次范围内修复，不声称全部JavaScript测试通过。

独立审阅完成：历史警告入口缺陷已修复，审阅未发现其他未解决的实际缺陷。

真实质量验收仍待运行。下一次使用原报告需求与19节大纲，通过正常统筹/正文流程生成，保存当次候选/分配诊断、模型配置、备用任务书数和生成耗时，再人工对照上述五组段落及必要证据。若候选不同，不能称为严格修改前后实验。本轮无真实模型调用，无全文审稿调用；离线回放不代表新正文已通过质量验收。

"""Pure selection of previously written statements for report reuse control."""

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

def grounding_for_task(task):
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
    grounding = grounding_for_task(task)
    terms = normalize_focus_terms(task.get("repetition_focus_terms", []), grounding)
    quoted = [a or b or c for a, b, c in
              re.findall(r"《([^》\n]{4,60})》|“([^”\n]{4,60})”|\"([^\"\n]{4,60})\"", grounding)]
    return normalize_focus_terms(terms + quoted, grounding)

def complete_sentences(text):
    return [m.group(0).strip() for m in re.finditer(
        r"[^\n]+?(?:(?:[。！？!?]|\.(?=\s|$))(?:\[C[1-9]\d*\])*|(?=\n|$))",
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

COMMON_REUSE_RULES = """同一资料可用于不同事实或分析用途，不因其他小节引用过就禁用当前证据。
必要背景可以短句承接，保留独有事实、分析、必要证据和用户明确要求的内容。
没有新增事实或分析时允许小节变短，不能为了凑篇幅重复案例、数字和结论。
如果用户明确要求重复某个背景、事实、案例或数据，应按用户要求重复，不得仅因避重而拒绝。"""

REUSE_RULES = "整篇报告避重与证据规则：\n" + COMMON_REUSE_RULES + """
前文已完整展开的背景通常只用一句承接，再围绕当前小节问题分析。
区分材料直接支持的事实、基于材料的分析判断和待验证条件；不能把改进建议反推为已发生问题。
不得扩大材料的研究对象或状态：行业总体数据不能直接代表细分领域数据，布局不能改写为已落地。
已写表述只用于避重，未经自动事实审阅；当前事实依据和引用只能来自当前材料。"""

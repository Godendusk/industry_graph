"""Rewrite agent for one industry report body section."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, List

from llm_client import llm

from .external_rag.retriever import retrieve_external_rag
from .graph_retriever import retrieve_ai_graph


SUPPORTED_INDUSTRIES = {
    "ai": "人工智能",
    "embodied": "具身智能",
}
DEFAULT_TOP_K = 10
DEFAULT_MAX_TOKENS = 5000


def recommend_rewrite_materials(
    rewrite_prompt: str,
    report_title: str,
    body_section: dict,
    industry: str = "ai",
    top_k: int = DEFAULT_TOP_K,
) -> dict:
    """Retrieve graph and external materials for one body-section rewrite."""
    normalized_prompt = _safe_text(rewrite_prompt)
    normalized_title = _safe_text(report_title)
    normalized_industry = _safe_text(industry) or "ai"
    normalized_top_k = _normalize_top_k(top_k)

    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry)
    if not industry_name:
        return _materials_error_response(
            f"unsupported industry: {normalized_industry}",
            normalized_industry,
            "",
        )
    if not normalized_prompt:
        return _materials_error_response("rewrite_prompt cannot be empty", normalized_industry, industry_name)
    if not normalized_title:
        return _materials_error_response("report_title cannot be empty", normalized_industry, industry_name)
    if not isinstance(body_section, dict):
        return _materials_error_response("body_section must be an object", normalized_industry, industry_name)

    section = _base_section_payload(body_section)
    if not section["title"]:
        return _materials_error_response("body_section.title cannot be empty", normalized_industry, industry_name)

    rewrite_retrieval_query = _build_rewrite_retrieval_query(
        rewrite_prompt=normalized_prompt,
        report_title=normalized_title,
        parent_level1_title=section["parent_level1_title"],
        subsection_title=section["title"],
    )

    warnings: List[dict] = []
    graph_retrieval = _retrieve_graph_for_rewrite(
        rewrite_retrieval_query, warnings, industry=normalized_industry
    )
    external_rag_retrieval = _retrieve_external_rag_for_rewrite(
        query=rewrite_retrieval_query,
        top_k=normalized_top_k,
        warnings=warnings,
        industry=normalized_industry,
    )

    graph_success = graph_retrieval.get("status") == "success"
    external_success = external_rag_retrieval.get("status") == "success"
    status = "success" if graph_success or external_success else "error"
    if status == "error":
        warnings.append(
            {
                "stage": "rewrite_materials",
                "message": "knowledge graph and external RAG retrieval both failed",
            }
        )

    return {
        "status": status,
        "industry": normalized_industry,
        "industry_name": industry_name,
        "rewrite_prompt": normalized_prompt,
        "report_title": normalized_title,
        "outline_id": section["outline_id"],
        "parent_level1_id": section["parent_level1_id"],
        "parent_level1_title": section["parent_level1_title"],
        "title": section["title"],
        "rewrite_retrieval_query": rewrite_retrieval_query,
        "graph_retrieval": graph_retrieval,
        "external_rag_retrieval": external_rag_retrieval,
        "warnings": warnings,
    }


def rewrite_body_section(
    rewrite_prompt: str,
    report_title: str,
    body_section: dict,
    graph_retrieval: dict,
    selected_external_evidence_blocks: list,
    industry: str = "ai",
) -> dict:
    """Rewrite one body section using selected materials."""
    normalized_prompt = _safe_text(rewrite_prompt)
    normalized_title = _safe_text(report_title)
    normalized_industry = _safe_text(industry) or "ai"

    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry)
    if not industry_name:
        return _rewrite_error_response(
            body_section if isinstance(body_section, dict) else {},
            f"unsupported industry: {normalized_industry}",
        )
    if not normalized_prompt:
        return _rewrite_error_response(
            body_section if isinstance(body_section, dict) else {},
            "rewrite_prompt cannot be empty",
        )
    if not normalized_title:
        return _rewrite_error_response(
            body_section if isinstance(body_section, dict) else {},
            "report_title cannot be empty",
        )
    if not isinstance(body_section, dict):
        return _rewrite_error_response({}, "body_section must be an object")
    if not isinstance(graph_retrieval, dict):
        graph_retrieval = {}
    if not isinstance(selected_external_evidence_blocks, list):
        return _rewrite_error_response(body_section, "selected_external_evidence_blocks must be an array")

    section = _base_section_payload(body_section)
    original_body_text = _safe_text(body_section.get("body_text"))
    if not section["title"]:
        return _rewrite_error_response(body_section, "body_section.title cannot be empty")
    if not original_body_text:
        return _rewrite_error_response(body_section, "body_section.body_text cannot be empty")

    user_prompt = _build_rewrite_user_prompt(
        rewrite_prompt=normalized_prompt,
        report_title=normalized_title,
        body_section=body_section,
        graph_retrieval=graph_retrieval,
        selected_external_evidence_blocks=selected_external_evidence_blocks,
    )
    system_prompt = """你是产业报告正文重写智能体。
你的任务是根据用户重写要求、原正文和用户选择的材料，重写当前二级标题下的正文。
只输出改写后的正文段落，不要输出当前二级标题、章节标题、摘要、目录、Word 导出说明、参考文献或资料来源说明。
不得在正文中标注 [知识图谱1]、[外部资料1] 等引用编号。
必须保持正式产业研究报告文风，逻辑清晰、表述准确，不要编造材料中没有的信息。"""

    try:
        content = llm.query(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=DEFAULT_MAX_TOKENS,
            extra_log_info=f"report_generation.rewrite_agent outline={section['title']}",
        )
    except Exception as exc:
        return _rewrite_error_response(body_section, f"rewrite LLM call failed: {exc}")

    if not content:
        return _rewrite_error_response(body_section, "rewrite LLM returned empty output")

    body_text, cleanup_warnings = _clean_rewrite_text(content, section["title"])
    if not body_text:
        return _rewrite_error_response(body_section, "rewrite LLM returned empty output after cleanup")

    result = _base_section_payload(body_section)
    result.update(
        {
            "status": "success",
            "industry": normalized_industry,
            "industry_name": industry_name,
            "original_body_text": original_body_text,
            "body_text": body_text,
            "graph_evidence_blocks": _copy_list(graph_retrieval.get("evidence_blocks")),
            "selected_external_evidence_blocks": _copy_list(selected_external_evidence_blocks),
            "warnings": cleanup_warnings,
        }
    )
    return result


def _build_rewrite_retrieval_query(
    rewrite_prompt: str,
    report_title: str,
    parent_level1_title: str,
    subsection_title: str,
) -> str:
    return "\n".join(
        [
            f"用户重写要求：{rewrite_prompt}",
            f"报告标题：{report_title}",
            f"当前一级标题：{parent_level1_title}",
            f"当前二级标题：{subsection_title}",
            "检索目标：为当前二级标题正文重写补充依据，检索相关产业链结构、央企布局、竞争格局、问题、政策、案例、趋势和建议材料。",
        ]
    )


def _retrieve_graph_for_rewrite(
    query: str, warnings: List[dict], industry: str = "ai"
) -> dict:
    try:
        from .graph_retriever import retrieve_graph

        result = retrieve_graph(query, industry=industry)
    except Exception as exc:
        warning = {
            "stage": "graph_retrieval",
            "message": str(exc),
        }
        warnings.append(warning)
        return _graph_error_response(query=query, message=str(exc))

    normalized = copy.deepcopy(result) if isinstance(result, dict) else {"status": "error"}
    normalized["query"] = _safe_text(normalized.get("query")) or query
    normalized["graph_context_text"] = _safe_text(normalized.get("graph_context_text"))
    normalized["matched_level3"] = normalized.get("matched_level3") or []
    normalized["evidence_blocks"] = normalized.get("evidence_blocks") or []

    if normalized.get("status") != "success":
        warnings.append(
            {
                "stage": "graph_retrieval",
                "message": normalized.get("message", "graph retrieval failed"),
            }
        )
    return normalized


def _retrieve_external_rag_for_rewrite(
    query: str, top_k: int, warnings: List[dict], industry: str = "ai"
) -> dict:
    try:
        result = retrieve_external_rag(query, top_k=top_k, industry=industry)
    except Exception as exc:
        warning = {
            "stage": "external_rag_retrieval",
            "message": str(exc),
        }
        warnings.append(warning)
        return _external_error_response(query=query, top_k=top_k, message=str(exc))

    normalized = copy.deepcopy(result) if isinstance(result, dict) else {"status": "error"}
    normalized["query"] = _safe_text(normalized.get("query")) or query
    normalized["top_k"] = _normalize_top_k(normalized.get("top_k", top_k))
    normalized["rag_context_text"] = _safe_text(normalized.get("rag_context_text"))
    normalized["evidence_blocks"] = normalized.get("evidence_blocks") or []
    normalized["warnings"] = normalized.get("warnings") or []

    if normalized.get("status") != "success":
        warnings.append(
            {
                "stage": "external_rag_retrieval",
                "message": normalized.get("message", "external RAG retrieval failed"),
            }
        )
    for item in normalized.get("warnings") or []:
        warnings.append(
            {
                "stage": "external_rag_retrieval",
                "message": item,
            }
        )
    return normalized


def _build_rewrite_user_prompt(
    rewrite_prompt: str,
    report_title: str,
    body_section: dict,
    graph_retrieval: dict,
    selected_external_evidence_blocks: list,
) -> str:
    graph_context_text = _safe_text(graph_retrieval.get("graph_context_text"))
    selected_rag_context_text = _build_selected_rag_context_text(
        selected_external_evidence_blocks
    )

    return f"""【原正文】
{_safe_text(body_section.get("body_text"))}

【用户重写要求】
{rewrite_prompt}

【报告标题】
{report_title}

【当前一级标题】
{_safe_text(body_section.get("parent_level1_title"))}

【当前二级标题】
{_safe_text(body_section.get("title"))}

【重新检索到的知识图谱上下文】
{graph_context_text or "未提供可用知识图谱上下文。"}

【用户选择的外部资料】
{selected_rag_context_text}

【生成要求】
请根据用户重写要求重写当前二级标题下的正文。
请直接输出正文段落，不要输出当前二级标题、章节标题或任何标题行。
请检查引用的资料，不要出现常识性错误，例如误把民营企业（华为海思）当成央企国企，误把外资企业（英伟达）当成民营企业。
要求报告正文不多于 1000字，段落不超过 3 段。
不得标注 [知识图谱1]、[外部资料1] 等引用编号。
不得输出参考文献、引用列表。
如果正文生成涉及到总书记讲话、数字、政策等内容需要在正文里面输出引用外部资料来源，外部资料来源只需要指明具体的外部资料标题，比如[外部资料标题]。
不得生成摘要、目录、标题页、Word 导出说明或其他章节内容。"""


def _build_selected_rag_context_text(evidence_blocks: list) -> str:
    lines = ["【外部资料库检索结果】"]
    if not evidence_blocks:
        lines.extend(["", "用户未选择外部资料。"])
        return "\n".join(lines)

    for index, block in enumerate(evidence_blocks, 1):
        if not isinstance(block, dict):
            continue
        citation_id = _safe_text(block.get("citation_id")) or f"外部资料{index}"
        paragraph_index = block.get("paragraph_index")
        lines.extend(
            [
                "",
                f"[{citation_id}]",
                f"资料类型：{_display_value(block.get('classification_name'))}",
                f"标题：{_display_value(block.get('title'))}",
                f"发布日期：{_display_value(block.get('publish_date'))}",
                f"来源：{_display_value(block.get('source_address'))}",
                f"段落序号：{paragraph_index if paragraph_index is not None else '未提供'}",
                f"内容：{_display_value(block.get('text'))}",
            ]
        )
    if len(lines) == 1:
        lines.extend(["", "用户未选择外部资料。"])
    return "\n".join(lines)


def _clean_rewrite_text(content: str, subsection_title: str) -> tuple[str, List[dict]]:
    warnings: List[dict] = []
    text = _safe_text(content)

    fenced_match = re.fullmatch(r"```(?:markdown|md|text)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()
        warnings.append(
            {
                "stage": "rewrite_cleanup",
                "message": "removed enclosing code fence from rewrite output",
            }
        )

    json_text, json_warning = _extract_rewrite_text_from_json(text)
    if json_text:
        text = json_text
        warnings.append(json_warning)

    text, removed_title = _remove_leading_title_line(text, subsection_title)
    if removed_title:
        warnings.append(
            {
                "stage": "rewrite_cleanup",
                "message": "removed leading subsection title from rewrite output",
            }
        )

    cleaned = re.sub(r"\[(?:知识图谱|外部资料)\d+\]", "", text)
    if cleaned != text:
        text = cleaned
        warnings.append(
            {
                "stage": "rewrite_cleanup",
                "message": "removed explicit citation markers from rewrite output",
            }
        )

    reference_heading = re.search(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:参考文献|引用列表|资料来源|资料来源说明)[:：]?\s*$",
        text,
    )
    if reference_heading:
        text = text[: reference_heading.start()].rstrip()
        warnings.append(
            {
                "stage": "rewrite_cleanup",
                "message": "removed trailing reference/source section from rewrite output",
            }
        )

    return text.strip(), warnings


def _extract_rewrite_text_from_json(text: str) -> tuple[str, dict]:
    """Handle LLMs that return JSON instead of plain rewritten paragraphs."""
    raw = _safe_text(text)
    if not raw:
        return "", {}

    fenced_match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fenced_match:
        raw = fenced_match.group(1).strip()

    if not (raw.startswith("{") or raw.startswith("[")):
        return "", {}

    try:
        payload = json.loads(raw)
    except Exception:
        return "", {}

    keys = (
        "body_text",
        "new_content",
        "rewritten_content",
        "rewritten_text",
        "content",
        "text",
        "result",
        "output",
    )
    candidates: List[Any] = []
    if isinstance(payload, dict):
        candidates.extend(payload.get(key) for key in keys)
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend(data.get(key) for key in keys)
    elif isinstance(payload, list):
        candidates.extend(payload)

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), {
                "stage": "rewrite_cleanup",
                "message": "extracted rewritten body text from JSON output",
            }
        if isinstance(candidate, dict):
            nested, warning = _extract_rewrite_text_from_json(json.dumps(candidate, ensure_ascii=False))
            if nested:
                return nested, warning

    return "", {}


def _remove_leading_title_line(text: str, subsection_title: str) -> tuple[str, bool]:
    title = _safe_text(subsection_title)
    if not title:
        return text, False

    lines = text.splitlines()
    if not lines:
        return text, False

    first_line = lines[0].strip()
    normalized_first = re.sub(r"^[#\s\d一二三四五六七八九十、.．（）()]+", "", first_line).strip()
    if first_line == title or normalized_first == title:
        remaining = "\n".join(lines[1:]).strip()
        return remaining, True
    return text, False


def _base_section_payload(body_section: dict) -> dict:
    section = body_section if isinstance(body_section, dict) else {}
    return {
        "outline_id": _safe_text(section.get("outline_id")),
        "parent_level1_id": _safe_text(section.get("parent_level1_id")),
        "parent_level1_title": _safe_text(section.get("parent_level1_title")),
        "title": _safe_text(section.get("title")),
    }


def _rewrite_error_response(body_section: dict, message: str) -> dict:
    result = _base_section_payload(body_section)
    result.update(
        {
            "status": "error",
            "message": message,
            "original_body_text": _safe_text(body_section.get("body_text")) if isinstance(body_section, dict) else "",
            "body_text": "",
            "graph_evidence_blocks": [],
            "selected_external_evidence_blocks": [],
            "warnings": [
                {
                    "outline_id": result.get("outline_id", ""),
                    "stage": "rewrite_generation",
                    "message": message,
                }
            ],
        }
    )
    return result


def _materials_error_response(message: str, industry: str, industry_name: str) -> dict:
    return {
        "status": "error",
        "industry": industry,
        "industry_name": industry_name,
        "message": message,
        "warnings": [],
    }


def _graph_error_response(query: str, message: str) -> dict:
    return {
        "status": "error",
        "query": query,
        "message": message,
        "graph_context_text": "",
        "matched_level3": [],
        "evidence_blocks": [],
    }


def _external_error_response(query: str, top_k: int, message: str) -> dict:
    return {
        "status": "error",
        "query": query,
        "message": message,
        "top_k": top_k,
        "rag_context_text": "",
        "evidence_blocks": [],
        "warnings": [],
    }


def _copy_list(value: Any) -> List[dict]:
    if not isinstance(value, list):
        return []
    return copy.deepcopy(value)


def _normalize_top_k(top_k: Any) -> int:
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        return DEFAULT_TOP_K
    return value if value > 0 else DEFAULT_TOP_K


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _display_value(value: Any) -> str:
    text = _safe_text(value)
    return text if text else "未提供"

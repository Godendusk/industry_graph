"""Coordinator agent for industry report writing tasks."""

from __future__ import annotations

import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from llm_client import llm

from .external_rag.retriever import retrieve_external_rag
from .graph_retriever import retrieve_industry_graph
from .industry_config import SUPPORTED_INDUSTRIES


DEFAULT_TOP_K = 10


def generate_writing_tasks(
    user_prompt: str,
    report_title: str,
    outline: list,
    industry: str = "ai",
    top_k: int = DEFAULT_TOP_K,
) -> dict:
    """Generate per-subsection writing system prompts after outline confirmation."""
    normalized_prompt = str(user_prompt or "").strip()
    normalized_title = str(report_title or "").strip()
    normalized_industry = str(industry or "").strip()
    normalized_top_k = _normalize_top_k(top_k)

    if not normalized_prompt:
        return _error_response("user_prompt cannot be empty", normalized_industry, "")
    if not normalized_title:
        return _error_response("report_title cannot be empty", normalized_industry, "")

    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry, "未配置行业")

    final_subsections = _flatten_body_subsections(outline)
    if not final_subsections:
        return _error_response(
            "outline must contain at least one body subsection",
            normalized_industry,
            industry_name,
        )

    writing_tasks: List[dict] = [None] * len(final_subsections)  # type: ignore[list-item]
    warning_groups: List[List[dict]] = [[] for _ in final_subsections]
    with ThreadPoolExecutor(max_workers=len(final_subsections)) as executor:
        future_to_index = {
            executor.submit(
                _generate_writing_task_for_subsection,
                subsection=subsection,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                industry=normalized_industry,
                top_k=normalized_top_k,
            ): index
            for index, subsection in enumerate(final_subsections)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            subsection = final_subsections[index]
            try:
                writing_task, task_warnings = future.result()
            except Exception as exc:
                writing_task, task_warnings = _writing_task_unhandled_error_response(
                    subsection=subsection,
                    user_prompt=normalized_prompt,
                    report_title=normalized_title,
                    top_k=normalized_top_k,
                    message=f"coordinator task generation failed: {exc}",
                )
            writing_tasks[index] = writing_task
            warning_groups[index] = task_warnings

    warnings: List[dict] = []
    for task_warnings in warning_groups:
        warnings.extend(task_warnings)

    return {
        "status": "success",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "user_prompt": normalized_prompt,
        "report_title": normalized_title,
        "writing_tasks": writing_tasks,
        "warnings": warnings,
    }


def _generate_writing_task_for_subsection(
    subsection: dict,
    user_prompt: str,
    report_title: str,
    industry: str,
    top_k: int,
) -> tuple[dict, List[dict]]:
    task_warnings: List[dict] = []
    warnings: List[dict] = []
    section_retrieval_query = _build_subsection_retrieval_query(
        user_prompt=user_prompt,
        report_title=report_title,
        parent_level1_title=subsection["parent_level1_title"],
        subsection_title=subsection["title"],
    )

    if industry:
        graph_retrieval = _retrieve_graph_for_subsection(
            query=section_retrieval_query,
            industry=industry,
            outline_id=subsection["outline_id"],
            warnings=warnings,
            task_warnings=task_warnings,
        )
        external_rag_retrieval = _retrieve_external_rag_for_subsection(
            query=section_retrieval_query,
            industry=industry,
            top_k=top_k,
            outline_id=subsection["outline_id"],
            warnings=warnings,
            task_warnings=task_warnings,
        )
    else:
        graph_retrieval = {"status": "skipped", "graph_evidence_blocks": []}
        external_rag_retrieval = {"status": "skipped", "evidence_blocks": []}

    prompt_result = _generate_writing_system_prompt(
        user_prompt=user_prompt,
        report_title=report_title,
        parent_level1_title=subsection["parent_level1_title"],
        subsection_title=subsection["title"],
        graph_context_text=graph_retrieval.get("graph_context_text", ""),
        rag_context_text=external_rag_retrieval.get("rag_context_text", ""),
    )
    if prompt_result["status"] == "success":
        writing_system_prompt = prompt_result["writing_system_prompt"]
    else:
        warning = {
            "outline_id": subsection["outline_id"],
            "stage": "writing_prompt_generation",
            "message": prompt_result.get("message", "failed to generate writing system prompt"),
        }
        if prompt_result.get("raw_output"):
            warning["raw_output"] = prompt_result["raw_output"]
        warnings.append(warning)
        task_warnings.append(warning)
        writing_system_prompt = _fallback_writing_system_prompt(
            user_prompt=user_prompt,
            report_title=report_title,
            parent_level1_title=subsection["parent_level1_title"],
            subsection_title=subsection["title"],
        )

    return (
        {
            "outline_id": subsection["outline_id"],
            "parent_level1_id": subsection["parent_level1_id"],
            "parent_level1_title": subsection["parent_level1_title"],
            "title": subsection["title"],
            "section_retrieval_query": section_retrieval_query,
            "graph_retrieval": graph_retrieval,
            "external_rag_retrieval": external_rag_retrieval,
            "writing_system_prompt": writing_system_prompt,
            "warnings": task_warnings,
        },
        warnings,
    )


def _writing_task_unhandled_error_response(
    subsection: dict,
    user_prompt: str,
    report_title: str,
    top_k: int,
    message: str,
) -> tuple[dict, List[dict]]:
    section_retrieval_query = _build_subsection_retrieval_query(
        user_prompt=user_prompt,
        report_title=report_title,
        parent_level1_title=_safe_text(subsection.get("parent_level1_title")),
        subsection_title=_safe_text(subsection.get("title")),
    )
    warning = {
        "outline_id": _safe_text(subsection.get("outline_id")),
        "stage": "coordinator_task_generation",
        "message": message,
    }
    task = {
        "outline_id": _safe_text(subsection.get("outline_id")),
        "parent_level1_id": _safe_text(subsection.get("parent_level1_id")),
        "parent_level1_title": _safe_text(subsection.get("parent_level1_title")),
        "title": _safe_text(subsection.get("title")),
        "section_retrieval_query": section_retrieval_query,
        "graph_retrieval": _graph_error_response(query=section_retrieval_query, message=message),
        "external_rag_retrieval": _external_error_response(
            query=section_retrieval_query,
            top_k=top_k,
            message=message,
        ),
        "writing_system_prompt": _fallback_writing_system_prompt(
            user_prompt=user_prompt,
            report_title=report_title,
            parent_level1_title=_safe_text(subsection.get("parent_level1_title")),
            subsection_title=_safe_text(subsection.get("title")),
        ),
        "warnings": [warning],
    }
    return task, [warning]


def _flatten_body_subsections(outline: Any) -> List[dict]:
    if not isinstance(outline, list):
        return []

    flat: List[dict] = []
    fallback_body_index = 0
    for section_index, section in enumerate(outline, 1):
        if not isinstance(section, dict):
            continue
        if section.get("section_type") != "body":
            continue

        fallback_body_index += 1
        level1_id = _safe_text(section.get("level1_id")) or f"S{section_index}"
        parent_level1_title = _safe_text(section.get("level1_title"))
        if not parent_level1_title:
            parent_level1_title = f"正文一级标题{fallback_body_index}"

        subsection_index = 0
        for subsection in section.get("subsections") or []:
            if not isinstance(subsection, dict):
                continue
            title = _safe_text(subsection.get("title"))
            if not title:
                continue
            subsection_index += 1
            outline_id = _safe_text(subsection.get("outline_id")) or f"{level1_id}.{subsection_index}"
            flat.append(
                {
                    "outline_id": outline_id,
                    "parent_level1_id": level1_id,
                    "parent_level1_title": parent_level1_title,
                    "title": title,
                }
            )
    return flat


def _build_subsection_retrieval_query(
    user_prompt: str,
    report_title: str,
    parent_level1_title: str,
    subsection_title: str,
) -> str:
    return "\n".join(
        [
            f"用户需求：{user_prompt}",
            f"报告标题：{report_title}",
            f"当前一级标题：{parent_level1_title}",
            f"当前二级标题：{subsection_title}",
            "检索目标：为当前二级标题生成正文写作要求，检索相关产业链结构、央企布局、竞争格局、问题、政策、案例和建议依据。",
        ]
    )


def _retrieve_graph_for_subsection(
    query: str,
    industry: str,
    outline_id: str,
    warnings: List[dict],
    task_warnings: List[dict],
) -> dict:
    if industry not in SUPPORTED_INDUSTRIES:
        return {"status": "skipped", "graph_evidence_blocks": [], "evidence_blocks": []}
    try:
        result = retrieve_industry_graph(query, industry=industry)
    except Exception as exc:
        warning = {
            "outline_id": outline_id,
            "stage": "graph_retrieval",
            "message": str(exc),
        }
        warnings.append(warning)
        task_warnings.append(warning)
        return _graph_error_response(query=query, message=str(exc))

    normalized = copy.deepcopy(result) if isinstance(result, dict) else {"status": "error"}
    normalized["query"] = _safe_text(normalized.get("query")) or query
    normalized["graph_context_text"] = _safe_text(normalized.get("graph_context_text"))
    normalized["matched_level3"] = normalized.get("matched_level3") or []
    normalized["evidence_blocks"] = normalized.get("evidence_blocks") or []

    if normalized.get("status") != "success":
        warning = {
            "outline_id": outline_id,
            "stage": "graph_retrieval",
            "message": normalized.get("message", "graph retrieval failed"),
        }
        warnings.append(warning)
        task_warnings.append(warning)
    return normalized


def _retrieve_external_rag_for_subsection(
    query: str,
    industry: str,
    top_k: int,
    outline_id: str,
    warnings: List[dict],
    task_warnings: List[dict],
) -> dict:
    if industry not in SUPPORTED_INDUSTRIES:
        return {"status": "skipped", "evidence_blocks": [], "warnings": []}
    try:
        result = retrieve_external_rag(query, industry=industry, top_k=top_k)
    except Exception as exc:
        warning = {
            "outline_id": outline_id,
            "stage": "external_rag_retrieval",
            "message": str(exc),
        }
        warnings.append(warning)
        task_warnings.append(warning)
        return _external_error_response(query=query, top_k=top_k, message=str(exc))

    normalized = copy.deepcopy(result) if isinstance(result, dict) else {"status": "error"}
    normalized["query"] = _safe_text(normalized.get("query")) or query
    normalized["top_k"] = _normalize_top_k(normalized.get("top_k", top_k))
    normalized["rag_context_text"] = _safe_text(normalized.get("rag_context_text"))
    normalized["evidence_blocks"] = normalized.get("evidence_blocks") or []
    normalized["warnings"] = normalized.get("warnings") or []

    if normalized.get("status") != "success":
        warning = {
            "outline_id": outline_id,
            "stage": "external_rag_retrieval",
            "message": normalized.get("message", "external RAG retrieval failed"),
        }
        warnings.append(warning)
        task_warnings.append(warning)
    for item in normalized.get("warnings") or []:
        warning = {
            "outline_id": outline_id,
            "stage": "external_rag_retrieval",
            "message": item.get("message", str(item)) if isinstance(item, dict) else item,
        }
        warnings.append(warning)
        task_warnings.append(warning)
    return normalized


def _generate_writing_system_prompt(
    user_prompt: str,
    report_title: str,
    parent_level1_title: str,
    subsection_title: str,
    graph_context_text: str,
    rag_context_text: str,
) -> dict:
    system_prompt = """你是产业报告统筹智能体。
你的任务是把检索材料转化为后续正文生成智能体可执行的写作任务书 system prompt，不要撰写正文。
生成写作任务书时要重点参考关注当前的一级标题和二级标题，不要生成关联度不高的内容，比如标题让你分析现状你就分析现状，不要自作主张去分析突出问题和对策建议；标题让你分析对策建议你就分析对策建议，不要自作主张去分析现状和问题；标题让你分析现状你就分析现状，不要自作主张去分析突出问题和对策建议，绝对不要做多余的事。
必须只输出 JSON 对象，不要输出 Markdown、代码块或解释说明。
JSON 只能包含 writing_system_prompt 字段。
writing_system_prompt 必须是带有具体材料要点的任务书，而不是泛化写作要求。
writing_system_prompt 必须要求正文生成智能体不标注 [知识图谱1]、[外部资料1] 等引用编号。"""

    user_prompt_text = f"""请根据以下信息，为当前二级标题生成正文生成智能体使用的 system prompt。

【用户原始需求】
{user_prompt}

【报告标题】
{report_title}

【当前一级标题】
{parent_level1_title}

【当前二级标题】
{subsection_title}

【知识图谱检索上下文】
{graph_context_text or "未检索到可用知识图谱上下文。"}

【外部资料库检索上下文】
{rag_context_text or "未检索到可用外部资料库上下文。"}

【writing_system_prompt 必须包含的要求】
1. 必须生成“正文生成智能体”的 system prompt，不要生成正文。
2. system prompt 必须采用任务书结构，至少包含以下小标题：当前写作范围、写作任务、材料要点、外部资料要点、写作结构、边界要求。
3. “当前写作范围”必须写明用户原始需求、报告标题、当前一级标题、当前二级标题。
4. “材料要点”必须从知识图谱检索上下文中提炼具体要点，例如产业链环节、上下游关系、企业/实体布局、可用于正文分析的产业链路径等；如果图谱上下文没有可用信息，要明确说明“知识图谱未提供可用要点”，不要编造。
5. 请检查引用的资料，不要出现常识性错误，例如误把民营企业（华为海思）当成央企国企，误把外资企业（英伟达）当成民营企业。
6. “外部资料要点”必须从外部资料库检索上下文中提炼具体要点，例如政策、案例、趋势、问题、建议、数据表述、机构观点等；如果外部资料上下文没有可用信息，要明确说明“外部资料未提供可用要点”，不要编造。
7. “写作结构”必须给出当前小节正文的建议展开层次，例如先写什么、再写什么、最后如何收束或过渡，要求规定正文不多于 1000 字，段落不超过 3 段。
8. 不要只写“结合上下文”“吸收材料”“形成专业正文”等泛化表述；必须把检索上下文中的具体名称、环节、企业、政策、案例、趋势或数据要点转写进 writing_system_prompt。
9. 正文生成智能体只写当前二级标题对应正文，不写其他章节。
10. 正文不得标注 [知识图谱1]、[外部资料1] 等引用编号。
11. 正文不得输出引用列表、参考文献或资料来源说明。
12. 正文不得生成摘要、标题页、目录、Word 导出说明或其他无关内容。

【输出格式】
{{"writing_system_prompt": "正文生成智能体 system prompt"}}
"""
    try:
        content = llm.query(
            user_prompt=user_prompt_text,
            system_prompt=system_prompt,
            max_tokens=5000,
            extra_log_info=f"report_generation.coordinator_agent outline={subsection_title}",
        )
    except Exception as exc:
        return {"status": "error", "message": f"writing prompt LLM call failed: {exc}"}

    if not content:
        return {"status": "error", "message": "writing prompt LLM returned empty output"}

    try:
        data = _parse_json_object(content)
    except ValueError as exc:
        return {
            "status": "error",
            "message": f"writing prompt JSON parse failed: {exc}",
            "raw_output": content,
        }

    writing_system_prompt = _safe_text(data.get("writing_system_prompt"))
    if not writing_system_prompt:
        return {
            "status": "error",
            "message": "writing prompt JSON missing writing_system_prompt",
            "raw_output": content,
        }
    return {
        "status": "success",
        "writing_system_prompt": _ensure_writing_prompt_constraints(writing_system_prompt),
    }


def _fallback_writing_system_prompt(
    user_prompt: str,
    report_title: str,
    parent_level1_title: str,
    subsection_title: str,
) -> str:
    return _ensure_writing_prompt_constraints(f"""你是产业报告正文生成智能体。
你只负责撰写当前二级标题对应正文，不要生成其他章节。
用户原始需求：{user_prompt}
报告标题：{report_title}
当前一级标题：{parent_level1_title}
当前二级标题：{subsection_title}
请结合传入的知识图谱上下文和外部资料库上下文，形成自然、连贯、专业的报告正文。
不得标注 [知识图谱1]、[外部资料1] 等引用编号。
不得输出引用列表、参考文献或资料来源说明。
不得生成摘要、标题页、目录、Word 导出说明或其他无关内容。""")


def _ensure_writing_prompt_constraints(prompt: str) -> str:
    text = _safe_text(prompt)
    hard_rules = [
        "不得标注 [知识图谱1]、[外部资料1] 等引用编号。",
        "不得输出引用列表、参考文献或资料来源说明。",
        "不得生成摘要、标题页、目录、Word 导出说明或其他无关内容。",
    ]
    missing_rules = [rule for rule in hard_rules if rule not in text]
    if not missing_rules:
        return text
    return text.rstrip() + "\n" + "\n".join(missing_rules)


def _parse_json_object(text: str) -> dict:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("JSON object not found")
        cleaned = cleaned[start:end + 1]

    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("top-level JSON is not an object")
    return data


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


def _error_response(message: str, industry: str, industry_name: str) -> dict:
    return {
        "status": "error",
        "industry": industry,
        "industry_name": industry_name,
        "message": message,
        "writing_tasks": [],
        "warnings": [],
    }

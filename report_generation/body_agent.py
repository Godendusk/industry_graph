"""Body generation agent for industry reports."""

from __future__ import annotations

import copy
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List

from llm_client import LLMQueryResult, llm
from .citations import collect_used_references, validate_body_citations
from .industry_config import SUPPORTED_INDUSTRIES


DEFAULT_MAX_WORKERS = 3
DEFAULT_MAX_TOKENS = 5000
RETRY_MAX_TOKENS = 3000


def generate_body_section(
    writing_task: dict,
    user_prompt: str,
    report_title: str,
    previous_body_sections: list = None,
) -> dict:
    """Generate body text for one second-level report outline item."""
    normalized_prompt = _safe_text(user_prompt)
    normalized_title = _safe_text(report_title)

    if not isinstance(writing_task, dict):
        return _section_error_response({}, "writing_task must be an object")
    if not normalized_prompt:
        return _section_error_response(writing_task, "user_prompt cannot be empty")
    if not normalized_title:
        return _section_error_response(writing_task, "report_title cannot be empty")

    writing_system_prompt = _safe_text(writing_task.get("writing_system_prompt"))
    if not writing_system_prompt:
        return _section_error_response(writing_task, "writing_system_prompt cannot be empty")

    subsection_title = _safe_text(writing_task.get("title"))
    if not subsection_title:
        return _section_error_response(writing_task, "writing_task.title cannot be empty")

    body_user_prompt = _build_body_user_prompt(
        writing_task=writing_task,
        user_prompt=normalized_prompt,
        report_title=normalized_title,
        previous_body_sections=previous_body_sections,
    )

    body_text, cleanup_warnings, failure_message = _generate_body_text_with_retry(
        body_user_prompt=body_user_prompt,
        writing_system_prompt=writing_system_prompt,
        subsection_title=subsection_title,
    )
    if not body_text:
        return _section_error_response(writing_task, failure_message)

    section_warnings = _copy_list(writing_task.get("warnings"))
    section_warnings.extend(cleanup_warnings)
    external_evidence_blocks = _external_evidence_blocks(writing_task)
    body_text, citation_ids, citation_warnings = validate_body_citations(
        body_text, external_evidence_blocks
    )
    section_warnings.extend(citation_warnings)

    result = _base_section_payload(writing_task)
    result.update(
        {
            "status": "success",
            "body_text": body_text,
            "graph_evidence_blocks": _graph_evidence_blocks(writing_task),
            "external_evidence_blocks": external_evidence_blocks,
            "citation_ids": citation_ids,
            "warnings": section_warnings,
        }
    )
    return result


def _generate_body_text_with_retry(
    body_user_prompt: str,
    writing_system_prompt: str,
    subsection_title: str,
) -> tuple[str, List[dict], str]:
    """Generate one body section without accepting hidden/truncated output."""
    cleanup_warnings: List[dict] = []
    last_failure = "body LLM returned empty output"
    for attempt in range(2):
        request_kwargs = {
            "user_prompt": body_user_prompt,
            "system_prompt": writing_system_prompt,
            "max_tokens": DEFAULT_MAX_TOKENS if attempt == 0 else RETRY_MAX_TOKENS,
            "extra_log_info": f"report_generation.body_agent outline={subsection_title} attempt={attempt + 1}",
        }
        if attempt:
            request_kwargs.update(
                {
                    "reasoning_effort": None,
                    "extra_body": {"thinking": {"type": "disabled"}},
                    "user_prompt": (
                        f"{body_user_prompt}\n\n"
                        "【重试要求】上一次输出为空或达到长度上限。请直接给出当前小节的完整正文，"
                        "只写本小节内容，最多3段，优先写清楚可核验的公司筛选标准和公司名单，"
                        "不要输出思考过程、标题或参考文献。"
                    ),
                }
            )
        try:
            result = llm.query_result(**request_kwargs)
        except Exception as exc:
            last_failure = f"body LLM call failed: {exc}"
            continue

        if not isinstance(result, LLMQueryResult):
            last_failure = "body LLM returned an invalid response object"
            continue
        if result.error_message:
            last_failure = f"body LLM call failed: {result.error_message}"
            continue

        content = _safe_text(result.content)
        body_text, warnings = _clean_body_text(content)
        cleanup_warnings.extend(warnings)
        if result.finish_reason == "length":
            last_failure = "正文模型重试后仍被截断"
            continue
        if body_text:
            return body_text, cleanup_warnings, ""
        last_failure = "body LLM returned empty output after cleanup"

    return "", cleanup_warnings, last_failure


def generate_report_bodies(
    user_prompt: str,
    report_title: str,
    writing_tasks: list,
    industry: str = "ai",
    max_workers: int = DEFAULT_MAX_WORKERS,
    references: list = None,
) -> dict:
    """Generate body text for all writing tasks, preserving input order."""
    normalized_prompt = _safe_text(user_prompt)
    normalized_title = _safe_text(report_title)
    normalized_industry = _safe_text(industry)

    if references is not None and not isinstance(references, list):
        return _error_response("references must be an array", normalized_industry, "")

    if not normalized_prompt:
        return _error_response("user_prompt cannot be empty", normalized_industry, "")
    if not normalized_title:
        return _error_response("report_title cannot be empty", normalized_industry, "")

    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry, "未配置行业")

    if not isinstance(writing_tasks, list) or not writing_tasks:
        return _error_response(
            "writing_tasks must contain at least one item",
            normalized_industry,
            industry_name,
        )

    task_groups = _group_writing_tasks_by_level1(writing_tasks)
    actual_workers = _normalize_max_workers(max_workers, len(task_groups))
    body_sections: List[dict] = [None] * len(writing_tasks)  # type: ignore[list-item]

    if actual_workers == 1:
        for group in task_groups:
            for index, section in _generate_body_group(
                task_group=group,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
            ):
                body_sections[index] = section
    else:
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            future_to_group = {
                executor.submit(
                    _generate_body_group,
                    task_group=group,
                    user_prompt=normalized_prompt,
                    report_title=normalized_title,
                ): group
                for group in task_groups
            }
            for future in as_completed(future_to_group):
                group = future_to_group[future]
                try:
                    generated_sections = future.result()
                except Exception as exc:
                    generated_sections = [
                        (
                            item["index"],
                            _section_error_response(
                                item["task"] if isinstance(item["task"], dict) else {},
                                f"body group generation failed: {exc}",
                            ),
                        )
                        for item in group
                    ]
                for index, section in generated_sections:
                    body_sections[index] = section

    warnings = _collect_warnings(body_sections)
    used_references = collect_used_references(body_sections, references or [])
    success_count = sum(
        1 for section in body_sections if section.get("status") == "success"
    )
    if success_count == len(body_sections):
        status = "success"
    elif success_count == 0:
        status = "error"
    else:
        status = "partial_success"

    return {
        "status": status,
        "industry": normalized_industry,
        "industry_name": industry_name,
        "user_prompt": normalized_prompt,
        "report_title": normalized_title,
        "body_sections": body_sections,
        "references": used_references,
        "warnings": warnings,
    }


def _group_writing_tasks_by_level1(writing_tasks: list) -> List[List[dict]]:
    groups: List[List[dict]] = []
    group_index_by_key = {}
    for index, task in enumerate(writing_tasks):
        group_key = _level1_group_key(task, index)
        if group_key not in group_index_by_key:
            group_index_by_key[group_key] = len(groups)
            groups.append([])
        groups[group_index_by_key[group_key]].append(
            {
                "index": index,
                "task": task,
            }
        )
    return groups


def _level1_group_key(task: Any, index: int) -> str:
    if isinstance(task, dict):
        parent_level1_id = _safe_text(task.get("parent_level1_id"))
        if parent_level1_id:
            return parent_level1_id
        parent_level1_title = _safe_text(task.get("parent_level1_title"))
        if parent_level1_title:
            return f"title:{parent_level1_title}"
    return f"task:{index}"


def _generate_body_group(
    task_group: List[dict],
    user_prompt: str,
    report_title: str,
) -> List[tuple[int, dict]]:
    generated_sections: List[tuple[int, dict]] = []
    previous_success_sections: List[dict] = []

    for item in task_group:
        index = item["index"]
        task = item["task"]
        try:
            section = generate_body_section(
                writing_task=task,
                user_prompt=user_prompt,
                report_title=report_title,
                previous_body_sections=previous_success_sections,
            )
        except Exception as exc:
            section = _section_error_response(
                task if isinstance(task, dict) else {},
                f"body generation failed: {exc}",
            )

        generated_sections.append((index, section))
        if (
            isinstance(section, dict)
            and section.get("status") == "success"
            and _safe_text(section.get("body_text"))
        ):
            previous_success_sections.append(section)

    return generated_sections


def _format_previous_body_sections(previous_body_sections: Any) -> str:
    if not isinstance(previous_body_sections, list) or not previous_body_sections:
        return ""

    blocks = []
    for index, section in enumerate(previous_body_sections, 1):
        if not isinstance(section, dict):
            continue
        body_text = _safe_text(section.get("body_text"))
        if not body_text:
            continue
        title = _safe_text(section.get("title")) or f"已生成二级标题{index}"
        blocks.append(f"{index}. {title}\n{_truncate_text(body_text, 1200)}")

    return "\n\n".join(blocks)


def _truncate_text(text: str, max_length: int) -> str:
    safe_text = _safe_text(text)
    if len(safe_text) <= max_length:
        return safe_text
    return safe_text[:max_length].rstrip() + "..."


def _build_body_user_prompt(
    writing_task: dict,
    user_prompt: str,
    report_title: str,
    previous_body_sections: list = None,
) -> str:
    graph_retrieval = writing_task.get("graph_retrieval")
    if not isinstance(graph_retrieval, dict):
        graph_retrieval = {}

    external_rag_retrieval = writing_task.get("external_rag_retrieval")
    if not isinstance(external_rag_retrieval, dict):
        external_rag_retrieval = {}

    graph_context_text = _safe_text(graph_retrieval.get("graph_context_text"))
    rag_context_text = _safe_text(external_rag_retrieval.get("rag_context_text"))
    previous_body_text = _format_previous_body_sections(previous_body_sections)
    previous_body_context = previous_body_text or "暂无同一一级标题下已生成正文。"

    return f"""【用户原始需求】
{user_prompt}

【报告标题】
{report_title}

【当前一级标题】
{_safe_text(writing_task.get("parent_level1_title"))}

【当前二级标题】
{_safe_text(writing_task.get("title"))}

【同一一级标题下已生成正文】
{previous_body_context}

【知识图谱上下文】
{graph_context_text or "未提供可用知识图谱上下文。"}

【外部资料库上下文】
{rag_context_text or "未提供可用外部资料库上下文。"}

【生成要求】
请生成当前二级标题下的报告正文。
请直接输出正文段落，不要输出当前二级标题、章节标题或任何标题行。
如果同一一级标题下已有前文正文，请主动避开前文已写过和引用过的知识图谱和外部资料、观点、案例、数据、句式和分析角度，不要生成高度相似的内容。
生成正文时要重点参考关注当前的一级标题和二级标题，不要生成关联度不高的内容，比如标题让你分析现状你就分析现状，不要自作主张去分析突出问题和对策建议；标题让你分析对策建议你就分析对策建议，不要自作主张去分析现状和问题；标题让你分析现状你就分析现状，不要自作主张去分析突出问题和对策建议，绝对不要做多余的事。
特别需要注意生成正文时要刻意避免当前二级标题下以及同一一级标题不同二级标题下的每一自然段生成的正文的首句内容和句式重复或者高度相似。
请检查引用的资料，不要出现常识性错误，例如误把民营企业（华为海思）当成央企国企，误把外资企业（英伟达）当成民营企业。
要求报告正文绝对不多于 1000字，段落绝对不超过 3 段。
不得把 [知识图谱1] 等知识图谱编号当作文章来源。
凡使用外部资料中的数字、政策、领导讲话、专家观点或企业案例，必须在对应句末保留该资料的 [C数字] 引用编号。
只能使用“外部资料库上下文”中真实出现的 [C数字]，不得编造引用编号、资料标题或网址。
正文不输出独立参考文献列表，参考资料列表由系统生成。
不要生成表格、图片等内容。
不得生成摘要、目录、标题页、Word 导出说明或其他章节内容。"""


def _clean_body_text(content: str) -> tuple[str, List[dict]]:
    warnings: List[dict] = []
    text = _safe_text(content)

    fenced_match = re.fullmatch(r"```(?:markdown|md|text)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()
        warnings.append(
            {
                "stage": "body_cleanup",
                "message": "removed enclosing code fence from body output",
            }
        )

    cleaned = re.sub(r"\[(?:知识图谱|外部资料)\d+\]", "", text)
    if cleaned != text:
        text = cleaned
        warnings.append(
            {
                "stage": "body_cleanup",
                "message": "removed explicit citation markers from body output",
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
                "stage": "body_cleanup",
                "message": "removed trailing reference/source section from body output",
            }
        )

    return text.strip(), warnings


def _base_section_payload(writing_task: dict) -> dict:
    task = writing_task if isinstance(writing_task, dict) else {}
    return {
        "outline_id": _safe_text(task.get("outline_id")),
        "parent_level1_id": _safe_text(task.get("parent_level1_id")),
        "parent_level1_title": _safe_text(task.get("parent_level1_title")),
        "title": _safe_text(task.get("title")),
    }


def _section_error_response(writing_task: dict, message: str) -> dict:
    result = _base_section_payload(writing_task)
    warning = {
        "outline_id": result.get("outline_id", ""),
        "stage": "body_generation",
        "message": message,
    }
    result.update(
        {
            "status": "error",
            "message": message,
            "body_text": "",
            "graph_evidence_blocks": _graph_evidence_blocks(writing_task),
            "external_evidence_blocks": _external_evidence_blocks(writing_task),
            "citation_ids": [],
            "warnings": _copy_list(writing_task.get("warnings")) + [warning]
            if isinstance(writing_task, dict)
            else [warning],
        }
    )
    return result


def _collect_warnings(body_sections: List[dict]) -> List[dict]:
    warnings: List[dict] = []
    for section in body_sections:
        if not isinstance(section, dict):
            continue
        for warning in section.get("warnings") or []:
            warnings.append(copy.deepcopy(warning))
    return warnings


def _graph_evidence_blocks(writing_task: dict) -> List[dict]:
    if not isinstance(writing_task, dict):
        return []
    graph_retrieval = writing_task.get("graph_retrieval")
    if not isinstance(graph_retrieval, dict):
        return []
    return _copy_list(graph_retrieval.get("evidence_blocks"))


def _external_evidence_blocks(writing_task: dict) -> List[dict]:
    if not isinstance(writing_task, dict):
        return []
    external_rag_retrieval = writing_task.get("external_rag_retrieval")
    if not isinstance(external_rag_retrieval, dict):
        return []
    return _copy_list(external_rag_retrieval.get("evidence_blocks"))


def _copy_list(value: Any) -> List[dict]:
    if not isinstance(value, list):
        return []
    return copy.deepcopy(value)


def _normalize_max_workers(max_workers: Any, task_count: int) -> int:
    try:
        value = int(max_workers)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_WORKERS
    if value <= 0:
        value = DEFAULT_MAX_WORKERS
    if task_count <= 0:
        return 0
    return min(value, task_count)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _error_response(message: str, industry: str, industry_name: str) -> dict:
    return {
        "status": "error",
        "industry": industry,
        "industry_name": industry_name,
        "message": message,
        "body_sections": [],
        "references": [],
        "warnings": [],
    }

"""Body generation agent for industry reports."""

from __future__ import annotations

import copy
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
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
    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        future_to_group = {
            executor.submit(
                _generate_body_group,
                task_group=task_group,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
            ): task_group
            for task_group in task_groups
        }
        for future in as_completed(future_to_group):
            try:
                generated = future.result()
            except Exception as exc:
                generated = [
                    (
                        item["index"],
                        _section_error_response(
                            item["task"] if isinstance(item.get("task"), dict) else {},
                            f"body generation failed: {exc}",
                        ),
                    )
                    for item in future_to_group[future]
                ]
            for index, section in generated:
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
        "max_workers": actual_workers,
        "references": used_references,
        "warnings": warnings,
    }


def stream_report_bodies(
    user_prompt: str,
    report_title: str,
    writing_tasks: list,
    industry: str = "ai",
    max_workers: int = DEFAULT_MAX_WORKERS,
    references: list = None,
):
    """Yield body-generation progress events as sections complete."""
    normalized_prompt = _safe_text(user_prompt)
    normalized_title = _safe_text(report_title)
    normalized_industry = _safe_text(industry)
    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry, "未配置行业")

    if references is not None and not isinstance(references, list):
        yield _stream_error_event("references must be an array", normalized_industry, industry_name)
        return
    if not normalized_prompt:
        yield _stream_error_event("user_prompt cannot be empty", normalized_industry, industry_name)
        return
    if not normalized_title:
        yield _stream_error_event("report_title cannot be empty", normalized_industry, industry_name)
        return
    if not isinstance(writing_tasks, list) or not writing_tasks:
        yield _stream_error_event("writing_tasks must contain at least one item", normalized_industry, industry_name)
        return

    task_groups = _group_writing_tasks_by_level1(writing_tasks)
    actual_workers = _normalize_max_workers(max_workers, len(task_groups))
    body_sections: List[dict] = [None] * len(writing_tasks)  # type: ignore[list-item]
    event_queue: Queue = Queue()
    stop_token = object()

    yield {
        "event": "started",
        "status": "started",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "total": len(writing_tasks),
        "group_count": len(task_groups),
        "max_workers": actual_workers,
    }

    def producer() -> None:
        try:
            with ThreadPoolExecutor(max_workers=actual_workers) as executor:
                future_to_group = {
                    executor.submit(
                        _generate_body_group,
                        task_group=task_group,
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        on_event=event_queue.put,
                    ): task_group
                    for task_group in task_groups
                }
                for future in as_completed(future_to_group):
                    try:
                        generated = future.result()
                    except Exception as exc:
                        generated = [
                            (
                                item["index"],
                                _section_error_response(
                                    item["task"] if isinstance(item.get("task"), dict) else {},
                                    f"body generation failed: {exc}",
                                ),
                            )
                            for item in future_to_group[future]
                        ]
                        for item, (index, section) in zip(future_to_group[future], generated):
                            event_queue.put(_task_stream_event("section_started", index, item.get("task", {})))
                            event_queue.put(_section_stream_event("section_failed", index, section))
                    for index, section in generated:
                        body_sections[index] = section

            warnings = _collect_warnings(body_sections)
            used_references = collect_used_references(body_sections, references or [])
            success_count = sum(
                1 for section in body_sections if isinstance(section, dict) and section.get("status") == "success"
            )
            if success_count == len(body_sections):
                status = "success"
            elif success_count == 0:
                status = "error"
            else:
                status = "partial_success"
            event_queue.put({
                "event": "completed",
                "status": status,
                "industry": normalized_industry,
                "industry_name": industry_name,
                "user_prompt": normalized_prompt,
                "report_title": normalized_title,
                "body_sections": body_sections,
                "references": used_references,
                "warnings": warnings,
                "success_count": success_count,
                "total": len(body_sections),
                "group_count": len(task_groups),
                "max_workers": actual_workers,
            })
        except Exception as exc:
            event_queue.put({
                "event": "error",
                "status": "error",
                "industry": normalized_industry,
                "industry_name": industry_name,
                "message": str(exc),
            })
        finally:
            event_queue.put(stop_token)

    threading.Thread(target=producer, daemon=True).start()
    while True:
        event = event_queue.get()
        if event is stop_token:
            break
        yield event


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
    on_event=None,
) -> List[tuple[int, dict]]:
    generated_sections: List[tuple[int, dict]] = []
    previous_success_sections: List[dict] = []

    for item in task_group:
        index = item["index"]
        task = item["task"]
        if callable(on_event):
            on_event(_task_stream_event("section_started", index, task))
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
        if callable(on_event):
            event_name = "section_completed" if section.get("status") == "success" else "section_failed"
            on_event(_section_stream_event(event_name, index, section))
        if (
            isinstance(section, dict)
            and section.get("status") == "success"
            and _safe_text(section.get("body_text"))
        ):
            previous_success_sections.append(section)

    return generated_sections


def _task_stream_event(event_name: str, index: int, task: Any) -> dict:
    payload = _base_section_payload(task if isinstance(task, dict) else {})
    payload.update({"event": event_name, "index": index, "status": "started"})
    return payload


def _section_stream_event(event_name: str, index: int, section: dict) -> dict:
    payload = dict(section if isinstance(section, dict) else {})
    payload.update({
        "event": event_name,
        "index": index,
        "status": payload.get("status") or ("success" if event_name == "section_completed" else "error"),
    })
    return payload


def _stream_error_event(message: str, industry: str, industry_name: str) -> dict:
    return {
        "event": "error",
        "status": "error",
        "industry": industry,
        "industry_name": industry_name,
        "message": message,
    }


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


def _format_prior_report_facts(previous_sections: Any, current_task: Any) -> str:
    """Format compact, deterministic avoidance context from prior body sections.

    The returned text is deliberately derived from existing section output and
    never calls the model.  Only successful sections contribute facts, and
    citation-bearing sentences are included when their citation is available to
    the current task.
    """
    if not isinstance(previous_sections, list) or not previous_sections:
        return "暂无本章已生成正文"

    current_evidence_ids = {
        _safe_text(row.get("citation_id"))
        for row in _external_evidence_blocks(current_task if isinstance(current_task, dict) else {})
        if isinstance(row, dict) and _safe_text(row.get("citation_id"))
    }
    blocks: List[str] = []
    for index, section in enumerate(previous_sections, 1):
        if not isinstance(section, dict):
            continue
        status = _safe_text(section.get("status"))
        if status and status != "success":
            continue
        body_text = _safe_text(section.get("body_text"))
        if not body_text:
            continue
        sentences = _complete_sentences(body_text)
        if not sentences:
            continue
        title = _safe_text(section.get("title")) or f"已生成二级标题{index}"
        lines = [f"- {title}：{_truncate_sentence(sentences[0])}"]

        matching_sentences = []
        for sentence in sentences:
            if sentence == sentences[0]:
                continue
            if any(f"[{citation_id}]" in sentence for citation_id in current_evidence_ids):
                matching_sentences.append(_truncate_sentence(sentence))
                if len(matching_sentences) >= 2:
                    break
        if matching_sentences:
            lines.append("  当前资料对应事实：" + " ".join(matching_sentences))
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) or "暂无本章已生成正文"


def _complete_sentences(text: str) -> List[str]:
    """Return complete sentences terminated by common Chinese/Latin punctuation."""
    safe_text = _safe_text(text)
    if not safe_text:
        return []
    return [
        match.group(0).strip()
        for match in re.finditer(r"[^\n]+?(?:[。！？!?；;]|\.(?=\s|$))", safe_text)
        if match.group(0).strip()
    ]


def _truncate_sentence(text: str, max_length: int = 160) -> str:
    safe_text = _safe_text(text)
    if len(safe_text) <= max_length:
        return safe_text
    return safe_text[: max_length - 1].rstrip() + "…"


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
    prior_report_facts = _format_prior_report_facts(previous_body_sections, writing_task)

    return f"""【用户原始需求】
{user_prompt}

【报告标题】
{report_title}

【当前一级标题】
{_safe_text(writing_task.get("parent_level1_title"))}

【当前二级标题】
{_safe_text(writing_task.get("title"))}

【本章已写事实（仅用于避重）】
{prior_report_facts}

【知识图谱上下文】
{graph_context_text or "未提供可用知识图谱上下文。"}

【外部资料库上下文】
{rag_context_text or "未提供可用外部资料库上下文。"}

【生成要求】

请根据用户原始需求、报告标题、当前一级标题和当前二级标题，撰写可直接纳入研究报告的正文。

一、内容范围与分析重点
紧扣当前二级标题所要解决的问题，不偏离其所属一级标题的主题。
现状类内容重点说明已有事实、主要特征和发展变化；问题类内容重点分析具体表现、形成原因及实际影响；对策类内容重点提出具体措施、作用机制和实施条件。
允许简要交代必要的背景或关联信息，但不要将其他小节的分析任务扩展为当前小节的主要内容。
根据资料的信息量确定分析深度，不为增加篇幅而引入缺乏依据的内容。

二、语言风格与论证方式
采用专业研究人员面向决策读者的写作方式，语言准确、自然、具体，保持研究报告应有的专业性，同时避免机械化的公文表达。
优先使用清晰、完整的句子，减少冗长修饰、抽象概念堆叠、空泛评价和缺乏实际信息的过渡句。
每个自然段围绕一个明确的信息重点展开，将事实依据、分析判断和实际意义有机结合。重点解释事实说明了什么、为什么重要，而不只是罗列材料。
观点应有相应依据，涉及原因、影响及趋势时，应交代合理的分析逻辑，不将推测写成确定事实。
避免反复使用相同的段落开头、衔接方式和总结性套话，但不必为了追求语言变化而刻意改变自然表达。
对于“持续赋能”“不断深化”“显著提升”等概括性表述，只有在具有具体事实支撑时才使用，优先说明实际变化、作用机制或具体表现。

三、前文衔接与内容去重
“本章已写事实”仅用于了解前文内容和减少重复，不作为当前小节的引用证据。
尽量避免重复展开前文已经充分论述的观点、案例和分析过程。确有必要时，可以简要复用关键事实或资料，但应服务于当前小节不同的分析重点。
优先增加与当前二级标题直接相关的事实、解释和分析，不为了追求内容差异而编造新观点、新数据或新案例。
段落之间应有自然的逻辑联系，避免相邻段落及可见前文中高度重复的开头和论述方式。

四、资料使用与事实准确性
以当前提供的知识图谱上下文和外部资料库上下文为信息基础，区分资料中的客观事实与基于事实形成的分析判断。
知识图谱可用于理解实体关系、梳理分析线索，但不得将[知识图谱1]等编号当作外部文献来源。
对于统计数字、政策文件、领导讲话、专家观点、企业案例及其他需要外部证据支持的具体事实，应使用当前外部资料库中能够支持相关内容的资料，并在对应句末标注[C数字]。
引用编号只能来自当前小节“外部资料库上下文”中真实提供的编号，不得编造引用、资料标题或网址，也不得引用与论述内容不相关的资料。
当资料不足以支持具体结论时，应适当收窄判断范围或省略未经证实的细节，不得自行补充缺失事实。
特别注意企业所有制、国别、业务性质以及政策和事件的时间信息，不能将民营企业、国有企业和外国企业等不同类别混淆。

五、正文结构与输出格式
根据内容逻辑自然分段，每段集中阐述一个相对完整的信息重点。
正文总字数不超过1000字，自然段不超过3段。信息充分时适当展开，信息有限时以准确、完整为先，不刻意凑满字数或段落数。
直接输出正文段落，不输出当前二级标题、章节标题、摘要、目录、独立参考文献列表、表格、图片、Word导出说明或其他无关内容。
"""


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

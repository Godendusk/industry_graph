"""Body generation agent for industry reports."""

from __future__ import annotations
from .runtime_budget import budgeted_stage, current_budget, bind_runtime_context, submit_with_context


import copy
import re
import json
from .delivery import delivery_state
import threading
from queue import Queue
from typing import Any, List

from .agentic_rag.assessment import render_evidence_pack
from llm_client import LLMQueryResult, llm
from .citations import collect_used_references, validate_body_citations, bind_report_sources
from .industry_config import SUPPORTED_INDUSTRIES
from .repetition_context import REUSE_RULES, build_prior_context, focus_terms_for_task
from .writing_decisions import render_decision_prompt
from .review_agent import review_report_bodies


DEFAULT_MAX_WORKERS = 3
DEFAULT_MAX_TOKENS = 5000
RETRY_MAX_TOKENS = 3000


def generate_body_section(
    writing_task: dict,
    user_prompt: str,
    report_title: str,
    previous_body_sections: list = None,
    report_evidence_blocks: list = None,
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

    if "writing_decision" in writing_task:
        try:
            writing_system_prompt = render_decision_prompt(writing_task["writing_decision"])
        except (ValueError, TypeError) as exc:
            error = _section_error_response(writing_task, f"invalid writing_decision: {exc}")
            error["warnings"].append({"stage": "writing_decision_validation", "message": str(exc),
                                      "outline_id": writing_task.get("outline_id", "")})
            return error
    else:
        # Saved reports without decisions retain their existing writing instructions.
        writing_system_prompt = _safe_text(writing_task.get("writing_system_prompt"))
    if not writing_system_prompt:
        return _section_error_response(writing_task, "writing_system_prompt cannot be empty")

    subsection_title = _safe_text(writing_task.get("title"))
    if not subsection_title:
        return _section_error_response(writing_task, "writing_task.title cannot be empty")

    prior_context = build_prior_context(previous_body_sections, writing_task)
    body_user_prompt = _build_body_user_prompt(
        writing_task=writing_task,
        user_prompt=normalized_prompt,
        report_title=normalized_title,
        previous_body_sections=previous_body_sections,
        prior_report_facts=prior_context["text"],
    )

    body_text, cleanup_warnings, failure_message = _generate_body_text_with_retry(
        body_user_prompt=body_user_prompt,
        writing_system_prompt=writing_system_prompt + "\n" + REUSE_RULES,
        subsection_title=subsection_title,
    )
    if not body_text:
        return _section_error_response(writing_task, failure_message)

    section_warnings = _copy_list(writing_task.get("warnings"))
    section_warnings.extend(cleanup_warnings)
    if prior_context["omitted_fact_count"]:
        section_warnings.append({"stage": "repetition_context",
            "message": "related prior statements omitted by prompt budget",
            "omitted_fact_count": prior_context["omitted_fact_count"]})
    external_evidence_blocks = bind_report_sources(body_text, _external_evidence_blocks(writing_task), report_evidence_blocks)
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
            "repetition_focus_terms": focus_terms_for_task(writing_task),
            "report_facts": copy.deepcopy(writing_task.get("report_facts", [])),
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
        if current_budget():
            request_kwargs.update(reasoning_effort='low', extra_body={'thinking': {'type': 'disabled'}})
        if attempt:
            request_kwargs.update(
                {
                    "reasoning_effort": None,
                    "extra_body": {"thinking": {"type": "disabled"}},
                    "user_prompt": (
                        f"{body_user_prompt}\n\n"
                        "【重试要求】上一次输出为空或达到长度上限。请直接给出当前小节的完整正文，"
                        "只写本小节内容，优先完成当前小节的核心问题，保留必要证据和分析深度，"
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


@budgeted_stage("body")
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

    if any((task.get('report_scope') or {}).get('status') == 'incomplete' for task in writing_tasks):
        return _error_response('研究范围尚未确认，保留已检索资料，未继续按原大纲扩写', normalized_industry, industry_name)

    # ``max_workers`` remains an accepted request field for client compatibility,
    # while prior-section context requires one ordered generation stream.
    actual_workers = 1
    report_sources = [b for task in writing_tasks for b in _external_evidence_blocks(task)]
    body_sections: List[dict] = [None] * len(writing_tasks)  # type: ignore[list-item]
    previous_success_sections: List[dict] = []
    for index, task in enumerate(writing_tasks):
        if current_budget() and current_budget().remaining_seconds('body') <= 0:
            body_sections[index] = _section_error_response(task, '正文时间预算已耗尽')
            continue
        try:
            section = generate_body_section(
                writing_task=task,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                previous_body_sections=previous_success_sections,
                report_evidence_blocks=report_sources,
            )
        except Exception as exc:
            section = _section_error_response(
                task if isinstance(task, dict) else {},
                f"body generation failed: {exc}",
            )
        body_sections[index] = section
        if (
            isinstance(section, dict)
            and section.get("status") == "success"
            and _safe_text(section.get("body_text"))
        ):
            previous_success_sections.append(section)

    review_result = review_report_bodies(
        body_sections=body_sections, writing_tasks=writing_tasks,
        report_title=normalized_title, user_prompt=normalized_prompt,
        references=references or [],
    ) if previous_success_sections else None
    if review_result:
        body_sections = review_result['body_sections']
    warnings = _collect_warnings(body_sections) + (review_result['warnings'] if review_result else [])
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
        "review": review_result['review'] if review_result else None,
        "report_scope": writing_tasks[0].get('report_scope'),
        **delivery_state(body_sections, review_result['review'] if review_result else None,
                         report_scope=writing_tasks[0].get('report_scope')),
        "adjustment_notes": review_result['adjustment_notes'] if review_result else [],
    }


@budgeted_stage("body")
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

    if any((task.get('report_scope') or {}).get('status') == 'incomplete' for task in writing_tasks):
        yield _stream_error_event('研究范围尚未确认，保留已检索资料，未继续按原大纲扩写', normalized_industry, industry_name)
        return

    # ``max_workers`` remains accepted for API compatibility; generation is
    # intentionally ordered so each section can see prior successful sections.
    task_groups = _group_writing_tasks_by_level1(writing_tasks)
    actual_workers = 1
    report_sources = [b for task in writing_tasks for b in _external_evidence_blocks(task)]
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
            previous_success_sections: List[dict] = []
            for index, task in enumerate(writing_tasks):
                if current_budget() and current_budget().remaining_seconds('body') <= 0:
                    body_sections[index] = _section_error_response(task, '正文时间预算已耗尽')
                    continue
                event_queue.put(_task_stream_event("section_started", index, task))
                try:
                    section = generate_body_section(
                        writing_task=task,
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        previous_body_sections=previous_success_sections,
                        report_evidence_blocks=report_sources,
                    )
                except Exception as exc:
                    section = _section_error_response(
                        task if isinstance(task, dict) else {},
                        f"body generation failed: {exc}",
                    )
                body_sections[index] = section
                event_name = "section_completed" if section.get("status") == "success" else "section_failed"
                event_queue.put(_section_stream_event(event_name, index, section))
                if (
                    isinstance(section, dict)
                    and section.get("status") == "success"
                    and _safe_text(section.get("body_text"))
                ):
                    previous_success_sections.append(section)

            review_result = review_report_bodies(
                body_sections=body_sections, writing_tasks=writing_tasks,
                report_title=normalized_title, user_prompt=normalized_prompt,
                references=references or [], on_event=event_queue.put,
            ) if previous_success_sections else None
            if review_result:
                body_sections[:] = review_result['body_sections']
            warnings = _collect_warnings(body_sections) + (review_result['warnings'] if review_result else [])
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
                "review": review_result['review'] if review_result else None,
                "report_scope": writing_tasks[0].get('report_scope'),
                **delivery_state(body_sections, review_result['review'] if review_result else None,
                                 report_scope=writing_tasks[0].get('report_scope')),
                "adjustment_notes": review_result['adjustment_notes'] if review_result else [],
                "success_count": success_count,
                "total": len(body_sections),
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

    threading.Thread(target=bind_runtime_context(producer), daemon=True).start()
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
    report_sources = [b for item in task_group for b in _external_evidence_blocks(item["task"])]
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
                report_evidence_blocks=report_sources,
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
    return build_prior_context(previous_sections, current_task)["text"]


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
    prior_report_facts: str = None,
) -> str:
    graph_retrieval = writing_task.get("graph_retrieval")
    if not isinstance(graph_retrieval, dict):
        graph_retrieval = {}

    external_rag_retrieval = writing_task.get("external_rag_retrieval")
    if not isinstance(external_rag_retrieval, dict):
        external_rag_retrieval = {}

    graph_context_text = _safe_text(graph_retrieval.get("graph_context_text"))
    rag_context_text = _safe_text(external_rag_retrieval.get("rag_context_text"))
    if prior_report_facts is None:
        prior_report_facts = _format_prior_report_facts(previous_body_sections, writing_task)

    packs = ([writing_task["evidence_pack"]] if writing_task.get("evidence_pack") else []) + writing_task.get("merged_evidence_packs", [])
    evidence_requirements = "\n\n".join(render_evidence_pack(pack) for pack in packs)

    return f"""【用户原始需求】
{user_prompt}

【有效研究范围（优先遵守，原始需求不代表缺失事实已经得到回答）】
{json.dumps(writing_task.get('report_scope') or {}, ensure_ascii=False)}

【报告标题】
{report_title}

【当前一级标题】
{_safe_text(writing_task.get("parent_level1_title"))}

【当前二级标题】
{_safe_text(writing_task.get("title"))}

【整篇报告已写事实（仅用于避重）】
{prior_report_facts}

【知识图谱上下文】
{graph_context_text or "未提供可用知识图谱上下文。"}

【外部资料库上下文】
{rag_context_text or "未提供可用外部资料库上下文。"}

【本节拟完成的实质回答】
{json.dumps(writing_task.get("section_answer") or {}, ensure_ascii=False)}
这是基于材料的写作安排，不是事实证据。直接展开本节的回答及其依据，必要时按原文收窄。不要把“将研究什么”写成正文，也不照抄其他节已完整展开的背景或重复资料缺口。

【本次报告关键事实索引（仍以支持的原文为准）】
{json.dumps(writing_task.get('report_facts') or [], ensure_ascii=False)}
相同企业的不同型号、不同证照与不同时点分开叙述；已检索到后续已实现节点时，不只复述旧预测或以本节材料有限宣称全篇没有记录。项目申报指南仅用于说明该项目要求，不能推出整条产业路线必须满足同一工程或准入门槛。

【比较口径】
每组经营、收入、份额、订单和产能数字标明对应时期及对象，不以“报告期”代替具体年份。无法确认时期或无法比较的数字，不用于横向高低判断。
同一分类框架全篇一致；不同材料采用不同框架时先说明对应关系，不把分类差异当成企业差异。证照和项目进度写具体类型、时间与计划/已实现状态。
允许基于已核实事实提出自己的比较、条件情景和启示；方法说明和分析边界不需要外部文章替本报告下结论。

【章节证据要求与写作边界】
{evidence_requirements or "未提供章节证据评估；不得将资料数量或图谱线索等同于事实支持。"}

【合并来源小节的分析任务】
{json.dumps(writing_task.get('merged_writing_decisions') or [], ensure_ascii=False)}

【生成要求】
请生成当前二级标题下的报告正文。
章节证据包中的未解决需求与写作边界必须遵守，即使写作安排预设了相关结论，也不得越过证据范围。
请直接输出正文段落，不要输出当前二级标题、章节标题或任何标题行。
上面的整篇报告已写事实仅用于改变当前叙述角度和避免重复，不是当前小节的可引用证据。正文中的 [C数字] 只能来自当前小节“外部资料库上下文”中真实出现的引用编号。
生成正文时要重点参考关注当前的一级标题和二级标题，不要生成关联度不高的内容，比如标题让你分析现状你就分析现状，不要自作主张去分析突出问题和对策建议；标题让你分析对策建议你就分析对策建议，不要自作主张去分析现状和问题；标题让你分析现状你就分析现状，不要自作主张去分析突出问题和对策建议，绝对不要做多余的事。
请检查引用的资料，不要出现常识性错误，例如误把民营企业（华为海思）当成央企国企，误把外资企业（英伟达）当成民营企业。
本节篇幅由实际证据和分析任务决定。保留具体比较、差异解释和必要条件；资料少时简洁作答，不重复背景凑字数。
不在每节开头重述研究方法、取样原则或证据局限，也不在结尾重复总结已经逐项介绍的事实；这些说明只在实际影响本节判断处用一句必要限定。直接从本节能回答的具体问题写起。
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

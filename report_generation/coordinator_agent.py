"""Coordinator agent for industry report writing tasks."""

from __future__ import annotations

import copy
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from typing import Any, Dict, List, Optional

from llm_client import llm

from .external_rag.retriever import retrieve_external_rag
from .external_rag.report_adapter import build_rag_context_text
from .citations import register_evidence_blocks
from .material_allocator import allocate_evidence_blocks
from .repetition_context import focus_terms_for_task
from .writing_decisions import request_decision, fallback_decision, render_decision_prompt, decision_topics
from .task_coordination import coordinate_writing_tasks
from .outline_adjustments import apply_outline_adjustments
from .graph_retriever import retrieve_industry_graph
from .industry_config import SUPPORTED_INDUSTRIES


DEFAULT_TOP_K = 10
DEFAULT_MAX_COORDINATOR_WORKERS = 3
MAX_COORDINATOR_WORKERS_LIMIT = 6


def finalize_coordination_outline(outline, writing_tasks, coordination, user_prompt):
    """Apply the coordinator's bounded outline proposal after decisions settle."""
    operations = (coordination or {}).get('outline_operations') or []
    protected = set()
    for task in writing_tasks:
        title = str(task.get('title') or '').strip()
        if title and title in user_prompt:
            protected.add(task.get('outline_id'))
        external = (task.get('external_rag_retrieval') or {}).get('status')
        graph = (task.get('graph_retrieval') or {}).get('status')
        if external in ('error', 'skipped') and graph != 'success':
            protected.add(task.get('outline_id'))
    return apply_outline_adjustments(outline, writing_tasks, operations, protected)


def generate_writing_tasks(
    user_prompt: str,
    report_title: str,
    outline: list,
    industry: str = "ai",
    top_k: int = DEFAULT_TOP_K,
    use_graph: bool = True,
    use_external_rag: bool = True,
    max_workers: int = DEFAULT_MAX_COORDINATOR_WORKERS,
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

    _attach_outline_context(final_subsections)

    retrieval_rows: List[dict] = [None] * len(final_subsections)  # type: ignore[list-item]
    warning_groups: List[List[dict]] = [[] for _ in final_subsections]
    worker_count = _normalize_max_workers(max_workers, len(final_subsections))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _generate_writing_task_for_subsection,
                subsection=subsection,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                industry=normalized_industry,
                top_k=normalized_top_k,
                use_graph=use_graph,
                use_external_rag=use_external_rag,
            ): index
            for index, subsection in enumerate(final_subsections)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            subsection = final_subsections[index]
            try:
                retrieval, task_warnings = future.result()
            except Exception as exc:
                retrieval, task_warnings = _retrieval_unhandled_error_response(
                    subsection=subsection,
                    user_prompt=normalized_prompt,
                    report_title=normalized_title,
                    top_k=normalized_top_k,
                    message=f"coordinator task generation failed: {exc}",
                )
            retrieval_rows[index] = retrieval
            warning_groups[index] = task_warnings

    warnings: List[dict] = []
    for task_warnings in warning_groups:
        warnings.extend(task_warnings)

    allocated = _allocate_retrieved_evidence(final_subsections, retrieval_rows, normalized_top_k)
    references: List[dict] = []
    for index, row in enumerate(allocated):
        retrieval = row.get("external_rag_retrieval") or {}
        mapped_blocks, references = register_evidence_blocks(
            retrieval.get("evidence_blocks") or [], references
        )
        retrieval["evidence_blocks"] = mapped_blocks
        retrieval["rag_context_text"] = build_rag_context_text(mapped_blocks)
        row["external_rag_retrieval"] = retrieval

    writing_tasks: List[dict] = [None] * len(final_subsections)  # type: ignore[list-item]
    for index, subsection in enumerate(final_subsections):
        row = allocated[index]
        if row.get("_retrieval_failed"):
            writing_tasks[index], _ = _writing_task_unhandled_error_response(
                subsection=subsection,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                top_k=normalized_top_k,
                message=row.get("_retrieval_error", "retrieval failed"),
            )
            continue
        try:
            writing_tasks[index], prompt_warnings = _build_writing_task_from_retrieval(
                subsection=subsection,
                graph_retrieval=row.get("graph_retrieval") or {},
                external_rag_retrieval=row.get("external_rag_retrieval") or {},
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                warnings=warning_groups[index],
                previous_tasks=writing_tasks[:index],
                outline_ids={item["outline_id"] for item in final_subsections},
            )
        except Exception as exc:
            writing_tasks[index], prompt_warnings = _writing_task_unhandled_error_response(
                subsection=subsection,
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                top_k=normalized_top_k,
                message=f"coordinator task generation failed: {exc}",
            )
            warning_groups[index].extend(prompt_warnings)

    writing_tasks, coordination, review_warnings = coordinate_writing_tasks(writing_tasks)
    final_outline, writing_tasks, adjustment_notes, adjustment_warnings = finalize_coordination_outline(
        outline, writing_tasks, coordination, normalized_prompt)
    warnings = ([warning for task in writing_tasks for warning in task.get("warnings", [])]
                + review_warnings + adjustment_warnings)

    return {
        "status": "success",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "use_graph": bool(use_graph),
        "use_external_rag": bool(use_external_rag),
        "user_prompt": normalized_prompt,
        "report_title": normalized_title,
        "max_workers": worker_count,
        "writing_tasks": writing_tasks,
        "final_outline": final_outline,
        "adjustment_notes": adjustment_notes,
        "fallback_count": _fallback_count(writing_tasks),
        "coordination": coordination,
        "references": references,
        "warnings": warnings,
    }


def stream_writing_tasks(
    user_prompt: str,
    report_title: str,
    outline: list,
    industry: str = "ai",
    top_k: int = DEFAULT_TOP_K,
    use_graph: bool = True,
    use_external_rag: bool = True,
    max_workers: int = DEFAULT_MAX_COORDINATOR_WORKERS,
):
    """Yield coordinator progress events as subsection tasks complete."""
    normalized_prompt = str(user_prompt or "").strip()
    normalized_title = str(report_title or "").strip()
    normalized_industry = str(industry or "").strip()
    normalized_top_k = _normalize_top_k(top_k)
    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry, "未配置行业")

    if not normalized_prompt:
        yield _stream_error_event("user_prompt cannot be empty", normalized_industry, industry_name)
        return
    if not normalized_title:
        yield _stream_error_event("report_title cannot be empty", normalized_industry, industry_name)
        return

    final_subsections = _flatten_body_subsections(outline)
    if not final_subsections:
        yield _stream_error_event("outline must contain at least one body subsection", normalized_industry, industry_name)
        return

    _attach_outline_context(final_subsections)

    retrieval_rows: List[dict] = [None] * len(final_subsections)  # type: ignore[list-item]
    warning_groups: List[List[dict]] = [[] for _ in final_subsections]
    event_queue: Queue = Queue()
    stop_token = object()
    worker_count = _normalize_max_workers(max_workers, len(final_subsections))

    yield {
        "event": "started",
        "status": "started",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "total": len(final_subsections),
        "max_workers": worker_count,
    }

    def producer() -> None:
        try:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_index = {}
                for index, subsection in enumerate(final_subsections):
                    event_queue.put(_subsection_stream_event("task_started", index, subsection))
                    future = executor.submit(
                        _generate_writing_task_for_subsection,
                        subsection=subsection,
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        industry=normalized_industry,
                        top_k=normalized_top_k,
                        use_graph=use_graph,
                        use_external_rag=use_external_rag,
                    )
                    future_to_index[future] = index

                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    subsection = final_subsections[index]
                    try:
                        retrieval, task_warnings = future.result()
                    except Exception as exc:
                        retrieval, task_warnings = _retrieval_unhandled_error_response(
                            subsection=subsection,
                            user_prompt=normalized_prompt,
                            report_title=normalized_title,
                            top_k=normalized_top_k,
                            message=f"coordinator task generation failed: {exc}",
                        )
                    retrieval_rows[index] = retrieval
                    warning_groups[index] = task_warnings

            warnings: List[dict] = []
            for task_warnings in warning_groups:
                warnings.extend(task_warnings)

            allocated = _allocate_retrieved_evidence(final_subsections, retrieval_rows, normalized_top_k)
            references: List[dict] = []
            for row in allocated:
                retrieval = row.get("external_rag_retrieval") or {}
                mapped_blocks, references = register_evidence_blocks(
                    retrieval.get("evidence_blocks") or [], references
                )
                retrieval["evidence_blocks"] = mapped_blocks
                retrieval["rag_context_text"] = build_rag_context_text(mapped_blocks)
                row["external_rag_retrieval"] = retrieval

            writing_tasks: List[dict] = [None] * len(final_subsections)  # type: ignore[list-item]
            for index, subsection in enumerate(final_subsections):
                row = allocated[index]
                if row.get("_retrieval_failed"):
                    writing_task, _ = _writing_task_unhandled_error_response(
                        subsection=subsection,
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        top_k=normalized_top_k,
                        message=row.get("_retrieval_error", "retrieval failed"),
                    )
                    writing_tasks[index] = writing_task
                    event_queue.put(_task_stream_event("task_failed", index, writing_task))
                    continue
                try:
                    writing_task, prompt_warnings = _build_writing_task_from_retrieval(
                        subsection=subsection,
                        graph_retrieval=row.get("graph_retrieval") or {},
                        external_rag_retrieval=row.get("external_rag_retrieval") or {},
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        warnings=warning_groups[index],
                        previous_tasks=writing_tasks[:index],
                        outline_ids={item["outline_id"] for item in final_subsections},
                    )
                    writing_tasks[index] = writing_task
                    event_name = "task_completed"
                except Exception as exc:
                    writing_task, prompt_warnings = _writing_task_unhandled_error_response(
                        subsection=subsection,
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        top_k=normalized_top_k,
                        message=f"coordinator task generation failed: {exc}",
                    )
                    writing_tasks[index] = writing_task
                    event_name = "task_failed"
                event = _task_stream_event(event_name, index, writing_task)
                event["references"] = copy.deepcopy(references)
                event_queue.put(event)

            event_queue.put({"event": "coordination_started", "status": "started"})
            writing_tasks, coordination, review_warnings = coordinate_writing_tasks(writing_tasks)
            final_outline, writing_tasks, adjustment_notes, adjustment_warnings = finalize_coordination_outline(
                outline, writing_tasks, coordination, normalized_prompt)
            warnings = ([warning for task in writing_tasks for warning in task.get("warnings", [])]
                        + review_warnings + adjustment_warnings)
            event_queue.put({"event": "coordination_completed", "coordination": coordination,
                             "warnings": review_warnings + adjustment_warnings})

            event_queue.put({
                "event": "completed",
                "status": "success",
                "industry": normalized_industry,
                "industry_name": industry_name,
                "use_graph": bool(use_graph),
                "use_external_rag": bool(use_external_rag),
                "user_prompt": normalized_prompt,
                "report_title": normalized_title,
                "writing_tasks": writing_tasks,
                "final_outline": final_outline,
                "adjustment_notes": adjustment_notes,
                "fallback_count": _fallback_count(writing_tasks),
                "coordination": coordination,
                "references": references,
                "warnings": warnings,
                "success_count": len([task for task in writing_tasks if isinstance(task, dict)]),
                "total": len(writing_tasks),
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


def _attach_outline_context(subsections: List[dict]) -> None:
    context = "\n".join(
        f"{row['outline_id']} | {row['parent_level1_title']} | {row['title']}"
        for row in subsections
    )
    for row in subsections:
        row["report_outline_context"] = context


def _fallback_count(tasks: list) -> int:
    return sum(task.get("writing_prompt_status") == "fallback"
               for task in tasks if isinstance(task, dict))


def _retrieve_candidates_for_subsection(
    subsection: dict,
    user_prompt: str,
    report_title: str,
    top_k: int,
    industry: str = "ai",
    use_graph: bool = True,
    use_external_rag: bool = True,
) -> tuple[dict, List[dict]]:
    """Retrieve graph context and unallocated external candidates for one section."""
    task_warnings: List[dict] = []
    warnings: List[dict] = []
    query = _build_subsection_retrieval_query(
        user_prompt=user_prompt,
        report_title=report_title,
        parent_level1_title=subsection["parent_level1_title"],
        subsection_title=subsection["title"],
        chapter_goal=subsection.get("chapter_goal", ""),
        content_requirements=subsection.get("content_requirements", []),
        writing_focus=subsection.get("writing_focus", ""),
        suggested_query=subsection.get("suggested_query", ""),
    )
    if industry and use_graph:
        graph_retrieval = _retrieve_graph_for_subsection(
            query=query, industry=industry, outline_id=subsection["outline_id"],
            warnings=warnings, task_warnings=task_warnings,
        )
    else:
        graph_retrieval = {"status": "skipped", "graph_evidence_blocks": [], "evidence_blocks": []}

    if industry and use_external_rag:
        candidate_top_k = max(top_k, min(top_k * 2, 20))
        external_rag_retrieval = _retrieve_external_rag_for_subsection(
            query=query, industry=industry, top_k=candidate_top_k,
            outline_id=subsection["outline_id"], warnings=warnings,
            task_warnings=task_warnings,
        )
        _expand_external_candidates_if_needed(
            external_rag_retrieval=external_rag_retrieval,
            query=query,
            subsection=subsection,
            industry=industry,
            candidate_top_k=candidate_top_k,
            warnings=warnings,
            task_warnings=task_warnings,
        )
    else:
        external_rag_retrieval = {"status": "skipped", "evidence_blocks": []}

    return (
        {
            "outline_id": subsection["outline_id"],
            "parent_level1_id": subsection["parent_level1_id"],
            "parent_level1_title": subsection["parent_level1_title"],
            "title": subsection["title"],
            "section_retrieval_query": query,
            "graph_retrieval": graph_retrieval,
            "external_rag_retrieval": external_rag_retrieval,
        },
        task_warnings,
    )


def _build_writing_task_from_retrieval(
    subsection: dict,
    graph_retrieval: dict,
    external_rag_retrieval: dict,
    user_prompt: str,
    report_title: str,
    warnings: List[dict],
    previous_tasks: list = None,
    outline_ids: set = None,
) -> tuple[dict, List[dict]]:
    """Generate a bounded writing decision from already allocated evidence."""
    task = {
        "outline_id": subsection["outline_id"],
        "parent_level1_id": subsection["parent_level1_id"],
        "parent_level1_title": subsection["parent_level1_title"],
        "title": subsection["title"],
        "section_retrieval_query": _build_subsection_retrieval_query(
            user_prompt=user_prompt, report_title=report_title,
            parent_level1_title=subsection["parent_level1_title"],
            subsection_title=subsection["title"],
            chapter_goal=subsection.get("chapter_goal", ""),
            content_requirements=subsection.get("content_requirements", []),
            writing_focus=subsection.get("writing_focus", ""),
            suggested_query=subsection.get("suggested_query", ""),
        ),
        "graph_retrieval": graph_retrieval,
        "external_rag_retrieval": external_rag_retrieval,
        "warnings": list(warnings or []),
    }
    result = request_decision(
        task=task, user_prompt=user_prompt, report_title=report_title,
        outline_context=subsection.get("report_outline_context", ""),
        previous_tasks=previous_tasks or [],
        outline_ids=outline_ids or {subsection["outline_id"]},
    )
    task["writing_decision"] = result["decision"]
    task["writing_prompt_status"] = result["status"]
    task["decision_review_status"] = "unchanged"
    task["writing_system_prompt"] = render_decision_prompt(result["decision"])
    task["warnings"].extend(result["warnings"])
    task["repetition_focus_terms"] = decision_topics(result["decision"])
    task["repetition_focus_terms"] = focus_terms_for_task(task)
    return task, task["warnings"]


def _allocate_retrieved_evidence(subsections: List[dict], retrieval_rows: List[dict], top_k: int) -> List[dict]:
    candidate_sections = []
    for subsection, row in zip(subsections, retrieval_rows):
        row = row if isinstance(row, dict) else {}
        retrieval = row.get("external_rag_retrieval") if isinstance(row.get("external_rag_retrieval"), dict) else {}
        candidate_sections.append({
            "outline_id": subsection.get("outline_id", ""),
            "candidates": retrieval.get("evidence_blocks") or [],
        })
    allocated = allocate_evidence_blocks(candidate_sections, target_per_section=top_k)
    output = []
    for subsection, row, allocation in zip(subsections, retrieval_rows, allocated):
        source = copy.deepcopy(row) if isinstance(row, dict) else {}
        retrieval = source.get("external_rag_retrieval")
        if not isinstance(retrieval, dict):
            retrieval = {"status": "skipped", "evidence_blocks": []}
        retrieval["evidence_blocks"] = allocation.get("evidence_blocks", [])
        diagnostics = dict(retrieval.get("diagnostics") or {})
        diagnostics.update(allocation.get("diagnostics", {}))
        retrieval["diagnostics"] = diagnostics
        source["external_rag_retrieval"] = retrieval
        source.setdefault("outline_id", subsection.get("outline_id", ""))
        output.append(source)
    return output


def _expand_external_candidates_if_needed(
    external_rag_retrieval: dict,
    query: str,
    subsection: dict,
    industry: str,
    candidate_top_k: int,
    warnings: List[dict],
    task_warnings: List[dict],
) -> None:
    blocks = external_rag_retrieval.get("evidence_blocks") or []
    distinct = {_candidate_material_key(block) for block in blocks if _candidate_material_key(block)}
    if len(distinct) >= 3:
        return
    focused_query = "\n".join([
        query,
        f"聚焦补充：仅补充{_safe_text(subsection.get('parent_level1_title'))} / {_safe_text(subsection.get('title'))}所需的不同资料来源。",
    ])
    retry_warnings: List[dict] = []
    retry_task_warnings: List[dict] = []
    try:
        retry = _retrieve_external_rag_for_subsection(
            query=focused_query,
            industry=industry,
            top_k=candidate_top_k,
            outline_id=subsection["outline_id"],
            warnings=retry_warnings,
            task_warnings=retry_task_warnings,
        )
    except Exception as exc:
        warning = {"outline_id": subsection["outline_id"], "stage": "external_rag_candidate_retry", "message": str(exc)}
        warnings.append(warning)
        task_warnings.append(warning)
        return
    warnings.extend(retry_warnings)
    task_warnings.extend(retry_task_warnings)
    if not isinstance(retry, dict):
        return
    if retry.get("status") != "success":
        if retry_warnings:
            return
        warning = {
            "outline_id": subsection["outline_id"],
            "stage": "external_rag_candidate_retry",
            "message": retry.get("message", "focused candidate retrieval failed"),
        }
        warnings.append(warning)
        task_warnings.append(warning)
        return
    retry_blocks = retry.get("evidence_blocks") or []
    seen_vectors = {_candidate_vector_key(block) for block in blocks if _candidate_vector_key(block)}
    seen_materials = {_candidate_material_key(block) for block in blocks if _candidate_material_key(block)}
    for block in retry_blocks:
        vector_key = _candidate_vector_key(block)
        material_key = _candidate_material_key(block)
        if vector_key and vector_key in seen_vectors:
            continue
        if not vector_key and material_key in seen_materials:
            continue
        blocks.append(copy.deepcopy(block))
        if vector_key:
            seen_vectors.add(vector_key)
        if material_key:
            seen_materials.add(material_key)
    external_rag_retrieval["evidence_blocks"] = blocks
    # The helper above already propagated retry warnings into both warning lists.
    # Do not re-emit ``retry["warnings"]`` here: backend stages may differ after
    # normalization and would otherwise produce duplicate entries.
    external_rag_retrieval["status"] = "success"
    for key in ("retrieval_version",):
        if retry.get(key):
            external_rag_retrieval[key] = retry[key]


def _candidate_material_key(block: Any) -> str:
    if not isinstance(block, dict):
        return ""
    library = _safe_text(block.get("library"))
    identity = _safe_text(block.get("material_id")) or _safe_text(block.get("vector_id"))
    return f"{library}:{identity}" if identity else ""


def _candidate_vector_key(block: Any) -> str:
    if not isinstance(block, dict):
        return ""
    return f"{_safe_text(block.get('library'))}:{_safe_text(block.get('vector_id'))}" if _safe_text(block.get("vector_id")) else ""


def _retrieval_unhandled_error_response(
    subsection: dict,
    user_prompt: str,
    report_title: str,
    top_k: int,
    message: str,
) -> tuple[dict, List[dict]]:
    query = _build_subsection_retrieval_query(
        user_prompt=user_prompt, report_title=report_title,
        parent_level1_title=_safe_text(subsection.get("parent_level1_title")),
        subsection_title=_safe_text(subsection.get("title")),
        chapter_goal=subsection.get("chapter_goal", ""),
        content_requirements=subsection.get("content_requirements", []),
        writing_focus=subsection.get("writing_focus", ""),
        suggested_query=subsection.get("suggested_query", ""),
    )
    warning = {"outline_id": _safe_text(subsection.get("outline_id")), "stage": "coordinator_task_generation", "message": message}
    return ({
        "outline_id": _safe_text(subsection.get("outline_id")),
        "parent_level1_id": _safe_text(subsection.get("parent_level1_id")),
        "parent_level1_title": _safe_text(subsection.get("parent_level1_title")),
        "title": _safe_text(subsection.get("title")),
        "section_retrieval_query": query,
        "graph_retrieval": _graph_error_response(query=query, message=message),
        "external_rag_retrieval": _external_error_response(query=query, top_k=top_k, message=message),
        "_retrieval_failed": True,
        "_retrieval_error": message,
    }, [warning])


def _generate_writing_task_for_subsection(
    subsection: dict,
    user_prompt: str,
    report_title: str,
    top_k: int,
    industry: str = "ai",
    use_graph: bool = True,
    use_external_rag: bool = True,
) -> tuple[dict, List[dict]]:
    """Backward-compatible worker name that now performs retrieval only."""
    return _retrieve_candidates_for_subsection(
        subsection=subsection,
        user_prompt=user_prompt,
        report_title=report_title,
        top_k=top_k,
        industry=industry,
        use_graph=use_graph,
        use_external_rag=use_external_rag,
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
        chapter_goal=subsection.get("chapter_goal", ""),
        content_requirements=subsection.get("content_requirements", []),
        writing_focus=subsection.get("writing_focus", ""),
        suggested_query=subsection.get("suggested_query", ""),
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
        "writing_prompt_status": "fallback",
        "warnings": [warning],
    }
    task["writing_decision"] = fallback_decision(task)
    task["writing_system_prompt"] = render_decision_prompt(task["writing_decision"])
    task["decision_review_status"] = "unchanged"
    task["repetition_focus_terms"] = focus_terms_for_task(task)
    return task, [warning]


def _subsection_stream_event(event_name: str, index: int, subsection: dict) -> dict:
    return {
        "event": event_name,
        "index": index,
        "status": "started",
        "outline_id": _safe_text(subsection.get("outline_id")),
        "parent_level1_id": _safe_text(subsection.get("parent_level1_id")),
        "parent_level1_title": _safe_text(subsection.get("parent_level1_title")),
        "title": _safe_text(subsection.get("title")),
    }


def _task_stream_event(event_name: str, index: int, task: dict) -> dict:
    payload = dict(task if isinstance(task, dict) else {})
    payload.update({
        "event": event_name,
        "index": index,
        "status": "success" if event_name == "task_completed" else "error",
        "outline_id": _safe_text(payload.get("outline_id")),
        "parent_level1_title": _safe_text(payload.get("parent_level1_title")),
        "title": _safe_text(payload.get("title")),
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
        chapter_goal = _safe_text(section.get("chapter_goal"))
        content_requirements = _safe_text_list(section.get("content_requirements"))

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
                    "chapter_goal": chapter_goal,
                    "content_requirements": content_requirements,
                    "writing_focus": _safe_text(subsection.get("writing_focus")),
                    "suggested_query": _safe_text(subsection.get("suggested_query")),
                }
            )
    return flat


def _build_subsection_retrieval_query(
    user_prompt: str,
    report_title: str,
    parent_level1_title: str,
    subsection_title: str,
    chapter_goal: Any = "",
    content_requirements: Any = None,
    writing_focus: Any = "",
    suggested_query: Any = "",
) -> str:
    '''把一个二级标题的写作任务信息，整理成一段给图谱检索和外部 RAG 检索使用的 query 字符串'''
    '''
    生成example
    用户需求：分析人工智能产业
    报告标题：人工智能产业报告
    当前一级标题：应用落地
    章节目标：回答应用落地路径
    内容边界：企业案例；政策建议
    当前二级标题：标杆案例与推进建议
    二级写作重点：结合项目落地提出实践路径
    建议检索 query：人工智能 企业案例 项目落地 政策建议
    检索目标：为当前二级标题生成正文写作要求，检索政策建议、实践路径、推进措施、标杆经验和
    可操作对策。 检索企业案例、项目落地、应用场景、标杆实践和商业化进展。
    '''
    requirement_text = "；".join(_safe_text_list(content_requirements))
    lines = [
        f"用户需求：{_safe_text(user_prompt)}",
        f"报告标题：{_safe_text(report_title)}",
        f"当前一级标题：{_safe_text(parent_level1_title)}",
    ]
    if _safe_text(chapter_goal):
        lines.append(f"章节目标：{_safe_text(chapter_goal)}")
    if requirement_text:
        lines.append(f"内容边界：{requirement_text}")
    lines.append(f"当前二级标题：{_safe_text(subsection_title)}")
    if _safe_text(writing_focus):
        lines.append(f"二级写作重点：{_safe_text(writing_focus)}")
    if _safe_text(suggested_query):
        lines.append(f"建议检索 query：{_safe_text(suggested_query)}")
    lines.append(
        "检索目标：为当前二级标题生成正文写作要求，"
        + _subsection_retrieval_goal(
            subsection_title=subsection_title,
            writing_focus=writing_focus,
            suggested_query=suggested_query,
        )
    )
    return "\n".join(lines)


def _subsection_retrieval_goal(subsection_title: Any, writing_focus: Any = "", suggested_query: Any = "") -> str:
    '''
    **根据小节标题、写作侧重点、推荐查询词，自动判断这一小节需要检索什么信息，
    生成检索目标描述字符串**，用于给检索模块（向量库 / 搜索引擎）明确该段落要查找哪类资料。
    '''
    text = " ".join(
        item for item in (
            _safe_text(subsection_title),
            _safe_text(writing_focus),
            _safe_text(suggested_query),
        ) if item
    )
    matched_goals: List[str] = []
    for keywords, goal in (
        (("现状", "当前", "格局", "规模", "布局", "发展基础", "产业链"), "检索市场规模、产业链结构、上下游关系、核心企业布局和阶段性发展特征。"),
        (("问题", "瓶颈", "挑战", "风险", "短板", "制约", "约束", "不足", "困难"), "检索产业瓶颈、风险挑战、能力短板、资源约束和落地障碍。"),
        (("趋势", "演进", "展望", "预测", "方向", "前景", "未来"), "检索技术演进、政策趋势、市场预测、产业发展方向和长期影响。"),
        (("建议", "对策", "路径", "策略", "措施", "启示", "推进", "优化"), "检索政策建议、实践路径、推进措施、标杆经验和可操作对策。"),
        (("案例", "实践", "落地", "应用", "场景", "项目", "标杆", "企业案例"), "检索企业案例、项目落地、应用场景、标杆实践和商业化进展。"),
    ):
        if any(keyword in text for keyword in keywords):
            matched_goals.append(goal)

    if not matched_goals:
        matched_goals.append("检索相关产业链结构、央企布局、竞争格局、问题、政策、案例和建议依据。")
    return " ".join(dict.fromkeys(matched_goals))


def _retrieve_graph_for_subsection(
    query: str,
    outline_id: str,
    warnings: List[dict],
    task_warnings: List[dict],
    industry: str = "ai",
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
    normalized["matched_segments"] = normalized.get("matched_segments") or []
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
    top_k: int,
    outline_id: str,
    warnings: List[dict],
    task_warnings: List[dict],
    industry: str = "ai",
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


def _normalize_max_workers(max_workers: Any, task_count: int) -> int:
    try:
        value = int(max_workers)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_COORDINATOR_WORKERS
    if value <= 0:
        value = DEFAULT_MAX_COORDINATOR_WORKERS
    value = min(value, MAX_COORDINATOR_WORKERS_LIMIT)
    return min(value, max(1, task_count))


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_text_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [_safe_text(item) for item in value if _safe_text(item)]
    text = _safe_text(value)
    return [text] if text else []


def _graph_error_response(query: str, message: str) -> dict:
    return {
        "status": "error",
        "query": query,
        "message": message,
        "graph_context_text": "",
        "matched_segments": [],
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

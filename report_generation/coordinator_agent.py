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
from .graph_retriever import retrieve_industry_graph
from .industry_config import SUPPORTED_INDUSTRIES


DEFAULT_TOP_K = 10
DEFAULT_MAX_COORDINATOR_WORKERS = 3
MAX_COORDINATOR_WORKERS_LIMIT = 6


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
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {}
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
            future = executor.submit(
                _build_writing_task_from_retrieval,
                subsection=subsection,
                graph_retrieval=row.get("graph_retrieval") or {},
                external_rag_retrieval=row.get("external_rag_retrieval") or {},
                user_prompt=normalized_prompt,
                report_title=normalized_title,
                warnings=warning_groups[index],
            )
            future_to_index[future] = index

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            subsection = final_subsections[index]
            try:
                writing_tasks[index], prompt_warnings = future.result()
            except Exception as exc:
                writing_tasks[index], prompt_warnings = _writing_task_unhandled_error_response(
                    subsection=subsection,
                    user_prompt=normalized_prompt,
                    report_title=normalized_title,
                    top_k=normalized_top_k,
                    message=f"coordinator task generation failed: {exc}",
                )
                warning_groups[index].extend(prompt_warnings)

    warnings = [warning for group in warning_groups for warning in group]

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
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_to_index = {}
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
                    future = executor.submit(
                        _build_writing_task_from_retrieval,
                        subsection=subsection,
                        graph_retrieval=row.get("graph_retrieval") or {},
                        external_rag_retrieval=row.get("external_rag_retrieval") or {},
                        user_prompt=normalized_prompt,
                        report_title=normalized_title,
                        warnings=warning_groups[index],
                    )
                    future_to_index[future] = index

                for future in as_completed(future_to_index):
                    index = future_to_index[future]
                    subsection = final_subsections[index]
                    try:
                        writing_task, prompt_warnings = future.result()
                        event_name = "task_completed"
                    except Exception as exc:
                        writing_task, prompt_warnings = _writing_task_unhandled_error_response(
                            subsection=subsection,
                            user_prompt=normalized_prompt,
                            report_title=normalized_title,
                            top_k=normalized_top_k,
                            message=f"coordinator task generation failed: {exc}",
                        )
                        warning_groups[index].extend(prompt_warnings)
                        event_name = "task_failed"
                    writing_tasks[index] = writing_task
                    event = _task_stream_event(event_name, index, writing_task)
                    event["references"] = copy.deepcopy(references)
                    event_queue.put(event)

            warnings = [warning for group in warning_groups for warning in group]

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
) -> tuple[dict, List[dict]]:
    """Generate one writing task from retrieval already allocated at report level."""
    task_warnings: List[dict] = list(warnings or [])
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
            user_prompt=user_prompt, report_title=report_title,
            parent_level1_title=subsection["parent_level1_title"],
            subsection_title=subsection["title"],
        )
    return ({
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
        "writing_system_prompt": writing_system_prompt,
        "warnings": task_warnings,
    }, task_warnings)


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
        retrieval["diagnostics"] = allocation.get("diagnostics", {})
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
        "writing_system_prompt": _fallback_writing_system_prompt(
            user_prompt=user_prompt,
            report_title=report_title,
            parent_level1_title=_safe_text(subsection.get("parent_level1_title")),
            subsection_title=_safe_text(subsection.get("title")),
        ),
        "warnings": [warning],
    }
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
writing_system_prompt 必须要求正文生成智能体使用外部资料上下文中真实存在的 [C数字] 引用编号，不得把知识图谱编号当作文章来源。"""

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
10. 不得把 [知识图谱1] 等知识图谱编号当作文章来源。
11. 正文使用外部资料中的数字、政策、领导讲话、专家观点或企业案例时，必须在对应句末使用上下文中真实存在的 [C数字]。
12. 不得编造 [C数字]、资料标题或网址；正文不输出独立参考文献列表，参考资料由系统生成。
13. 正文不得生成摘要、标题页、目录、Word 导出说明或其他无关内容。

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
不得把 [知识图谱1] 等知识图谱编号当作文章来源。
使用外部资料中的数字、政策、领导讲话、专家观点或企业案例时，必须使用上下文中真实存在的 [C数字]。
不得编造 [C数字]、资料标题或网址；正文不输出独立参考文献列表，参考资料由系统生成。
不得生成摘要、标题页、目录、Word 导出说明或其他无关内容。""")


def _ensure_writing_prompt_constraints(prompt: str) -> str:
    text = _safe_text(prompt)
    hard_rules = [
        "不得把 [知识图谱1] 等知识图谱编号当作文章来源。",
        "使用外部资料中的数字、政策、领导讲话、专家观点或企业案例时，必须使用上下文中真实存在的 [C数字]。",
        "不得编造 [C数字]、资料标题或网址；正文不输出独立参考文献列表，参考资料由系统生成。",
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

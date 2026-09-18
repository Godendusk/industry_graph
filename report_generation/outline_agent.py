"""Outline generation agent for industry reports."""

from __future__ import annotations

import copy
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_client import llm

from .external_rag.retriever import retrieve_external_rag
from .graph_retriever import retrieve_industry_graph
from .industry_config import INDUSTRY_CONFIG


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "产业链报告模板.docx"
BODY_SECTION_MIN = 3
BODY_SECTION_MAX = 6
BODY_SUBSECTION_MIN = 2
BODY_SUBSECTION_MAX = 4


def generate_report_outline(
    title: str,
    user_requirement: str = "",
    industry: str = "",
    industry_confirmed: bool = False,
) -> dict:
    """Generate a report outline directly from the confirmed task card."""
    report_title = str(title or "").strip()
    normalized_requirement = str(user_requirement or "").strip()
    resolved_industry = str(industry or "").strip()
    if not report_title:
        return _error_response("title cannot be empty", "", "")
    if not normalized_requirement:
        return _error_response("user_requirement cannot be empty", resolved_industry, "")
    if not industry_confirmed:
        return _error_response("confirmed task_card is required", resolved_industry, "")
    if resolved_industry and resolved_industry not in INDUSTRY_CONFIG:
        return _error_response(f"unsupported confirmed industry: {resolved_industry}", resolved_industry, "")

    resolved_industry_name = _industry_name(resolved_industry)
    effective_prompt = normalized_requirement or report_title
    direct_result = _generate_direct_outline(
        report_title=report_title,
        user_requirement=effective_prompt,
        industry=resolved_industry,
        industry_name=resolved_industry_name,
    )
    if direct_result.get("status") != "success":
        return direct_result

    warnings: List[dict] = direct_result.get("warnings") or []
    outline: List[dict] = []

    for index, section in enumerate(direct_result.get("chapters") or [], 1):
        level1_id = f"S{index}"
        level1_title = str(section.get("title") or "").strip()
        chapter_goal = str(section.get("chapter_goal") or "").strip()
        content_requirements = section.get("content_requirements") or []
        template_requirement = _format_direct_requirement(
            chapter_goal,
            content_requirements,
        )
        section_warnings: List[dict] = []
        section_retrieval_query = _build_section_retrieval_query(
            user_prompt=effective_prompt,
            industry_name=resolved_industry_name,
            report_title=report_title,
            level1_title=level1_title,
            template_requirement=template_requirement,
        )
        subsections = _normalize_subsections(
            raw_subsections=section.get("subsections") or [],
            level1_id=level1_id,
            warnings=warnings,
            section_warnings=section_warnings,
        )
        outline.append(
            {
                "level1_id": level1_id,
                "level1_title": level1_title,
                "section_type": "body",
                "template_requirement": template_requirement,
                "chapter_goal": chapter_goal,
                "content_requirements": content_requirements,
                "section_retrieval_query": section_retrieval_query,
                "graph_retrieval": {"status": "skipped", "graph_evidence_blocks": []},
                "external_rag_retrieval": {"status": "skipped", "evidence_blocks": []},
                "subsections": subsections,
                "warnings": section_warnings,
            }
        )

    return {
        "status": "success",
        "industry": resolved_industry,
        "industry_name": resolved_industry_name,
        "resolved_industry": resolved_industry,
        "resolved_industry_name": resolved_industry_name,
        "user_requirement": normalized_requirement,
        "effective_user_prompt": effective_prompt,
        "report_title": report_title,
        "outline": outline,
        "flat_subsections": _build_flat_subsections(outline),
        "warnings": warnings,
    }


def _generate_direct_outline(
    report_title: str,
    user_requirement: str,
    industry: str,
    industry_name: str,
) -> dict:
    system_prompt = f"""你是企业产业洞察报告大纲生成智能体。
你只根据已经人工确认的任务卡生成报告大纲，不再重新理解任务、改写标题或改换产业方向。
必须严格继承任务卡中的研究边界；用户明确排除、不得、不包含、不分析的方向，不得进入一级或二级标题。
生成 {BODY_SECTION_MIN} 到 {BODY_SECTION_MAX} 个一级章节，每个一级章节生成 {BODY_SUBSECTION_MIN} 到 {BODY_SUBSECTION_MAX} 个二级标题。
不要生成正文，不要输出 Markdown 或解释说明。
只输出一个 JSON 对象。"""

    user_prompt_text = f"""请根据以下已确认任务卡生成完整报告大纲。

【最终报告标题】
{report_title}

【最终报告需求】
{user_requirement}

【最终产业方向】
{industry_name or '不使用特定产业图谱'}（系统产业键：{industry or '无'}）

【输出要求】
1. 一级章节必须服务于最终报告标题和最终报告需求。
2. 二级标题必须落在所属一级章节范围内，互不重复，且适合后续检索和正文写作。
3. chapter_goal 说明该一级章节要回答的问题。
4. content_requirements 给出该一级章节的内容边界。
5. writing_focus 说明该二级小节后续正文重点。
6. suggested_query 应适合后续统筹智能体或正文生成智能体再次检索。

【输出格式】
{{
  "chapters": [
    {{
      "level1_title": "一级章节标题",
      "chapter_goal": "本章要回答的问题",
      "content_requirements": ["内容要求"],
      "subsections": [
        {{
          "title": "二级标题",
          "writing_focus": "写作重点",
          "suggested_query": "后续检索 query"
        }}
      ]
    }}
  ]
}}
"""
    try:
        content = llm.query(
            user_prompt=user_prompt_text,
            system_prompt=system_prompt,
            max_tokens=5000,
            extra_log_info=f"report_generation.outline_agent direct_outline industry={industry or 'none'}",
        )
    except Exception as exc:
        return _error_response(f"direct outline LLM call failed: {exc}", industry, industry_name)

    if not content:
        return _error_response("direct outline LLM returned empty output", industry, industry_name)

    try:
        data = _parse_json_object(content)
    except ValueError as exc:
        result = _error_response(f"direct outline JSON parse failed: {exc}", industry, industry_name)
        result["raw_output"] = content
        return result

    try:
        chapters, warnings = _normalize_direct_chapters(data.get("chapters"))
    except ValueError as exc:
        result = _error_response(str(exc), industry, industry_name)
        result["raw_output"] = content
        return result
    return {"status": "success", "chapters": chapters, "warnings": warnings}


def _normalize_direct_chapters(value: Any) -> tuple[List[dict], List[dict]]:
    if not isinstance(value, list):
        raise ValueError("direct outline JSON missing chapters array")

    chapters: List[dict] = []
    warnings: List[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("level1_title") or item.get("title") or "").strip()
        if not title:
            continue
        chapters.append(
            {
                "title": title,
                "chapter_goal": str(item.get("chapter_goal") or "").strip(),
                "content_requirements": _clean_string_list(item.get("content_requirements")),
                "subsections": item.get("subsections") or [],
            }
        )

    if len(chapters) > BODY_SECTION_MAX:
        warnings.append({
            "stage": "outline_validation",
            "message": f"chapter count {len(chapters)} exceeds {BODY_SECTION_MAX}; truncated",
        })
        chapters = chapters[:BODY_SECTION_MAX]
    if len(chapters) < BODY_SECTION_MIN:
        raise ValueError(f"chapter count {len(chapters)} is less than {BODY_SECTION_MIN}")
    return chapters, warnings


def _clean_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _format_direct_requirement(
    chapter_goal: str,
    content_requirements: List[str],
) -> str:
    parts = []
    if chapter_goal:
        parts.append(f"章节目标：{chapter_goal}")
    if content_requirements:
        parts.append("内容要求：" + "；".join(content_requirements))
    return "\n".join(parts)


def _industry_name(industry: str) -> str:
    return str((INDUSTRY_CONFIG.get(industry) or {}).get("name") or "").strip()


def _parse_template(path: Path) -> dict:
    """解析 Word 模板中的标题、摘要要求和一级正文章节。"""
    if not path.exists():
        raise FileNotFoundError(str(path))

    paragraphs = _read_docx_paragraphs(path)
    title_requirement = ""
    abstract_requirement = ""
    body_sections: List[dict] = []

    for index, paragraph in enumerate(paragraphs):
        heading_type = _heading_type(paragraph)
        if not heading_type:
            continue

        requirement = _find_requirement_after(paragraphs, index)
        if heading_type == "title":
            title_requirement = requirement
        elif heading_type == "abstract":
            abstract_requirement = requirement
        elif heading_type == "body":
            body_sections.append({"title": paragraph, "requirement": requirement})

    if not title_requirement:
        raise ValueError("template missing title requirement")
    if not body_sections:
        raise ValueError("template missing body sections")

    return {
        "title_requirement": title_requirement,
        "abstract_requirement": abstract_requirement,
        "body_sections": body_sections,
    }


def _read_docx_paragraphs(path: Path) -> List[str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as docx:
        root = ET.fromstring(docx.read("word/document.xml"))

    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(
            node.text or ""
            for node in paragraph.findall(".//w:t", namespace)
        ).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _heading_type(text: str) -> Optional[str]:
    normalized = text.strip()
    if normalized.startswith("标题"):
        return "title"
    if normalized.startswith("摘要"):
        return "abstract"
    body_markers = (
        "产业链发展总体态势",
        "产业链布局现状分析",
        "产业链发展面临的突出问题",
        "产业链发展的对策建议",
    )
    if any(marker in normalized for marker in body_markers):
        return "body"
    return None


def _find_requirement_after(paragraphs: List[str], heading_index: int) -> str:
    for paragraph in paragraphs[heading_index + 1:]:
        if _heading_type(paragraph):
            break
        if paragraph.startswith("要求：") or paragraph.startswith("要求:"):
            return re.sub(r"^要求[:：]\s*", "", paragraph).strip()
    return ""


def _generate_report_title(user_prompt: str, industry_name: str, title_requirement: str) -> dict:
    system_prompt = """你是产业报告标题生成智能体。
你只负责生成报告标题，不判断产业名称。
生成的报告标题要优先与用户原始需求和固定产业名称高度相关，突出重点。
生成的报告标题字数不能超过 20 个汉字。
必须只输出 JSON 对象，不要输出 Markdown、代码块或解释说明。
JSON 只能包含 report_title 字段。
标题必须围绕系统提供的固定产业名称，不能改写为其他产业。"""
    user_prompt_text = f"""请根据以下信息生成产业报告标题。

【固定产业名称】
{industry_name}

【用户原始需求】
{user_prompt}

【甲方模板标题要求】
{title_requirement}

【输出格式】
{{"report_title": "标题文本"}}
"""
    try:
        content = llm.query(
            user_prompt=user_prompt_text,
            system_prompt=system_prompt,
            max_tokens=5000,
            extra_log_info=f"report_generation.outline_agent title industry={industry_name}",
        )
    except Exception as exc:
        return {"status": "error", "message": f"title LLM call failed: {exc}"}

    if not content:
        return {"status": "error", "message": "title LLM returned empty output"}

    try:
        data = _parse_json_object(content)
    except ValueError as exc:
        return {
            "status": "error",
            "message": f"title JSON parse failed: {exc}",
            "raw_output": content,
        }

    report_title = str(data.get("report_title") or "").strip()
    if not report_title:
        return {
            "status": "error",
            "message": "title JSON missing report_title",
            "raw_output": content,
        }
    return {"status": "success", "report_title": report_title}


def _build_section_retrieval_query(
    user_prompt: str,
    industry_name: str,
    report_title: str,
    level1_title: str,
    template_requirement: str,
) -> str:
    # 检索问题同时带上报告主题和当前章节要求，减少跨章节资料干扰。
    return "\n".join(
        [
            f"用户需求：{user_prompt}",
            f"报告标题：{report_title}",
            f"产业领域：{industry_name}",
            f"当前一级大纲：{level1_title}",
            f"当前一级大纲要求：{template_requirement}",
            "检索目标：为当前一级大纲生成二级大纲，检索相关的产业链结构、竞争格局、央企布局、突出问题、政策趋势、企业案例和对策依据。",
        ]
    )


def _retrieve_graph_for_section(
    query: str,
    level1_id: str,
    warnings: List[dict],
    section_warnings: List[dict],
    industry: str = "ai",
) -> dict:
    try:
        result = retrieve_industry_graph(query, industry=industry)
    except Exception as exc:
        warning = {
            "level1_id": level1_id,
            "stage": "graph_retrieval",
            "message": str(exc),
        }
        warnings.append(warning)
        section_warnings.append(warning)
        return {"status": "error", "message": str(exc), "graph_evidence_blocks": []}

    normalized = copy.deepcopy(result) if isinstance(result, dict) else {"status": "error"}
    normalized["graph_evidence_blocks"] = _normalize_graph_evidence_blocks(
        normalized.get("evidence_blocks") or []
    )
    if normalized.get("status") != "success":
        warning = {
            "level1_id": level1_id,
            "stage": "graph_retrieval",
            "message": normalized.get("message", "graph retrieval failed"),
        }
        warnings.append(warning)
        section_warnings.append(warning)
    return normalized


def _retrieve_external_rag_for_section(
    query: str,
    level1_id: str,
    warnings: List[dict],
    section_warnings: List[dict],
    industry: str = "ai",
) -> dict:
    try:
        result = retrieve_external_rag(query, industry=industry, top_k=10)
    except Exception as exc:
        warning = {
            "level1_id": level1_id,
            "stage": "external_rag_retrieval",
            "message": str(exc),
        }
        warnings.append(warning)
        section_warnings.append(warning)
        return {"status": "error", "message": str(exc), "evidence_blocks": []}

    normalized = copy.deepcopy(result) if isinstance(result, dict) else {"status": "error"}
    if normalized.get("status") != "success":
        warning = {
            "level1_id": level1_id,
            "stage": "external_rag_retrieval",
            "message": normalized.get("message", "external RAG retrieval failed"),
        }
        warnings.append(warning)
        section_warnings.append(warning)
    for item in normalized.get("warnings") or []:
        warning = {
            "level1_id": level1_id,
            "stage": "external_rag_retrieval",
            "message": item.get("message", str(item)) if isinstance(item, dict) else item,
        }
        warnings.append(warning)
        section_warnings.append(warning)
    return normalized


def _normalize_graph_evidence_blocks(evidence_blocks: List[dict]) -> List[dict]:
    normalized = []
    for index, block in enumerate(evidence_blocks, 1):
        normalized.append(
            {
                "citation_id": f"知识图谱{index}",
                "rank": index,
                "source_type": "knowledge_graph",
                "level3": block.get("level3"),
                "chain_path": block.get("chain_path", ""),
                "upward_path": block.get("upward_path", []),
                "downward_entities": block.get("downward_entities", []),
                "context_text": block.get("context_text", ""),
            }
        )
    return normalized


def _normalize_subsections(
    raw_subsections: List[Any],
    level1_id: str,
    warnings: List[dict],
    section_warnings: List[dict],
) -> List[dict]:
    # 统一清洗 LLM 输出，并限制每个一级章节下的二级标题数量。
    subsections = []
    for item in raw_subsections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        writing_focus = str(item.get("writing_focus") or "").strip()
        suggested_query = str(item.get("suggested_query") or "").strip()
        if not title:
            continue
        subsections.append(
            {
                "title": title,
                "writing_focus": writing_focus,
                "suggested_query": suggested_query,
                "generation_instruction": writing_focus,
            }
        )

    if len(subsections) > BODY_SUBSECTION_MAX:
        warning = {
            "level1_id": level1_id,
            "stage": "subsection_validation",
            "message": f"subsection count {len(subsections)} exceeds {BODY_SUBSECTION_MAX}; truncated",
        }
        warnings.append(warning)
        section_warnings.append(warning)
        subsections = subsections[:BODY_SUBSECTION_MAX]

    if len(subsections) < BODY_SUBSECTION_MIN:
        warning = {
            "level1_id": level1_id,
            "stage": "subsection_validation",
            "message": f"subsection count {len(subsections)} is less than {BODY_SUBSECTION_MIN}",
        }
        warnings.append(warning)
        section_warnings.append(warning)

    for index, subsection in enumerate(subsections, 1):
        subsection["outline_id"] = f"{level1_id}.{index}"
    return subsections


def _build_flat_subsections(outline: List[dict]) -> List[dict]:
    flat = []
    for section in outline:
        if section.get("section_type") != "body":
            continue
        for subsection in section.get("subsections") or []:
            item = dict(subsection)
            item["parent_level1_id"] = section.get("level1_id", "")
            item["parent_level1_title"] = section.get("level1_title", "")
            flat.append(item)
    return flat


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


def _replace_industry_placeholder(text: str, industry_name: str) -> str:
    return str(text or "").replace("×××", industry_name).strip()


def _error_response(message: str, industry: str, industry_name: str) -> dict:
    return {
        "status": "error",
        "industry": industry,
        "industry_name": industry_name,
        "message": message,
        "outline": [],
        "flat_subsections": [],
        "warnings": [],
    }

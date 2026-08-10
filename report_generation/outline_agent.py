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
from .intent_agent import parse_report_intent
from .planner_agent import plan_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "产业链报告模板.docx"
BODY_SUBSECTION_MIN = 2
BODY_SUBSECTION_MAX = 4


def generate_report_outline(
    title: str,
    user_requirement: str = "",
    industry: str = "",
) -> dict:
    """按 Intent → Planner → Outline 流程生成报告大纲。"""
    report_title = str(title or "").strip()
    normalized_requirement = str(user_requirement or "").strip()
    if not report_title:
        return _error_response("title cannot be empty", "", "")

    # Intent 必须忠实保留标题；页面当前行业只作上下文，不覆盖标题识别结果。
    intent_result = parse_report_intent(report_title, normalized_requirement)
    if intent_result.get("status") != "success":
        return intent_result
    intent = intent_result["intent"]
    resolved_industry = intent_result.get("resolved_industry", "")
    resolved_industry_name = intent_result.get("resolved_industry_name", "")

    # Planner 只消费已经校验的 Intent，不直接重新理解标题。
    planner_result = plan_report(intent, resolved_industry=resolved_industry)
    if planner_result.get("status") != "success":
        planner_result["intent"] = intent
        return planner_result
    planner = planner_result["planner"]

    effective_prompt = normalized_requirement or report_title
    warnings: List[dict] = []
    warnings.extend(intent_result.get("warnings") or [])
    warnings.extend(planner_result.get("warnings") or [])
    outline: List[dict] = []

    # Planner 的章节直接成为一级章节，不再套用 Word 固定一级章节模板。
    for index, section in enumerate(planner.get("chapters") or [], 1):
        level1_id = f"S{index}"
        level1_title = str(section.get("title") or "").strip()
        research_question = str(section.get("research_question") or "").strip()
        content_requirements = section.get("content_requirements") or []
        evidence_requirements = section.get("evidence_requirements") or []
        template_requirement = _format_planner_requirement(
            research_question,
            content_requirements,
            evidence_requirements,
        )
        section_warnings: List[dict] = []
        section_retrieval_query = _build_section_retrieval_query(
            user_prompt=effective_prompt,
            industry_name=intent.get("industry", ""),
            report_title=report_title,
            level1_title=level1_title,
            template_requirement=template_requirement,
        )

        # 产业图谱和外部 RAG 都是可选证据源，不可用时不能阻断大纲。
        if (
            planner.get("need_industry_graph")
            and planner.get("industry_graph_available")
            and resolved_industry
        ):
            graph_retrieval = _retrieve_graph_for_section(
                query=section_retrieval_query,
                industry=resolved_industry,
                level1_id=level1_id,
                warnings=warnings,
                section_warnings=section_warnings,
            )
        else:
            graph_retrieval = {"status": "skipped", "graph_evidence_blocks": []}

        if resolved_industry:
            external_rag_retrieval = _retrieve_external_rag_for_section(
                query=section_retrieval_query,
                industry=resolved_industry,
                level1_id=level1_id,
                warnings=warnings,
                section_warnings=section_warnings,
            )
        else:
            external_rag_retrieval = {"status": "skipped", "evidence_blocks": []}

        # 二级标题必须严格围绕 Planner 为当前章定义的问题和证据要求。
        subsection_result = _generate_section_subsections(
            user_prompt=effective_prompt,
            industry_name=intent.get("industry", ""),
            report_title=report_title,
            level1_title=level1_title,
            template_requirement=template_requirement,
            research_question=research_question,
            content_requirements=content_requirements,
            evidence_requirements=evidence_requirements,
            graph_context_text=graph_retrieval.get("graph_context_text", ""),
            rag_context_text=external_rag_retrieval.get("rag_context_text", ""),
        )
        raw_subsections = []
        if subsection_result["status"] == "success":
            raw_subsections = subsection_result["subsections"]
        else:
            warning = {
                "level1_id": level1_id,
                "stage": "subsection_generation",
                "message": subsection_result.get("message", "failed to generate subsections"),
            }
            if subsection_result.get("raw_output"):
                warning["raw_output"] = subsection_result["raw_output"]
            warnings.append(warning)
            section_warnings.append(warning)

        subsections = _normalize_subsections(
            raw_subsections=raw_subsections,
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
                "research_question": research_question,
                "content_requirements": content_requirements,
                "evidence_requirements": evidence_requirements,
                "section_retrieval_query": section_retrieval_query,
                "graph_retrieval": graph_retrieval,
                "external_rag_retrieval": external_rag_retrieval,
                "subsections": subsections,
                "warnings": section_warnings,
            }
        )

    return {
        "status": "success",
        "industry": resolved_industry,
        "industry_name": resolved_industry_name or intent.get("industry", ""),
        "resolved_industry": resolved_industry,
        "resolved_industry_name": resolved_industry_name,
        "user_requirement": normalized_requirement,
        "effective_user_prompt": effective_prompt,
        "report_title": report_title,
        "intent": intent,
        "planner": planner,
        "outline": outline,
        "flat_subsections": _build_flat_subsections(outline),
        "warnings": warnings,
    }


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
    industry: str,
    level1_id: str,
    warnings: List[dict],
    section_warnings: List[dict],
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
    industry: str,
    level1_id: str,
    warnings: List[dict],
    section_warnings: List[dict],
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


def _generate_section_subsections(
    user_prompt: str,
    industry_name: str,
    report_title: str,
    level1_title: str,
    template_requirement: str,
    research_question: str,
    content_requirements: List[str],
    evidence_requirements: List[str],
    graph_context_text: str,
    rag_context_text: str,
) -> dict:
    system_prompt = f"""你是产业报告二级大纲生成智能体。
你只负责为当前一级大纲生成二级标题，不要生成其他一级大纲。
当前版本固定产业为“{industry_name}”，不要判断或改写产业名称。
必须生成 {BODY_SUBSECTION_MIN} 到 {BODY_SUBSECTION_MAX} 个二级标题。
不要生成正文，不要写段落。
必须只输出 JSON 对象，不要输出 Markdown、代码块或解释说明。
JSON 必须包含 subsections 数组。
每个 subsections 项必须包含 title、writing_focus、suggested_query。"""

    user_prompt_text = f"""请根据以下信息，为当前一级大纲生成二级标题。

【用户原始需求】
{user_prompt}

【报告标题】
{report_title}

【固定产业名称】
{industry_name}

【当前一级大纲】
{level1_title}

【当前一级大纲要求】
{template_requirement}

【本章必须回答的研究问题】
{research_question}

【Planner 内容要求】
{json.dumps(content_requirements, ensure_ascii=False)}

【Planner 证据要求】
{json.dumps(evidence_requirements, ensure_ascii=False)}

【当前一级大纲的知识图谱检索结果】
{graph_context_text or "未检索到可用知识图谱上下文。"}

【当前一级大纲的外部资料库检索结果】
{rag_context_text or "未检索到可用外部资料库上下文。"}

【生成要求】
1. 只生成当前一级大纲下的二级标题。
2. 二级标题数量必须为 {BODY_SUBSECTION_MIN} 到 {BODY_SUBSECTION_MAX} 个。
3. 二级标题之间应互不重复，覆盖当前一级大纲要求中的关键分析角度。
4. 所生成的二级标题一定要与用户原始需求高度相关。
5. writing_focus 说明该小节后续正文要重点写什么。
6. suggested_query 应适合后续统筹智能体或正文生成智能体再次检索。
7. 不要生成正文。
8. 生成的二级标题之间需要有较大的独立性，不要生成高度相似的二级标题。
9. 生成二级标题时必须以本章 research_question 为边界，不得加入 Planner 未要求或 Intent 禁止扩展的分析方向。

【输出格式】
{{
  "subsections": [
    {{
      "title": "二级标题",
      "writing_focus": "写作重点",
      "suggested_query": "后续检索 query"
    }}
  ]
}}
"""
    try:
        content = llm.query(
            user_prompt=user_prompt_text,
            system_prompt=system_prompt,
            max_tokens=5000,
            extra_log_info=f"report_generation.outline_agent subsection level1={level1_title}",
        )
    except Exception as exc:
        return {"status": "error", "message": f"subsection LLM call failed: {exc}"}

    if not content:
        return {"status": "error", "message": "subsection LLM returned empty output"}

    try:
        data = _parse_json_object(content)
    except ValueError as exc:
        return {
            "status": "error",
            "message": f"subsection JSON parse failed: {exc}",
            "raw_output": content,
        }

    subsections = data.get("subsections")
    if not isinstance(subsections, list):
        return {
            "status": "error",
            "message": "subsection JSON missing subsections array",
            "raw_output": content,
        }
    return {"status": "success", "subsections": subsections}


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


def _format_planner_requirement(
    research_question: str,
    content_requirements: List[str],
    evidence_requirements: List[str],
) -> str:
    """将 Planner 章节约束适配为下游沿用的 template_requirement 文本。"""
    parts = [f"研究问题：{research_question}"]
    if content_requirements:
        parts.append("内容要求：" + "；".join(content_requirements))
    if evidence_requirements:
        parts.append("证据要求：" + "；".join(evidence_requirements))
    return "\n".join(parts)


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

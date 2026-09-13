"""Summary generation agent for industry reports."""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, List, Optional

from llm_client import llm


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "产业链报告模板.docx"
SUPPORTED_INDUSTRIES = {
    "ai": "人工智能",
    "embodied": "具身智能",
}
DEFAULT_MAX_TOKENS = 5000


def generate_report_summary(
    report_title: str,
    outline: list,
    body_sections: list,
    industry: str = "ai",
    template_path: Optional[str] = None,
) -> dict:
    """Generate report abstract from the final outline and body sections."""
    normalized_title = _safe_text(report_title)
    normalized_industry = _safe_text(industry) or "ai"

    if not normalized_title:
        return _error_response("report_title cannot be empty", normalized_industry, "")

    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry)
    if not industry_name:
        return _error_response(
            f"unsupported industry: {normalized_industry}",
            normalized_industry,
            "",
        )

    if not isinstance(outline, list):
        return _error_response("outline must be an array", normalized_industry, industry_name)
    if not outline:
        return _error_response("outline must contain at least one item", normalized_industry, industry_name)
    if not isinstance(body_sections, list):
        return _error_response("body_sections must be an array", normalized_industry, industry_name)
    if not body_sections:
        return _error_response(
            "body_sections must contain at least one item",
            normalized_industry,
            industry_name,
        )

    try:
        abstract_template = _read_abstract_template(
            Path(template_path) if template_path else DEFAULT_TEMPLATE_PATH
        )
    except Exception as exc:
        return _error_response(
            f"failed to parse abstract template: {exc}",
            normalized_industry,
            industry_name,
        )

    warnings: List[dict] = []
    outline_text = _format_outline(outline)
    body_text = _format_body_sections(body_sections, warnings)
    if not body_text:
        return _error_response(
            "body_sections must contain at least one non-empty body_text",
            normalized_industry,
            industry_name,
        )

    summary_user_prompt = _build_summary_user_prompt(
        report_title=normalized_title,
        outline_text=outline_text,
        body_text=body_text,
    )
    summary_system_prompt = _build_summary_system_prompt(abstract_template)

    try:
        content = llm.query(
            user_prompt=summary_user_prompt,
            system_prompt=summary_system_prompt,
            max_tokens=DEFAULT_MAX_TOKENS,
            extra_log_info="report_generation.summary_agent",
        )
    except Exception as exc:
        return _error_response(
            f"summary LLM call failed: {exc}",
            normalized_industry,
            industry_name,
        )

    if not content:
        return _error_response("summary LLM returned empty output", normalized_industry, industry_name)

    abstract_text, cleanup_warnings = _clean_abstract_text(content)
    warnings.extend(cleanup_warnings)
    if not abstract_text:
        return _error_response(
            "summary LLM returned empty output after cleanup",
            normalized_industry,
            industry_name,
        )

    return {
        "status": "success",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "report_title": normalized_title,
        "abstract_text": abstract_text,
        "warnings": warnings,
    }


def _read_abstract_template(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(str(path))

    paragraphs = _read_docx_paragraphs(path)
    for index, paragraph in enumerate(paragraphs):
        if _heading_type(paragraph) != "abstract":
            continue
        requirement = _find_requirement_after(paragraphs, index)
        if not requirement:
            raise ValueError("template missing abstract requirement")
        return {
            "heading": paragraph,
            "requirement": requirement,
        }
    raise ValueError("template missing abstract section")


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
    normalized = _safe_text(text)
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


def _build_summary_system_prompt(abstract_template: dict) -> str:
    heading = _safe_text(abstract_template.get("heading"))
    requirement = _safe_text(abstract_template.get("requirement"))
    return f"""你是产业报告摘要生成智能体。
请严格依据甲方模板摘要要求，为产业链报告生成摘要。

【甲方模板摘要标题】
{heading or "摘要（400-600字）"}

【甲方模板摘要要求】
{requirement}

【硬性要求】
1. 只输出摘要正文，不要输出“摘要”标题、目录、标题页或 Word 导出说明。
2. 摘要应基于用户提供的报告标题、大纲和正文，不要补充正文中没有的信息。
3. 摘要字数严格限制在 400-600 字。
4. 不得标注 [知识图谱1]、[外部资料1] 等引用编号。
5. 不得输出参考文献、引用列表、资料来源或资料来源说明。
6. 保持正式产业研究报告文风，逻辑清晰、表述准确。"""


def _build_summary_user_prompt(report_title: str, outline_text: str, body_text: str) -> str:
    return f"""【报告标题】
{report_title}

【报告大纲】
{outline_text}

【报告正文】
{body_text}

请根据以上报告标题、大纲和正文生成报告摘要。"""


def _format_outline(outline: list) -> str:
    lines: List[str] = []
    for section_index, section in enumerate(outline, 1):
        if not isinstance(section, dict):
            continue
        if section.get("section_type") == "abstract":
            continue

        level1_id = _safe_text(section.get("level1_id")) or f"S{section_index}"
        level1_title = _safe_text(section.get("level1_title"))
        if level1_title:
            lines.append(f"{level1_id} {level1_title}")

        subsection_index = 0
        for subsection in section.get("subsections") or []:
            if not isinstance(subsection, dict):
                continue
            subsection_title = _safe_text(subsection.get("title"))
            if not subsection_title:
                continue
            subsection_index += 1
            outline_id = _safe_text(subsection.get("outline_id")) or f"{level1_id}.{subsection_index}"
            lines.append(f"{outline_id} {subsection_title}")

    return "\n".join(lines).strip() or "未提供可用报告大纲。"


def _format_body_sections(body_sections: list, warnings: List[dict]) -> str:
    blocks: List[str] = []
    for index, section in enumerate(body_sections, 1):
        if not isinstance(section, dict):
            warnings.append(
                {
                    "stage": "summary_prompt_build",
                    "message": f"skipped invalid body section at index {index}",
                }
            )
            continue

        body_text = _safe_text(section.get("body_text"))
        if not body_text:
            warnings.append(
                {
                    "outline_id": _safe_text(section.get("outline_id")),
                    "stage": "summary_prompt_build",
                    "message": "skipped body section with empty body_text",
                }
            )
            continue

        outline_id = _safe_text(section.get("outline_id")) or f"正文段落{index}"
        blocks.append(f"[{outline_id}]\n{body_text}")

    return "\n\n".join(blocks).strip()


def _clean_abstract_text(content: str) -> tuple[str, List[dict]]:
    warnings: List[dict] = []
    text = _safe_text(content)

    fenced_match = re.fullmatch(r"```(?:markdown|md|text)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()
        warnings.append(
            {
                "stage": "summary_cleanup",
                "message": "removed enclosing code fence from summary output",
            }
        )

    text, removed_heading = _remove_leading_summary_heading(text)
    if removed_heading:
        warnings.append(
            {
                "stage": "summary_cleanup",
                "message": "removed leading summary heading from summary output",
            }
        )

    cleaned = re.sub(r"\[(?:知识图谱|外部资料)\d+\]", "", text)
    if cleaned != text:
        text = cleaned
        warnings.append(
            {
                "stage": "summary_cleanup",
                "message": "removed explicit citation markers from summary output",
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
                "stage": "summary_cleanup",
                "message": "removed trailing reference/source section from summary output",
            }
        )

    return text.strip(), warnings


def _remove_leading_summary_heading(text: str) -> tuple[str, bool]:
    stripped = text.strip()
    prefixed = re.sub(r"^\s*摘要\s*[:：]\s*", "", stripped, count=1)
    if prefixed != stripped:
        return prefixed.strip(), True

    lines = stripped.splitlines()
    if not lines:
        return text, False

    first_line = lines[0].strip()
    normalized_first = re.sub(r"^[#\s\d一二三四五六七八九十、.．（）()]+", "", first_line).strip()
    if re.fullmatch(r"摘要(?:（[^）]*）|\([^)]*\))?[:：]?", normalized_first):
        return "\n".join(lines[1:]).strip(), True
    return text, False


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
        "abstract_text": "",
        "warnings": [],
    }

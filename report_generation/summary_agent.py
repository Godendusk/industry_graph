"""Summary generation agent for industry reports."""

from __future__ import annotations
from .runtime_budget import budgeted_stage, current_budget, bind_runtime_context, submit_with_context


import re
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, List, Optional

from llm_client import llm
from .industry_config import SUPPORTED_INDUSTRIES
from .structured_output import parse_json_object


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "产业链报告模板.docx"
# 摘要保留深度思考。模型的推理和可见摘要共同计入输出预算；8000 不足以
# 稳定完成当前报告摘要，因此为思考和 400—600 字正文预留 12000 tokens。
DEFAULT_MAX_TOKENS = 12000
RETRY_MAX_TOKENS = 16000


@budgeted_stage("summary")
def generate_report_summary(
    report_title: str,
    outline: list,
    body_sections: list,
    industry: str = "ai",
    template_path: Optional[str] = None,
    report_scope: dict = None,
) -> dict:
    """Generate report abstract from the final outline and body sections."""
    normalized_title = _safe_text((report_scope or {}).get("effective_title") or report_title)
    normalized_industry = _safe_text(industry)

    if not normalized_title:
        return _error_response("report_title cannot be empty", normalized_industry, "")

    industry_name = SUPPORTED_INDUSTRIES.get(normalized_industry, "未配置行业")

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
    if report_scope:
        summary_user_prompt += '\n【有效研究范围】\n' + json.dumps(report_scope, ensure_ascii=False)
    summary_system_prompt = _build_summary_system_prompt(abstract_template)

    try:
        query_kwargs = {
            "user_prompt": summary_user_prompt,
            "system_prompt": summary_system_prompt,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
            "extra_log_info": "report_generation.summary_agent",
        }
        if current_budget():
            query_kwargs.update(max_tokens=2400, reasoning_effort=None,
                                extra_body={'thinking': {'type': 'disabled'}})
        query_result = llm.query_result(**query_kwargs)
    except Exception as exc:
        return _error_response(
            f"summary LLM call failed: {exc}",
            normalized_industry,
            industry_name,
        )

    if query_result.error_message:
        return _error_response(
            f"summary LLM call failed: {query_result.error_message}",
            normalized_industry,
            industry_name,
        )

    # 深度思考和可见正文共用输出预算。若第一次调用把预算耗尽，增加一次预算
    # 重试；始终保留思考模式，不把失败退化为无思考摘要。
    if not query_result.error_message and (
        not query_result.content or query_result.finish_reason == "length"
    ):
        warnings.append(
            {
                "stage": "summary_retry",
                "message": "summary output was empty or truncated; retried with a larger thinking budget",
            }
        )
        query_kwargs["max_tokens"] = RETRY_MAX_TOKENS
        try:
            query_result = llm.query_result(**query_kwargs)
        except Exception as exc:
            return _error_response(
                f"summary LLM retry failed: {exc}",
                normalized_industry,
                industry_name,
            )

        if query_result.error_message:
            return _error_response(
                f"summary LLM retry failed: {query_result.error_message}",
                normalized_industry,
                industry_name,
            )

    if query_result.finish_reason == "length":
        return _error_response(
            "summary LLM output remained truncated after retry (finish_reason=length)",
            normalized_industry,
            industry_name,
        )

    content = query_result.content
    if not content:
        finish_reason = _safe_text(query_result.finish_reason)
        suffix = f" (finish_reason={finish_reason})" if finish_reason else ""
        return _error_response(
            f"summary LLM returned empty output{suffix}",
            normalized_industry,
            industry_name,
        )

    abstract_text, cleanup_warnings = _clean_abstract_text(content)
    warnings.extend(cleanup_warnings)
    if not abstract_text:
        return _error_response(
            "summary LLM returned empty output after cleanup",
            normalized_industry,
            industry_name,
        )

    summary_review, review_warnings, notes, abstract_text = _review_summary(
        normalized_title, body_text, abstract_text, report_scope=report_scope)
    warnings.extend(review_warnings)
    return {
        "status": "success",
        "industry": normalized_industry,
        "industry_name": industry_name,
        "report_title": normalized_title,
        "abstract_text": abstract_text,
        "warnings": warnings,
        "summary_review": summary_review,
        "delivery_status": "incomplete",
        "adjustment_notes": notes,
    }


def _review_summary(title, body_text, abstract_text, report_scope=None):
    """One final consistency check; failures retain the generated abstract."""
    prompt = """你是报告成稿审查Agent，只核对摘要与最终正文的一致性。
检查摘要是否新增无依据结论，是否把建议、待验证条件、计划或预测改写为已发生事实，是否丢失时间、对象、统计口径或必要限定。
正文有明确资料冲突时，摘要不得挑选其中一条作为无条件现状。只依据正文，不补查或补造事实。
有效研究范围优先于模板通用要求；正文没有形成国资央企专题判断或建议时，摘要不得因模板要求自行添加该视角、问题或建议。只概括当前报告已经回答的研究问题和已有结论，不能把资料缺口改写为行业或企业能力不足。
发现问题直接修正摘要，保留有依据的主要判断及建议，400—600字。没有问题则保留原摘要。
只返回JSON：{\"issues\":[{\"reason\":\"具体问题\"}],\"corrected_abstract_text\":\"有问题时完整修正摘要，无问题时空字符串\"}。"""
    warnings, notes = [], []
    review = {'status': 'failed', 'issue_count': 0, 'changed': False}
    payload = json.dumps({'report_title': title, 'body_text': body_text, 'abstract_text': abstract_text,
                          'report_scope': report_scope or {}}, ensure_ascii=False)
    try:
        if len(payload) > 70000:
            raise ValueError('summary_review_budget')
        query_kwargs = dict(user_prompt=payload, system_prompt=prompt, max_tokens=DEFAULT_MAX_TOKENS,
                            reasoning_effort='high', extra_body={'thinking': {'type': 'enabled'}},
                            extra_log_info='report_generation.summary_review')
        if current_budget():
            query_kwargs.update(max_tokens=2400, reasoning_effort=None,
                                extra_body={'thinking': {'type': 'disabled'}})
        result = llm.query_result(**query_kwargs)
        # 与摘要生成一样，思考和可见JSON共用预算。仅截断时增加一次预算，
        # 不重试连接错误，也不把未完成的修正当作核对通过。
        if not result.error_message and result.finish_reason == 'length':
            query_kwargs['max_tokens'] = RETRY_MAX_TOKENS
            result = llm.query_result(**query_kwargs)
        if result.error_message or result.finish_reason == 'length' or not result.content:
            raise ValueError('summary_review_unavailable')
        answer = parse_json_object(result.content)
        if (not {'issues'} <= set(answer) <= {'issues', 'corrected_abstract_text'}
                or not isinstance(answer['issues'], list)
                or any(not isinstance(i, dict) or set(i) != {'reason'} or not isinstance(i['reason'], str)
                       or not i['reason'].strip() for i in answer['issues'])):
            raise ValueError('invalid_summary_review')
        review.update(status='completed', issue_count=len(answer['issues']))
        corrected = answer.get('corrected_abstract_text', '')
        if not isinstance(corrected, str):
            raise ValueError('invalid_corrected_summary')
        if answer['issues']:
            if corrected.strip():
                cleaned, cleanup = _clean_abstract_text(corrected)
                if not cleaned:
                    raise ValueError('empty_corrected_summary')
                abstract_text = cleaned
                warnings.extend(cleanup)
                review['changed'] = True
                notes.append({'kind': 'summary_review', 'outline_ids': [],
                              'reason': '摘要已按最终正文修正无依据结论及必要限定。'})
            else:
                review['status'] = 'partial'
            for issue in answer['issues']:
                warnings.append({'stage': 'summary_review', 'message': issue['reason'], 'corrected': review['changed']})
                if not review['changed']:
                    notes.append({'kind': 'summary_review', 'outline_ids': [], 'reason': '摘要待核实：' + issue['reason']})
    except Exception:
        review['status'] = 'failed'
        warnings.append({'stage': 'summary_review', 'message': '摘要一致性核对未完成；保留生成摘要'})
        notes.append({'kind': 'summary_review', 'outline_ids': [], 'reason': '摘要一致性核对未完成，生成摘要已保留。'})
    return review, warnings, notes, abstract_text


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
4. 不得标注 [C1]、[知识图谱1]、[外部资料1] 等引用编号。
5. 不得输出参考文献、引用列表、资料来源或资料来源说明。
6. 保持正式产业研究报告文风，逻辑清晰、表述准确。
7. 有效研究范围和最终正文优先于模板通用要求。模板只约束组织方式；正文未形成国资央企专题判断或建议时，不得自行添加该视角或凑写建议。概括本报告实际回答的问题、有据差异和必要边界，不把资料缺口写成企业能力不足。"""


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

    cleaned = re.sub(r"\[(?:C|知识图谱|外部资料)\d+\]", "", text)
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

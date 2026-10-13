"""One report-wide repetition review followed by bounded section edits."""

from __future__ import annotations

import copy
import json
import re
from collections import defaultdict

from llm_client import llm
from .citations import collect_used_references, validate_body_citations
from .structured_output import parse_json_object
from .repetition_context import COMMON_REUSE_RULES

MAX_REVIEW_INPUT_CHARS = 60000
_CITATION = re.compile(r"\[(C[1-9]\d*)\]")

_CHECK_PROMPT = """你是产业报告重复审查Agent。检查已生成正文中无新增用途的重复事实、数字、案例和结论，含同节重复。
完整介绍留在最适合解释事实的小节，不默认保留最早出现处。
只返回JSON对象：{\"issues\":[{\"reason\":\"具体重复内容\",\"keep_paragraph_ids\":[\"S1.1:P1\"],\"edits\":[{\"outline_id\":\"S2.1\",\"paragraph_ids\":[\"S2.1:P1\"],\"instruction\":\"删减或压缩要求\",\"preserve_paragraph_ids\":[\"S2.1:P2\"]}]}]}。
无须修改返回{\"issues\":[]}。只列具体位置和必要改动；不进行全文事实核验，不建议删除标题或小节。""" + "\n" + COMMON_REUSE_RULES

_EDIT_PROMPT = """你是产业报告重复审查Agent，只定点修改指定小节。压缩指定的重复背景。
不得补造新结论或新引用，不改变标题和其他小节。只返回JSON对象：{\"outline_id\":\"当前小节ID\",\"body_text\":\"修改后的完整本节正文\"}。""" + "\n" + COMMON_REUSE_RULES


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _warning(reason, outline_id=''):
    return {'stage': 'report_review', 'reason': reason, 'outline_id': outline_id,
            'message': '重复审查未完成；保留当前正文' if not outline_id else '本节精简未采用；保留当前正文'}


def _query(prompt, system_prompt, max_tokens):
    result = llm.query_result(user_prompt=prompt, system_prompt=system_prompt,
                              max_tokens=max_tokens, reasoning_effort=None,
                              extra_body={'thinking': {'type': 'disabled'}},
                              extra_log_info='report_generation.review_agent')
    if result.error_message or result.finish_reason == 'length' or not (result.content or '').strip():
        raise ValueError('model_output_unavailable')
    return parse_json_object(result.content)


def _paragraphs(sections):
    indexed = {}
    for section in sections:
        if not isinstance(section, dict) or section.get('status') != 'success':
            continue
        outline_id = section.get('outline_id')
        if not isinstance(outline_id, str) or not outline_id:
            continue
        parts = [part.strip() for part in re.split(r'\n\s*\n|\n', section.get('body_text') or '') if part.strip()]
        for number, part in enumerate(parts, 1):
            indexed[f'{outline_id}:P{number}'] = part
    return indexed


def _validate_issues(response, paragraphs, target_outline_id):
    if set(response) != {'issues'} or not isinstance(response['issues'], list):
        raise ValueError('invalid_review_response')
    edits = defaultdict(list)
    for issue in response['issues']:
        if not isinstance(issue, dict) or set(issue) != {'reason', 'keep_paragraph_ids', 'edits'}:
            raise ValueError('invalid_issue')
        if not isinstance(issue['reason'], str) or not issue['reason'].strip():
            raise ValueError('empty_reason')
        keep = issue['keep_paragraph_ids']
        if not isinstance(keep, list) or not keep or any(pid not in paragraphs for pid in keep):
            raise ValueError('invalid_keep_paragraph')
        if not isinstance(issue['edits'], list) or not issue['edits']:
            raise ValueError('empty_edits')
        for edit in issue['edits']:
            if not isinstance(edit, dict) or set(edit) != {'outline_id', 'paragraph_ids', 'instruction', 'preserve_paragraph_ids'}:
                raise ValueError('invalid_edit')
            outline_id = edit['outline_id']
            if target_outline_id and outline_id != target_outline_id:
                raise ValueError('edit_outside_target')
            affected = edit['paragraph_ids']
            preserve = edit['preserve_paragraph_ids']
            if not isinstance(affected, list) or not affected or not isinstance(preserve, list):
                raise ValueError('invalid_edit_paragraphs')
            if any(pid not in paragraphs or not pid.startswith(outline_id + ':P') for pid in affected + preserve):
                raise ValueError('invalid_edit_paragraphs')
            if set(affected) & set(keep) or set(affected) & set(preserve):
                raise ValueError('conflicting_paragraph_instructions')
            if not isinstance(edit['instruction'], str) or not edit['instruction'].strip():
                raise ValueError('empty_instruction')
            edits[outline_id].append({'reason': issue['reason'], 'keep_paragraph_ids': keep,
                                      'paragraph_ids': affected, 'instruction': edit['instruction'],
                                      'preserve_paragraph_ids': preserve})
    return edits


def review_report_bodies(*, body_sections, writing_tasks, report_title, user_prompt,
                         references, target_outline_id=None, on_event=None):
    """Check once and edit each affected section once; never mutate caller data."""
    sections = copy.deepcopy(body_sections)
    warnings = []
    review = {'status': 'failed', 'checked_outline_ids': [], 'changed_outline_ids': [],
              'failed_outline_ids': [], 'issue_count': 0}
    notes = []

    def finish():
        return {'body_sections': sections,
                'references': collect_used_references(sections, references or []),
                'review': review, 'adjustment_notes': notes, 'warnings': warnings}

    available = [section for section in sections if isinstance(section, dict) and section.get('status') == 'success'
                 and (section.get('body_text') or '').strip()]
    incomplete_coverage = any(
        not isinstance(section, dict)
        or section.get('status') != 'success'
        or not (section.get('body_text') or '').strip()
        for section in sections
    )
    if target_outline_id:
        if not any(section.get('outline_id') == target_outline_id for section in available):
            warnings.append(_warning('target_missing', target_outline_id))
            return finish()
    if not available:
        warnings.append(_warning('no_body_sections'))
        return finish()
    paragraphs = _paragraphs(available)
    review['checked_outline_ids'] = [section['outline_id'] for section in available]
    if incomplete_coverage:
        warnings.append(_warning('incomplete_coverage'))
    payload = {'report_title': report_title, 'user_prompt': user_prompt,
               'target_outline_id': target_outline_id,
               'sections': [{'outline_id': section['outline_id'], 'title': section.get('title', ''),
                             'paragraphs': [{'id': pid, 'text': value} for pid, value in paragraphs.items()
                                            if pid.startswith(section['outline_id'] + ':P')],
                             'writing_decision': next((task.get('writing_decision') for task in writing_tasks
                                                       if task.get('outline_id') == section['outline_id']), None)}
                            for section in available]}
    payload_text = _json(payload)
    if len(payload_text) > MAX_REVIEW_INPUT_CHARS:
        review['status'] = 'skipped_budget'
        warnings.append(_warning('input_budget'))
        return finish()
    if callable(on_event):
        on_event({'event': 'review_started', 'status': 'started'})
    try:
        response = _query(payload_text, _CHECK_PROMPT, 5000)
        edits = _validate_issues(response, paragraphs, target_outline_id)
        review['issue_count'] = len(response['issues'])
    except (Exception, ValueError):
        warnings.append(_warning('check_failed'))
        if callable(on_event):
            on_event({'event': 'review_completed', 'status': 'failed'})
        return finish()
    if callable(on_event):
        on_event({'event': 'review_checked', 'status': 'completed', 'issue_count': review['issue_count']})
    for outline_id, instructions in edits.items():
        section = next(section for section in sections if section.get('outline_id') == outline_id)
        allowed = {str(block.get('citation_id')) for block in section.get('external_evidence_blocks', [])}
        edit_payload = {'report_title': report_title, 'user_prompt': user_prompt,
                        'outline_id': outline_id, 'title': section.get('title', ''),
                        'body_text': section['body_text'], 'instructions': instructions,
                        'related_paragraphs': {pid: paragraphs[pid] for item in instructions
                                               for pid in item['keep_paragraph_ids']},
                        'evidence_blocks': section.get('external_evidence_blocks', [])}
        try:
            answer = _query(_json(edit_payload), _EDIT_PROMPT, 5000)
            if set(answer) != {'outline_id', 'body_text'} or answer['outline_id'] != outline_id:
                raise ValueError('invalid_edit_response')
            new_text = answer['body_text']
            if not isinstance(new_text, str) or not new_text.strip():
                raise ValueError('empty_edit')
            if any(cid not in allowed for cid in _CITATION.findall(new_text)):
                raise ValueError('invalid_citation')
            new_text, citation_ids, citation_warnings = validate_body_citations(
                new_text, section.get('external_evidence_blocks', []))
            if any(warning.get('invalid_citation_ids') for warning in citation_warnings):
                raise ValueError('invalid_citation')
            warnings.extend(citation_warnings)
            if new_text != section['body_text']:
                section['body_text'] = new_text
                section['citation_ids'] = citation_ids
                review['changed_outline_ids'].append(outline_id)
                notes.append({'kind': 'body_edit', 'outline_ids': [outline_id],
                              'reason': '; '.join(dict.fromkeys(item['reason'] for item in instructions))})
            if callable(on_event):
                on_event({'event': 'review_section_completed', 'status': 'success', 'outline_id': outline_id})
        except (Exception, ValueError):
            review['failed_outline_ids'].append(outline_id)
            warnings.append(_warning('edit_failed', outline_id))
            if callable(on_event):
                on_event({'event': 'review_section_completed', 'status': 'failed', 'outline_id': outline_id})
    review['status'] = 'partial' if (review['failed_outline_ids'] or incomplete_coverage) else 'completed'
    if callable(on_event):
        on_event({'event': 'review_completed', 'status': review['status']})
    return finish()

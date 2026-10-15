"""One report-wide repetition review followed by bounded section edits."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter, defaultdict

from llm_client import llm
from .citations import collect_used_references, validate_body_citations
from .structured_output import parse_json_object
from .repetition_context import COMMON_REUSE_RULES

MAX_REVIEW_INPUT_CHARS = 60000
_CITATION = re.compile(r"\[(C[1-9]\d*)\]")
_BROKEN_PUNCTUATION = re.compile(r'(?=([。，；]{2}))')
_BARE_CITATION = re.compile(r'(?<![A-Za-z0-9_\[])(C[1-9]\d*)(?![A-Za-z0-9_\]])')

_CHECK_PROMPT = """你是产业报告重复审查Agent。检查已生成正文中无新增用途的重复事实、数字、案例和结论，含同节重复。
完整介绍留在最适合解释事实的小节，不默认保留最早出现处。
只返回JSON对象：{"issues":[{"reason":"具体重复内容","keep_spans":[{"paragraph_id":"S1.1:P1","quote":"保留处逐字原文"}],"edits":[{"outline_id":"S2.1","spans":[{"paragraph_id":"S2.1:P1","quote":"待压缩处逐字原文"}],"instruction":"删减或压缩要求","preserve_paragraph_ids":["S2.1:P2"]}]}]}。
quote必须逐字摘自指定正文段落，并能在该段唯一定位；不得根据写作意图或证据补出正文不存在的文字。
只授权重复句或最小连续片段，不选整段混有独有事实、案例或限定的文字；同一段内可以分别保留与压缩不同片段。片段边界应包含需要一起调整的标点和连接词，避免删后留下悬空标点、主语或指代。
各issue的keep_spans与其他issue待改片段不得重叠；preserve_paragraph_ids只约束当前edit，其他问题可另行授权该段的不同重复片段。
可另返回evidence_warnings数组，每项为{\"outline_id\":\"S2.1\",\"reason\":\"具体证据疑点\",\"citation_ids\":[\"C1\"]}。
依据输入证据检查资料日期、研究对象、计划/预测/已实现状态是否被混淆，或同报告存在未解释的相反结论；证据不足只提示，不猜测事实。
无须修改返回{\"issues\":[],\"evidence_warnings\":[]}。只列具体位置和必要改动；不联网全文事实核验，不建议删除标题或小节。
先逐节检查段内、段间及首尾总结，再检查跨节重复；不能只检查跨节。
同一分类、排序或实施阶段在一节反复完整列举，即使用了不同措辞，也要明确列出全部重复位置；保留一次完整介绍，其他位置保留新增的条件、行动或分析，不再复述整套分类。
只将sections.paragraphs当作现有正文，writing_decision仅提供写作意图，不能把其中未写入正文的内容当作重复事实。
同一事实的全部重复位置合并成一个issue；reason用一句话概括，instruction用短句说明压缩要求；不在reason和instruction重复抄写quote，不为同一事实拆出多个issue。
证据提示只列正文尚未解释的具体冲突或缺失限定；若正文已明确来源层级、计划属性、统计口径或图谱边界，不重复要求同一限定。
不同日期或“培育期/加速期”等可并存描述本身不证明矛盾；标准体系发布也不等于安全评测已完整，必须说明对象、时间或适用范围何处实际冲突。保留不同用途的分析，只压缩重复介绍。""" + "\n" + COMMON_REUSE_RULES

_EDIT_PROMPT = """你是产业报告重复审查Agent，只为指定小节的editable_spans提供最小片段替换。
只返回JSON对象：{"outline_id":"当前小节ID","patches":[{"span_index":0,"replacement":"该编号片段的替换内容；纯删除可为空字符串"}]}。
span_index只能取editable_spans中的编号；不返回original、段落号或整节正文。程序只替换该编号quote原文，其他文字逐字保留。
同一编号最多输出一次；原文重叠的编号只选一处，不得重复替换。所有片段都以原文为准。
只压缩重复背景。片段混有独有事实、实体、分析、计划/落地状态、时间、适用范围及必要引用时，replacement必须保留这些内容，不能把它们随重复背景删除。
不得补造新结论或新引用，不改变标题和其他小节。避免机械回指；确需回指只使用输入实际章节名称，保留必要限定与引用。
replacement只写替换quote的内容，不复制quote外已经存在的前后句、主语、冒号引导语或标点。必须放回原段检查语法、断句和逻辑衔接，不能留下“。，”“，，。”或重复半句。
未输出的编号保持原文；无可安全修改的片段时返回空patches，最终提示尚未完成。""" + "\n" + COMMON_REUSE_RULES

_VERIFY_PROMPT = """只复核输入中已提出的修改要求，不新增问题，不重新审稿。
对每个issue_index核对：重复介绍是否已压缩，指定保留的独有事实、分析、限定及必要引用是否完整，是否出现机械回指或错误章节回指。还需把每处替换放回原段检查语法、重复半句、指代与论据衔接；删掉具体例证后不得留下“这些信息”等没有所指的结论。片段内计划/落地状态及证据边界被丢失也必须判未完成。
只返回JSON：{\"resolved_issue_indexes\":[0],\"unresolved\":[{\"issue_index\":1,\"reason\":\"具体未解决内容或信息损失\",\"revert_outline_ids\":[]}]}。
只有独有事实、分析、限定或必要证据被误删、引入错误时，在revert_outline_ids列出需恢复原文的小节。仅重复仍未压缩时该数组为空。
每个输入问题必须恰好归入一个数组。"""


def _reader_reason(reason):
    return re.sub(r'S\d+\.\d+(?::P\d+)?', '相关段落', reason).strip()


def _review_evidence(sections, budget=24000):
    evidence, seen, omitted = [], set(), 0
    for section in sections:
        used = set(_CITATION.findall(section['body_text']) + _BARE_CITATION.findall(section['body_text']))
        for block in section.get('external_evidence_blocks', []):
            key = (block.get('citation_id'), block.get('vector_id'), block.get('text'))
            if block.get('citation_id') not in used or key in seen:
                continue
            seen.add(key)
            raw = str(block.get('text') or '')
            row = {k: block.get(k, '') for k in ('citation_id', 'title', 'publish_date', 'source_address')}
            row.update(text=raw[:1200], truncated=len(raw) > 1200)
            size = len(_json(row))
            if size > budget:
                omitted += 1
                continue
            budget -= size
            evidence.append(row)
    return {'blocks': evidence, 'omitted_block_count': omitted,
            'scope': '仅展示已引用检索片段；片段截断或未展示不代表原资料不存在'}


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


def _span_range(span, paragraphs):
    if (not isinstance(span, dict) or set(span) != {'paragraph_id', 'quote'}
            or not isinstance(span['paragraph_id'], str) or span['paragraph_id'] not in paragraphs
            or not isinstance(span['quote'], str) or not span['quote'].strip()):
        raise ValueError('invalid_span')
    text, quote = paragraphs[span['paragraph_id']], span['quote']
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise ValueError('nonunique_span')
    return start, start + len(quote)


def _validate_issue(response, paragraphs, target_outline_id):
    if not {'issues'} <= set(response) <= {'issues', 'evidence_warnings'} or not isinstance(response['issues'], list):
        raise ValueError('invalid_review_response')
    edits = defaultdict(list)
    protected = []
    for issue in response['issues']:
        if not isinstance(issue, dict) or set(issue) != {'reason', 'keep_spans', 'edits'}:
            raise ValueError('invalid_issue')
        if not isinstance(issue['reason'], str) or not issue['reason'].strip():
            raise ValueError('empty_reason')
        keep = issue['keep_spans']
        if not isinstance(keep, list) or not keep:
            raise ValueError('invalid_keep_span')
        for span in keep:
            protected.append((span['paragraph_id'], *_span_range(span, paragraphs)))
        if not isinstance(issue['edits'], list) or not issue['edits']:
            raise ValueError('empty_edits')
        for edit in issue['edits']:
            if not isinstance(edit, dict) or set(edit) != {'outline_id', 'spans', 'instruction', 'preserve_paragraph_ids'}:
                raise ValueError('invalid_edit')
            outline_id = edit['outline_id']
            if not isinstance(outline_id, str) or (target_outline_id and outline_id != target_outline_id):
                raise ValueError('edit_outside_target')
            spans, preserve = edit['spans'], edit['preserve_paragraph_ids']
            if not isinstance(spans, list) or not spans or not isinstance(preserve, list):
                raise ValueError('invalid_edit_spans')
            for span in spans:
                _span_range(span, paragraphs)
                if not span['paragraph_id'].startswith(outline_id + ':P'):
                    raise ValueError('edit_outside_section')
            for pid in preserve:
                if not isinstance(pid, str) or pid not in paragraphs or not pid.startswith(outline_id + ':P'):
                    raise ValueError('invalid_preserve_paragraph')
            if any(span['paragraph_id'] in preserve for span in spans):
                raise ValueError('conflicting_span_instructions')
            if not isinstance(edit['instruction'], str) or not edit['instruction'].strip():
                raise ValueError('empty_instruction')
            edits[outline_id].append({'reason': issue['reason'], 'keep_spans': keep,
                                      'spans': spans, 'instruction': edit['instruction'],
                                      'preserve_paragraph_ids': preserve})
    for instructions in edits.values():
        for item in instructions:
            for span in item['spans']:
                start, end = _span_range(span, paragraphs)
                if any(pid == span['paragraph_id'] and start < right and left < end
                       for pid, left, right in protected):
                    raise ValueError('conflicting_span_instructions')
    return edits


def _validate_issues(response, paragraphs, target_outline_id):
    if not {'issues'} <= set(response) <= {'issues', 'evidence_warnings'} or not isinstance(response['issues'], list):
        raise ValueError('invalid_review_response')
    candidates, rejected = [], []
    for index, issue in enumerate(response['issues']):
        try:
            edits = _validate_issue({'issues': [issue]}, paragraphs, target_outline_id)
            candidates.append((index, issue, edits))
        except (ValueError, TypeError, KeyError):
            rejected.append(index)
    # A kept span remains protected across issues, even when another issue
    # mistakenly authorizes editing the same text.
    protected = [(span['paragraph_id'], *_span_range(span, paragraphs))
                 for _, issue, _ in candidates for span in issue['keep_spans']]
    merged, accepted = defaultdict(list), []
    for index, issue, edits in candidates:
        conflict = any(pid == span['paragraph_id'] and start < right and left < end
                       for edit in issue['edits'] for span in edit['spans']
                       for start, end in [_span_range(span, paragraphs)]
                       for pid, left, right in protected)
        if conflict:
            rejected.append(index)
            continue
        accepted.append(issue)
        for oid, instructions in edits.items():
            merged[oid].extend(instructions)
    if rejected and not accepted:
        raise ValueError('no_valid_review_issues')
    return merged, accepted, sorted(rejected)


def _editable_spans(instructions):
    spans, seen = [], set()
    for item in instructions:
        for span in item['spans']:
            key = (span['paragraph_id'], span['quote'])
            if key not in seen:
                seen.add(key)
                spans.append({'span_index': len(spans), **span})
    return spans


def _apply_patches(answer, section, instructions):
    outline_id, body = section['outline_id'], section['body_text']
    if (set(answer) != {'outline_id', 'patches'} or answer['outline_id'] != outline_id
            or not isinstance(answer['patches'], list)):
        raise ValueError('invalid_edit_response')
    # Locate original paragraph ranges without normalizing whitespace or line breaks.
    ranges = {}
    for match in re.finditer(r'[^\n]+', body):
        raw = match.group()
        if raw.strip():
            pid = f'{outline_id}:P{len(ranges) + 1}'
            start = match.start() + len(raw) - len(raw.lstrip())
            ranges[pid] = (start, raw.strip())
    paragraphs = {pid: text for pid, (_, text) in ranges.items()}
    replacements, warnings, changed_spans = [], [], []
    allowed = {str(b.get('citation_id')) for b in section.get('external_evidence_blocks', [])}
    targets = _editable_spans(instructions)
    for patch in answer['patches']:
        if (not isinstance(patch, dict) or set(patch) != {'span_index', 'replacement'}
                or type(patch['span_index']) is not int or not 0 <= patch['span_index'] < len(targets)
                or not isinstance(patch['replacement'], str)):
            raise ValueError('invalid_patch')
        target = targets[patch['span_index']]
        span = {'paragraph_id': target['paragraph_id'], 'quote': target['quote']}
        start, end = _span_range(span, paragraphs)
        pid = span['paragraph_id']
        replacement = patch['replacement']
        if any(cid not in allowed for cid in _CITATION.findall(replacement)):
            raise ValueError('invalid_citation')
        cleaned, _, citation_warnings = validate_body_citations(replacement, section.get('external_evidence_blocks', []))
        # Citation helper strips whitespace; only use its text when it removed markers.
        if citation_warnings:
            replacement = cleaned
        warnings.extend(citation_warnings)
        offset = ranges[pid][0]
        replacements.append((offset + start, offset + end, replacement))
        if replacement != span['quote']:
            changed_spans.append(span)
    replacements.sort()
    if any(right > next_left for (_, right, _), (next_left, _, _) in zip(replacements, replacements[1:])):
        raise ValueError('overlapping_patches')
    for start, end, replacement in reversed(replacements):
        body = body[:start] + replacement + body[end:]
    if not body.strip():
        raise ValueError('empty_edit')
    before_pairs = Counter(_BROKEN_PUNCTUATION.findall(section['body_text']))
    if any(count > before_pairs[pair] for pair, count in Counter(_BROKEN_PUNCTUATION.findall(body)).items()):
        raise ValueError('broken_patch_punctuation')
    return body, list(dict.fromkeys(_CITATION.findall(body))), warnings, changed_spans


def _verify_edits(issues, original_sections, sections, applied_spans=None):
    payload = {'issues': [{'issue_index': i, **issue} for i, issue in enumerate(issues)],
               'original_sections': [{'outline_id': s['outline_id'], 'title': s.get('title', ''),
                                      'body_text': s['body_text']} for s in original_sections],
               'final_sections': [{'outline_id': s['outline_id'], 'title': s.get('title', ''),
                                   'body_text': s['body_text']} for s in sections
                                  if isinstance(s, dict) and s.get('status') == 'success']}
    answer = _query(_json(payload), _VERIFY_PROMPT, 3000)
    if set(answer) != {'resolved_issue_indexes', 'unresolved'}:
        raise ValueError('invalid_verification')
    resolved, unresolved = answer['resolved_issue_indexes'], answer['unresolved']
    if not isinstance(resolved, list) or not isinstance(unresolved, list):
        raise ValueError('invalid_verification')
    for row in unresolved:
        if (not isinstance(row, dict) or not {'issue_index', 'reason'} <= set(row) <= {'issue_index', 'reason', 'revert_outline_ids'}
                or not isinstance(row['reason'], str) or not row['reason'].strip()):
            raise ValueError('invalid_verification')
    indexes = resolved + [row['issue_index'] for row in unresolved]
    if any(type(i) is not int for i in indexes) or sorted(indexes) != list(range(len(issues))):
        raise ValueError('incomplete_verification')
    for row in unresolved:
        allowed = {edit['outline_id'] for edit in issues[row['issue_index']]['edits']}
        revert = row.get('revert_outline_ids', [])
        if not isinstance(revert, list) or any(not isinstance(oid, str) or oid not in allowed for oid in revert):
            raise ValueError('invalid_verification_revert')
    original_by_id = {s['outline_id']: s for s in original_sections}
    final_by_id = {s['outline_id']: s for s in sections if isinstance(s, dict)}
    original_paragraphs = _paragraphs(original_sections)
    for index in resolved:
        unchanged = []
        untouched_spans = False
        for edit in issues[index]['edits']:
            oid = edit['outline_id']
            whole_unchanged = (oid in original_by_id and oid in final_by_id
                               and original_by_id[oid]['body_text'] == final_by_id[oid].get('body_text'))
            span_unchanged = applied_spans is not None and any(
                not any(changed['paragraph_id'] == span['paragraph_id'] and left < end and start < right
                        for changed in applied_spans.get(oid, [])
                        for left, right in [_span_range(changed, original_paragraphs)])
                for span in edit['spans'] for start, end in [_span_range(span, original_paragraphs)])
            if whole_unchanged or span_unchanged:
                unchanged.append(original_by_id[oid].get('title') or oid)
                untouched_spans = untouched_spans or (span_unchanged and not whole_unchanged)
        if unchanged:
            unresolved.append({'issue_index': index, 'reason':
                               '、'.join(f'《{title}》' for title in dict.fromkeys(unchanged))
                               + ('指定重复片段未产生修改，指定压缩尚未执行。' if untouched_spans else
                                  '正文未产生修改，指定压缩尚未执行。'), 'revert_outline_ids': []})
    unresolved.sort(key=lambda row: row['issue_index'])
    return {'status': 'partial' if unresolved else 'completed',
            'unresolved_issue_indexes': [row['issue_index'] for row in unresolved],
            'unresolved': unresolved}


def review_report_bodies(*, body_sections, writing_tasks, report_title, user_prompt,
                         references, target_outline_id=None, on_event=None):
    """Check once and edit each affected section once; never mutate caller data."""
    sections = copy.deepcopy(body_sections)
    warnings = []
    review = {'status': 'failed', 'checked_outline_ids': [], 'changed_outline_ids': [],
              'failed_outline_ids': [], 'issue_count': 0, 'evidence_warning_count': 0,
              'verification': {'status': 'not_needed', 'unresolved_issue_indexes': []}}
    notes = []

    def finish():
        for section in sections:
            if not isinstance(section, dict) or section.get('status') != 'success':
                continue
            allowed = {b.get('citation_id') for b in section.get('external_evidence_blocks', [])}
            bare = sorted(set(_BARE_CITATION.findall(section.get('body_text', ''))) & allowed)
            if bare:
                message = f'《{section.get("title", section["outline_id"])}》使用资料代号但缺少规范引用标记：' + '、'.join(bare)
                warnings.append({'stage': 'report_review', 'reason': 'bare_citation_code',
                                 'outline_id': section['outline_id'], 'message': message})
                notes.append({'kind': 'review_warning', 'outline_ids': [section['outline_id']], 'reason': message})
                if review['status'] == 'completed':
                    review['status'] = 'partial'
        for warning in warnings:
            if warning.get('reason') in ('check_failed', 'input_budget', 'edit_failed', 'incomplete_coverage'):
                notes.append({'kind': 'review_warning', 'outline_ids': [warning['outline_id']] if warning.get('outline_id') else [],
                              'reason': warning['message']})
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
                            for section in available], 'evidence': _review_evidence(available)}
    payload_text = _json(payload)
    if len(payload_text) > MAX_REVIEW_INPUT_CHARS + 26000:
        review['status'] = 'skipped_budget'
        warnings.append(_warning('input_budget'))
        return finish()
    if callable(on_event):
        on_event({'event': 'review_started', 'status': 'started'})
    try:
        # 原文片段协议需要输出定位引文；真实量子八节报告曾耗尽12000 tokens。
        response = _query(payload_text, _CHECK_PROMPT, 16000)
        edits, accepted_issues, rejected = _validate_issues(response, paragraphs, target_outline_id)
        review['issue_count'] = len(response['issues'])
        response['issues'] = accepted_issues
        if rejected:
            message = f'有{len(rejected)}项精简要求无法按原文定位或存在保留冲突，未执行这些要求；其余有效要求继续处理。'
            warnings.append({'stage': 'report_review', 'reason': 'invalid_review_issue', 'message': message})
            notes.append({'kind': 'review_warning', 'outline_ids': [], 'reason': message})
        evidence_warnings = response.get('evidence_warnings', [])
        if not isinstance(evidence_warnings, list):
            raise ValueError('invalid_evidence_warnings')
        for row in evidence_warnings:
            if (not isinstance(row, dict) or set(row) != {'outline_id', 'reason', 'citation_ids'}
                    or row['outline_id'] not in review['checked_outline_ids']
                    or not isinstance(row['reason'], str) or not row['reason'].strip()
                    or not isinstance(row['citation_ids'], list)
                    or any(cid not in {b['citation_id'] for b in payload['evidence']['blocks']} for cid in row['citation_ids'])):
                raise ValueError('invalid_evidence_warning')
            warnings.append({'stage': 'report_review', 'reason': 'evidence_consistency_warning',
                             'outline_id': row['outline_id'], 'message': row['reason'],
                             'citation_ids': row['citation_ids']})
            title = next(s.get('title', s['outline_id']) for s in available if s['outline_id'] == row['outline_id'])
            notes.append({'kind': 'review_warning', 'outline_ids': [row['outline_id']],
                          'reason': f'《{title}》证据待核实：{_reader_reason(row["reason"])}'})
        review['evidence_warning_count'] = len(evidence_warnings)
    except (Exception, ValueError):
        warnings.append(_warning('check_failed'))
        if callable(on_event):
            on_event({'event': 'review_completed', 'status': 'failed'})
        return finish()
    if callable(on_event):
        on_event({'event': 'review_checked', 'status': 'completed', 'issue_count': review['issue_count']})
    original_sections = copy.deepcopy(available)
    applied_spans = {}
    for outline_id, instructions in edits.items():
        section = next(section for section in sections if section.get('outline_id') == outline_id)
        edit_payload = {'report_title': report_title, 'user_prompt': user_prompt,
                        'outline_id': outline_id, 'title': section.get('title', ''),
                        'body_text': section['body_text'], 'instructions': instructions,
                        'editable_spans': _editable_spans(instructions),
                        'paragraphs': {pid: text for pid, text in paragraphs.items() if pid.startswith(outline_id + ':P')},
                        'section_titles': {s['outline_id']: s.get('title', '') for s in available},
                        'related_paragraphs': {pid: paragraphs[pid] for item in instructions
                                               for span in item['keep_spans'] for pid in [span['paragraph_id']]},
                        'evidence_blocks': section.get('external_evidence_blocks', [])}
        try:
            answer = _query(_json(edit_payload), _EDIT_PROMPT, 5000)
            new_text, citation_ids, citation_warnings, changed_spans = _apply_patches(answer, section, instructions)
            applied_spans[outline_id] = changed_spans
            warnings.extend(citation_warnings)
            if new_text != section['body_text']:
                section['body_text'] = new_text
                section['citation_ids'] = citation_ids
                review['changed_outline_ids'].append(outline_id)
                notes.append({'kind': 'body_edit', 'outline_ids': [outline_id],
                              'reason': f'《{section.get("title", outline_id)}》已精简重复介绍，保留本节分析与必要限定。'})
            if callable(on_event):
                on_event({'event': 'review_section_completed', 'status': 'success', 'outline_id': outline_id})
        except (Exception, ValueError):
            review['failed_outline_ids'].append(outline_id)
            warnings.append(_warning('edit_failed', outline_id))
            if callable(on_event):
                on_event({'event': 'review_section_completed', 'status': 'failed', 'outline_id': outline_id})
    if edits:
        try:
            review['verification'] = _verify_edits(response['issues'], original_sections, sections, applied_spans)
            for row in review['verification']['unresolved']:
                for outline_id in row.get('revert_outline_ids', []):
                    if outline_id not in review['changed_outline_ids']:
                        continue
                    original = next(s for s in original_sections if s['outline_id'] == outline_id)
                    index = next(i for i, s in enumerate(sections) if s.get('outline_id') == outline_id)
                    sections[index] = copy.deepcopy(original)
                    review['changed_outline_ids'].remove(outline_id)
                    review['failed_outline_ids'].append(outline_id)
                    notes[:] = [note for note in notes if not (note['kind'] == 'body_edit' and outline_id in note['outline_ids'])]
                message = _reader_reason(row['reason'])
                if not any(w.get('reason') == 'edit_verification_failed' and w.get('message') == message for w in warnings):
                    warnings.append({'stage': 'report_review', 'reason': 'edit_verification_failed', 'message': message})
                    notes.append({'kind': 'review_warning', 'outline_ids': [], 'reason': '审查修正仍有待完善内容：' + message})
        except Exception:
            review['verification'] = {'status': 'failed', 'unresolved_issue_indexes': list(range(len(response['issues'])))}
            warnings.append({'stage': 'report_review', 'reason': 'verification_unavailable', 'message': '修正复核未完成；保留当前正文'})
            notes.append({'kind': 'review_warning', 'outline_ids': [], 'reason': '修正复核未完成，当前正文已保留，不能视为质量验收通过。'})
    review['status'] = 'partial' if (rejected or review['failed_outline_ids'] or incomplete_coverage
                                   or review['evidence_warning_count']
                                   or review['verification']['status'] in ('partial', 'failed')) else 'completed'
    result = finish()
    if callable(on_event):
        on_event({'event': 'review_completed', 'status': review['status']})
    return result

"""Independent bounded claim/repetition review followed by minimal section edits."""

from __future__ import annotations
from .runtime_budget import budgeted_stage, current_budget, bind_runtime_context, submit_with_context


import copy
import json
import re
from collections import Counter, defaultdict

from llm_client import llm
from .citations import collect_used_references, validate_body_citations
from .structured_output import parse_json_object
from .repetition_context import COMMON_REUSE_RULES
from .agentic_rag import verification as claim_verifier
from .review_batches import check_claim_batches, repetition_responses

MAX_REVIEW_INPUT_CHARS = 60000
_CITATION = re.compile(r"\[(C[1-9]\d*)\]")
_BROKEN_PUNCTUATION = re.compile(r'(?=([。，；]{2}))')
_DUPLICATED_CLAUSE = re.compile(r'([^\n]{8,80}?[，。：；])\1')
_BARE_CITATION = re.compile(r'(?<![A-Za-z0-9_\[])(C[1-9]\d*)(?![A-Za-z0-9_\]])')

_CHECK_PROMPT = """你是产业报告重复审查Agent。检查已生成正文中无新增用途的重复事实、数字、案例和结论，含同节重复。
完整介绍留在最适合解释事实的小节，不默认保留最早出现处。
只返回JSON对象：{"issues":[{"reason":"具体重复内容","keep_spans":[{"span_id":"输入中保留句的span_id"}],"edits":[{"outline_id":"S2.1","spans":[{"span_id":"输入中待压缩句的span_id"}],"instruction":"删减或压缩要求","preserve_paragraph_ids":["S2.1:P2"]}]}]}。
sections.paragraphs.sentences列出程序绑定原文的片段编号。直接选择span_id，不重抄原文、不自造编号；一个修改可选多个片段。编号只用于定位，不属于报告文字。
只授权重复句或最小连续片段，不选整段混有独有事实、案例或限定的文字；同一段内可以分别保留与压缩不同片段。片段边界应包含需要一起调整的标点和连接词，避免删后留下悬空标点、主语或指代。
各issue的keep_spans与其他issue待改片段不得重叠；preserve_paragraph_ids只列本次完全不改的段落；修改段内片段时，其余原文由程序原样保留，不要把该段本身又列为整段保留。其他问题可另行授权不同重复片段。
可另返回evidence_warnings数组，每项为{\"outline_id\":\"S2.1\",\"reason\":\"具体证据疑点\",\"citation_ids\":[\"C1\"]}。
依据输入证据检查资料日期、研究对象、计划/预测/已实现状态是否被混淆，或同报告存在未解释的相反结论；证据不足只提示，不猜测事实。
无须修改返回{\"issues\":[],\"evidence_warnings\":[]}。只列具体位置和必要改动；不联网全文事实核验，不建议删除标题或小节。
先逐节检查段内、段间及首尾总结，再检查跨节重复；不能只检查跨节。
同一分类、排序或实施阶段在一节反复完整列举，即使用了不同措辞，也要明确列出全部重复位置；保留一次完整介绍，其他位置保留新增的条件、行动或分析，不再复述整套分类。
只将sections.paragraphs.sentences的text当作现有正文，writing_decision仅提供写作意图，不能把其中未写入正文的内容当作重复事实。
同一事实的全部重复位置合并成一个issue；reason用一句话概括，instruction用短句说明压缩要求；不在reason和instruction重复抄写quote，不为同一事实拆出多个issue。
证据提示只列正文尚未解释的具体冲突或缺失限定；若正文已明确来源层级、计划属性、统计口径或图谱边界，不重复要求同一限定。
不同日期或“培育期/加速期”等可并存描述本身不证明矛盾；标准体系发布也不等于安全评测已完整，必须说明对象、时间或适用范围何处实际冲突。保留不同用途的分析，只压缩重复介绍。""" + "\n" + COMMON_REUSE_RULES

_EDIT_PROMPT = """你是产业报告重复审查Agent，只为指定小节的editable_spans提供最小片段替换。
只返回JSON对象：{"outline_id":"当前小节ID","patches":[{"span_index":0,"replacement":"该编号片段的替换内容；纯删除可为空字符串"}]}。
span_index只能取editable_spans中的编号；不返回original、段落号或整节正文。程序只替换该编号quote原文，其他文字逐字保留。
同一编号最多输出一次；原文重叠的编号只选一处，不得重复替换。所有片段都以原文为准。
按instructions精简重复背景，或删除/收窄证据不支持的断言。片段混有独有事实、实体、分析、计划/落地状态、时间、适用范围及必要引用时，replacement必须保留这些内容，不能把它们随重复背景删除。
不得补造新结论或新引用，不改变标题和其他小节。避免机械回指；确需回指只使用输入实际章节名称，保留必要限定与引用。
replacement只写替换quote的内容，不复制quote外已经存在的前后句、主语、冒号引导语或标点。必须放回原段检查语法、断句和逻辑衔接，不能留下“。，”“，，。”或重复半句。
未输出的编号保持原文；无可安全修改的片段时返回空patches，最终提示尚未完成。""" + "\n" + COMMON_REUSE_RULES

_VERIFY_PROMPT = """只复核输入中已提出的修改要求，不新增问题，不重新审稿。
同时遵守authorized_edits中的事实修正授权，并对照final_sections.claim_verification的实际来源核对结果。原keep_spans若含已核对为错误的事实或状态，不要求保留错误措辞；依据来源收窄、改为计划或补充实际节点不属于误删独有信息。仍需核对其余有据事实、不同分析用途与必要限定是否保留。
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
    if result.finish_reason == 'length':
        raise ValueError('model_output_truncated')
    if result.error_message or not (result.content or '').strip():
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


def _repetition_query(query):
    """Bind model-selected IDs to exact positions in this request's original text."""
    def prepare(prompt):
        payload = json.loads(prompt)
        if 'sections' not in payload:
            return prompt, {}
        catalog = {}
        for section in payload['sections']:
            for paragraph in section.get('paragraphs', []):
                raw = paragraph.pop('text')
                offset = paragraph.get('start', 0)
                sentences = []
                # Keep following citations attached to their sentence.
                matches = list(re.finditer(r'[^。！？；\n]+[。！？；]?(?:\[C[1-9]\d*\])*|[。！？；\n]', raw))
                intervals = []
                for match in matches:
                    if len(matches) > 64 and intervals and intervals[-1][1] - intervals[-1][0] < 80:
                        intervals[-1] = (intervals[-1][0], match.end())
                    else:
                        intervals.append((match.start(), match.end()))
                for left, right in intervals:
                    start, end = offset + left, offset + right
                    sid = f"{paragraph['id']}:{start}-{end}"
                    catalog[sid] = {'paragraph_id': paragraph['id'], 'quote': raw[left:right],
                                    'start': start, 'end': end}
                    sentences.append({'span_id': sid, 'text': raw[left:right]})
                paragraph['sentences'] = sentences
        return _json(payload), catalog

    def run(prompt, system_prompt, max_tokens):
        wire, catalog = prepare(prompt)
        answer = query(wire, system_prompt, max_tokens)
        if isinstance(answer, dict) and isinstance(answer.get('issues'), list):
            for issue in answer['issues']:
                if not isinstance(issue, dict):
                    continue
                lists = [issue.get('keep_spans')]
                edits = issue.get('edits')
                if isinstance(edits, list):
                    lists.extend(edit.get('spans') for edit in edits if isinstance(edit, dict))
                for spans in lists:
                    if not isinstance(spans, list):
                        continue
                    for index, span in enumerate(spans):
                        if isinstance(span, dict) and set(span) == {'span_id'}:
                            spans[index] = copy.deepcopy(catalog.get(span['span_id'], {}))
        return answer
    run.input_size = lambda payload: len(prepare(_json(payload))[0])
    return run


def _span_range(span, paragraphs):
    if (not isinstance(span, dict) or set(span) not in ({'paragraph_id', 'quote'}, {'paragraph_id', 'quote', 'start', 'end'})
            or not isinstance(span.get('paragraph_id'), str) or span['paragraph_id'] not in paragraphs
            or not isinstance(span.get('quote'), str) or not span['quote'].strip()):
        raise ValueError('invalid_span')
    text, quote = paragraphs[span['paragraph_id']], span['quote']
    if 'start' in span:
        start, end = span['start'], span['end']
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or text[start:end] != quote):
            raise ValueError('invalid_span')
        return start, end
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise ValueError('nonunique_span')
    return start, start + len(quote)


def _validate_issue(response, paragraphs, target_outline_id):
    if not {'issues'} <= set(response) <= {'issues', 'evidence_warnings', 'claim_checks', 'information_loss'} or not isinstance(response['issues'], list):
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
            start, end = _span_range(span, paragraphs)
            protected.append((span['paragraph_id'], start, end))
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
            local_ids = {span['paragraph_id'] for span in spans}
            for pid in local_ids & set(preserve):
                intervals = sorted(_span_range(span, paragraphs) for span in spans if span['paragraph_id'] == pid)
                cursor, rest = 0, []
                for start, end in intervals:
                    if start > cursor:
                        rest.append(paragraphs[pid][cursor:start])
                    cursor = max(cursor, end)
                rest.append(paragraphs[pid][cursor:])
                if not re.search(r'\w', _CITATION.sub('', ''.join(rest))):
                    raise ValueError('conflicting_span_instructions')
            # A partial patch preserves all original text outside its ranges by
            # construction. The same-paragraph instruction refers to that remainder.
            preserve = [pid for pid in preserve if pid not in local_ids]
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
    if not {'issues'} <= set(response) <= {'issues', 'evidence_warnings', 'claim_checks', 'information_loss'} or not isinstance(response['issues'], list):
        raise ValueError('invalid_review_response')
    candidates, rejected, rejection_reasons = [], [], {}
    for index, issue in enumerate(response['issues']):
        try:
            edits = _validate_issue({'issues': [issue]}, paragraphs, target_outline_id)
            normalized = copy.deepcopy(issue)
            for edit in normalized['edits']:
                local_ids = {span['paragraph_id'] for span in edit['spans']}
                edit['preserve_paragraph_ids'] = [pid for pid in edit['preserve_paragraph_ids'] if pid not in local_ids]
            candidates.append((index, normalized, edits))
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append(index)
            rejection_reasons[index] = str(exc)
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
        raise ValueError('no_valid_review_issues: ' + str(rejection_reasons))
    return merged, accepted, sorted(rejected)


def _editable_spans(instructions, paragraphs=None):
    spans, seen = [], set()
    for item in instructions:
        for span in item['spans']:
            key = (span['paragraph_id'], span['quote'], span.get('start'), span.get('end'))
            if key not in seen:
                seen.add(key)
                spans.append({'span_index': len(spans), **span})
    if paragraphs is None:
        return spans
    ranges = []
    for span in spans:
        start, end = _span_range({k: v for k, v in span.items() if k != 'span_index'}, paragraphs)
        ranges.append((span['paragraph_id'], start, end))
    combined = []
    for pid, start, end in sorted(ranges):
        if combined and combined[-1][0] == pid and start < combined[-1][2]:
            combined[-1] = (pid, combined[-1][1], max(end, combined[-1][2]))
        else:
            combined.append((pid, start, end))
    return [{'span_index': i, 'paragraph_id': pid, 'quote': paragraphs[pid][start:end], 'start': start, 'end': end}
            for i, (pid, start, end) in enumerate(combined)]


def _merge_consistency_edits(edits, sections, claim_payloads, warnings_by_id, paragraphs):
    """Use already retrieved cross-section sources to repair dated-state conflicts."""
    for section in sections:
        oid = section['outline_id']
        rows = warnings_by_id.get(oid, [])
        if not rows:
            continue
        ids = {cid for row in rows for cid in row['citation_ids']}
        existing = {(b.get('citation_id'), b.get('vector_id'), b.get('text'))
                    for b in section.get('external_evidence_blocks', [])}
        for owner in sections:
            for block in owner.get('external_evidence_blocks', []):
                key = (block.get('citation_id'), block.get('vector_id'), block.get('text'))
                if block.get('citation_id') in ids and key not in existing:
                    section.setdefault('external_evidence_blocks', []).append(copy.deepcopy(block))
                    existing.add(key)
        for claim in claim_payloads.get(oid, {}).get('claims', []):
            used = claim['citation_ids'] or claim.get('context_citation_ids', [])
            relevant = [row for row in rows if set(used) & set(row['citation_ids'])]
            if not relevant:
                continue
            instruction = ('核对以下日期、对象、口径或计划/已实现疑点，仅在现有原文确有依据时修正；'
                           '旧预测保留其作出日期，补充已发生节点的具体时间与引用，不把不同证书混为同一状态。'
                           '疑点不成立或没有足够依据时不改，不删除有依据分析。疑点：'
                           + '；'.join(row['message'] for row in relevant))
            span = claim_verifier.claim_span(claim, section)
            try:
                left, right = _span_range(span, paragraphs)
            except ValueError:
                # Ambiguous repeated sentences cannot authorize a positional patch.
                # Keep their warning instead of aborting the entire review.
                continue
            overlaps = [item for item in edits.get(oid, []) if any(
                other['paragraph_id'] == span['paragraph_id'] and left < end and start < right
                for other in item['spans'] for start, end in [_span_range(other, paragraphs)])]
            if overlaps:
                for item in overlaps:
                    item['instruction'] += '\n' + instruction
            else:
                edits.setdefault(oid, []).append({'reason': '来源日期或状态一致性修正',
                    'keep_spans': [], 'spans': [span], 'preserve_paragraph_ids': [], 'instruction': instruction})
    return edits


def _consistency_proven(loss_rows, section, warning_count):
    """A model's resolved flag needs actual final wording and bound source quotes."""
    if not loss_rows or not all(row.get('consistency_resolved') is True for row in loss_rows):
        return False
    blocks = section.get('external_evidence_blocks', [])
    body = section['body_text']
    for row in loss_rows:
        checks = row.get('consistency_checks')
        if not isinstance(checks, list) or len(checks) != warning_count:
            return False
        if {c.get('warning_index') for c in checks if isinstance(c, dict)} != set(range(warning_count)):
            return False
        for check in checks:
            final_quote = check.get('final_quote')
            if (check.get('resolved') is not True or not isinstance(final_quote, str)
                    or not final_quote.strip() or final_quote not in body or not check.get('supports')):
                return False
            for support in check['supports']:
                if not isinstance(support, dict):
                    return False
                cid, quote = support.get('citation_id'), support.get('quote')
                if (not isinstance(quote, str) or not quote.strip() or cid not in _CITATION.findall(body)
                        or not any(b.get('citation_id') == cid and quote in str(b.get('text') or '') for b in blocks)):
                    return False
    return True


def _consistency_source_candidates(sections):
    """Bounded previews of this report's retrieved sources, never new evidence."""
    sources, seen = [], set()
    for section in sections:
        for block in section.get('external_evidence_blocks', []):
            key = (block.get('citation_id'), block.get('vector_id'), block.get('text'))
            if key in seen:
                continue
            seen.add(key)
            sources.append(block)
    preview_size = min(600, max(80, 24000 // max(1, len(sources)) - 180))
    return [{**{k: b.get(k, '') for k in ('citation_id', 'title', 'publish_date', 'vector_id')},
             'text': str(b.get('text') or '')[:preview_size],
             'truncated': len(str(b.get('text') or '')) > preview_size}
            for b in sources]


def _adopt_patch_sources(section, answer, sections):
    """Allow only references actually returned by a patch and already retrieved."""
    used = {cid for patch in answer.get('patches', []) if isinstance(patch, dict)
            for cid in _CITATION.findall(str(patch.get('replacement') or ''))}
    existing = {(b.get('citation_id'), b.get('vector_id'), b.get('text'))
                for b in section.get('external_evidence_blocks', [])}
    for owner in sections:
        for block in owner.get('external_evidence_blocks', []):
            key = (block.get('citation_id'), block.get('vector_id'), block.get('text'))
            if block.get('citation_id') in used and key not in existing:
                section.setdefault('external_evidence_blocks', []).append(copy.deepcopy(block))
                existing.add(key)


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
    targets = _editable_spans(instructions, paragraphs)
    for patch in answer['patches']:
        if (not isinstance(patch, dict) or set(patch) != {'span_index', 'replacement'}
                or type(patch['span_index']) is not int or not 0 <= patch['span_index'] < len(targets)
                or not isinstance(patch['replacement'], str)):
            raise ValueError('invalid_patch')
        target = targets[patch['span_index']]
        span = {k: v for k, v in target.items() if k != 'span_index'}
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
    before_clauses = Counter(_DUPLICATED_CLAUSE.findall(section['body_text']))
    if any(count > before_clauses[clause] for clause, count in Counter(_DUPLICATED_CLAUSE.findall(body)).items()):
        raise ValueError('duplicated_patch_clause')
    return body, list(dict.fromkeys(_CITATION.findall(body))), warnings, changed_spans


def _restore_unverified_paragraphs(original, section, checked):
    """Restore affected paragraphs only when paragraph correspondence is preserved.

    This constructs a candidate, never certifies it. The caller must recheck the
    resulting body and information preservation before adopting any retained edit.
    """
    before, after = original['body_text'], section['body_text']
    old_lines = [m for m in re.finditer(r'[^\n]+', before) if m.group().strip()]
    new_lines = [m for m in re.finditer(r'[^\n]+', after) if m.group().strip()]
    if len(old_lines) != len(new_lines):
        return None
    old_claims = {c['quote'] for c in claim_verifier.prepare_section(
        {**original, 'outline_id': section['outline_id']})['claims']}
    targets = set()
    for claim in checked['claims']:
        if claim['status'] in claim_verifier.RESOLVED_STATUSES or claim['quote'] in old_claims:
            continue
        start, end = claim.get('start'), claim.get('end')
        if not isinstance(start, int) or not isinstance(end, int) or after[start:end] != claim['quote']:
            return None
        matches = [i for i, line in enumerate(new_lines) if line.start() <= start < end <= line.end()]
        if len(matches) != 1:
            return None
        targets.add(matches[0])
    if not targets:
        return None
    for i in sorted(targets, reverse=True):
        line = new_lines[i]
        after = after[:line.start()] + old_lines[i].group() + after[line.end():]
    return after if after != section['body_text'] and after != before else None


def _verify_edits(issues, original_sections, sections, applied_spans=None, authorized_edits=None):
    payload = {'authorized_edits': authorized_edits or {},
               'issues': [{'issue_index': i, **issue} for i, issue in enumerate(issues)],
               'original_sections': [{'outline_id': s['outline_id'], 'title': s.get('title', ''),
                                      'body_text': s['body_text']} for s in original_sections],
               'final_sections': [{'outline_id': s['outline_id'], 'title': s.get('title', ''),
                                   'body_text': s['body_text'], 'claim_verification': s.get('claim_verification', {})} for s in sections
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


@budgeted_stage("review")
def review_report_bodies(*, body_sections, writing_tasks, report_title, user_prompt,
                         references, target_outline_id=None, on_event=None):
    """Review all sections in bounded requests; never mutate caller data."""
    sections = copy.deepcopy(body_sections)
    warnings = []
    review = {'status': 'failed', 'checked_outline_ids': [], 'changed_outline_ids': [],
              'failed_outline_ids': [], 'issue_count': 0, 'evidence_warning_count': 0,
              'verification': {'status': 'not_needed', 'unresolved_issue_indexes': []}}
    notes = []
    claim_payloads = {}
    claim_execution_incomplete = False
    consistency_rows = defaultdict(list)
    consistency_notes = defaultdict(list)
    source_candidates = _consistency_source_candidates(sections)

    def finish():
        execution_failures = {'check_failed', 'input_budget', 'incomplete_coverage',
                              'verification_unavailable', 'no_body_sections', 'target_missing'}
        claim_execution_failed = any(
            '声明核对批次未覆盖' in c.get('reason', '')
            for s in sections if isinstance(s, dict)
            for c in (s.get('claim_verification') or {}).get('claims', []))
        review['execution_status'] = ('failed' if review['status'] == 'failed' else
            'partial' if claim_execution_incomplete or claim_execution_failed or any(w.get('reason') in execution_failures for w in warnings)
            else 'completed')
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
        pending = []
        for section in sections:
            result = section.get('claim_verification') if isinstance(section, dict) else None
            if result and result['status'] == 'needs_confirmation':
                pending.append(section['outline_id'])
                notes.append({'kind': 'review_warning', 'outline_ids': [section['outline_id']],
                              'reason': '《' + section.get('title', section['outline_id']) + '》关键事实仍有待确认项，详见声明核对记录。'})
        if claim_payloads:
            review['claim_verification'] = {'status': 'needs_confirmation' if pending else 'completed',
                                           'pending_outline_ids': pending}
        if pending and review['status'] == 'completed':
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
    for section in available:
        if target_outline_id and section['outline_id'] != target_outline_id:
            continue
        prepared = claim_verifier.prepare_section(section)
        section.pop('claim_verification', None)
        if prepared['claims'] or prepared['omitted_claim_count']:
            claim_payloads[section['outline_id']] = prepared
            section['claim_verification'] = claim_verifier.validate_checks(prepared, [])
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
                            for section in available], 'evidence': _review_evidence(available),
               'report_facts': [fact for section in available for fact in section.get('report_facts', [])]}
    if callable(on_event):
        on_event({'event': 'review_started', 'status': 'started'})
    claim_rows, claim_failures, _ = check_claim_batches(list(claim_payloads.values()), _query, claim_verifier.PROMPT)
    claim_execution_incomplete |= bool(claim_failures)
    claim_results = {}
    for section in available:
        oid = section['outline_id']
        if oid in claim_payloads:
            section['claim_verification'] = claim_verifier.validate_checks(claim_payloads[oid], claim_rows.get(oid, []), failure_reasons=claim_failures)
            claim_results[oid] = section['claim_verification']
    repetition_failed = False
    try:
        responses = repetition_responses(payload, _repetition_query(_query), _CHECK_PROMPT)
        response = {'issues': [], 'evidence_warnings': []}
        seen_issues = set()
        valid_responses = 0
        for answer, error in responses:
            if not isinstance(answer, dict) or not isinstance(answer.get('issues'), list):
                repetition_failed = True
                warnings.append({**_warning('check_failed'), 'detail': error or 'invalid_repetition_response'})
                continue
            valid_responses += 1
            for issue in answer['issues']:
                key = _json(issue)
                if key not in seen_issues:
                    response['issues'].append(issue)
                    seen_issues.add(key)
            rows = answer.get('evidence_warnings', [])
            if isinstance(rows, list):
                response['evidence_warnings'].extend(rows)
            else:
                repetition_failed = True
                warnings.append(_warning('check_failed'))
        if not valid_responses and not claim_payloads:
            raise ValueError('repetition_check_unavailable')
        try:
            edits, accepted_issues, rejected = _validate_issues(response, paragraphs, target_outline_id)
        except ValueError as exc:
            if str(exc) != 'no_valid_review_issues' or not claim_payloads:
                raise
            edits, accepted_issues, rejected = {}, [], list(range(len(response['issues'])))
        review['issue_count'] = len(response['issues'])
        response['issues'] = accepted_issues
        if rejected:
            message = f'有{len(rejected)}项精简要求无法按原文定位或存在保留冲突，未执行这些要求；其余有效要求继续处理。'
            warnings.append({'stage': 'report_review', 'reason': 'invalid_review_issue', 'message': message})
            notes.append({'kind': 'review_warning', 'outline_ids': [], 'reason': message})
        evidence_warnings = response.get('evidence_warnings', [])
        if not isinstance(evidence_warnings, list):
            raise ValueError('invalid_evidence_warnings')
        valid_evidence_warnings = 0
        for row in evidence_warnings:
            if (not isinstance(row, dict) or set(row) != {'outline_id', 'reason', 'citation_ids'}
                    or row['outline_id'] not in review['checked_outline_ids']
                    or not isinstance(row['reason'], str) or not row['reason'].strip()
                    or not isinstance(row['citation_ids'], list)
                    or any(cid not in {b['citation_id'] for b in payload['evidence']['blocks']} for cid in row['citation_ids'])):
                repetition_failed = True
                warnings.append(_warning('check_failed'))
                continue
            valid_evidence_warnings += 1
            warnings.append({'stage': 'report_review', 'reason': 'evidence_consistency_warning',
                             'outline_id': row['outline_id'], 'message': row['reason'],
                             'citation_ids': row['citation_ids']})
            consistency_rows[row['outline_id']].append(warnings[-1])
            title = next(s.get('title', s['outline_id']) for s in available if s['outline_id'] == row['outline_id'])
            notes.append({'kind': 'review_warning', 'outline_ids': [row['outline_id']],
                          'reason': f'《{title}》证据待核实：{_reader_reason(row["reason"])}'})
            consistency_notes[row['outline_id']].append(notes[-1])
        review['evidence_warning_count'] = valid_evidence_warnings
    except Exception as exc:
        warnings.append({**_warning('check_failed'), 'detail': str(exc) or type(exc).__name__})
        if callable(on_event):
            on_event({'event': 'review_completed', 'status': 'failed'})
        return finish()
    if callable(on_event):
        on_event({'event': 'review_checked', 'status': 'completed', 'issue_count': review['issue_count']})
    repetition_edits = copy.deepcopy(edits)
    edits, deferred = claim_verifier.merge_edits(edits, available, claim_results)
    edits = _merge_consistency_edits(edits, available, claim_payloads, consistency_rows, paragraphs)
    review['deferred_claim_ids'] = deferred
    review['claim_issue_count'] = sum(c['status'] in ('partial', 'unsupported', 'conflicting')
                                      for result in claim_results.values() for c in result['claims'])
    original_sections = copy.deepcopy(available)
    applied_spans = {}
    review['edit_attempts'] = []
    repair_used = set()
    for outline_id, instructions in edits.items():
        section = next(section for section in sections if section.get('outline_id') == outline_id)
        edit_payload = {'report_title': report_title, 'user_prompt': user_prompt,
                        'outline_id': outline_id, 'title': section.get('title', ''),
                        'body_text': section['body_text'], 'instructions': instructions,
                        'editable_spans': [],
                        'paragraphs': {pid: text for pid, text in paragraphs.items() if pid.startswith(outline_id + ':P')},
                        'section_titles': {s['outline_id']: s.get('title', '') for s in available},
                        'related_paragraphs': {pid: paragraphs[pid] for item in instructions
                                               for span in item['keep_spans'] for pid in [span['paragraph_id']]},
                        'evidence_blocks': section.get('external_evidence_blocks', []),
                        'report_facts': section.get('report_facts', [])}
        if consistency_rows.get(outline_id):
            edit_payload['report_source_candidates'] = source_candidates
            edit_payload['source_selection_rule'] = ('本次报告其他章节已检索到的资料预览，可选择实际支持当前修正的引用。'
                '涉及旧预测时先核对是否已有后续状态，不能仅补旧日期就断言没有进展；预览截断不代表完整材料无该事实。')
        attempt = {'outline_id': outline_id, 'status': 'started'}
        review['edit_attempts'].append(attempt)
        try:
            edit_payload['editable_spans'] = _editable_spans(instructions, paragraphs)
            answer = _query(_json(edit_payload), _EDIT_PROMPT, 5000)
            try:
                if consistency_rows.get(outline_id):
                    _adopt_patch_sources(section, answer, sections)
                new_text, citation_ids, citation_warnings, changed_spans = _apply_patches(answer, section, instructions)
            except ValueError as exc:
                repair_used.add(outline_id)
                attempt.update(retry_count=1, first_rejection=str(exc))
                edit_payload.update(patch_failure_reason=str(exc), rejected_candidate=answer)
                answer = _query(_json(edit_payload), _EDIT_PROMPT, 5000)
                if consistency_rows.get(outline_id):
                    _adopt_patch_sources(section, answer, sections)
                new_text, citation_ids, citation_warnings, changed_spans = _apply_patches(answer, section, instructions)
            attempt['status'] = 'applied' if new_text != section['body_text'] else 'unchanged'
            applied_spans[outline_id] = changed_spans
            warnings.extend(citation_warnings)
            if new_text != section['body_text']:
                section['body_text'] = new_text
                section['citation_ids'] = citation_ids
                review['changed_outline_ids'].append(outline_id)
                notes.append({'kind': 'body_edit', 'outline_ids': [outline_id],
                              'reason': f'《{section.get("title", outline_id)}》已完成局部修正，保留本节分析与必要限定。'})
            if callable(on_event):
                on_event({'event': 'review_section_completed', 'status': 'success', 'outline_id': outline_id})
        except Exception as exc:
            attempt.update(status='rejected', detail=str(exc) or type(exc).__name__)
            review['failed_outline_ids'].append(outline_id)
            warnings.append({**_warning('edit_failed', outline_id), 'detail': attempt['detail']})
            if callable(on_event):
                on_event({'event': 'review_section_completed', 'status': 'failed', 'outline_id': outline_id})
    # Any local edit invalidates prior checks. Recheck only changed target sections once.
    changed = [s for s in sections if isinstance(s, dict) and (s.get('outline_id') in review['changed_outline_ids']
               or consistency_rows.get(s.get('outline_id')))
               and s.get('outline_id') in claim_payloads]
    if changed:
        updated = [claim_verifier.prepare_section(section) for section in changed]
        originals = [{**{k: s.get(k, '') for k in ('outline_id', 'title', 'body_text')},
                      'authorized_edits': edits.get(s['outline_id'], []),
                      'consistency_warnings': consistency_rows.get(s['outline_id'], []),
                      **({'report_source_candidates': source_candidates} if consistency_rows.get(s['outline_id']) else {})}
                     for s in original_sections if s['outline_id'] in {x['outline_id'] for x in changed}]
        recheck_rows, recheck_failures, losses_by_id = check_claim_batches(
            updated, _query, claim_verifier.PROMPT, originals=originals)
        claim_execution_incomplete |= bool(recheck_failures)
        repaired = []
        for section, prepared in zip(changed, updated):
            oid = section['outline_id']
            checked = claim_verifier.validate_checks(prepared, recheck_rows.get(oid, []), failure_reasons=recheck_failures)
            actionable = [c for c in checked['claims'] if c['status'] in ('partial', 'unsupported', 'conflicting')]
            if not actionable or oid not in review['changed_outline_ids'] or oid in repair_used:
                continue
            # One local repair, never delete claims solely because checking failed.
            instructions = [{'reason': c['reason'], 'spans': [claim_verifier.claim_span(c, section)],
                             'keep_spans': [], 'preserve_paragraph_ids': [],
                             'instruction': '仅修正此处已指出的事实或越界归纳；保留有据分析及独有信息。依据：' + str(c['supports'])}
                            for c in actionable]
            repair_used.add(oid)
            repair_paragraphs = _paragraphs([section])
            attempt = {'outline_id': oid, 'status': 'started', 'kind': 'semantic_repair'}
            review['edit_attempts'].append(attempt)
            try:
                repair_payload = {'outline_id': oid, 'title': section.get('title', ''), 'body_text': section['body_text'],
                    'instructions': instructions, 'editable_spans': _editable_spans(instructions, repair_paragraphs),
                    'paragraphs': repair_paragraphs, 'evidence_blocks': section.get('external_evidence_blocks', []),
                    'report_facts': section.get('report_facts', []), 'repair_failure_reasons': actionable}
                answer = _query(_json(repair_payload), _EDIT_PROMPT, 5000)
                new_text, ids, patch_warnings, _ = _apply_patches(answer, section, instructions)
                warnings.extend(patch_warnings)
                attempt['status'] = 'applied' if new_text != section['body_text'] else 'unchanged'
                if new_text != section['body_text']:
                    section.update(body_text=new_text, citation_ids=ids)
                    repaired.append(section)
                    for original in originals:
                        if original['outline_id'] == oid:
                            original['authorized_edits'] = original['authorized_edits'] + instructions
            except Exception as exc:
                attempt.update(status='rejected', detail=str(exc) or type(exc).__name__)
        if repaired:
            retry_prepared = [claim_verifier.prepare_section(section) for section in repaired]
            retry_rows, retry_failures, retry_losses = check_claim_batches(retry_prepared, _query, claim_verifier.PROMPT,
                originals=[o for o in originals if o['outline_id'] in {s['outline_id'] for s in repaired}])
            claim_execution_incomplete |= bool(retry_failures)
            recheck_rows.update(retry_rows)
            recheck_failures.update(retry_failures)
            losses_by_id.update(retry_losses)
            updated = [claim_verifier.prepare_section(section) for section in changed]
        # A new unresolved sentence must not automatically erase independent
        # successful edits in other paragraphs. Each mixed candidate is checked
        # once against the full original; no stale checks certify the new text.
        localized = []
        for section, prepared in zip(changed, updated):
            oid = section['outline_id']
            loss = losses_by_id.get(oid, [])
            if not loss or not all(r.get('lost') is False and str(r.get('reason') or '').strip() for r in loss):
                continue
            checked = claim_verifier.validate_checks(prepared, recheck_rows.get(oid, []), failure_reasons=recheck_failures)
            original = next(s for s in original_sections if s['outline_id'] == oid)
            candidate = _restore_unverified_paragraphs(original, section, checked)
            if candidate is not None and oid in review['changed_outline_ids']:
                section.update(body_text=candidate, citation_ids=list(dict.fromkeys(_CITATION.findall(candidate))))
                original_paragraphs = _paragraphs([original])
                final_paragraphs = _paragraphs([section])
                applied_spans[oid] = [span for span in applied_spans.get(oid, [])
                    if final_paragraphs.get(span['paragraph_id']) != original_paragraphs.get(span['paragraph_id'])]
                localized.append(section)
                review['edit_attempts'].append({'outline_id': oid, 'kind': 'paragraph_restore',
                                               'status': 'pending_recheck'})
        if localized:
            localized_ids = {s['outline_id'] for s in localized}
            rows, failures, losses = check_claim_batches(
                [claim_verifier.prepare_section(s) for s in localized], _query, claim_verifier.PROMPT,
                originals=[o for o in originals if o['outline_id'] in localized_ids])
            claim_execution_incomplete |= bool(failures)
            for oid in localized_ids:
                recheck_rows[oid] = rows.get(oid, [])
                losses_by_id[oid] = losses.get(oid, [])
            recheck_failures.update(failures)
            updated = [claim_verifier.prepare_section(s) for s in changed]
        for section, prepared in zip(changed, updated):
            oid = section['outline_id']
            loss = losses_by_id.get(oid, [])
            valid_preservation = (bool(loss) and all(r.get('lost') is False
                                  and isinstance(r.get('reason'), str) and bool(r['reason'].strip()) for r in loss))
            checked = claim_verifier.validate_checks(prepared, recheck_rows.get(oid, []), failure_reasons=recheck_failures)
            # Failed or incomplete final checks cannot certify an automatic factual edit.
            original = next(s for s in original_sections if s['outline_id'] == oid)
            original_claims = {c['quote'] for c in original.get('claim_verification', {}).get('claims', [])}
            affected_unresolved = (prepared['omitted_claim_count'] > 0 or any(
                c['status'] not in claim_verifier.RESOLVED_STATUSES and c['quote'] not in original_claims for c in checked['claims']))
            if oid in review['changed_outline_ids'] and (not valid_preservation or affected_unresolved):
                original = next(s for s in original_sections if s['outline_id'] == oid)
                section.clear()
                section.update(copy.deepcopy(original))
                section['claim_verification']['status'] = 'needs_confirmation'
                section['claim_verification']['correction_status'] = 'reverted'
                review['changed_outline_ids'].remove(oid)
                review['failed_outline_ids'].append(oid)
                notes[:] = [n for n in notes if not (n['kind'] == 'body_edit' and oid in n['outline_ids'])]
                warnings.append({'stage': 'report_review', 'reason': 'claim_correction_reverted',
                                 'outline_id': oid, 'message': '局部修正未通过事实与信息保留复核，已恢复原文并标为待确认。',
                                 'preservation_checks': loss, 'unresolved_claim_ids': [c['claim_id'] for c in checked['claims']
                                     if c['status'] not in claim_verifier.RESOLVED_STATUSES and c['quote'] not in original_claims]})
            else:
                section['claim_verification'] = checked
                if (valid_preservation and consistency_rows.get(oid)
                        and _consistency_proven(loss, section, len(consistency_rows[oid]))):
                    for row in consistency_rows[oid]:
                        row['corrected'] = True
                    notes[:] = [n for n in notes if n not in consistency_notes[oid]]
    if repetition_edits:
        try:
            review['verification'] = _verify_edits(response['issues'], original_sections, sections, applied_spans, authorized_edits=edits)
            for row in review['verification']['unresolved']:
                for outline_id in row.get('revert_outline_ids', []):
                    if outline_id not in review['changed_outline_ids']:
                        continue
                    original = next(s for s in original_sections if s['outline_id'] == outline_id)
                    index = next(i for i, s in enumerate(sections) if s.get('outline_id') == outline_id)
                    sections[index] = copy.deepcopy(original)
                    for warning in consistency_rows.get(outline_id, []):
                        warning.pop('corrected', None)
                    for note in consistency_notes.get(outline_id, []):
                        if note not in notes:
                            notes.append(note)
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
    for attempt in review['edit_attempts']:
        if attempt.get('kind') == 'paragraph_restore':
            attempt['status'] = 'retained_after_recheck' if attempt['outline_id'] in review['changed_outline_ids'] else 'reverted'
    review['evidence_warning_count'] = sum(not row.get('corrected')
                                          for rows in consistency_rows.values() for row in rows)
    review['status'] = 'partial' if (repetition_failed or rejected or review['failed_outline_ids'] or incomplete_coverage
                                   or review['evidence_warning_count']
                                   or review['verification']['status'] in ('partial', 'failed')) else 'completed'
    result = finish()
    if callable(on_event):
        on_event({'event': 'review_completed', 'status': review['status']})
    return result

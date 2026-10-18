"""Bounded claim checks against retrieved, individually identified citation fragments."""
from __future__ import annotations

import copy
import json
import re

from ..report_facts import source_identity

_CITATION = re.compile(r'\[(C[1-9]\d*)\]')
_PRIORITY = re.compile(r'\d|最大|最小|首家|第一|领先|排名|份额|政策|条例|办法|条款|供应|合作|产品|发布|投产|量产|扩产|订单|产能|营收|业务|公司|集团|企业|厂商|旗下|用于|覆盖|合作|签约|收购|合资|路线|审批|合规|准入|资格|门槛|前置|商业化')
STATUSES = {'supported', 'not_factual', 'partial', 'unsupported', 'conflicting', 'unknown'}
RESOLVED_STATUSES = {'supported', 'not_factual'}

PROMPT = """
只返回一个JSON对象，禁止在对象外另写文字或第二个对象。对象同时包含claim_checks，以及需要时的information_loss。
同时核对claim_verification中的全部关键声明，返回claim_checks数组，每项：
{"claim_id":"输入ID","status":"supported|not_factual|partial|unsupported|conflicting|unknown","reason":"具体原因","supports":[{"evidence_id":"输入片段ID","quote":"该片段逐字原文"}]}。
不得新增或遗漏claim_id。优先核对数字、年份、排名、政策条款、企业产品和合作关系。
paragraph_context是同一paragraph_id的正文上下文，用于解析“公司”“该项目”“这一阶段”等主体与指代；批次里相邻的声明不一定相邻成文，不能用其他段落的主体覆盖当前段落。正文上下文不是外部事实证据，不能用它替代来源支持。上下文截断不代表原文不存在某内容。
引用编号只代表资料，必须核对实际片段、对象、时间、单位、统计口径及计划/预测/已实现状态。
context_citation_ids、section_citation_ids和report_facts是可选依据候选，候选中有无关图谱或其他来源不构成partial理由，只选择真正支持当前事实的片段；不要求每个候选都支持当前句。资料局限若明确限定为本次所示材料，不要求引用原文另行声明“本资料缺少某项”，但不能推广为企业或行业没有该业务。
同句多个引用以其集合共同核对各子句；只要各事实分别有对应片段支持即可，不要求每一条引用都支持句中全部企业或全部子句。
同句出现多个企业、产品或数字时逐个核对，不得用名单中部分实体支持整句；reason指出具体覆盖与缺失。任何一个具体外部事实部分缺少该句所引资料依据，最多为partial，不能supported。明确的分析归纳另行判断，不要求原文用相同措辞表达。显式引用错误时，即使其他未被该句引用的资料出现该实体，也不能借用为本句已正确引用的依据。供应商不能推出最大供应商，计划扩产不能写成已经投产。
先区分外部事实、研究方法与分析推断。not_factual仅用于完全不含外部事实断言的研究方法、取样规则、检索范围或证据边界说明，以及明确的条件假设或分析推断。例如“本节以公开业务材料选样”“未检索到不代表没有业务”“若满足条件，则可考虑合作”，无需外部片段支持，supports可为空。
混有事实与分析时，必须逐项核对全部具体事实部分，包括企业身份、业务、产品、数字、关系、时间和状态，不能用not_factual绕过事实核验；包含“可能”等措辞本身不构成not_factual，有具体事实前提仍要核对该前提。
supported表示全部外部事实部分和限定均有语义支持；分析不要求逐字出现在证据中，明确标注的条件推断、研究判断和建议本身不应仅因原文未复述而降为partial。仍须判断分析是否把未证实事实、因果关系或落地状态伪装为既成事实；这些具体断言继续按证据核对。
partial表示具体外部事实只有部分有支持；unsupported表示完整所示证据不支持具体外部事实；conflicting表示证据明确相反；截断、缺失或事实含义不明用unknown。
外部事实的支持与冲突判断必须绑定对应引用的具体片段和逐字摘录；不能用同一资料编号掩盖不同片段。无句内引用时可用context_citation_ids标明的同段引用，或section_citation_ids中本节已引事实来核对综合判断，仍须绑定支持的具体原文，不能用分析推出新增外部事实。不得覆盖错误的显式引用。纯方法和分析边界不因此判unknown。
graph类型证据只支持图谱中实际记录的实体与关系，不支持历史增长、经营、能力或落地状态。描述“图谱记录甲公司参与整机制造”包含具体关系事实，必须核对graph证据，不能判not_factual；“甲公司提供整机并参与运营，因此角色重叠”包含具体企业业务事实，也必须先核对事实前提；不要求证据逐字写出“角色重叠”这个分析结论。
纯方法说明通常不含引用；带citation_ids的具体声明不能判not_factual。supported或partial只摘足以支撑判断的最短原文，多个不连续原文分别返回supports，不拼成一条quote。
已明确“未核实/缺乏依据/计划”等边界的正文不要重复要求限定。分析推断与事实陈述分开判断。
遵守evidence_scope、review_method、review_note中的证据范围和审查限定。
不在重复issues中提出事实修改，由程序合并关键声明的最小修正。
若提供original_sections，再返回information_loss数组，每项{"outline_id":"被修改节ID","lost":false,"reason":"说明"}。
对每个被修改小节比较修改前后：original_sections.authorized_edits给出已授权删除/压缩的重复片段和无依据断言。依照这些授权删重复背景、移除错误前提或收窄无据分析不属于信息丢失；keep_spans指出报告保留处，不要求在当前节重新保留相同细节。其余独有事实、分析、计划/已实现状态、时间、范围和有效引用都必须保留；有误删或新造事实lost=true。无论本批只核对该节部分claims，都必须返回每节information_loss，不能省略。
original_sections.consistency_warnings若非空，还需对照全部新正文判断这些具体来源疑点是否已被解释或修正；在对应information_loss行增加consistency_resolved:true/false。只有全部疑点已解决且新正文未混淆对象、日期、统计口径和计划/已实现状态才为true，reason说明原因；不能因正文有改动就默认通过。同时在该information_loss行返回consistency_checks数组，逐个对应本节原始consistency_warnings的下标：{"warning_index":0,"resolved":true,"final_quote":"最终正文逐字句子","supports":[{"citation_id":"C1","quote":"该来源逐字原文"}]}。不存在修复证据则resolved=false；只返回consistency_resolved不构成已修复。
同时查看report_source_candidates中本报告其他章节已取得的资料；旧预测后有已取证、已交付、已试运行等后续节点时，不能只补旧预测日期而仍宣称当前没有后续进展。商业化交付、收费运营与试运行按各自状态区分，不互相代替。候选预览仅供发现冲突，不能把预览未展示等同于没有资料。
"""


def prepare_section(section, evidence_budget=24000):
    body, oid = section.get('body_text', ''), section['outline_id']
    section_citations = list(dict.fromkeys(_CITATION.findall(body)))
    claims, omitted = [], 0
    # Positions refer to the original string; no whitespace normalization.
    paragraph = 0
    for line in re.finditer(r'[^\n]+', body):
        if not line.group().strip():
            continue
        paragraph += 1
        paragraph_citations = list(dict.fromkeys(_CITATION.findall(line.group())))
        for sentence in re.finditer(r'[^。！？]+[。！？]?(?:\[C[1-9]\d*\])*', line.group()):
            raw_quote = sentence.group()
            quote = raw_quote.strip()
            if not quote.strip() or not _PRIORITY.search(_CITATION.sub('', quote)):
                continue
            start = line.start() + sentence.start() + len(raw_quote) - len(raw_quote.lstrip())
            claims.append({'claim_id': f'{oid}:K{len(claims)+1}', 'paragraph_id': f'{oid}:P{paragraph}',
                           'start': start, 'end': start + len(quote), 'quote': quote,
                           'citation_ids': list(dict.fromkeys(_CITATION.findall(quote))),
                           'context_citation_ids': paragraph_citations if not _CITATION.search(quote) else [],
                           'section_citation_ids': section_citations if not _CITATION.search(quote) else []})
    used = {cid for c in claims for cid in c['citation_ids'] + c['context_citation_ids'] + c['section_citation_ids']}
    evidence, incomplete, unavailable_citations = [], False, set()
    seen_sources = set()
    for number, block in enumerate(section.get('external_evidence_blocks', []), 1):
        identity = source_identity(block)
        if block.get('citation_id') not in used or identity in seen_sources:
            continue
        seen_sources.add(identity)
        raw = str(block.get('text') or '')
        # Select a relevant window of an already retrieved fragment; retain its identity.
        terms = set(re.findall(r'[\u4e00-\u9fff]{2,4}|\d{4}', ' '.join(c['quote'] for c in claims)))
        offsets = [m.start() for term in terms for m in re.finditer(re.escape(term), raw)]
        offset = max(0, min(offsets, default=0) - 300)
        size = min(4000, evidence_budget)
        if size <= 0:
            incomplete = True
            unavailable_citations.add(block['citation_id'])
            continue
        text = raw[offset:offset+size]
        truncated = offset > 0 or offset + len(text) < len(raw)
        evidence.append({'evidence_id': f'{oid}:E{number}',
                         **{k: block.get(k, '') for k in ('citation_id', 'library', 'material_id', 'document_id', 'vector_id', 'chunk_id', 'title', 'publish_date', 'source_address', 'evidence_scope', 'review_method', 'review_note')},
                         'text': text, 'text_offset': offset, 'truncated': truncated})
        evidence_budget -= len(text)
        incomplete |= truncated
        if truncated:
            unavailable_citations.add(block['citation_id'])
    for number, block in enumerate(section.get('graph_evidence_blocks', []), 1):
        if not isinstance(block, dict):
            continue
        # Keep only recorded relations, with the same IDs/names as writer input.
        segment = block.get('segment') or {}
        entities = [entity for entity in block.get('downward_entities', []) if isinstance(entity, dict)]
        compact = {'segment': {k: segment[k] for k in ('id', 'name') if k in segment},
                   'chain_path': block.get('chain_path', ''),
                   'recorded_entity_count': len(entities),
                   'entity_selection': '下列实体仅列出本节提及者，未列出不代表图谱不存在。',
                   'downward_entities': [{k: entity[k] for k in ('id', 'name', 'edge_type') if k in entity}
                                         for entity in entities if entity.get('name') and entity['name'] in body],
                   'upward_path': [{k: edge[k] for k in ('source_name', 'type', 'target_name') if k in edge}
                                   for edge in block.get('upward_path', []) if isinstance(edge, dict)]}
        text = json.dumps(compact, ensure_ascii=False, separators=(',', ':'))
        if text == '{}' or len(text) > evidence_budget:
            incomplete |= text != '{}'
            continue
        gid = f'G{number}'
        evidence.append({'evidence_id': f'{oid}:G{number}', 'citation_id': gid,
                         'evidence_type': 'graph', 'library': 'knowledge_graph',
                         'material_id': '', 'document_id': '', 'vector_id': '', 'chunk_id': '',
                         'text': text, 'truncated': False,
                         'evidence_scope': '仅证明图谱记录的实体与关系，不证明历史变化、经营、能力或落地状态。'})
        evidence_budget -= len(text)
        for claim in claims:
            graph_names = ([segment.get('name', '')] + [e.get('name', '') for e in entities]
                           + [edge.get(k, '') for edge in compact['upward_path'] for k in ('source_name', 'target_name')])
            if not claim['citation_ids'] and any(name and name in claim['quote'] for name in graph_names):
                claim['context_citation_ids'].append(gid)
    return {'outline_id': oid, 'body_text': body, 'claims': claims, 'evidence': evidence,
            'report_facts': copy.deepcopy(section.get('report_facts', [])),
            'incomplete_evidence': incomplete, 'unavailable_citation_ids': sorted(unavailable_citations), 'omitted_claim_count': omitted}


def _uncovered_list_entities(claim, supports):
    """Check explicit lists; do not infer names from arbitrary prose."""
    entities = []
    text = _CITATION.sub('', claim['quote'])
    for clause in re.split(r'[，；。]', text):
        match = re.search(r'(?:供应商|企业|公司|机构|厂商|客户|合作方|参与者|路线)(?:主要)?(?:包括|有)(.+)', clause)
        if not match or '、' not in match.group(1):
            continue
        listing = match.group(1).split('等', 1)[0]
        if (listing.startswith('与') and re.search(r'等(?:企业)?(?:达成|开展|签署|建立)', match.group(1))):
            # In '包括与甲、乙等达成合作', 与 introduces the relationship,
            # rather than belonging to the first listed company's name.
            listing = listing[1:]
        for name in re.split(r'、|/|及', listing):
            name = name.strip()
            if name and len(name) <= 30 and not name.startswith(('一批', '其他', '多家')):
                entities.append(name)
    quoted = '\n'.join(s['quote'] for s in supports)
    def covered(name):
        if name in quoted:
            return True
        # "甲、乙和丙" may end a list. Only split a conjunction when both
        # complete sides actually occur in the verified source quotations.
        return any(name[:i] and name[i+1:] and name[:i] in quoted and name[i+1:] in quoted
                   for i, char in enumerate(name) if char in '和与')
    return [name for name in dict.fromkeys(entities) if not covered(name)]


def _source_quote(quote, text):
    """Recover only whitespace differences, returning an actual source substring."""
    if not isinstance(quote, str) or not quote.strip():
        return None
    if quote in text:
        return quote
    compact = re.sub(r'\s+', '', quote)
    positions = [match.start() for match in re.finditer(r'\S', text)]
    normalized = ''.join(text[index] for index in positions)
    start = normalized.find(compact)
    if start < 0:
        return None
    return text[positions[start]:positions[start + len(compact) - 1] + 1]


def validate_checks(payload, checks, failure_reason='未返回有效的声明核对结果', failure_reasons=None):
    by_id = {}
    if isinstance(checks, list):
        for row in checks:
            if isinstance(row, dict) and isinstance(row.get('claim_id'), str):
                by_id.setdefault(row['claim_id'], []).append(row)
    evidence = {e['evidence_id']: e for e in payload['evidence']}
    claims = []
    for claim in payload['claims']:
        result = {**claim, 'status': 'unknown', 'reason': (failure_reasons or {}).get(claim['claim_id'], failure_reason), 'supports': []}
        rows = by_id.get(claim['claim_id'], [])
        result['validation_error'] = 'missing_check' if not rows else 'duplicate_check' if len(rows) > 1 else 'invalid_check'
        if len(rows) == 1:
            row, supports = rows[0], []
            result['reason'] = str(row.get('reason') or failure_reason) + '；返回的引用或逐字摘录未通过校验，仍需确认'
            valid = (row.get('status') in STATUSES and isinstance(row.get('reason'), str)
                     and bool(row['reason'].strip()) and isinstance(row.get('supports'), list))
            for support in row.get('supports', []) if isinstance(row.get('supports'), list) else []:
                e = evidence.get(support.get('evidence_id')) if isinstance(support, dict) else None
                quote = support.get('quote') if isinstance(support, dict) else None
                quote = _source_quote(quote, e['text']) if e else None
                allowed = claim['citation_ids'] or (claim.get('context_citation_ids', []) + claim.get('section_citation_ids', []))
                if not e or e['citation_id'] not in allowed or quote is None:
                    valid = False
                    break
                supports.append({k: e[k] for k in ('evidence_id', 'citation_id', 'library', 'material_id', 'document_id', 'vector_id', 'chunk_id')} | {'quote': quote})
            if row.get('status') in ('supported', 'partial', 'conflicting') and not supports:
                valid = False
            if row.get('status') == 'not_factual' and claim['citation_ids']:
                valid = False
            if valid:
                result.pop('validation_error', None)
                result.update(status=row['status'], reason=row['reason'], supports=supports)
                if row['status'] == 'supported':
                    missing = _uncovered_list_entities(claim, supports)
                    if missing:
                        result.update(status='unknown', reason=row['reason'] + '；名单措辞未能与逐字依据对应，需人工确认，不据此确定缺少证据：' + '、'.join(missing))
                if row['status'] == 'unsupported' and (bool(set(claim['citation_ids']) & set(payload.get('unavailable_citation_ids', []))) or not claim['citation_ids']
                        or not set(claim['citation_ids']) <= {e['citation_id'] for e in payload['evidence']}):
                    result.update(status='unknown', reason='证据截断、遗漏或不可用，不能据此确定不支持')
        claims.append(result)
    status = 'completed' if claims and all(c['status'] in RESOLVED_STATUSES for c in claims) and not payload['omitted_claim_count'] else 'needs_confirmation'
    if not claims and not payload['omitted_claim_count']:
        status = 'not_needed'
    return {'status': status, 'body_text': payload['body_text'], 'claims': claims,
            'omitted_claim_count': payload['omitted_claim_count'], 'incomplete_evidence': payload['incomplete_evidence']}


def claim_span(claim, section):
    """Translate original-body claim positions to the stripped paragraph view."""
    span = {'paragraph_id': claim['paragraph_id'], 'quote': claim['quote']}
    if 'start' not in claim or 'end' not in claim:
        return span
    number = 0
    for match in re.finditer(r'[^\n]+', section['body_text']):
        raw = match.group()
        if not raw.strip():
            continue
        number += 1
        if f"{section['outline_id']}:P{number}" != claim['paragraph_id']:
            continue
        offset = match.start() + len(raw) - len(raw.lstrip())
        start, end = claim['start'] - offset, claim['end'] - offset
        if not 0 <= start < end <= len(raw.strip()) or raw.strip()[start:end] != claim['quote']:
            raise ValueError('invalid_claim_position')
        return {**span, 'start': start, 'end': end}
    raise ValueError('invalid_claim_paragraph')


def merge_edits(edits, sections, results):
    merged = copy.deepcopy(edits)
    for section in sections:
        oid = section['outline_id']
        lines = {f'{oid}:P{i+1}': line.strip() for i, line in enumerate(
            line for line in section['body_text'].splitlines() if line.strip())}
        for claim in results.get(oid, {}).get('claims', []):
            if claim['status'] not in ('partial', 'unsupported', 'conflicting'):
                continue
            span = claim_span(claim, section)
            def overlaps(other):
                if other['paragraph_id'] != span['paragraph_id']:
                    return False
                text = lines.get(span['paragraph_id'], '')
                a, b = span.get('start', text.find(span['quote'])), other.get('start', text.find(other['quote']))
                return a >= 0 and b >= 0 and a < b + len(other['quote']) and b < a + len(span['quote'])
            # A repetition keep-location protects information, not erroneous wording.
            for instructions in merged.values():
                for item in instructions:
                    item['keep_spans'] = [s for s in item['keep_spans'] if not overlaps(s)]
            instruction = ('仅删除或收窄无依据断言；保留片段内所有有据事实、时间、对象、计划/已实现限定与有效引用。'
                           '事实优先于保留错误措辞，重复压缩与事实修正一次完成。依据：' + str(claim['supports']))
            matches = [item for item in merged.get(oid, []) if any(overlaps(s) for s in item['spans'])]
            if matches:
                for item in matches:
                    item['instruction'] += '\n' + claim['reason'] + '；' + instruction
                if span not in matches[0]['spans']:
                    matches[0]['spans'].append(span)
            else:
                merged.setdefault(oid, []).append({'reason': claim['reason'], 'keep_spans': [], 'spans': [span],
                    'preserve_paragraph_ids': [], 'instruction': instruction})
    return merged, []

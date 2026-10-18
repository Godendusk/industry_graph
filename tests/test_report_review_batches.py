import json
from unittest.mock import patch

from report_generation.review_agent import review_report_bodies


def sections(count=21, claims=10):
    result = []
    for i in range(count):
        oid = f'S{i + 1}.1'
        text = '\n'.join(f'第{i + 1}节公司计划2025年第{j + 1}批扩产。[C1]' for j in range(claims))
        result.append({'outline_id': oid, 'title': f'公司{i + 1}', 'status': 'success', 'body_text': text,
                       'external_evidence_blocks': [{'citation_id': 'C1', 'library': 'report',
                           'material_id': str(i), 'text': text}], 'citation_ids': ['C1']})
    return result


def run(data, query):
    with patch('report_generation.review_agent._query', side_effect=query):
        return review_report_bodies(body_sections=data, writing_tasks=[], report_title='产业', user_prompt='', references=[])


def supported(payload):
    rows = []
    for section in payload['claim_verification']:
        for c in section['claims']:
            e = section['evidence'][0]
            rows.append({'claim_id': c['claim_id'], 'status': 'supported', 'reason': '逐字支持',
                         'supports': [{'evidence_id': e['evidence_id'], 'quote': c['quote']}]})
    return {'claim_checks': rows}


def test_twenty_one_sections_all_claims_use_independent_bounded_batches():
    data, seen = sections(), []
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            assert 'sections' not in p
            assert len(p['claim_verification']) <= 3
            assert all(len(s['claims']) <= 8 for s in p['claim_verification'])
            seen.extend(c['claim_id'] for s in p['claim_verification'] for c in s['claims'])
            return supported(p)
        return {'related_section_groups': [], 'issues': []}
    result = run(data, query)
    assert len(seen) == len(set(seen)) == 210
    assert result['body_sections'][-1]['claim_verification']['status'] == 'completed'


def test_one_failed_claim_batch_keeps_later_completed_checks_and_reports_missing_reason():
    data = sections(4, 8)
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            if p['claim_verification'][0]['outline_id'] == 'S1.1':
                raise ValueError('model_output_unavailable')
            return supported(p)
        return {'issues': []}
    result = run(data, query)
    assert result['body_sections'][-1]['claim_verification']['status'] == 'completed'
    missing = result['body_sections'][0]['claim_verification']['claims']
    assert all(c['status'] == 'unknown' and '批次' in c['reason'] for c in missing)


def test_long_repetition_index_locates_duplicates_in_late_sections():
    data = sections(21, 0)
    for s in data:
        s['body_text'] = '独有行业分析。'
    data[1]['body_text'] = data[-1]['body_text'] = '联盟重复背景。独有分析。'
    saw_raw_pair, saw_index = [], []
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'section_index' in p:
            saw_index.append(True)
            assert p['section_index'][-1]['outline_id'] == 'S21.1'
            return {'related_section_groups': [['S2.1', 'S21.1']]}
        if 'editable_spans' in p:
            return {'outline_id': 'S21.1', 'patches': [{'span_index': 0, 'replacement': ''}]}
        if 'issues' in p and 'original_sections' in p:
            return {'resolved_issue_indexes': [0], 'unresolved': []}
        ids = {s['outline_id'] for s in p['sections']}
        if ids == {'S1.1', 'S2.1', 'S3.1'}:
            return {'issues': [], 'evidence_warnings': [{'outline_id': 'missing', 'reason': '无效位置', 'citation_ids': []}]}
        if {'S2.1', 'S21.1'} <= ids:
            saw_raw_pair.append(True)
            return {'issues': [{'reason': '联盟背景重复', 'keep_spans': [{'paragraph_id': 'S2.1:P1', 'quote': '联盟重复背景。'}],
                'edits': [{'outline_id': 'S21.1', 'spans': [{'paragraph_id': 'S21.1:P1', 'quote': '联盟重复背景。'}],
                           'instruction': '删除重复背景', 'preserve_paragraph_ids': []}]}]}
        return {'issues': []}
    result = run(data, query)
    assert saw_raw_pair and saw_index
    assert result['body_sections'][-1]['body_text'] == '独有分析。'


def test_repetition_failure_does_not_discard_successful_claim_batches():
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            return supported(p)
        raise ValueError('model_output_truncated')
    result = run(sections(1, 2), query)
    assert result['body_sections'][0]['claim_verification']['status'] == 'completed'


def test_truncated_claim_batch_is_split_once_without_repeating_successes():
    seen = []
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' not in p:
            return {'issues': []}
        claims = [c for s in p['claim_verification'] for c in s['claims']]
        seen.append([c['claim_id'] for c in claims])
        if len(claims) > 4:
            raise ValueError('model_output_truncated')
        return supported(p)
    result = run(sections(1, 8), query)
    assert [len(ids) for ids in seen] == [8, 4, 4]
    assert result['body_sections'][0]['claim_verification']['status'] == 'completed'


def test_all_thirty_claims_are_assigned_to_batches_instead_of_omitted():
    seen = []
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            seen.extend(c['claim_id'] for s in p['claim_verification'] for c in s['claims'])
            return supported(p)
        return {'issues': []}
    result = run(sections(1, 30), query)
    assert len(seen) == len(set(seen)) == 30
    assert result['body_sections'][0]['claim_verification']['omitted_claim_count'] == 0


def test_batches_propagate_runtime_context_and_use_at_most_two_workers():
    from report_generation.runtime_budget import RuntimeBudget, current_budget
    import threading
    budget = RuntimeBudget()
    lock = threading.Lock()
    rendezvous = threading.Barrier(2)
    active = [0]
    maximum = [0]
    def query(text, prompt, tokens):
        p = json.loads(text)
        assert current_budget() is budget
        if 'claim_verification' in p:
            with lock:
                active[0] += 1
                maximum[0] = max(maximum[0], active[0])
            rendezvous.wait(timeout=2)
            with lock:
                active[0] -= 1
            return supported(p)
        return {'issues': []}
    with budget.activate('review'):
        result = run(sections(4, 8), query)
    assert maximum[0] == 2
    assert all(s['claim_verification']['status'] == 'completed' for s in result['body_sections'])


def test_claim_deletion_still_checks_information_loss_when_no_claims_remain():
    data = sections(1, 1)
    data[0]['body_text'] += '\n独有分析。'
    def query(text, prompt, tokens):
        p = json.loads(text)
        if 'claim_verification' in p:
            if 'original_sections' in p:
                assert not p['claim_verification'][0]['claims']
                assert p['claim_verification'][0]['body_text'] == '\n独有分析。'
                assert p['original_sections'][0]['body_text'] == data[0]['body_text']
                return {'claim_checks': [], 'information_loss': [{'outline_id': 'S1.1', 'lost': False, 'reason': '独有分析保留'}]}
            answer = supported(p)
            answer['claim_checks'][0].update(status='unsupported', reason='完整证据未支持')
            return answer
        if 'editable_spans' in p:
            return {'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': ''}]}
        return {'issues': []}
    result = run(data, query)
    assert result['body_sections'][0]['body_text'].strip() == '独有分析。'
    assert result['review']['changed_outline_ids'] == ['S1.1']


def test_long_single_paragraph_uses_raw_position_windows_without_truncating_tail():
    data = sections(1, 0)
    data[0]['body_text'] = '独有分析。' * 20000 + '报告末尾独有内容。'
    covered = []
    def query(text, prompt, tokens):
        assert len(text) <= 86000
        p = json.loads(text)
        if 'section_index' in p:
            return {'related_section_groups': []}
        for s in p['sections']:
            covered.extend(s['paragraphs'])
        return {'issues': []}
    result = run(data, query)
    assert result['review']['status'] == 'completed'
    assert any('报告末尾独有内容。' in ''.join(s['text'] for s in p['sentences']) for p in covered)
    assert all(''.join(s['text'] for s in p['sentences']) == data[0]['body_text'][p['start']:p['end']] for p in covered)


def test_recheck_groups_account_for_both_complete_bodies_in_input_budget():
    from report_generation.review_batches import check_claim_batches
    from report_generation.agentic_rag.verification import prepare_section
    data = sections(3, 1)
    for section in data:
        section['body_text'] += '\n' + '独有分析。' * 4500
    prepared = [prepare_section(section) for section in data]
    seen = []
    def query(text, prompt, tokens):
        assert len(text) <= 86000
        payload = json.loads(text)
        seen.append(payload)
        for section in payload['claim_verification']:
            original = next(s for s in payload['original_sections'] if s['outline_id'] == section['outline_id'])
            assert section['body_text'] == original['body_text']
            assert section['body_text'].endswith('独有分析。')
        return supported(payload)
    rows, failures, _ = check_claim_batches(prepared, query, '', originals=data)
    assert len(seen) >= 2
    assert len(rows) == 3 and not failures


def test_initial_claim_checks_keep_full_bodies_out_of_compact_payload():
    from report_generation.review_batches import check_claim_batches
    from report_generation.agentic_rag.verification import prepare_section
    seen = []
    def query(text, prompt, tokens):
        payload = json.loads(text)
        seen.append(payload)
        assert all('body_text' not in s for s in payload['claim_verification'])
        assert 'original_sections' not in payload
        return supported(payload)
    rows, failures, _ = check_claim_batches([prepare_section(sections(1, 1)[0])], query, '')
    assert seen and rows['S1.1'][0]['status'] == 'supported' and not failures


def test_preservation_recheck_receives_authorized_removals():
    from report_generation.review_batches import check_claim_batches
    from report_generation.agentic_rag.verification import prepare_section
    s = {'outline_id': 'S1.1', 'body_text': '甲公司业务比较。', 'external_evidence_blocks': []}
    original = {'outline_id': 'S1.1', 'body_text': '甲公司业务比较。重复的业务背景。',
                'authorized_edits': [{'instruction': '删重复背景', 'spans': [{'quote': '重复的业务背景。'}]}]}
    seen = []
    def query(payload, *args):
        seen.append(json.loads(payload))
        return {'claim_checks': []}
    check_claim_batches([prepare_section(s)], query, '检查', originals=[original])
    assert seen[0]['original_sections'][0]['authorized_edits'] == original['authorized_edits']


def test_missing_claims_retry_only_missing_once_and_keep_valid_rows():
    from report_generation.review_batches import check_claim_batches
    from report_generation.agentic_rag.verification import prepare_section
    calls = []
    def query(text, prompt, tokens):
        p = json.loads(text); calls.append(p)
        answer = supported(p)
        if len(calls) == 1:
            answer['claim_checks'] = answer['claim_checks'][:1]
        return answer
    prepared = [prepare_section(s) for s in sections(1, 3)]
    rows, failures, _ = check_claim_batches(prepared, query, '')
    assert len(calls) == 2
    assert len(calls[1]['claim_verification'][0]['claims']) == 2
    assert not failures
    assert len(rows['S1.1']) == 3
    assert all(row['status'] == 'supported' for row in rows['S1.1'])


def test_missing_claim_retry_does_not_repeat_or_accept_duplicate_rows():
    from report_generation.review_batches import check_claim_batches
    from report_generation.agentic_rag.verification import prepare_section
    calls = []
    def query(text, prompt, tokens):
        p = json.loads(text); calls.append(p)
        answer = supported(p)
        if len(calls) == 1:
            answer['claim_checks'] = [answer['claim_checks'][0]] * 2
        else:
            answer['claim_checks'] = []
        return answer
    prepared = [prepare_section(s) for s in sections(1, 2)]
    rows, failures, _ = check_claim_batches(prepared, query, '')
    assert len(calls) == 2
    assert len(rows['S1.1']) == 2
    assert all(row['status'] == 'unknown' for row in rows['S1.1'])
    assert len(failures) == 2


def test_parse_failure_uses_one_retry_but_does_not_retry_transport_failure():
    from report_generation.review_batches import check_claim_batches
    from report_generation.agentic_rag.verification import prepare_section
    calls = []
    def query(text, prompt, tokens):
        p = json.loads(text); calls.append(p)
        if len(calls) == 1:
            raise ValueError('无法解析JSON对象')
        return supported(p)
    rows, failures, _ = check_claim_batches([prepare_section(s) for s in sections(1, 1)], query, '')
    assert len(calls) == 2 and not failures
    assert rows['S1.1'][0]['status'] == 'supported'


def test_initial_claim_batch_keeps_current_paragraph_for_subject_resolution():
    from report_generation.agentic_rag.verification import prepare_section
    from report_generation.review_batches import claim_batches, _claim_payload
    text = '纵横通信将深化低空经济战略。[C1]\n\n中航高科的位置体现在组织安排。2024年，公司新设控股子公司。[C2]'
    s = {'outline_id': 'S1.1', 'body_text': text, 'external_evidence_blocks': [
        {'citation_id': 'C1', 'text': '纵横通信将深化低空经济战略。'},
        {'citation_id': 'C2', 'text': '中航高科2024年新设控股子公司。'}]}
    batch = claim_batches([prepare_section(s)])[0]
    wire = _claim_payload(batch)['claim_verification'][0]
    assert 'body_text' not in wire
    contexts = wire['paragraph_context']
    current = next(p for p in contexts if p['paragraph_id'] == 'S1.1:P2')
    assert current['text'] == text.split('\n\n')[1]
    assert '纵横通信' not in current['text']
    assert text[current['start']:current['end']] == current['text']


def test_long_paragraph_context_retains_subject_and_claim_neighbors_within_input_budget():
    from report_generation.agentic_rag.verification import prepare_section
    from report_generation.review_batches import claim_batches, _claim_payload
    text = '甲公司是本段研究对象。' + '背景信息。' * 10000 + '公司于2025年投产。[C1]随后扩大供货。'
    s = {'outline_id': 'S1.1', 'body_text': text, 'external_evidence_blocks': [
        {'citation_id': 'C1', 'text': '甲公司于2025年投产。'}]}
    prepared = prepare_section(s)
    for batch in claim_batches([prepared]):
        wire = _claim_payload(batch)
        assert len(json.dumps(wire,ensure_ascii=False,separators=(',',':'))) <= 86000
        contexts = wire['claim_verification'][0]['paragraph_context']
        assert any('甲公司是本段研究对象。' in p['text'] for p in contexts)
        assert any('随后扩大供货。' in p['text'] for p in contexts)
        assert all(text[p['start']:p['end']] == p['text'] for p in contexts)
        assert any(p['truncated'] for p in contexts)

import json

from report_generation import review_agent


def test_numbered_span_targets_second_identical_sentence_only():
    body = '重复背景。[C1]独有分析。重复背景。[C1]'
    payload = {'sections': [{'outline_id': 'S1.1', 'paragraphs': [{'id': 'S1.1:P1', 'text': body}]}]}
    def query(prompt, system_prompt, max_tokens):
        wire = json.loads(prompt)
        sentences = wire['sections'][0]['paragraphs'][0]['sentences']
        assert ''.join(s['text'] for s in sentences) == body
        return {'issues': [{'reason': '同段重复', 'keep_spans': [{'span_id': sentences[0]['span_id']}],
            'edits': [{'outline_id': 'S1.1', 'spans': [{'span_id': sentences[-1]['span_id']}],
                       'instruction': '删除重复介绍', 'preserve_paragraph_ids': []}]}]}
    response = review_agent._repetition_query(query)(json.dumps(payload), '', 100)
    paragraphs = {'S1.1:P1': body}
    edits, _, rejected = review_agent._validate_issues(response, paragraphs, None)
    assert rejected == []
    result = review_agent._apply_patches({'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': ''}]},
        {'outline_id': 'S1.1', 'body_text': body, 'external_evidence_blocks': [{'citation_id': 'C1'}]}, edits['S1.1'])
    assert result[0] == '重复背景。[C1]独有分析。'


def test_unknown_span_id_does_not_authorize_any_text():
    payload = {'sections': [{'outline_id': 'S1.1', 'paragraphs': [{'id': 'S1.1:P1', 'text': '真实原文。'}]}]}
    response = review_agent._repetition_query(lambda *args: {'issues': [{'reason': '重复',
        'keep_spans': [{'span_id': '不存在'}], 'edits': []}]})(json.dumps(payload), '', 100)
    try:
        review_agent._validate_issues(response, {'S1.1:P1': '真实原文。'}, None)
    except ValueError as exc:
        assert 'invalid_span' in str(exc)
    else:
        raise AssertionError('unknown ID accepted')


def test_window_span_offsets_refer_to_original_paragraph():
    body = '前文。末尾独有结论。[C1]'
    payload = {'sections': [{'outline_id': 'S1.1', 'paragraphs': [{'id': 'S1.1:P1', 'text': body[3:], 'start': 3}]}]}
    def query(prompt, *args):
        spans = json.loads(prompt)['sections'][0]['paragraphs'][0]['sentences']
        return {'issues': [{'keep_spans': [{'span_id': spans[0]['span_id']}], 'edits': []}]}
    response = review_agent._repetition_query(query)(json.dumps(payload), '', 100)
    span = response['issues'][0]['keep_spans'][0]
    assert review_agent._span_range(span, {'S1.1:P1': body}) == (3, len(body))


def test_factual_correction_does_not_unprotect_a_different_identical_occurrence():
    from report_generation.agentic_rag.verification import merge_edits
    body = '公司已投产。[C1]独有分析。公司已投产。[C1]'
    quote = '公司已投产。[C1]'
    start = body.rfind(quote)
    protected = {'paragraph_id': 'S1.1:P1', 'quote': quote, 'start': start, 'end': len(body)}
    edits = {'S1.1': [{'reason': '重复', 'keep_spans': [protected], 'spans': [], 'instruction': ''}]}
    claims = {'S1.1': {'claims': [{'status': 'conflicting', 'paragraph_id': 'S1.1:P1',
        'quote': quote, 'reason': '第一处有误', 'supports': []}]}}
    merged, _ = merge_edits(edits, [{'outline_id': 'S1.1', 'body_text': body}], claims)
    assert merged['S1.1'][0]['keep_spans'] == [protected]


def test_malformed_issue_does_not_discard_valid_numbered_issue_in_same_batch():
    payload = {'sections': [{'outline_id': 'S1.1', 'paragraphs': [{'id': 'S1.1:P1', 'text': '保留事实。重复事实。'}]}]}
    def query(prompt, *args):
        spans = json.loads(prompt)['sections'][0]['paragraphs'][0]['sentences']
        return {'issues': [{'reason': '格式错', 'edits': None}, {'reason': '重复',
            'keep_spans': [{'span_id': spans[0]['span_id']}], 'edits': [{'outline_id': 'S1.1',
            'spans': [{'span_id': spans[1]['span_id']}], 'instruction': '压缩', 'preserve_paragraph_ids': []}]}]}
    response = review_agent._repetition_query(query)(json.dumps(payload), '', 100)
    _, accepted, rejected = review_agent._validate_issues(response, {'S1.1:P1': '保留事实。重复事实。'}, None)
    assert len(accepted) == 1
    assert rejected == [0]


def test_real_claim_positions_survive_merge_on_second_paragraph_and_second_occurrence():
    from report_generation.agentic_rag.verification import prepare_section, merge_edits
    body = '背景介绍。\n\n  公司已投产。[C1]独有分析。公司已投产。[C1]  '
    section = {'outline_id': 'S1.1', 'body_text': body, 'status': 'success'}
    claims = prepare_section(section)['claims']
    claim = {**claims[-1], 'status': 'conflicting', 'reason': '应为计划', 'supports': []}
    paragraphs = review_agent._paragraphs([section])
    quote = claim['quote']; start = paragraphs['S1.1:P2'].rfind(quote)
    span = {'paragraph_id': 'S1.1:P2', 'quote': quote, 'start': start, 'end': start + len(quote)}
    edits = {'S1.1': [{'reason': '去重', 'keep_spans': [], 'spans': [span], 'instruction': ''}]}
    merged, _ = merge_edits(edits, [section], {'S1.1': {'claims': [claim]}})
    targets = review_agent._editable_spans(merged['S1.1'], paragraphs)
    assert len(targets) == 1
    assert targets[0]['start'] == start
    result = review_agent._apply_patches({'outline_id': 'S1.1', 'patches': [{'span_index': 0, 'replacement': ''}]},section,merged['S1.1'])
    assert result[0] == '背景介绍。\n\n  公司已投产。[C1]独有分析。  '

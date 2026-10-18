from report_generation.citations import validate_body_citations, collect_used_references


def test_bare_source_codes_are_bound_only_to_real_section_evidence():
    text, ids, warnings = validate_body_citations('C43指出计划，另见 C7。',
                                                 [{'citation_id': 'C43'}])
    assert '[C43]' in text
    assert ids == ['C43']
    assert any(w.get('unresolved_citation_ids') == ['C7'] for w in warnings)


def test_reference_collection_recovers_markers_from_actual_body():
    assert collect_used_references([{'status': 'success', 'body_text': '产品[C2]',
                                     'citation_ids': []}], [{'citation_id': 'C2'}]) == [{'citation_id': 'C2'}]

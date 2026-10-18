import pytest
from report_generation.structured_output import parse_json_object


def test_single_json_object_allows_trailing_explanation():
    assert parse_json_object('{"claim_checks":[]}\n以上为核对结果。') == {'claim_checks': []}


def test_two_json_objects_are_not_silently_accepted():
    with pytest.raises(ValueError):
        parse_json_object('{"claim_checks":[]}\n{"claim_checks":[{}]}')

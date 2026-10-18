from tools.sea_pilot import is_relevant, merge_records, split_chunks


def test_keeps_marine_industry_article():
    assert is_relevant({'title': '海洋经济发展提速', 'summary': '海洋牧场和海上风电带动产业增长', 'content': '相关项目建设中。'})


def test_drops_unrelated_military_article():
    assert not is_relevant({'title': '海军舰艇演习', 'summary': '军事行动', 'content': '海上武器训练。'})


def test_chunks_are_bounded_and_labeled():
    chunks = split_chunks('海洋产业报告', '海洋经济发展。' * 200, max_chars=500)
    assert chunks and all(len(c['document']) <= 500 for c in chunks)
    assert all(c['metadata']['title'] == '海洋产业报告' for c in chunks)


def test_source_id_deduplication():
    assert len(merge_records([{'id': 'a'}, {'id': 'a'}])) == 1

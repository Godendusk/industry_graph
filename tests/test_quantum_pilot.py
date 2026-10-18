from tools.quantum_pilot import is_relevant, merge_records, split_chunks


def test_keeps_quantum_technology_article():
    assert is_relevant({'title': '量子计算技术取得新进展', 'summary': '超导量子比特与量子芯片研究', 'content': '量子计算机实验取得进展。'})


def test_drops_quantum_pseudoscience_product():
    assert not is_relevant({'title': '量子养生杯促销', 'summary': '量子水产品', 'content': '消费产品广告。'})


def test_chunks_are_bounded_and_labeled():
    chunks = split_chunks('量子科技报告', '量子计算取得进展。' * 200, max_chars=500)
    assert chunks and all(len(c['document']) <= 500 for c in chunks)
    assert all(c['metadata']['title'] == '量子科技报告' for c in chunks)


def test_source_id_deduplication():
    assert len(merge_records([{'id': 'a'}, {'id': 'a'}])) == 1


def test_drops_body_only_quantum_mention_when_headline_is_unrelated():
    record = {'title': '上海创投月报', 'summary': '本月私募基金募资增加。', 'content': '文末顺带提及量子计算企业融资。'}
    assert not is_relevant(record)


def test_drops_quantum_consciousness_article():
    record = {'title': '宇宙间的量子意识交互', 'summary': '意识波研究', 'content': '正文提到量子纠缠。'}
    assert not is_relevant(record)


def test_keeps_broad_quantum_research_headline():
    record = {'title': '中国科大团队瞄准量子研究', 'summary': '科研团队取得进展。', 'content': '研究成果。'}
    assert is_relevant(record)


def test_drops_generic_multitopic_headline_with_quantum_in_summary():
    record = {
        'title': '明日主题前瞻：芯片材料与机器人',
        'summary': '金刚石散热、机器人和自主超导量子计算机均有进展。',
        'content': '多主题资讯。',
    }
    assert not is_relevant(record)


def test_long_summary_does_not_make_chunks_exceed_limit():
    chunks = split_chunks('Quantum Computing Stocks', 'Quantum research advances. ' * 100, 'Summary ' * 200, max_chars=500)
    assert chunks and all(len(c['document']) <= 500 for c in chunks)

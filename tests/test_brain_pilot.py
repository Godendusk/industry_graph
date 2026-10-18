from tools.brain_pilot import is_relevant, merge_records, split_chunks


def test_keeps_explicit_brain_interface_topics():
    assert is_relevant({'title': '脑机接口迈入医疗器械时代'})
    assert is_relevant({'title': '神经接口技术帮助瘫痪患者控制机械臂'})
    assert is_relevant({'title': 'Neuralink植入式脑机接口临床进展'})
    assert is_relevant({'title': '脑控假肢实现精细动作'})


def test_keeps_bci_only_with_neural_context():
    assert is_relevant({'title': 'BCI脑信号解码设备进入临床'})
    assert not is_relevant({'title': 'BCI Chairman apologises to law students'})


def test_drops_generic_brain_science_and_body_only_mention():
    assert not is_relevant({'title': '本周脑科学研究有哪些发现？'})
    assert not is_relevant({'title': '人工智能与物联网创新峰会', 'content': '会议提及脑机接口。'})
    assert not is_relevant({'title': 'Meta AI chief willing to wait to have kids till Neuralink'})


def test_chunks_bounded_and_ids_deduplicated():
    chunks = split_chunks('脑机接口报告', '脑信号解码取得进展。' * 200, max_chars=500)
    assert chunks and all(len(x['document']) <= 500 for x in chunks)
    assert len(merge_records([{'id': 'a'}, {'id': 'a'}])) == 1

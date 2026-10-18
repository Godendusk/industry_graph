from tools.biology_pilot import is_relevant, merge_records, split_chunks


def test_keeps_explicit_biomanufacturing_and_synthetic_biology():
    assert is_relevant({'title': '生物制造产业创新蓄力提质加速'})
    assert is_relevant({'title': '合成生物学驱动新型材料产业化'})


def test_keeps_specific_manufacturing_technology():
    assert is_relevant({'title': '细胞工厂实现麦角硫因规模化生产'})
    assert is_relevant({'title': '精准发酵助推替代蛋白量产'})
    assert is_relevant({'title': '生物基材料用于绿色纺织面料'})


def test_drops_generic_biotech_finance_and_unrelated_news():
    assert not is_relevant({'title': '金斯瑞生物科技拟拆分子公司独立上市'})
    assert not is_relevant({'title': 'Senate panel OKs proposed Ombudsman budget'})
    assert not is_relevant({'title': 'AI制药铲子第一股，暴涨'})


def test_drops_body_only_mention_and_product_marketing():
    assert not is_relevant({'title': '某地科创产业园动态', 'content': '园区企业涉及生物制造。'})
    assert not is_relevant({'title': '2026麦角硫因哪个品牌好：剂量与纯度排行榜'})


def test_chunks_bounded_and_source_ids_deduplicated():
    chunks = split_chunks('生物制造报告', '细胞工厂实现生产。' * 200, max_chars=500)
    assert chunks and all(len(c['document']) <= 500 for c in chunks)
    assert len(merge_records([{'id': 'a'}, {'id': 'a'}])) == 1

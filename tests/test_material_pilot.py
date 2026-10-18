from tools.material_pilot import is_relevant, merge_records, split_chunks


def test_keeps_material_technology_and_industry():
    assert is_relevant({'title': '新材料产业基地推进高性能复合材料量产'})
    assert is_relevant({'title': '全固态电池固态电解质进入中试阶段'})
    assert is_relevant({'title': '镁合金防腐处理取得新突破'})
    assert is_relevant({'title': '碳纤维复合材料用于航空结构件'})


def test_drops_stock_and_company_notices():
    assert not is_relevant({'title': '某新材料股份有限公司关于控股股东持股变更的公告'})
    assert not is_relevant({'title': '宝武镁业中报解读：镁合金销量增长，净利润下降'})
    assert not is_relevant({'title': '全固态电池概念股名单出炉，14股或有机会'})
    assert not is_relevant({'title': '中证新材料主题ETF获净申购'})
    assert not is_relevant({'title': '恒越新材料精选混合即将首发'})
    assert not is_relevant({'title': '金属新材料指数跌2%跑输上证指数'})
    assert not is_relevant({'title': '上证早知道：碳纤维巨头动作与汽车板块涨跌'})
    assert not is_relevant({'title': '新股消息：复合材料企业冲刺科创板'})
    assert not is_relevant({'title': '某新材料企业董事长确认出席财经论坛'})
    assert not is_relevant({'title': '铸造铝合金期货和期权上市'})
    assert not is_relevant({'title': '新材料产业园工程招标中标候选人公告'})


def test_drops_generic_material_word_and_body_only_mentions():
    assert not is_relevant({'title': '国家标准申报材料提交指南'})
    assert not is_relevant({'title': '某地产业服务体系升级', 'content': '正文提到碳纤维。'})


def test_chunks_bounded_and_ids_deduplicated():
    chunks=split_chunks('新材料报告', '复合材料实现量产。'*200, max_chars=500)
    assert chunks and all(len(x['document']) <= 500 for x in chunks)
    assert len(merge_records([{'id':'a'},{'id':'a'}])) == 1

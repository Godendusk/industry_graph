from tools.low_altitude_pilot import is_relevant, merge_records, split_chunks


def test_relevance_keeps_low_altitude_business_article():
    record = {"title": "低空经济基础设施建设提速", "summary": "通感一体和飞行服务平台推动产业发展", "content": "面向城市低空物流和巡检应用。"}
    assert is_relevant(record)


def test_relevance_drops_obvious_unrelated_war_article():
    record = {"title": "俄乌战争中的无人机战术", "summary": "战场武器和军事行动", "content": "军事装备。"}
    assert not is_relevant(record)


def test_relevance_drops_body_only_drone_mention():
    record = {"title": "俄罗斯与乌克兰局势新进展", "content": "正文顺带提及无人机。"}
    assert not is_relevant(record)


def test_relevance_drops_military_drone_headline():
    assert not is_relevant({"title": "乌军无人机袭击俄军阵地"})


def test_relevance_keeps_industry_headlines_with_different_terms():
    assert is_relevant({"title": "垂直起降飞行器创新共同体在天津成立"})
    assert is_relevant({"title": "民用无人驾驶航空发展国际论坛举行"})


def test_split_chunks_keeps_title_and_bounded_text():
    chunks = split_chunks("低空经济报告", "第一段内容。" * 300, max_chars=500)
    assert chunks
    assert all(len(item["document"]) <= 500 for item in chunks)
    assert all(item["metadata"]["title"] == "低空经济报告" for item in chunks)


def test_merge_records_deduplicates_source_ids():
    records = [{"id": "a", "title": "A", "content": "正文"}, {"id": "a", "title": "A2", "content": "正文2"}]
    merged = merge_records(records)
    assert len(merged) == 1
    assert merged[0]["id"] == "a"

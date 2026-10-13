from report_generation import graph_retriever as gr


def test_report_query_drops_global_requirement_but_keeps_section_focus():
    query = '用户需求：全篇研究芯片、制造与运输\n这里还有多行全局要求\n报告标题：产业研判\n当前一级标题：商业化\n当前二级标题：仓储物流\n检索目标：验证场景需求'
    focused = gr._focus_graph_query(query)
    assert '全篇研究' not in focused
    assert '多行全局要求' not in focused
    assert '报告标题：产业研判' in focused
    assert '当前二级标题：仓储物流' in focused
    assert '检索目标：验证场景需求' in focused


def test_plain_query_and_explicit_rewrite_request_are_preserved():
    assert gr._focus_graph_query('工业制造与能源电力') == '工业制造与能源电力'
    query = '用户重写要求：改为分析量子通信\n报告标题：量子产业\n当前二级标题：量子计算'
    assert '用户重写要求：改为分析量子通信' in gr._focus_graph_query(query)


def test_prefilter_keeps_relevant_paths_and_caps_candidates():
    rows = [f'ID: {i} | Level: 3 | 路径: 上游 > 核心器件 > 芯片设计{i}' for i in range(20)]
    rows += [f'ID: {i} | Level: 3 | 路径: 下游 > 应用场景 > 仓储物流{i}' for i in range(20, 40)]
    candidates, mode = gr._prefilter_terminal_rows(rows, '芯片设计环节')
    assert mode == 'keyword'
    assert len(candidates) == 15
    assert all('芯片设计' in row for row in candidates)


def test_weak_or_missing_matches_keep_full_list():
    rows = [f'ID: {i} | Level: 3 | 路径: 上游 > 核心器件 > 芯片设计{i}' for i in range(20)]
    for query in ['资源禀赋与能力基础', '芯片以外的技术']:
        candidates, mode = gr._prefilter_terminal_rows(rows, query)
        assert candidates == rows
        assert mode == 'full_fallback'


def test_global_title_does_not_drive_keyword_prefilter():
    assert gr._graph_candidate_focus('报告标题：芯片产业研判\n当前一级标题：产业链\n当前二级标题：仓储物流\n检索目标：相关技术与政策') == '仓储物流'


def test_industry_name_alone_does_not_narrow_to_arbitrary_intelligent_nodes():
    rows = [f'ID: {i} | Level: 3 | 路径: 中游 > 具身智能模型 > 智能控制{i}' for i in range(20)]
    candidates, mode = gr._prefilter_terminal_rows(rows, '具身智能产业演进阶段与驱动因素')
    assert candidates == rows
    assert mode == 'full_fallback'


def test_model_cannot_select_node_outside_sent_candidates():
    from unittest.mock import patch
    from pathlib import Path
    graph = gr._IndustryGraph(Path(__file__).parent / 'fixtures/mixed_depth_graph.json')
    rows = [f'ID: {i} | Level: 3 | 路径: 上游 > 芯片设计 > 芯片封装{i}' for i in range(100, 120)]
    rows.append('ID: 40 | Level: 5 | 路径: 下游 > 五级叶子')
    with patch.object(graph, 'terminal_prompt_rows', return_value=rows), patch.object(gr.llm, 'query', return_value='[40]'):
        result = gr._select_terminal_segments_with_llm('芯片设计与封装', graph, '测试产业')
    assert result['status'] == 'error'
    assert result['diagnostics']['sent_candidates'] == 15

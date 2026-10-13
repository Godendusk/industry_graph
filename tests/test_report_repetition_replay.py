import unittest

from report_generation.material_allocator import allocate_evidence_blocks


def _block(material_id, vector_id, rank, title):
    return {
        "library": "policy",
        "material_id": material_id,
        "vector_id": vector_id,
        "rank": rank,
        "title": title,
        "text": f"{title}片段",
    }


class ReportRepetitionReplayTest(unittest.TestCase):
    def test_replay_keeps_evidence_and_spreads_materials(self):
        sections = [
            {
                "outline_id": "S1.1",
                "parent_level1_id": "S1",
                "candidates": [
                    _block("m1", "v11", 1, "标准体系"),
                    _block("m2", "v12", 2, "产业报告"),
                ],
            },
            {
                "outline_id": "S2.1",
                "parent_level1_id": "S2",
                "candidates": [
                    _block("m1", "v21", 1, "标准体系"),
                    _block("m3", "v22", 2, "应用案例"),
                ],
            },
        ]

        allocated = allocate_evidence_blocks(sections, target_per_section=10)

        self.assertTrue(all(row["evidence_blocks"] for row in allocated))
        self.assertEqual(
            [row["material_id"] for row in allocated[1]["evidence_blocks"]],
            ["m3", "m1"],
        )
        for row in allocated:
            vectors = [block["vector_id"] for block in row["evidence_blocks"]]
            self.assertEqual(len(vectors), len(set(vectors)))

    def test_replay_reports_cross_level1_source_reuse_without_treating_it_as_error(self):
        sections = [
            {"outline_id": "S1.1", "parent_level1_id": "S1", "candidates": [_block("m1", "v1", 1, "权威政策")]},
            {"outline_id": "S2.1", "parent_level1_id": "S2", "candidates": [_block("m1", "v2", 1, "权威政策")]},
        ]

        allocated = allocate_evidence_blocks(sections, target_per_section=10)
        source_use = {
            block["material_id"]: set()
            for row in allocated
            for block in row["evidence_blocks"]
        }
        for row in allocated:
            for block in row["evidence_blocks"]:
                source_use[block["material_id"]].add(row["parent_level1_id"])

        self.assertEqual(source_use["m1"], {"S1", "S2"})
        self.assertEqual(allocated[1]["diagnostics"]["reused_material_ids"], ["policy:m1"])


if __name__ == "__main__":
    unittest.main()


def test_real_history_financing_is_selected_after_other_citations():
    import json
    from pathlib import Path
    from report_generation.repetition_context import build_prior_context, build_fact_records
    fixture = json.loads((Path(__file__).parent/'fixtures/report_repetition_20261002.json').read_text())
    assert fixture['candidate_pool_available'] is False
    task = next(t for t in fixture['writing_tasks'] if t['outline_id']=='S1.2')
    prior = [fixture['body_sections'][0]]
    assert any('80%' in row['sentence'] for row in build_fact_records(prior))
    assert '80%' in build_prior_context(prior,task)['text']


def test_real_history_alliance_matches_c17_without_shared_id():
    import json
    from pathlib import Path
    from report_generation.repetition_context import build_prior_context
    fixture=json.loads((Path(__file__).parent/'fixtures/report_repetition_20261002.json').read_text())
    task=next(t for t in fixture['writing_tasks'] if t['outline_id']=='S5.2')
    task['external_rag_retrieval']['evidence_blocks']=[b for b in task['external_rag_retrieval']['evidence_blocks'] if b['citation_id']=='C17']
    task['repetition_focus_terms']=['中国移动','具身智能产业联盟']
    prior=[s for s in fixture['body_sections'] if s['outline_id']=='S3.1']
    context=build_prior_context(prior,task)
    assert '中国移动牵头成立具身智能产业联盟' in context['text']
    assert '[C15][C14]' in context['text']


def test_real_history_malformed_marker_keeps_statement_without_guessed_source():
    import json
    from pathlib import Path
    from report_generation.citations import validate_body_citations
    fixture=json.loads((Path(__file__).parent/'fixtures/report_repetition_20261002.json').read_text())
    section=next(s for s in fixture['body_sections'] if s['outline_id']=='S4.2')
    text, used, warnings=validate_body_citations(section['body_text'],section['external_evidence_blocks'])
    assert text==section['body_text'].replace('[citation:4]','')
    assert 'C4' not in used
    assert any(w.get('malformed_citation_markers')==['[citation:4]'] for w in warnings)


def test_real_materials_with_synthetic_decisions_coordinate_without_losing_evidence():
    import copy
    import json
    from pathlib import Path
    from unittest.mock import patch
    from llm_client import LLMQueryResult
    from report_generation import writing_decisions as wd, task_coordination as tc

    fixture=json.loads((Path(__file__).parent/'fixtures/report_writing_decisions_20261007.json').read_text())
    tasks=copy.deepcopy(fixture['writing_tasks'])
    ids={t['outline_id'] for t in tasks}
    previous=[]
    for task in tasks:
        task['external_rag_retrieval']['rag_context_text']='\n'.join(b['text'] for b in task['external_rag_retrieval']['evidence_blocks'])
        with patch.object(wd.llm,'query_result',return_value=LLMQueryResult(content=wd.compact_json(task['synthetic_decision']),finish_reason='stop')):
            result=wd.request_decision(task,'需求','标题','全篇大纲',previous,ids)
        assert result['status']=='generated'
        task['writing_decision']=result['decision']
        previous.append(task)
    ledger=wd.build_prior_ledger(tasks)
    assert '联盟成员和任务' in ledger and 'S3.1' in ledger
    assert all(b['text'] not in ledger for t in tasks for b in t['external_rag_retrieval']['evidence_blocks'])
    changes=[]
    for task in tasks:
        if task['outline_id'] not in {'S3.2','S5.2','S4.4'}:
            continue
        d=copy.deepcopy(task['writing_decision'])
        if task['outline_id']=='S4.4':
            d['section_question']='组织协同需要哪些条件，现有材料能判断什么？'
            d['judgment_limits']=['不把协同建议反推为现有机制未打通']
        else:
            d['content_scope']={'full_exposition':[], 'carry_over':[{'topic':'联盟成员和任务','section_id':'S3.1','use':'一句承接组织基础'}]}
            d['evidence_uses'][0]['use']='分析资源转化条件' if task['outline_id']=='S3.2' else '分析协同建议的适用条件'
        updates={key: value for key, value in d.items() if value != task['writing_decision'][key]}
        changes.append({'outline_id':task['outline_id'],'reason':'减少重复介绍并取消预定结论','set':updates})
    original=copy.deepcopy(tasks)
    with patch.object(tc.llm,'query_result',return_value=LLMQueryResult(content=wd.compact_json({'changes':changes}),finish_reason='stop')) as call:
        final,meta,warnings=tc.coordinate_writing_tasks(tasks)
    assert call.call_count==1 and meta['status']=='completed' and warnings==[]
    assert tasks==original
    assert [t['external_rag_retrieval'] for t in final]==[t['external_rag_retrieval'] for t in original]
    assert [t['outline_id'] for t in final if '联盟成员和任务' in t['writing_decision']['content_scope']['full_exposition']]==['S3.1']
    mechanism=next(t for t in final if t['outline_id']=='S4.4')
    assert '为什么央企机制未打通' not in mechanism['writing_system_prompt']

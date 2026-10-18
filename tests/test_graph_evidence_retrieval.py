import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_generation.external_rag import graph_evidence_retrieval as module


class GraphEvidenceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'lexical.sqlite3'
        with sqlite3.connect(self.path) as c:
            c.execute('CREATE TABLE chunks(chunk_id TEXT,document_id TEXT,text TEXT,metadata_json TEXT)')
            c.execute('INSERT INTO chunks VALUES(?,?,?,?)', ('c1','m1','甲公司生产减速器',json.dumps({'material_id':'m1','industry':'embodied','library':'embodied_news','title':'公告'})))
        self.graph = {'status':'success','industry':'embodied','evidence_blocks':[{'graph_evidence_refs':[{'material_id':'m1','chunk_id':'c1'}]}]}
        self.base = {'status':'success','evidence_blocks':[{'material_id':'m2','vector_id':'c2','library':'embodied_news','text':'无关内容','citation_id':'外部资料1'}]}

    def test_exact_lookup_checks_material_identity_and_reports_missing(self):
        rows, warnings = module.resolve_refs([{'material_id':'m1','chunk_id':'c1'}, {'material_id':'wrong','chunk_id':'c1'}, {'chunk_id':'missing'}], 'embodied', self.path)
        self.assertEqual([r.chunk_id for r in rows], ['c1'])
        self.assertEqual({w['code'] for w in warnings}, {'graph_ref_identity_mismatch','graph_ref_missing'})

    def test_exact_lookup_preserves_curation_constraints(self):
        rows, warnings = module.resolve_refs([{
            'material_id': 'm1', 'chunk_id': 'c1',
            'review_method': 'ai_assisted_source_review',
            'review_note': '仅支持展演表述',
        }], 'embodied', self.path)
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0].metadata['review_method'], 'ai_assisted_source_review')
        self.assertEqual(rows[0].metadata['review_note'], '仅支持展演表述')

    def test_validated_refs_only_include_successful_lookups_within_limit(self):
        valid = {'chunk_id': 'c1', 'material_id': 'm1'}
        validated = []
        rows, warnings = module.resolve_refs(
            [{'chunk_id': f'missing-{i}'} for i in range(module.MAX_GRAPH_REFS)] + [valid],
            'embodied', self.path, validated_refs=validated,
        )
        self.assertEqual(rows, [])
        self.assertEqual(validated, [])
        self.assertEqual(len(warnings), module.MAX_GRAPH_REFS)
        graph = {'evidence_blocks': [{'segment_path': [{'id': 30, 'evidence_refs': [valid]}]}]}
        self.assertEqual(module.graph_matches(graph, 'c1', validated_refs=validated), [])

    def test_merges_deduplicates_and_reranks_against_original_query(self):
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence('减速器厂商', self.graph, self.base, 'embodied', 2, scorer=lambda pairs: [0.0, 1.0])
        self.assertEqual([b['vector_id'] for b in result['evidence_blocks']], ['c1','c2'])
        self.assertIn('甲公司生产减速器', result['rag_context_text'])
        self.assertEqual(result['evidence_blocks'][0]['citation_id'], '外部资料1')
        self.assertEqual(result['graph_diagnostics']['resolved'], 1)
        self.assertNotIn('graph_diagnostics', self.base)

    def test_context_exposes_curation_constraints(self):
        graph = {'status': 'success', 'industry': 'embodied', 'evidence_blocks': [{
            'graph_evidence_refs': [{
                'material_id': 'm1', 'chunk_id': 'c1',
                'review_note': '仅支持展演表述',
            }]
        }]}
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence(
                '减速器厂商', graph, self.base, 'embodied', 2,
                scorer=lambda pairs: [0.0, 1.0],
            )
        self.assertIn('审核备注：仅支持展演表述', result['rag_context_text'])
        linked = next(block for block in result['evidence_blocks'] if block['vector_id'] == 'c1')
        self.assertEqual(linked['review_note'], '仅支持展演表述')

    def test_without_links_preserves_result_and_does_not_load_models(self):
        with patch.object(module, 'index_path', side_effect=AssertionError('accessed index')):
            self.assertIs(module.augment_with_graph_evidence('q',{},self.base,'embodied',2), self.base)

    def test_wrong_industry_is_rejected(self):
        rows, warnings = module.resolve_refs([{'chunk_id':'c1'}], 'brain', self.path)
        self.assertEqual(rows, [])
        self.assertEqual(warnings[0]['code'], 'graph_ref_identity_mismatch')

    def test_reranker_failure_preserves_baseline_order_and_warns(self):
        def fail(pairs):
            raise RuntimeError('model unavailable')
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence('q',self.graph,self.base,'embodied',2,scorer=fail)
        self.assertEqual(result['evidence_blocks'][0]['vector_id'], 'c2')
        self.assertIn('graph_rerank_fallback', [w['code'] for w in result['warnings']])

    def test_keyword_candidates_are_merged_with_source_diagnostics(self):
        from retrieval_core.schemas import RetrievalCandidate
        keyword = RetrievalCandidate(chunk_id='c3', document_id='m3', text='关键词候选', metadata={})
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence(
                '减速器厂商', self.graph, self.base, 'embodied', 3,
                keyword_candidates=[keyword], scorer=lambda pairs: [0.0, 0.5, 1.0],
            )
        self.assertEqual({b['vector_id'] for b in result['evidence_blocks']}, {'c1', 'c2', 'c3'})
        sources = {b['vector_id']: b.get('retrieval_source') for b in result['evidence_blocks']}
        self.assertEqual(sources['c1'], 'graph_evidence')
        self.assertEqual(sources['c3'], 'graph_keyword')
        self.assertEqual(result['graph_diagnostics']['keyword_candidate_count'], 1)

class CoordinatorGraphEvidenceTests(unittest.TestCase):
    def test_section_candidates_include_graph_evidence_before_allocation(self):
        from report_generation import coordinator_agent as coordinator
        subsection = {'outline_id':'S1.1','parent_level1_id':'S1','parent_level1_title':'产业链','title':'减速器'}
        graph = {'status':'success','industry':'embodied','evidence_blocks':[{'graph_evidence_refs':[{'chunk_id':'c1'}]}]}
        enriched = {'status':'success','evidence_blocks':[{'vector_id':'c1','text':'证据'}]}
        with patch.object(coordinator,'_retrieve_graph_for_subsection',return_value=graph), patch.object(coordinator,'_retrieve_external_rag_for_subsection',return_value={'status':'success','evidence_blocks':[]}), patch.object(coordinator,'augment_with_graph_evidence',return_value=enriched) as augment:
            row, _ = coordinator._retrieve_candidates_for_subsection(subsection,'产业分析','机器人',2,industry='embodied')
        self.assertEqual(row['external_rag_retrieval']['evidence_blocks'][0]['vector_id'],'c1')
        self.assertEqual(augment.call_args.args[1],graph)

    def test_pending_sidecar_links_are_not_used(self):
        from report_generation.graph_evidence import GraphEvidenceIndex
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'links.json'
            path.write_text(json.dumps({'links':[{'element_type':'node','id':1,'verification_status':'pending','evidence_refs':[{'chunk_id':'c1'}]}]}))
            self.assertEqual(GraphEvidenceIndex.from_path(path).for_node(1), ())

class ChromaEvidenceFallbackTests(unittest.TestCase):
    def test_original_news_chunk_can_be_resolved_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'chroma.sqlite3'
            with sqlite3.connect(path) as c:
                c.executescript("CREATE TABLE collections(id TEXT,name TEXT,dimension INTEGER); CREATE TABLE segments(id TEXT,collection TEXT,scope TEXT); CREATE TABLE embeddings(id INTEGER PRIMARY KEY,segment_id TEXT,embedding_id TEXT); CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT,int_value INTEGER,float_value REAL,bool_value INTEGER); INSERT INTO collections VALUES('col','embodied_news',768); INSERT INTO segments VALUES('seg','col','METADATA'); INSERT INTO embeddings VALUES(1,'seg','m1:0');")
                for key,value in {'chroma:document':'甲企业生产机器人','source_id':'m1','title':'公告','url':'https://example.test/1'}.items():
                    c.execute('INSERT INTO embedding_metadata(id,key,string_value) VALUES(1,?,?)',(key,value))
            rows,warnings=module.resolve_refs([{'material_id':'m1','chunk_id':'m1:0'}],'embodied',path)
            self.assertEqual(rows[0].text,'甲企业生产机器人')
            self.assertEqual(rows[0].metadata['source_address'],'https://example.test/1')
            self.assertEqual(warnings,[])

class GraphLinkCitationTests(unittest.TestCase):
    setUp = GraphEvidenceRetrievalTests.setUp
    def test_linked_chunk_uses_existing_report_citation_registry(self):
        from report_generation.citations import register_evidence_blocks
        with patch.object(module,'index_path',return_value=self.path):
            result=module.augment_with_graph_evidence('减速器',self.graph,self.base,'embodied',2,scorer=lambda pairs:[0.0,1.0])
        blocks, refs=register_evidence_blocks(result['evidence_blocks'],[])
        self.assertEqual(blocks[0]['citation_id'],'C1')
        self.assertEqual(refs[0]['material_id'],'m1')
        self.assertEqual(refs[0]['vector_ids'],['c1'])

    def test_duplicate_baseline_chunk_is_not_added_twice(self):
        self.base['evidence_blocks'][0].update(vector_id='c1',material_id='m1')
        with patch.object(module,'index_path',return_value=self.path):
            result=module.augment_with_graph_evidence('q',self.graph,self.base,'embodied',2,scorer=lambda pairs:[1.0])
        self.assertEqual(len(result['evidence_blocks']),1)
        self.assertTrue(result['evidence_blocks'][0]['graph_linked'])

class NewsCurrentSourceTests(unittest.TestCase):
    def test_existing_lexical_sidecar_does_not_override_current_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            lexical=root/'indexes'/'embodied'/'lexical.sqlite3'
            lexical.parent.mkdir(parents=True)
            lexical.touch()
            source=root/'current_source'
            with patch.object(module,'get_industry_config',return_value={'rag_type':'news','vector_db_path':source}), patch('report_generation.external_rag.news_index.INDEX_ROOT',root/'indexes'):
                self.assertEqual(module.index_path('embodied'),source/'chroma.sqlite3')

class GraphEvidenceTraceTests(unittest.TestCase):
    setUp = GraphEvidenceRetrievalTests.setUp
    def test_trace_distinguishes_new_graph_candidates_and_retained_chunks(self):
        ref = self.graph['evidence_blocks'][0]['graph_evidence_refs'][0]
        self.graph['evidence_blocks'][0].update(segment={'id':49,'name':'人形机器人'},downward_entities=[{'id':721,'name':'乐聚机器人','edge_type':'参与环节','relationship_evidence_refs':[ref],'node_evidence_refs':[]}])
        with patch.object(module,'index_path',return_value=self.path):
            result=module.augment_with_graph_evidence('q',self.graph,self.base,'embodied',1,scorer=lambda pairs:[0.0,1.0])
        trace=result['graph_diagnostics']
        self.assertEqual(trace['added_chunk_ids'],['c1'])
        self.assertEqual(trace['selected_chunk_ids'],['c1'])
        match=result['evidence_blocks'][0]['graph_matches'][0]
        self.assertEqual(match['source'],721)
        self.assertEqual(match['target'],49)
        self.assertEqual(match['kind'],'relationship_support')

    def test_node_mention_trace_does_not_claim_relationship_support(self):
        ref = self.graph['evidence_blocks'][0]['graph_evidence_refs'][0]
        self.graph['evidence_blocks'][0].update(segment={'id':49,'name':'人形机器人'},downward_entities=[{'id':721,'name':'乐聚机器人','edge_type':'参与环节','relationship_evidence_refs':[],'node_evidence_refs':[ref]}])
        matches=module.graph_matches(self.graph,'c1',validated_refs=[ref])
        self.assertEqual([match['kind'] for match in matches],['entity_mention'])
        self.assertNotIn('type',matches[0])

class SidecarCurationIntegrationTests(unittest.TestCase):
    setUp = GraphEvidenceRetrievalTests.setUp

    def _selected_graph(self, links=None):
        from report_generation import graph_retriever
        root = Path(self.tmp.name)
        path = root / 'graph_data.json'
        path.write_text((Path(__file__).parent / 'fixtures' / 'mixed_depth_graph.json').read_text())
        ref = {'material_id': 'm1', 'chunk_id': 'c1'}
        links = links if links is not None else [
            {'element_type': 'node', 'id': 101, 'review_note': '仅支持实体提及',
             'evidence_refs': [{**ref, 'review_method': 'source_review'}]},
            {'element_type': 'relationship', 'source': 101, 'target': 30,
             'type': '参与环节', 'review_note': '不能证明量产',
             'evidence_refs': [{**ref, 'review_note': '仅支持参与展演', 'evidence_scope': '展演参与'}]},
            {'element_type': 'node', 'id': 30,
             'evidence_refs': [{**ref, 'review_note': '第三条限定'},
                               {**ref, 'review_note': '第三条限定'}]},
            {'element_type': 'node', 'id': 102,
             'review_note': '未选中环节的备注', 'evidence_refs': [ref]},
        ]
        (root / 'graph_evidence_links.json').write_text(json.dumps({'links': links}))
        with patch.object(graph_retriever, 'get_industry_config', return_value={
            'name': '具身智能', 'graph_path': path,
        }), patch.object(graph_retriever, '_select_terminal_segments_with_llm', return_value={
            'status': 'success', 'data': [{'id': 30, 'name': '四级叶子', 'score': 1, 'reason': '匹配'}],
        }):
            graph = graph_retriever.retrieve_industry_graph('四级叶子', 'embodied')
        self.assertEqual(graph['status'], 'success', graph)
        return graph

    def _matches_from_links(self, links):
        graph = self._selected_graph(links)
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence(
                '四级叶子', graph, self.base, 'embodied', 2,
                scorer=lambda pairs: [1.0] * len(pairs),
            )
        linked = next(b for b in result['evidence_blocks'] if b['vector_id'] == 'c1')
        self.assertIn('graph_ref_identity_mismatch', [w['code'] for w in result['warnings']])
        return linked['graph_matches']

    def test_valid_node_does_not_restore_rejected_downward_relationship(self):
        for field, wrong in [('material_id', 'wrong'), ('document_id', 'wrong'),
                             ('library', 'wrong')]:
            with self.subTest(field=field):
                matches = self._matches_from_links([
                    {'element_type': 'node', 'id': 101,
                     'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'm1',
                                        'document_id': 'm1', 'library': 'embodied_news'}]},
                    {'element_type': 'relationship', 'source': 101, 'target': 30,
                     'type': '参与环节', 'evidence_refs': [{'chunk_id': 'c1', field: wrong}]},
                ])
                self.assertEqual([m['kind'] for m in matches], ['entity_mention'])

    def test_valid_relationship_does_not_restore_rejected_node(self):
        matches = self._matches_from_links([
            {'element_type': 'node', 'id': 101,
             'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'wrong'}]},
            {'element_type': 'relationship', 'source': 101, 'target': 30,
             'type': '参与环节', 'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'm1'}]},
        ])
        self.assertEqual([m['kind'] for m in matches], ['relationship_support'])

    def test_valid_segment_does_not_restore_rejected_upward_relationship(self):
        matches = self._matches_from_links([
            {'element_type': 'node', 'id': 30,
             'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'm1'}]},
            {'element_type': 'relationship', 'source': 30, 'target': 21,
             'type': '从属于', 'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'wrong'}]},
        ])
        self.assertEqual([m['kind'] for m in matches], ['entity_mention'])

    def test_compatible_identities_keep_node_downward_and_upward_matches(self):
        graph = self._selected_graph([
            {'element_type': 'node', 'id': 101, 'review_note': '实体限定',
             'evidence_refs': [{'chunk_id': 'c1'}]},
            {'element_type': 'relationship', 'source': 101, 'target': 30,
             'type': '参与环节', 'review_note': '关系限定',
             'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'm1'}]},
            {'element_type': 'relationship', 'source': 30, 'target': 21,
             'type': '从属于', 'review_note': '祖先限定',
             'evidence_refs': [{'chunk_id': 'c1', 'document_id': 'm1',
                                'library': 'embodied_news'}]},
        ])
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence(
                '四级叶子', graph, self.base, 'embodied', 2,
                scorer=lambda pairs: [1.0] * len(pairs),
            )
        linked = next(b for b in result['evidence_blocks'] if b['vector_id'] == 'c1')
        self.assertEqual(result['warnings'], [])
        self.assertEqual([m['kind'] for m in linked['graph_matches']],
                         ['entity_mention', 'relationship_support', 'relationship_support'])
        self.assertEqual([m.get('type') for m in linked['graph_matches'][1:]], ['参与环节', '从属于'])
        self.assertCountEqual(linked['review_note'].splitlines(), ['实体限定', '关系限定', '祖先限定'])

    def _assert_constraints_after_citation(self, baseline):
        from report_generation.citations import register_evidence_blocks
        graph = self._selected_graph()
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence(
                '四级叶子', graph, baseline, 'embodied', 2,
                scorer=lambda pairs: [1.0] * len(pairs),
            )
        blocks, _ = register_evidence_blocks(result['evidence_blocks'], [])
        linked = next(block for block in blocks if block['vector_id'] == 'c1')
        context = module.build_rag_context_text([linked])
        for note in ('仅支持实体提及', '仅支持参与展演', '第三条限定'):
            self.assertEqual(linked['review_note'].count(note), 1)
            self.assertIn(note, context)
        self.assertNotIn('不能证明量产', context)
        self.assertNotIn('未选中环节的备注', context)
        self.assertNotIn('甲公司生产减速器', linked['review_note'])
        self.assertEqual(linked['evidence_scope'], '展演参与')
        self.assertEqual(linked['review_method'], 'source_review')
        self.assertIn('[C', context)
        self.assertEqual({m['kind'] for m in linked['graph_matches']},
                         {'entity_mention', 'relationship_support'})
        return linked

    def test_selected_sidecar_constraints_survive_graph_and_citation_path(self):
        self._assert_constraints_after_citation(self.base)

    def test_existing_hybrid_chunk_keeps_baseline_and_graph_constraints(self):
        baseline = {'status': 'success', 'evidence_blocks': [{
            'vector_id': 'c1', 'material_id': 'm1', 'text': '原Hybrid正文',
            'review_note': 'Hybrid限定',
        }]}
        linked = self._assert_constraints_after_citation(baseline)
        self.assertEqual(linked['text'], '原Hybrid正文')
        self.assertIn('Hybrid限定', linked['review_note'])

    def test_resolve_same_chunk_merges_distinct_constraints(self):
        rows, warnings = module.resolve_refs([
            {'chunk_id': 'c1', 'review_note': '备注甲'},
            {'chunk_id': 'c1', 'review_note': '备注乙'},
            {'chunk_id': 'c1', 'review_note': '备注甲'},
        ], 'embodied', self.path)
        self.assertEqual(warnings, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].metadata['review_note'], '备注甲\n备注乙')

    def test_repeated_selected_chunk_constraints_do_not_consume_ref_limit(self):
        graph = {'status': 'success', 'industry': 'embodied', 'evidence_blocks': [
            {'graph_evidence_refs': [{'material_id': 'm1', 'chunk_id': 'c1',
                                      'review_note': f'限定{i}'}]}
            for i in range(module.MAX_GRAPH_REFS + 1)
        ]}
        with patch.object(module, 'index_path', return_value=self.path):
            result = module.augment_with_graph_evidence(
                'q', graph, self.base, 'embodied', 2,
                scorer=lambda pairs: [1.0] * len(pairs),
            )
        linked = next(b for b in result['evidence_blocks'] if b['vector_id'] == 'c1')
        self.assertIn(f'限定{module.MAX_GRAPH_REFS}', linked['review_note'].splitlines())
        self.assertEqual(result['graph_diagnostics']['requested'], 1)
        self.assertNotIn('graph_ref_limit', [w['code'] for w in result['warnings']])

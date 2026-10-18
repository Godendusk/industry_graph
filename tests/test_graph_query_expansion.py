import unittest
from unittest.mock import patch

from report_generation.external_rag.graph_query_expansion import build_graph_query_terms


class GraphQueryExpansionTests(unittest.TestCase):
    def test_terms_are_grouped_deduplicated_and_traceable(self):
        graph = {
            'status': 'success',
            'evidence_blocks': [{
                'segment': {'id': 21, 'name': '控制器与驱动器'},
                'segment_path': [{'id': 4, 'name': '执行系统'}, {'id': 21, 'name': '控制器与驱动器'}],
                'downward_entities': [{
                    'id': 943, 'name': '禾川科技',
                    'labels': ['公司'],
                    'edge_type': '参与环节',
                    'node_properties': {'products': ['伺服控制系统', '驱动器']},
                }],
                'graph_evidence_refs': [{'chunk_id': 'c1'}],
            }],
        }
        result = build_graph_query_terms(graph)
        self.assertEqual(result['groups']['segments'], ['执行系统', '控制器与驱动器'])
        self.assertEqual(result['groups']['entities'], ['禾川科技'])
        self.assertEqual(result['groups']['products'], ['伺服控制系统', '驱动器'])
        self.assertIn('禾川科技', result['terms'])
        self.assertEqual(result['source_graph_block_ids'], [0])
        self.assertEqual(result['diagnostics']['input_count'], 1)

    def test_generic_terms_are_removed_and_limits_are_bounded(self):
        graph = {'status': 'success', 'evidence_blocks': [{
            'segment': {'name': '产业发展'},
            'segment_path': [],
            'downward_entities': [{'name': '甲公司'}] * 50,
        }]}
        result = build_graph_query_terms(graph, max_total=3, max_group=2)
        self.assertNotIn('产业', result['terms'])
        self.assertLessEqual(len(result['terms']), 3)
        self.assertIn('甲公司', result['terms'])

    def test_failed_graph_returns_empty_terms_without_inventing_keywords(self):
        result = build_graph_query_terms({'status': 'error', 'evidence_blocks': []})
        self.assertEqual(result['terms'], [])
        self.assertEqual(result['source_graph_block_ids'], [])

    def test_keyword_candidates_are_marked_and_empty_terms_skip_store(self):
        from report_generation.external_rag.graph_query_expansion import retrieve_graph_keyword_candidates
        graph = {'status': 'success', 'graph_query_terms': {'terms': ['禾川科技', '控制器']}}
        candidate = type('Candidate', (), {'chunk_id': 'c1', 'document_id': 'm1', 'metadata': {}, 'text': '禾川科技 控制器证据'})()
        with patch('report_generation.external_rag.graph_query_expansion.NewsLexicalStore') as store:
            store.return_value.search.return_value = [candidate]
            result = retrieve_graph_keyword_candidates('控制器', graph, 'embodied', 5)
        self.assertEqual(result['terms'], ['禾川科技', '控制器'])
        self.assertEqual(result['candidates'][0].metadata['retrieval_source'], 'graph_keyword')
        self.assertIn('禾川科技', result['candidates'][0].metadata['graph_keyword_hits'])

        with patch('report_generation.external_rag.graph_query_expansion.NewsLexicalStore') as store:
            empty = retrieve_graph_keyword_candidates('q', {'status': 'success', 'graph_query_terms': {'terms': []}}, 'embodied', 5)
        store.assert_not_called()
        self.assertEqual(empty['candidates'], [])


class IndustryKeywordRoutingTests(unittest.TestCase):
    def test_biology_uses_only_biology_store_and_ai_report_skips(self):
        from report_generation.external_rag.graph_query_expansion import retrieve_graph_keyword_candidates
        graph = {'status': 'success', 'graph_query_terms': {'terms': ['凯赛生物']}}
        with patch('report_generation.external_rag.graph_query_expansion.NewsLexicalStore') as store:
            store.return_value.search.return_value = []
            result = retrieve_graph_keyword_candidates('q', graph, 'biology', 3)
            store.assert_called_once_with('biology')
        self.assertEqual(result['status'], 'success')
        with patch('report_generation.external_rag.graph_query_expansion.NewsLexicalStore') as store:
            result = retrieve_graph_keyword_candidates('q', graph, 'ai', 3)
            store.assert_not_called()
        self.assertEqual(result['status'], 'skipped')

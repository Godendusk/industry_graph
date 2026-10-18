"""Deterministic acceptance checks without models, indexes, or report generation."""
import copy
import json
import unittest

from scripts import run_graph_evidence_acceptance as module


class ReportAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.links = [{
            'element_type': 'node', 'id': 1, 'verification_status': 'approved',
            'review_note': '仅支持展演表述',
            'evidence_refs': [{'chunk_id': 'c1', 'material_id': 'm1'}],
        }]
        self.result = {
            'status': 'success', 'retrieval_version': 'hybrid_v2',
            'retrieval_fallback': None, 'hybrid_error': None,
            'graph_diagnostics': {'selected_chunk_ids': ['c1']},
            'warnings': [],
            'evidence_blocks': [{
                'vector_id': 'c1', 'material_id': 'm1', 'graph_linked': True,
                'graph_matches': [{'kind': 'entity_mention', 'node_id': 1}],
                'review_note': '仅支持展演表述',
            }],
            'rag_context_text': '审核备注：仅支持展演表述',
        }

    def validate(self):
        validator = getattr(module, 'validate_report_acceptance_result', None)
        self.assertIsNotNone(validator, '阶段 4 校验函数尚未存在')
        return validator(self.result, self.links)

    def test_fixed_five_acceptance_questions(self):
        self.assertEqual(module.QUESTIONS, [
            '人形机器人伺服电机和无框力矩电机有哪些企业参与？请给出产品证据。',
            '人形机器人控制器与驱动器有哪些企业，分别提供什么产品？',
            '触觉传感器与六维力传感器环节有哪些企业及其产品或检测服务？',
            '人形机器人动力电池的配套企业有哪些？',
            '人形机器人整机有哪些企业及应用案例？',
        ])

    def test_success_has_json_safe_diagnostics_and_preserves_inputs(self):
        original = copy.deepcopy((self.result, self.links))
        summary = self.validate()
        self.assertEqual(summary, {
            'retrieval_ok': True, 'version': 'hybrid_v2', 'fallback': None,
            'hybrid_error': None, 'identity_warning_count': 0,
            'curation_note_count': 1, 'failure_reasons': [],
        })
        self.assertEqual(json.loads(json.dumps(summary)), summary)
        self.assertEqual((self.result, self.links), original)

    def test_wrong_version_is_failure(self):
        self.result['retrieval_version'] = 'legacy_news'
        self.assertIn('unexpected_retrieval_version', self.validate()['failure_reasons'])

    def test_failures_remain_distinct_when_they_occur_together(self):
        self.result.update(retrieval_version='legacy_news', retrieval_fallback='legacy_news', hybrid_error='model unavailable')
        self.result['warnings'] = [{'code': 'graph_ref_identity_mismatch'}]
        del self.result['evidence_blocks'][0]['review_note']
        self.result['rag_context_text'] = ''
        summary = self.validate()
        self.assertFalse(summary['retrieval_ok'])
        self.assertEqual(set(summary['failure_reasons']), {
            'unexpected_retrieval_version', 'legacy_news_fallback', 'hybrid_error',
            'graph_identity_warning', 'missing_evidence_curation_note',
            'missing_context_curation_note',
        })
        self.assertEqual(summary['identity_warning_count'], 1)
        self.assertEqual(summary['curation_note_count'], 1)

    def test_ref_note_takes_precedence_over_link_note(self):
        self.links[0]['review_note'] = '旧通用备注'
        self.links[0]['evidence_refs'][0]['review_note'] = '仅支持展演表述'
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'])
        self.assertEqual(summary['curation_note_count'], 1)

    def test_selected_historical_links_without_notes_are_skipped(self):
        del self.links[0]['review_note']
        del self.result['evidence_blocks'][0]['review_note']
        self.result['rag_context_text'] = ''
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'])
        self.assertEqual(summary['curation_note_count'], 0)

    def test_duplicate_chunk_and_note_across_elements_count_once(self):
        duplicate = copy.deepcopy(self.links[0])
        duplicate.update(element_type='relationship', source=1, target=2, type='参与环节')
        self.links.append(duplicate)
        self.result['evidence_blocks'][0]['graph_matches'].append({
            'kind': 'relationship_support', 'source': 1, 'target': 2, 'type': '参与环节',
        })
        self.assertEqual(self.validate()['curation_note_count'], 1)

    def test_same_chunk_with_distinct_notes_requires_both(self):
        duplicate = copy.deepcopy(self.links[0])
        duplicate.update(element_type='relationship', source=1, target=2, type='参与环节')
        duplicate['review_note'] = '计划不等于量产'
        self.links.append(duplicate)
        self.result['evidence_blocks'][0]['graph_matches'].append({
            'kind': 'relationship_support', 'source': 1, 'target': 2, 'type': '参与环节',
        })
        self.result['evidence_blocks'][0]['review_note'] += '；计划不等于量产'
        self.result['rag_context_text'] += '；计划不等于量产'
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'])
        self.assertEqual(summary['curation_note_count'], 2)

    def test_same_chunk_unselected_graph_elements_do_not_require_notes(self):
        self.links.extend([
            {'element_type': 'node', 'id': 2, 'review_note': '其他企业限定',
             'evidence_refs': [{'chunk_id': 'c1'}]},
            {'element_type': 'relationship', 'source': 1, 'target': 16,
             'type': '参与环节', 'review_note': '伺服电机限定',
             'evidence_refs': [{'chunk_id': 'c1'}]},
            {'element_type': 'relationship', 'source': 1, 'target': 21,
             'type': '供应产品', 'review_note': '其他关系类型限定',
             'evidence_refs': [{'chunk_id': 'c1'}]},
            {'element_type': 'relationship', 'source': 21, 'target': 1,
             'type': '参与环节', 'review_note': '反向关系限定',
             'evidence_refs': [{'chunk_id': 'c1'}]},
            {'element_type': 'relationship', 'source': 1, 'target': 21,
             'type': '参与环节', 'review_note': '驱动器限定',
             'evidence_refs': [{'chunk_id': 'c1'}]},
        ])
        block = self.result['evidence_blocks'][0]
        block['graph_matches'].append({
            'kind': 'relationship_support', 'source': 1, 'target': 21, 'type': '参与环节',
        })
        block['review_note'] += '；驱动器限定'
        self.result['rag_context_text'] += '；驱动器限定'
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'], summary['failure_reasons'])
        self.assertEqual(summary['curation_note_count'], 2)

    def test_baseline_without_graph_matches_does_not_require_sidecar_notes(self):
        del self.result['evidence_blocks'][0]['graph_matches']
        del self.result['evidence_blocks'][0]['review_note']
        self.result['rag_context_text'] = ''
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'], summary['failure_reasons'])
        self.assertEqual(summary['curation_note_count'], 0)

    def test_selected_relationship_missing_note_still_fails(self):
        self.links[0].update(element_type='relationship', source=1, target=21, type='参与环节')
        self.result['evidence_blocks'][0]['graph_matches'] = [{
            'kind': 'relationship_support', 'source': 1, 'target': 21, 'type': '参与环节',
        }]
        del self.result['evidence_blocks'][0]['review_note']
        self.assertIn('missing_evidence_curation_note', self.validate()['failure_reasons'])

    def test_graph_identity_selected_for_another_chunk_does_not_require_note(self):
        self.result['evidence_blocks'].append({
            'chunk_id': 'c2',
            'graph_matches': [{'kind': 'entity_mention', 'node_id': 2}],
        })
        self.links.append({
            'element_type': 'node', 'id': 2, 'review_note': '仅属于另一路径',
            'evidence_refs': [{'chunk_id': 'c1'}],
        })
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'], summary['failure_reasons'])
        self.assertEqual(summary['curation_note_count'], 1)

    def test_pending_ref_on_selected_element_is_skipped(self):
        self.links[0]['evidence_refs'][0]['verification_status'] = 'pending'
        del self.result['evidence_blocks'][0]['review_note']
        self.result['rag_context_text'] = ''
        self.assertEqual(self.validate()['curation_note_count'], 0)
        self.assertTrue(self.validate()['retrieval_ok'])

    def test_identity_warnings_are_counted_separately_from_other_warnings(self):
        self.result['warnings'] = [
            {'code': 'graph_ref_identity_mismatch'}, {'code': 'graph_ref_missing'},
            {'code': 'graph_ref_identity_mismatch'},
        ]
        summary = self.validate()
        self.assertEqual(summary['identity_warning_count'], 2)
        self.assertEqual(summary['failure_reasons'], ['graph_identity_warning'])

    def test_formal_note_missing_from_linked_block_is_failure(self):
        del self.result['evidence_blocks'][0]['review_note']
        self.assertIn('missing_evidence_curation_note', self.validate()['failure_reasons'])

    def test_formal_note_missing_from_context_is_failure(self):
        self.result['rag_context_text'] = '产品证据'
        self.assertIn('missing_context_curation_note', self.validate()['failure_reasons'])

    def test_wrong_note_does_not_satisfy_formal_constraint(self):
        self.result['evidence_blocks'][0]['review_note'] = '其他审核备注'
        self.assertIn('missing_evidence_curation_note', self.validate()['failure_reasons'])

    def test_unselected_links_need_not_appear_in_context(self):
        self.links.append({
            'verification_status': 'approved', 'review_note': '计划不等于量产',
            'evidence_refs': [{'chunk_id': 'unselected'}],
        })
        self.assertTrue(self.validate()['retrieval_ok'])

    def test_unselected_historical_links_need_not_have_review_notes(self):
        self.links.append({
            'verification_status': 'approved',
            'evidence_refs': [{'chunk_id': 'historical'}],
        })
        summary = self.validate()
        self.assertTrue(summary['retrieval_ok'])
        self.assertEqual(summary['curation_note_count'], 1)

    def test_pending_links_are_not_accepted_as_formal_notes(self):
        self.links.append({
            'element_type': 'node', 'id': 1,
            'verification_status': 'pending',
            'review_note': '待审核的独有限定，不应进入正式验收',
            'evidence_refs': [{'chunk_id': 'c1'}],
        })
        self.assertEqual(self.validate()['curation_note_count'], 1)
        self.assertTrue(self.validate()['retrieval_ok'])

    def test_candidate_counts_do_not_determine_acceptance(self):
        self.result['evidence_blocks'] = []
        self.result['graph_diagnostics'] = {'selected_chunk_ids': [], 'candidate_count': 0}
        self.result['rag_context_text'] = ''
        self.assertTrue(self.validate()['retrieval_ok'])
        self.result['graph_diagnostics']['candidate_count'] = 999
        self.assertTrue(self.validate()['retrieval_ok'])

    def test_unsuccessful_retrieval_status_is_failure(self):
        self.result['status'] = 'error'
        self.assertIn('retrieval_not_successful', self.validate()['failure_reasons'])


if __name__ == '__main__':
    unittest.main()

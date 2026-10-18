import unittest
from report_generation import graph_evidence_contract as contract


class EvidenceContractTests(unittest.TestCase):
    def test_normalize_identity_and_kind_without_inventing_approval(self):
        link = contract.normalize_evidence_link({'element_type': ' NODE ', 'id': 7, 'evidence_refs': [{'chunk_id': 'c'}]})
        self.assertEqual(link['element_type'], 'node')
        self.assertEqual(link['evidence_kind'], 'entity_mention')
        self.assertNotIn('verification_status', link)
        self.assertNotIn('verification_status', link['evidence_refs'][0])

    def test_rejects_incomplete_or_confused_element_identity(self):
        for link in [
            {'element_type': 'node'},
            {'element_type': 'relationship', 'source': 1, 'target': 2},
            {'element_type': 'relationship', 'source': 1, 'target': 2, 'type': '生产', 'evidence_kind': 'entity_mention'},
            {'element_type': 'node', 'id': 1, 'evidence_kind': 'relationship_support'},
        ]:
            with self.subTest(link=link), self.assertRaises(ValueError):
                contract.normalize_evidence_link(link)
        self.assertTrue(contract.validate_evidence_sidecar({'links': [{'element_type': 'node'}]}))

    def test_filters_explicit_nonapproved_and_merges_notes(self):
        refs = contract.filter_approved_evidence_refs([
            {'chunk_id': 'c', 'review_note': '第一条'},
            {'chunk_id': 'c', 'review_note': '第二条', 'evidence_scope': ''},
            {'chunk_id': 'pending', 'verification_status': 'pending'},
            {'chunk_id': 'rejected', 'verification_status': 'rejected'},
            {'chunk_id': 'approved', 'verification_status': 'approved'},
        ])
        self.assertEqual([r['chunk_id'] for r in refs], ['c', 'approved'])
        self.assertEqual(refs[0]['review_note'], '第一条\n第二条')
        self.assertNotIn('verification_status', refs[0])
        self.assertEqual(refs[1]['verification_status'], 'approved')

    def test_index_does_not_load_invalid_or_unapproved_links(self):
        import json
        import tempfile
        from pathlib import Path
        from report_generation.graph_evidence import GraphEvidenceIndex
        links = [
            {'element_type': 'relationship', 'source': 1, 'target': 2, 'type': '生产', 'evidence_kind': 'entity_mention', 'evidence_refs': [{'chunk_id': 'wrong'}]},
            {'element_type': 'node', 'id': 1, 'verification_status': 'pending', 'evidence_refs': [{'chunk_id': 'pending'}]},
            {'element_type': 'node', 'id': 1, 'evidence_refs': [{'chunk_id': 'good'}]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'links.json'
            path.write_text(json.dumps({'links': links}))
            index = GraphEvidenceIndex.from_path(path)
        self.assertEqual(index.for_relationship({'source': 1, 'target': 2, 'type': '生产'}), ())
        self.assertEqual(index.for_node(1)[0]['chunk_id'], 'good')

class OptionalIdentityMergeTests(unittest.TestCase):
    def test_same_chunk_fills_optional_identity_and_keeps_all_notes(self):
        refs = contract.filter_approved_evidence_refs([
            {'material_id': 'm1', 'document_id': 'm1', 'chunk_id': 'c1', 'library': 'biology_news', 'review_note': 'sidecar限制'},
            {'chunk_id': 'c1', 'review_note': 'inline限制'},
        ])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['material_id'], 'm1')
        self.assertEqual(refs[0]['review_note'], 'sidecar限制\ninline限制')
        reverse = contract.filter_approved_evidence_refs([
            {'chunk_id': 'c1', 'review_note': 'inline限制'},
            {'material_id': 'm1', 'document_id': 'm1', 'chunk_id': 'c1', 'library': 'biology_news', 'review_note': 'sidecar限制'},
        ])
        self.assertEqual(len(reverse), 1)
        self.assertEqual(reverse[0]['library'], 'biology_news')
        from report_generation.graph_evidence import GraphEvidenceIndex
        index = GraphEvidenceIndex(nodes={1: [{
            'material_id': 'm1', 'document_id': 'm1', 'chunk_id': 'c1',
            'review_note': 'sidecar限制',
        }]})
        combined = index.for_node(1, {'evidence_refs': [{'chunk_id': 'c1', 'review_note': 'inline限制'}]})
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]['review_note'], 'sidecar限制\ninline限制')

    def test_explicit_identity_conflicts_survive_for_resolver_validation(self):
        full = {'material_id': 'm1', 'document_id': 'm1', 'chunk_id': 'c1', 'library': 'biology_news'}
        for field in ('material_id', 'document_id', 'library'):
            with self.subTest(field=field):
                refs = contract.filter_approved_evidence_refs([full, {**full, field: 'wrong'}])
                self.assertEqual(len(refs), 2)
                self.assertEqual(refs[1][field], 'wrong')
        refs = contract.filter_approved_evidence_refs([{'material_id': 'm1'}, {'material_id': 'm1', 'review_note': 'note'}])
        self.assertEqual(len(refs), 1)

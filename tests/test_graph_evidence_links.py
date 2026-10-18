import json
import tempfile
import unittest
from pathlib import Path

from report_generation.graph_evidence import GraphEvidenceIndex


class GraphEvidenceIndexTests(unittest.TestCase):
    def test_loads_node_and_relationship_evidence_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph_evidence_links.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "links": [
                            {
                                "element_type": "node",
                                "id": 101,
                                "evidence_refs": [
                                    {"material_id": "m1", "chunk_id": "c1"}
                                ],
                            },
                            {
                                "element_type": "relationship",
                                "source": 101,
                                "target": 205,
                                "type": "生产",
                                "evidence_refs": [
                                    {"material_id": "m2", "chunk_id": "c2"}
                                ],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            index = GraphEvidenceIndex.from_path(path)

            self.assertEqual(index.for_node(101)[0]["chunk_id"], "c1")
            self.assertEqual(
                index.for_relationship({"source": 101, "target": 205, "type": "生产"})[0]["chunk_id"],
                "c2",
            )

    def test_missing_file_is_an_empty_optional_index(self):
        index = GraphEvidenceIndex.from_path(Path("/does/not/exist.json"))

        self.assertEqual(index.for_node(1), ())
        self.assertEqual(index.for_relationship({"source": 1, "target": 2, "type": "生产"}), ())


if __name__ == "__main__":
    unittest.main()

class InlineRelationshipEvidenceTests(unittest.TestCase):
    def test_upward_path_keeps_inline_relationship_evidence(self):
        from report_generation.graph_retriever import _IndustryGraph
        fixture=Path(__file__).parent/'fixtures'/'mixed_depth_graph.json'
        data=json.loads(fixture.read_text())
        for rel in data['relationships']:
            if rel['source']==30 and rel['target']==21:
                rel['properties']={'evidence_refs':[{'material_id':'m1','chunk_id':'c1'}]}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'graph_data.json'
            path.write_text(json.dumps(data))
            graph=_IndustryGraph(path)
            self.assertEqual(graph.get_upward_path(30)[0]['evidence_refs'][0]['chunk_id'],'c1')

class CurationDefaultsTests(unittest.TestCase):
    def test_parent_constraints_are_defaults_and_same_chunk_refs_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'graph_evidence_links.json'
            path.write_text(json.dumps({'links': [{
                'element_type': 'node', 'id': 101,
                'review_note': '父备注', 'review_method': 'parent_review',
                'evidence_scope': '父范围',
                'evidence_refs': [
                    {'chunk_id': 'c1', 'review_note': 'ref备注', 'evidence_scope': 'ref范围'},
                    {'chunk_id': 'c1', 'review_note': '第二限定'},
                    {'chunk_id': 'c1', 'review_note': '第二限定'},
                ],
            }]}), encoding='utf-8')
            refs = GraphEvidenceIndex.from_path(path).for_node(101)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['review_note'], 'ref备注\n第二限定')
        self.assertEqual(refs[0]['review_method'], 'parent_review')
        self.assertEqual(refs[0]['evidence_scope'], 'ref范围\n父范围')

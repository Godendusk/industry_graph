import unittest
from scripts.build_graph_evidence_links import ALLOWED_TOPICS, match_entity_mentions

class GraphEvidenceCandidatesTests(unittest.TestCase):
    def test_exact_entity_mentions_do_not_claim_relationship_support(self):
        graph={'nodes':[{'id':1,'labels':['公司'],'properties':{'name':'甲机器人公司'}},{'id':2,'labels':['环节'],'properties':{'name':'机器人'}}], 'relationships':[{'source':1,'target':2,'type':'参与环节'}]}
        chunks=[{'chunk_id':'c1','document_id':'m1','text':'甲机器人公司发布新品。','metadata':{'material_id':'m1','library':'embodied_news'}}]
        links=match_entity_mentions(graph,chunks)
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['element_type'],'node')
        self.assertEqual(links[0]['evidence_kind'],'entity_mention')
        self.assertEqual(links[0]['id'],1)
        self.assertIn('甲机器人公司',links[0]['evidence_excerpt'])

    def test_candidates_include_topic_and_respect_topic_filter(self):
        graph={'nodes':[
            {'id':1,'labels':['公司'],'properties':{'name':'甲电机公司'}},
            {'id':2,'labels':['环节'],'properties':{'name':'伺服电机'}},
            {'id':3,'labels':['公司'],'properties':{'name':'乙电池公司'}},
            {'id':4,'labels':['环节'],'properties':{'name':'动力电池'}},
        ], 'relationships':[
            {'source':1,'target':2,'type':'参与环节'},
            {'source':3,'target':4,'type':'参与环节'},
        ]}
        chunks=[
            {'chunk_id':'c1','document_id':'m1','text':'甲电机公司发布新品。','metadata':{'material_id':'m1','library':'embodied_news'}},
            {'chunk_id':'c2','document_id':'m2','text':'乙电池公司发布新品。','metadata':{'material_id':'m2','library':'embodied_news'}},
        ]
        links=match_entity_mentions(graph,chunks,topics={'motor'})
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['topic'],'motor')
        self.assertEqual(links[0]['verification_status'],'pending')
        self.assertEqual(set(ALLOWED_TOPICS), {'motor','controller_driver','force_tactile_sensor','battery','humanoid_robot','application_case'})

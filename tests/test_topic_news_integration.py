from RAG import build_vector_db as qa
from report_generation.external_rag import retriever
from report_generation.industry_config import INDUSTRY_CONFIG
from report_generation.task_card_agent import _external_rag_available
from unittest.mock import patch, PropertyMock


def test_topic_news_stores_are_report_available():
    for industry in ("low_altitude", "sea", "quantum", "biology", "brain", "material"):
        assert _external_rag_available(INDUSTRY_CONFIG[industry])


def test_chat_uses_industry_news_and_its_metadata(monkeypatch):
    captured = {}

    def fake_query(query, industry, top_k):
        captured['industry'] = industry
        return {
            'ids': [['source-a:0']],
            'documents': [['固态电解质实现量产。']],
            'metadatas': [[{
                'source_id': 'source-a', 'title': '固态电解质项目',
                'publish_date': '2026-09-01', 'source_url': 'https://example.com/a',
            }]],
            'distances': [[0.2]],
        }

    monkeypatch.setattr('RAG.topic_news.query_topic_news', fake_query)
    monkeypatch.setattr(qa.KnowledgeGraphHandler, 'search_relevant_subgraph', lambda self, query: '')
    monkeypatch.setattr(qa.llm, 'query', lambda **kwargs: captured.setdefault('prompt', kwargs['user_prompt']) or '回答')
    answer = qa.query_vector_db('固态电解质进展', industry='material')
    assert captured['industry'] == 'material'
    assert '固态电解质实现量产' in captured['prompt']
    assert '固态电解质项目' in captured['prompt']
    assert answer


def test_report_uses_industry_news_evidence():
    from report_generation.external_rag.news_retrieval import NewsDenseStore
    raw = {
        'ids': [['source-b:0']],
        'documents': [['脑机接口帮助患者交流。']],
        'metadatas': [[{
            'source_id': 'source-b', 'title': '脑机接口临床进展',
            'publish_date': '2026-09-01', 'source_url': 'https://example.com/b',
            'chunk_index': 0,
        }]],
        'distances': [[0.3]],
    }
    with patch('report_generation.external_rag.news_retrieval.check_news_index', return_value={'status': 'ready'}), \
         patch('report_generation.external_rag.news_retrieval.local_models') as models, \
         patch('report_generation.external_rag.news_retrieval.NewsLexicalStore.search', return_value=[]), \
         patch.object(NewsDenseStore, 'collection', new_callable=PropertyMock) as collection:
        models.return_value.embed_documents.return_value = [[1.0] + [0.0] * 767]
        models.return_value.rerank_pairs.return_value = [0.9]
        collection.return_value.count.return_value = 1
        collection.return_value.query.return_value = raw
        result = retriever.retrieve_external_rag('脑机接口临床进展', industry='brain', top_k=3)
        collection.return_value.query.assert_called_once()
    assert result['status'] == 'success'
    assert result['evidence_blocks'][0]['title'] == '脑机接口临床进展'
    assert result['evidence_blocks'][0]['source_address'] == 'https://example.com/b'

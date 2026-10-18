from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Lock
from types import SimpleNamespace
from unittest.mock import patch
from report_generation.external_rag import news_retrieval as nr


def test_concurrent_first_queries_share_one_model_manager(monkeypatch):
    clear = getattr(nr.local_models, 'cache_clear', None)
    if clear:
        clear()
    monkeypatch.setattr(nr, '_local_models_instance', None, raising=False)
    gate, lock, created = Barrier(2), Lock(), []
    def create(*args):
        value = object()
        with lock:
            created.append(value)
        try:
            gate.wait(timeout=0.3)
        except BrokenBarrierError:
            pass
        return value
    config = SimpleNamespace(embedding_model_path='embedding', reranker_model_path='reranker')
    with patch.object(nr.RetrievalConfig, 'for_project', return_value=config), patch.object(nr, 'ModelManager', side_effect=create):
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = [f.result() for f in [pool.submit(nr.local_models), pool.submit(nr.local_models)]]
    assert len(created) == 1
    assert a is b
    if clear:
        clear()

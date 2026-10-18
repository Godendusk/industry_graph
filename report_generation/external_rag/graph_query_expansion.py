"""Build bounded lexical terms from selected graph context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from retrieval_core.schemas import RetrievalCandidate
from .news_index import NewsLexicalStore
from report_generation.industry_config import get_industry_config


_GENERIC_TERMS = {
    '产业', '技术', '环节', '布局', '发展', '能力', '条件', '分析', '研究',
    '价值', '现状', '趋势', '路径', '关键', '相关', '智能', '系统',
}


def _clean(value: object) -> str:
    return ' '.join(str(value or '').split()).strip()


def _values(value: object) -> Iterable[str]:
    if isinstance(value, (list, tuple, set)):
        for item in value:
            cleaned = _clean(item)
            if cleaned:
                yield cleaned
    else:
        cleaned = _clean(value)
        if cleaned:
            yield cleaned


def _append_unique(target: list[str], values: Iterable[str], *, max_group: int) -> None:
    for value in values:
        value = _clean(value)
        if value in _GENERIC_TERMS or len(value) < 2 or value in target:
            continue
        if len(target) >= max_group:
            return
        target.append(value)


def build_graph_query_terms(
    graph_result: Mapping[str, object],
    *,
    aliases: Mapping[str, Iterable[str]] | None = None,
    max_group: int = 10,
    max_total: int = 20,
) -> dict:
    """Return traceable lexical terms from selected graph blocks.

    The function only emits names already present in the graph result or an
    explicitly supplied alias map. It does not infer products or relationships
    from source text.
    """
    if max_group <= 0 or max_total <= 0:
        raise ValueError('max_group and max_total must be positive')
    if graph_result.get('status') != 'success':
        return {'terms': [], 'groups': {key: [] for key in ('segments', 'entities', 'products', 'relationship_types', 'aliases')},
                'source_graph_block_ids': [],
                'diagnostics': {'input_count': 0, 'term_count': 0, 'dropped_terms': []}}

    groups = {key: [] for key in ('segments', 'entities', 'products', 'relationship_types', 'aliases')}
    dropped: list[str] = []
    blocks = graph_result.get('evidence_blocks') or []
    source_ids = []
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            continue
        source_ids.append(index)
        segment = block.get('segment') or {}
        _append_unique(groups['segments'], [item.get('name') for item in (block.get('segment_path') or []) if isinstance(item, Mapping)], max_group=max_group)
        _append_unique(groups['segments'], [segment.get('name')], max_group=max_group)
        for entity in block.get('downward_entities') or []:
            if not isinstance(entity, Mapping):
                continue
            _append_unique(groups['entities'], [entity.get('name')], max_group=max_group)
            props = entity.get('node_properties') or entity.get('properties') or {}
            if isinstance(props, Mapping):
                _append_unique(groups['products'], _values(props.get('products')), max_group=max_group)
                _append_unique(groups['products'], _values(props.get('product_names')), max_group=max_group)
            _append_unique(groups['relationship_types'], [entity.get('edge_type')], max_group=max_group)

    if aliases:
        for canonical in groups['entities'] + groups['segments'] + groups['products']:
            _append_unique(groups['aliases'], _values(aliases.get(canonical)), max_group=max_group)

    terms = []
    for group_name in ('segments', 'entities', 'products', 'aliases', 'relationship_types'):
        for term in groups[group_name]:
            if term in terms:
                continue
            if len(terms) >= max_total:
                dropped.append(term)
                continue
            terms.append(term)
    return {
        'terms': terms,
        'groups': groups,
        'source_graph_block_ids': source_ids,
        'diagnostics': {
            'input_count': len(blocks),
            'term_count': len(terms),
            'dropped_terms': dropped,
        },
    }


def retrieve_graph_keyword_candidates(
    query: str,
    graph_result: Mapping[str, object],
    industry: str,
    limit: int,
) -> dict:
    """Retrieve bounded lexical candidates using graph-derived terms."""
    terms_payload = graph_result.get('graph_query_terms') or build_graph_query_terms(graph_result)
    terms = list(terms_payload.get('terms') or [])
    if not terms:
        return {'status': 'skipped', 'terms': [], 'candidates': [], 'warnings': []}
    if get_industry_config(industry).get('rag_type') == 'news':
        try:
            rows = NewsLexicalStore(industry).search(' '.join(terms), min(int(limit), 20))
        except Exception as exc:
            return {'status': 'error', 'terms': terms, 'candidates': [],
                    'warnings': [{'code': 'graph_keyword_error', 'message': str(exc)}]}
    else:
        return {'status': 'skipped', 'terms': terms, 'candidates': [],
                'warnings': [{'code': 'graph_keyword_unsupported_industry', 'message': industry}]}
    candidates = []
    for row in rows:
        metadata = dict(row.metadata)
        metadata['retrieval_source'] = 'graph_keyword'
        metadata['graph_keyword_hits'] = [term for term in terms if term in row.text]
        candidates.append(RetrievalCandidate(
            chunk_id=row.chunk_id, document_id=row.document_id, text=row.text,
            metadata=metadata, bm25_rank=getattr(row, 'bm25_rank', None), bm25_score=getattr(row, 'bm25_score', None),
            diagnostics={**getattr(row, 'diagnostics', {}), 'retrieval_source': 'graph_keyword'},
        ))
    return {'status': 'success', 'terms': terms, 'candidates': candidates, 'warnings': []}

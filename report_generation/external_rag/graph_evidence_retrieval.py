"""Resolve curated graph links and rerank source chunks with report candidates."""
from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import replace
from contextlib import closing
from pathlib import Path

from ..graph_evidence import GraphEvidenceIndex, merge_curation_fields
from ..industry_config import PROJECT_ROOT, get_industry_config
from retrieval_core.config import RetrievalConfig
from retrieval_core.schemas import RetrievalCandidate
from retrieval_core.reranker import rerank_candidates
from .report_adapter import to_evidence_blocks, build_rag_context_text

MAX_GRAPH_REFS = 40


def index_path(industry: str) -> Path:
    config = get_industry_config(industry)
    if config['rag_type'] == 'report':
        return RetrievalConfig.for_project(PROJECT_ROOT).index_root / 'lexical.sqlite3'
    # Resolve against the current source even if an old lexical sidecar exists.
    return config['vector_db_path'] / 'chroma.sqlite3'


def _news_record(connection, industry, segment, chunk_id):
    from .news_index import news_metadata
    embedding = connection.execute(
        'SELECT id FROM embeddings WHERE segment_id=? AND embedding_id=?',
        (segment, chunk_id),
    ).fetchone()
    if embedding is None:
        return None
    raw = {}
    for item in connection.execute('SELECT * FROM embedding_metadata WHERE id=?', (embedding['id'],)):
        raw[item['key']] = next((item[key] for key in ('string_value', 'int_value', 'float_value', 'bool_value') if item[key] is not None), None)
    text = str(raw.pop('chroma:document', '') or '')
    metadata = news_metadata(industry, chunk_id, raw)
    return {'chunk_id':chunk_id,'document_id':metadata['material_id'],
            'text':text,'metadata_json':json.dumps(metadata, ensure_ascii=False)}


def _news_segment(connection, industry):
    name = get_industry_config(industry)['collection_name']
    rows = connection.execute(
        "SELECT s.id FROM segments s JOIN collections c ON c.id=s.collection "
        "WHERE c.name=? AND s.scope='METADATA'", (name,),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError(f'Expected one metadata segment for {name}')
    return rows[0]['id']


def resolve_refs(refs: list, industry: str, path: Path | None = None, *, validated_refs: list | None = None) -> tuple[list, list]:
    """Fetch exact chunks and optionally collect refs that passed this bounded read."""
    config = get_industry_config(industry)
    path = path if path is not None else index_path(industry)
    rows, warnings, positions = [], [], {}
    if not path.is_file():
        return [], [{'code':'graph_index_missing','message':f'{industry} evidence index is missing'}]
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        lexical = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks'").fetchone()
        segment = None
        if not lexical:
            segment = _news_segment(connection, industry)
        for ref in refs[:MAX_GRAPH_REFS]:
            chunk_id = str(ref.get('chunk_id') or '').strip()
            if not chunk_id:
                warnings.append({'code':'graph_ref_needs_chunk','message':'Evidence link requires a chunk_id'})
                continue
            row = (connection.execute('SELECT chunk_id,document_id,text,metadata_json FROM chunks WHERE chunk_id=?', (chunk_id,)).fetchone()
                   if lexical else _news_record(connection, industry, segment, chunk_id))
            if row is None:
                warnings.append({'code':'graph_ref_missing','message':f'Chunk not found: {chunk_id}'})
                continue
            metadata = json.loads(row['metadata_json'])
            wrong = (
                (ref.get('material_id') and str(ref['material_id']) != str(metadata.get('material_id') or ''))
                or (ref.get('document_id') and str(ref['document_id']) != row['document_id'])
                or (ref.get('library') and str(ref['library']) != metadata.get('library'))
                or (metadata.get('industry') and metadata['industry'] != industry)
                or (config['rag_type'] == 'news' and metadata.get('library') != config['collection_name'])
            )
            if wrong:
                warnings.append({'code':'graph_ref_identity_mismatch','message':f'Evidence identity does not match: {chunk_id}'})
                continue
            if not row['text'].strip():
                continue
            if validated_refs is not None:
                validated_refs.append(ref)
            curated = {
                key: ref[key]
                for key in ('review_method', 'review_note', 'evidence_scope')
                if ref.get(key) not in (None, '')
            }
            if chunk_id in positions:
                position = positions[chunk_id]
                previous = rows[position]
                rows[position] = replace(previous, metadata={
                    **previous.metadata, **merge_curation_fields(previous.metadata, curated),
                })
                continue
            positions[chunk_id] = len(rows)
            rows.append(RetrievalCandidate(
                chunk_id=chunk_id,
                document_id=row['document_id'],
                text=row['text'],
                metadata={**metadata, **curated},
                diagnostics={'graph_link': True},
            ))
    return rows, warnings


def graph_matches(graph, chunk_id, *, validated_refs):
    """Trace only associations compatible with refs accepted by ``resolve_refs``."""
    def matches_ref(ref):
        if (str(ref.get('chunk_id') or '').strip() != chunk_id
                or ref.get('verification_status', 'approved') != 'approved'):
            return False
        return any(
            str(validated.get('chunk_id') or '').strip() == chunk_id
            and all(ref.get(field) in (None, '')
                    or str(ref[field]) == str(validated.get(field) or '')
                    for field in ('material_id', 'document_id', 'library'))
            for validated in validated_refs
        )

    matches = []
    for block in graph.get('evidence_blocks', []):
        segment = block.get('segment') or {}
        for entity in block.get('downward_entities', []):
            if any(matches_ref(ref) for ref in entity.get('node_evidence_refs', [])):
                matches.append({'kind':'entity_mention','node_id':entity.get('id'),
                                'name':entity.get('name'),'segment_name':segment.get('name')})
            if any(matches_ref(ref) for ref in entity.get('relationship_evidence_refs', [])):
                matches.append({'kind':'relationship_support','source':entity.get('id'),
                                'target':segment.get('id'),'type':entity.get('edge_type'),
                                'source_name':entity.get('name'),'target_name':segment.get('name')})
        for node in block.get('segment_path', []):
            if any(matches_ref(ref) for ref in node.get('evidence_refs', [])):
                matches.append({'kind':'entity_mention','node_id':node.get('id'),'name':node.get('name')})
        for edge in block.get('upward_path', []):
            if any(matches_ref(ref) for ref in edge.get('evidence_refs', [])):
                matches.append({'kind':'relationship_support', **{key:edge.get(key) for key in (
                    'source','target','type','source_name','target_name')}})
    return matches


def augment_with_graph_evidence(query, graph, retrieval, industry, top_k, *, keyword_candidates=None, scorer=None):
    """Join graph-selected source chunks before section material allocation."""
    if graph.get('status') != 'success' or graph.get('industry', industry) != industry:
        return retrieval
    refs = [ref for block in graph.get('evidence_blocks', [])
            for ref in block.get('graph_evidence_refs', [])
            if ref.get('verification_status', 'approved') == 'approved']
    refs = list(GraphEvidenceIndex._merge(refs))
    keyword_candidates = list(keyword_candidates or [])
    if not refs and not keyword_candidates:
        return retrieval
    result = copy.deepcopy(retrieval)
    warnings = result.setdefault('warnings', [])
    validated_refs = []
    try:
        linked, resolve_warnings = resolve_refs(refs, industry, validated_refs=validated_refs)
    except (OSError, ValueError, sqlite3.Error) as exc:
        linked, resolve_warnings = [], [{'code':'graph_evidence_error','message':str(exc)}]
    warnings.extend(resolve_warnings)
    result['graph_diagnostics'] = {'requested':len(refs),'resolved':len(linked),'limit':MAX_GRAPH_REFS}
    if len(refs) > MAX_GRAPH_REFS:
        warnings.append({'code':'graph_ref_limit','message':f'Only the first {MAX_GRAPH_REFS} graph evidence links were read'})
    if not linked and not keyword_candidates:
        return result
    rows, seen = [], set()
    originals = {}
    for block in result.get('evidence_blocks', []):
        chunk_id = str(block.get('chunk_id') or block.get('vector_id') or '')
        if not chunk_id or not block.get('text') or chunk_id in seen:
            continue
        seen.add(chunk_id)
        originals[chunk_id] = block
        rows.append(RetrievalCandidate(chunk_id=chunk_id, document_id=str(block.get('document_id') or block.get('material_id') or chunk_id), text=block['text'], metadata={**block, 'retrieval_source': block.get('retrieval_source', 'hybrid')}))
    linked_ids = {row.chunk_id for row in linked}
    linked_by_id = {row.chunk_id: row for row in linked}
    rows = [replace(row, metadata={
        **row.metadata,
        **merge_curation_fields(row.metadata, linked_by_id[row.chunk_id].metadata),
    }) if row.chunk_id in linked_by_id else row for row in rows]
    rows.extend(row for row in linked if row.chunk_id not in seen)
    keyword_ids = {row.chunk_id for row in keyword_candidates}
    rows.extend(row for row in keyword_candidates if row.chunk_id not in seen and row.chunk_id not in linked_ids)
    if scorer is None:
        def scorer(pairs):
            from .news_retrieval import local_models
            return local_models().rerank_pairs(query, [pair[1] for pair in pairs])
    ranked = rerank_candidates(query, rows, scorer=scorer, final_limit=top_k)
    fallback = any(row.diagnostics.get('reranker_fallback') for row in ranked)
    if fallback:
        warnings.append({'code':'graph_rerank_fallback','message':'Graph candidate reranking failed; kept baseline ordering'})
    blocks = to_evidence_blocks(ranked)
    for rank, (row, block) in enumerate(zip(ranked, blocks), 1):
        previous = originals.get(row.chunk_id)
        if previous:
            block.update(previous)
            block.update(merge_curation_fields(row.metadata))
        block.update(rank=rank, citation_id=f'外部资料{rank}', chunk_id=row.chunk_id,
                     document_id=row.document_id, industry=industry,
                     graph_linked=row.chunk_id in linked_ids)
        if row.chunk_id in linked_ids:
            block['retrieval_source'] = 'graph_evidence'
            block['graph_matches'] = graph_matches(graph, row.chunk_id, validated_refs=validated_refs)
        elif row.chunk_id in keyword_ids:
            block['retrieval_source'] = 'graph_keyword'
        else:
            block['retrieval_source'] = block.get('retrieval_source', 'hybrid')
        if row.rerank_score is not None:
            block['rerank_score'] = row.rerank_score
            block['rerank_rank'] = row.rerank_rank
    result['evidence_blocks'] = blocks
    result['rag_context_text'] = build_rag_context_text(blocks)
    if blocks:
        result['status'] = 'success'
        result['message'] = ''
    result['graph_diagnostics'].update(candidate_count=len(rows), rerank='fallback' if fallback else 'success',
                                       keyword_candidate_count=len(keyword_candidates),
                                       graph_evidence_candidate_count=len(linked),
                                       original_candidate_count=len(originals),
                                       deduped_candidate_count=len(rows))
    result['graph_diagnostics'].update(
        original_chunk_ids=list(originals), resolved_chunk_ids=[row.chunk_id for row in linked],
        added_chunk_ids=[row.chunk_id for row in linked if row.chunk_id not in originals],
        selected_chunk_ids=[row.chunk_id for row in ranked],
        dropped_linked_chunk_ids=[row.chunk_id for row in linked if row.chunk_id not in {r.chunk_id for r in ranked}],
    )
    return result

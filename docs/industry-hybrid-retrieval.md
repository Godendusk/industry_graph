# Industry Hybrid Retrieval

All eight report industries default to `hybrid_v2`. AI uses the existing five
report libraries. Each of the seven news industries queries its own `*_news`
collection, with its original 768-dimensional BGE vectors, a separate Chinese
FTS5 keyword index, RRF fusion, and the local BGE reranker.

## Local Setup

Run commands from the project root with the `kunlun` Python executable:

```powershell
& 'D:\Anaconda_envs\envs\kunlun\python.exe' scripts/build_news_hybrid_index.py --industry all --action check
& 'D:\Anaconda_envs\envs\kunlun\python.exe' scripts/build_news_hybrid_index.py --industry all --action build --workers 8
& 'D:\Anaconda_envs\envs\kunlun\python.exe' scripts/build_report_hybrid_index.py --source legacy-chroma --build --publish --embedding-workers 3
```

News indexes live under `RAG/indexes/report_v2_news/<industry>/`. Existing source
databases and vectors remain under `report_generation/vector_db/<industry>/`.
The AI hybrid index lives under `RAG/indexes/report_v2/`. Models, indexes, and
verification outputs are local artifacts and excluded from Git.

## Updates and Recovery

After updating news sources, run `--action sync` for the affected industry.
Sync copies the published keyword index to staging, updates changed documents,
removes obsolete chunks, and reuses tokens when only metadata changed. Queries
never build or scan the full source database. A changed Chroma ingestion sequence
marks the keyword index stale; maintenance writes and queue pruning do not.

An interrupted news build resumes with `--action resume`. Each committed batch
has a source-bound checkpoint. If the source changed, use `sync` or `build` instead.
The builder recovers locks belonging to exited processes and rejects live locks.
Publication checks the source count, original IDs, metadata/content digest, and
FTS integrity before replacing the index and publishing `READY`.

Keyword scoring covers complete news documents, using their saved chunk tokens.
Each lexical hit maps back to the best matching original chunk ID, so fusion
retains vector identity and does not require re-encoding the source databases.

For AI, rerun the build command with `--resume` after interruption. Completed
documents with matching IDs and versions in both stores are skipped. Failed or
partial documents are rebuilt. `--publish` retains an existing index as
`report_v2.previous`; archive that backup before the next replacement.
Publication waits for the isolated build process to exit, so Windows native
HNSW file handles are released before directories are moved. A failed move
restores the previous index when possible.

## Modes and Diagnostics

`REPORT_RETRIEVAL_MODE=hybrid_v2|legacy|compare` applies to every industry.
`compare` returns legacy evidence and includes hybrid comparison diagnostics.
`REPORT_RETRIEVAL_ALLOW_LEGACY_FALLBACK=0` disables fallback on hybrid errors.

Full success reports `retrieval_version=hybrid_v2`. A failed recall or reranking
stage that still yields evidence reports `hybrid_v2_degraded`, with warnings and
stage diagnostics. Fallback is explicitly marked `retrieval_fallback=legacy`.
News legacy retrieval reads the actual news collection, never another industry.

News citations preserve source IDs, chunk IDs, title, publication date, and
`url`/`source_url`. The coordinator registers them as `[C1]`, `[C2]`, etc. before
building the writing prompt and reference list.

## Verification

```powershell
& 'D:\Anaconda_envs\envs\kunlun\python.exe' scripts/verify_industry_hybrid_rag.py --industry all
& 'D:\Anaconda_envs\envs\kunlun\python.exe' scripts/verify_industry_hybrid_rag.py --industry all --writing-tasks
```

The verifier requires real dense and lexical recall, real reranking scores,
industry isolation, and evidence with sources. `--writing-tasks` also calls the
configured LLM to generate a small coordinator writing task. Results are written
to `report_generation/outputs/industry_hybrid_acceptance.json`; provider failures
or truncated output are reported as failures rather than retrieval success.
The coordinator disables thinking only for writing-task prompt synthesis to
reserve its output budget for complete JSON; body generation is unchanged.

Windows uses native byte-range locks and project-relative Chroma paths, so HNSW
files can persist in this project with its Chinese absolute path. BGE loading
supports the known newer Sentence Transformers export layout without changing
model files. The XLM-R reranker also has a narrow fallback for the known local
fast-tokenizer error in Transformers 4.57.2. Other model errors remain visible.

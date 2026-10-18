# Industry Hybrid Retrieval

All eight report industries use `hybrid_v2` exclusively. AI uses the existing five
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

## Retrieval and Diagnostics

Report retrieval has a single hybrid path. The legacy and compare branches,
comparison diagnostics, and automatic fallback to old vector stores have been
removed. `REPORT_RETRIEVAL_MODE` and `REPORT_RETRIEVAL_ALLOW_LEGACY_FALLBACK`
are no longer read and can be removed from launch environments.

Full success reports `retrieval_version=hybrid_v2`. A failed recall or reranking
stage that still yields evidence reports `hybrid_v2_degraded`, with warnings and
stage diagnostics. Index initialization failure or failure of both recall routes
returns an error without querying an old vector store. Repair the hybrid index
or restore a verified v2 backup before retrying.

AI ingestion now requires successful v2 dense and lexical writes before updating
the retained 384-dimensional offline source. A v2 write failure is recorded by the
existing ingestion error flow, rather than reported as a successful legacy-only
update. `REPORT_RAG_V2_DUAL_WRITE` is no longer used. Existing old databases and
`--source legacy-chroma` offline import remain available; no database migration
or deletion is performed by this cleanup.

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


## macOS 本机运行（2026-10-15）

本机项目目录为 `/Users/livictor/Desktop/industry/industry_graph`，Python 环境为
`/opt/miniconda3/envs/kunlun/bin/python`。从项目根目录运行：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/build_news_hybrid_index.py --industry all --action check
/opt/miniconda3/envs/kunlun/bin/python scripts/verify_industry_hybrid_rag.py --industry all --output report_generation/outputs/industry_hybrid_acceptance.json
```

七产业关键词索引已接入 `RAG/indexes/report_v2_news/`：复用原有具身智能正式索引，
将生物制造、量子科技、脑机接口、新材料、海洋经济、低空经济从本机验证目录同盘移动。
七产业正式 READY 检查和八产业真实混合检索均已通过。详细记录位于
`report_generation/outputs/hybrid-rollout-20261015/`，本轮完整报告与导出验收因外部模型生成超时未完成，详情及续跑方法见该目录的
`acceptance.md`。原验证目录里的构建记录仍反映历史状态，不代表当前发布状态。

后端无需检索模式或旧库回退环境变量。更新代码后，在无进行中报告的窗口重新加载实际服务；
以协调器响应中的 `external_rag_retrieval.retrieval_version` 确认使用了混合检索。
历史验收记录中的 legacy/compare/fallback 配置仅反映清理前状态。完整生成和导出验收的
历史限制仍见上述 `acceptance.md`。

新增或修改资讯后，仅同步受影响的产业。例如生物制造：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/build_news_hybrid_index.py --industry biology --action sync --workers 1
```

同步可能需要与对应关键词索引相当的临时空间。已有索引只需复用原向量，不要求重新嵌入；
不对所有产业重复 build。模型、索引和验收产物按现有忽略规则保留在本机，代码与操作文档可通过 Git 协作。

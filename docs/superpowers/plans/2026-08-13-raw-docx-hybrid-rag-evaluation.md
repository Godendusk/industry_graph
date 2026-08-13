# 原始资料 Hybrid-RAG 小样本评测实施计划

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: 从 RAG/raw_docx_files 建立五类、可追溯、与生产索引隔离的小样本资料集，并完成新版 Hybrid-RAG 的分阶段召回、重排和端到端评测。

Architecture: 新增只读原始 DOCX 处理模块，负责结构化抽取、规则分类、待复核标记和样本清单；新增独立评测索引构建入口，将结构化 blocks 转成现有 ChunkRecord 并写入 RAG/indexes/raw_docx_eval_v1。评测脚本复用现有 DenseStore、LexicalStore、RRF、reranker 和 HybridRetrievalPipeline，保存各阶段结果，不改变生产 legacy 路径。

Tech Stack: Python 3.10、python-docx、现有 retrieval_core、Chroma、SQLite FTS5、SentenceTransformers、JSONL、unittest/pytest（以项目可用环境为准）。

---

## 文件边界

- Create: evaluation/raw_docx_rag/__init__.py — 评测包入口。
- Create: evaluation/raw_docx_rag/classifier.py — DOCX 结构化抽取、标题识别和五类规则分类。
- Create: evaluation/raw_docx_rag/sample_builder.py — 分类清单、分层样本和汇总报告。
- Create: evaluation/raw_docx_rag/index_builder.py — 独立 v2 索引构建。
- Create: evaluation/raw_docx_rag/evaluate.py — 分阶段检索和指标计算。
- Create: evaluation/raw_docx_rag/README.md — 操作说明和人工审核门。
- Create: scripts/build_raw_docx_rag_sample.py — 分类/样本 CLI。
- Create: scripts/build_raw_docx_rag_index.py — 独立索引 CLI。
- Create: scripts/evaluate_raw_docx_rag.py — 评测 CLI。
- Create: evaluation/raw_docx_rag/queries.jsonl — 五个主题的初始诊断问题，初始 review_status 为 unreviewed。
- Create: tests/test_raw_docx_classifier.py
- Create: tests/test_raw_docx_sample_builder.py
- Create: tests/test_raw_docx_index_builder.py
- Create: tests/test_raw_docx_evaluate.py
- Generate, untracked: evaluation/raw_docx_rag/sample_manifest.jsonl、classification_summary.json、results/、RAG/indexes/raw_docx_eval_v1/
- Do not modify: RAG/vector_db、RAG/vector_db1、retrieval_core、现有生产报告 Agent。

## Task 1: 建立 DOCX 结构化抽取与确定性五类分类器

Files:
- Create: evaluation/raw_docx_rag/classifier.py
- Test: tests/test_raw_docx_classifier.py

- [ ] Step 1: Write failing tests for paragraph/table extraction. Create a temporary DOCX containing a Title paragraph, Heading 1, body paragraph, and 2x2 table. Assert extract_docx_material returns the title, ordered blocks heading/paragraph/table, and a table text containing 企业：甲公司；能力：智算。 Add an empty-document test expecting ValueError containing no usable text.
- [ ] Step 2: Run the focused test and confirm the expected missing-module or missing-symbol failure:
  cd industry_graph && python -m unittest tests.test_raw_docx_classifier -v
- [ ] Step 3: Implement frozen SourceBlock and ExtractedMaterial records plus extract_docx_material(path). Iterate OOXML body children through python-docx, preserve paragraph/table order, maintain Heading N section_path, convert tables to labeled text, derive the first title-style paragraph or first block as title, and raise ValueError for empty input.
- [ ] Step 4: Add failing classification tests for explicit policy, company case, and an ambiguous AI development observation. Assert policy, company_case, and review_required respectively.
- [ ] Step 5: Run the classification tests and confirm failure because classify_material is absent.
- [ ] Step 6: Implement immutable ClassificationResult and deterministic rules. Use the existing EXTERNAL_LIBRARIES mapping. Recognize policy terms such as 政策、法规、行动方案、管理办法、意见、通知、规划; speech terms such as 讲话、演讲、致辞、发言; company terms such as 案例、实践、经验、路径、标杆; expert terms such as 专家观点、专家视角、访谈、评论、观察; research terms such as 研究、分析、趋势、洞察、启示、建议、展望、报告. Give title hits higher weight than body hits, require a score margin, and return review_required for low-confidence or near-tied results while preserving matched_rules.
- [ ] Step 7: Run focused tests and commit:
  cd industry_graph && python -m unittest tests.test_raw_docx_classifier -v
  git add evaluation/raw_docx_rag/classifier.py tests/test_raw_docx_classifier.py
  git commit -m "feat: classify raw docx rag materials"

## Task 2: Build the 50-100 篇 sample manifest with review isolation

Files:
- Create: evaluation/raw_docx_rag/sample_builder.py
- Create: scripts/build_raw_docx_rag_sample.py
- Test: tests/test_raw_docx_sample_builder.py

- [ ] Step 1: Write failing tests for allocate_quotas and select_samples. Verify quotas never exceed availability; duplicate source paths collapse to one record; review_required rows are excluded; selected rows carry auto_labeled and unreviewed status.
- [ ] Step 2: Run:
  cd industry_graph && python -m unittest tests.test_raw_docx_sample_builder -v
  Expected: failure because sample builder functions do not exist.
- [ ] Step 3: Implement classify_directory(raw_root), allocate_quotas(available_counts, target_per_library=15), select_samples(rows, target_per_library=15), and write_manifest(rows, manifest_path, summary_path). Deduplicate by normalized filename plus SHA-256, require successful extraction and one of the five formal labels, sort deterministically by library/body-length bucket/source path, and record the full pool plus review_required counts in the summary.
- [ ] Step 4: Add the CLI with --raw-root, --output-manifest, --output-summary, and --target-per-library. Defaults are RAG/raw_docx_files, evaluation/raw_docx_rag/sample_manifest.jsonl, evaluation/raw_docx_rag/classification_summary.json, and 15. The CLI must never write to RAG/vector_db. Create queries.jsonl with five unreviewed questions covering端侧 AI、智算绿色化、DeepSeek/开源模型、AI Agent、运营商 AI 布局; each row includes query, report_title, current_section, current_subsection, retrieval_goal, relevant_material_ids, and review_status.
- [ ] Step 5: Run focused tests and commit:
  cd industry_graph && python -m unittest tests.test_raw_docx_sample_builder -v
  git add evaluation/raw_docx_rag/sample_builder.py scripts/build_raw_docx_rag_sample.py tests/test_raw_docx_sample_builder.py evaluation/raw_docx_rag/queries.jsonl
  git commit -m "feat: build raw docx rag sample manifest"

## Task 3: Build an isolated v2 index from approved sample rows

Files:
- Create: evaluation/raw_docx_rag/index_builder.py
- Create: scripts/build_raw_docx_rag_index.py
- Test: tests/test_raw_docx_index_builder.py

- [ ] Step 1: Write failing tests for approved_rows and evaluation_index_root. Only rows with review_status approved are indexable; evaluation_index_root(project_root) equals project_root/RAG/indexes/raw_docx_eval_v1 and is not RAG/vector_db.
- [ ] Step 2: Run:
  cd industry_graph && python -m unittest tests.test_raw_docx_index_builder -v
  Expected: failure because index_builder does not exist.
- [ ] Step 3: Implement approved_rows(rows), evaluation_index_root(project_root), and build_index(manifest_path, project_root, index_root=None, dry_run=False). Reject missing/empty category coverage with status blocked; reject unapproved rows; parse DOCX, convert blocks via build_report_chunks, and write through V2IndexWriter to the evaluation root. Store classification_name, source_path, source_sha256, manifest_sha256, model/chunker/dictionary versions. Call mark_ready only after every upsert succeeds. Missing local models must return blocked without READY.
- [ ] Step 4: Add CLI arguments --manifest, --project-root, --index-root, --build, and --dry-run. Default index root is RAG/indexes/raw_docx_eval_v1. Exit 0 only for dry-run or successful build.
- [ ] Step 5: Run focused tests and commit:
  cd industry_graph && python -m unittest tests.test_raw_docx_index_builder -v
  git add evaluation/raw_docx_rag/index_builder.py scripts/build_raw_docx_rag_index.py tests/test_raw_docx_index_builder.py
  git commit -m "feat: build isolated raw docx rag index"

## Task 4: Implement staged retrieval evaluation and metrics

Files:
- Create: evaluation/raw_docx_rag/evaluate.py
- Create: scripts/evaluate_raw_docx_rag.py
- Test: tests/test_raw_docx_evaluate.py

- [ ] Step 1: Write failing tests for evaluate_ranked_materials and stage_names. For ranked ids a,b,c and relevant b,c at k=3, assert recall 1.0, MRR 0.5, and nDCG greater than 0.7. Assert stage_names returns dense, lexical, fusion, rerank, full.
- [ ] Step 2: Run:
  cd industry_graph && python -m unittest tests.test_raw_docx_evaluate -v
  Expected: failure because the evaluator is absent.
- [ ] Step 3: Implement stage runners using RetrievalCandidate, DenseStore.search, LexicalStore.search, reciprocal_rank_fusion, rerank_candidates, and HybridRetrievalPipeline. Return JSON-safe per-query records preserving candidates, metadata, scores, diagnostics, warnings, and status for dense, lexical, fusion, rerank, and full. If a stage fails, mark it unavailable with exception type and warning rather than manufacturing candidates. Aggregate Recall@5/10, MRR, and nDCG@10 overall and by library only for approved query judgments.
- [ ] Step 4: Add CLI arguments --queries, --manifest, --index-root, --output-dir, --top-k, and --allow-unreviewed. Refuse unreviewed queries for formal metrics by default; diagnostic mode records reviewed false. Save results.jsonl, summary.json, and run_metadata.json under a run directory.
- [ ] Step 5: Run focused tests and commit:
  cd industry_graph && python -m unittest tests.test_raw_docx_evaluate -v
  git add evaluation/raw_docx_rag/evaluate.py scripts/evaluate_raw_docx_rag.py tests/test_raw_docx_evaluate.py
  git commit -m "feat: evaluate raw docx rag retrieval stages"

## Task 5: Add operating documentation and verification gates

Files:
- Create: evaluation/raw_docx_rag/README.md
- Modify: README.md with a short link to the evaluation workflow, leaving default mode unchanged.

- [ ] Step 1: Document the exact workflow:
  cd industry_graph
  python scripts/build_raw_docx_rag_sample.py
  manually review evaluation/raw_docx_rag/sample_manifest.jsonl
  python scripts/build_raw_docx_rag_index.py --manifest evaluation/raw_docx_rag/sample_manifest.jsonl --dry-run
  python scripts/build_raw_docx_rag_index.py --manifest evaluation/raw_docx_rag/sample_manifest.jsonl --build
  python scripts/evaluate_raw_docx_rag.py --queries evaluation/raw_docx_rag/queries.jsonl --manifest evaluation/raw_docx_rag/sample_manifest.jsonl --index-root RAG/indexes/raw_docx_eval_v1 --output-dir evaluation/raw_docx_rag/results --allow-unreviewed
  Explain that automatic labels are not final labels, production collections remain untouched, and formal metrics require approved material and query judgments.
- [ ] Step 2: Run structural verification:
  cd industry_graph
  python -m unittest discover -s tests -p 'test_raw_docx_*.py' -v
  python scripts/build_raw_docx_rag_sample.py --raw-root RAG/raw_docx_files --target-per-library 15
  python scripts/build_raw_docx_rag_index.py --manifest evaluation/raw_docx_rag/sample_manifest.jsonl --dry-run
  git diff --check HEAD~1..HEAD
  git status --short
  Confirm tests pass, five category counts and review_required are reported, dry-run does not create READY, and pre-existing user changes remain untouched.
- [ ] Step 3: Stop before real embedding/build if any category has fewer than 10 usable samples or if the manifest has no approved rows. Present the classification summary and sample manifest to the user for review. Do not claim retrieval metrics before approved judgments exist.
- [ ] Step 4: Commit documentation after verification:
  git add evaluation/raw_docx_rag/README.md README.md
  git commit -m "docs: document raw docx rag evaluation workflow"

## Verification checklist before completion

- [ ] Production RAG/vector_db and RAG/vector_db1 are unchanged by evaluation scripts.
- [ ] legacy remains the default RetrievalConfig mode.
- [ ] Five-category counts and review_required count are recorded.
- [ ] No unreviewed material enters the approved index.
- [ ] DOCX paragraph/table extraction is tested.
- [ ] READY is published only after all writes succeed.
- [ ] Query results retain candidate metadata and stage warnings.
- [ ] Recall@5, Recall@10, MRR, and nDCG@10 are computed only for approved judgments.
- [ ] Fresh verification commands are run and read before reporting status.

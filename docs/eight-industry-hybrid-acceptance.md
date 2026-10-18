# Eight Industries: Hybrid Retrieval Acceptance

> 2026-10-15 更新：本文保留早期实现/验收记录。当前报告检索已统一为 hybrid_v2，legacy、compare 与旧库自动回退已移除；AI 摄取必须写入 v2。当前操作说明见 docs/industry-hybrid-retrieval.md。


Completed on 2026-10-14 in the existing `kunlun` environment. The AI rebuild
paused during the earlier seven-industry delivery has now been resumed and
published. All eight industries have passed actual `hybrid_v2` retrieval and
one coordinator writing task with registered source citations. None of those
acceptance queries required fallback or degraded retrieval.

## AI Completion

- All five original report libraries retained: speech, research_report, policy,
  expert_view, and company_case.
- Source: 4,117 materials and 39,341 original 384-dimensional chunks.
- Published index: 30,598 new 768-dimensional BGE chunks, 583,610,708 bytes
  (about 0.54 GiB), under `RAG/indexes/report_v2/`.
- Resume skipped 2,647 completed materials and built the remaining 1,470.
  This resumed build took approximately 989 seconds, including recovery checks;
  that is not the duration of the earlier partial build or subsequent acceptance.
- Ready validation confirmed all document states succeeded, counts agreed,
  and dense/lexical chunk IDs matched exactly.
- A fresh process successfully reopened the published index, retrieved sourced
  evidence through dense recall, keyword recall, fusion and local reranking,
  and generated a real writing task containing `[C1]` citations.
- Actual legacy retrieval and comparison mode also passed. A simulated hybrid
  outage successfully returned real legacy evidence and explicit fallback
  diagnostics; this does not claim an actual production outage occurred.

The Windows publication command now builds in a child process and waits for
that process to exit before moving directories. Five publication regression
tests cover child failure, missing readiness, backup preservation, move-failure
rollback, and refusing to overwrite an existing backup. The 45 index/recovery
tests passed, with one POSIX-only skip; the earlier 100 report-RAG tests also
passed. `git diff --check` passed.

## Eight-Industry Result

| Industry | Indexed chunks | Documents | Actual hybrid and citation task |
| --- | ---: | ---: | --- |
| ai | 30,598 | 4,117 | Passed |
| embodied | 1,337,440 | 244,177 | Passed |
| low_altitude | 546,082 | 45,391 | Passed |
| sea | 83,981 | 10,279 | Passed |
| quantum | 56,601 | 4,903 | Passed |
| biology | 20,880 | 2,706 | Passed |
| brain | 32,798 | 4,465 | Passed |
| material | 70,866 | 13,000 | Passed |

Published indexes total 17,223,729,492 bytes (about 16.04 GiB), excluding original
databases, models, backups and diagnostic artifacts. The seven news industries
reuse their original vectors. Their earlier real acceptance results were
retained, and readiness plus content digests were rechecked after AI completion.

Detailed evidence, writing prompts, references, index receipts, dimensions and
mode results are in the local ignored artifact
`report_generation/outputs/eight_industry_hybrid_acceptance.json`.
Earlier news counts and build/sync timings are in
[seven-news-hybrid-acceptance.md](seven-news-hybrid-acceptance.md).
Operation and update commands are in
[industry-hybrid-retrieval.md](industry-hybrid-retrieval.md).

Scope: actual retrieval and small coordinator writing tasks, not eight complete
long-form reports or their exported files. Restart an existing report backend
to load the updated code. A pre-publication index is retained as
`RAG/indexes/report_v2.previous/`; archive it before another replacement build.

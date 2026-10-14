# Seven News Industries: Acceptance

Verified on 2026-10-14 with `D:\Anaconda_envs\envs\kunlun\python.exe`.
This is the earlier seven-industry snapshot. AI was subsequently completed;
see [eight-industry-hybrid-acceptance.md](eight-industry-hybrid-acceptance.md).
The user narrowed delivery to seven news industries and paused the AI index
rebuild. AI is NOT claimed as fully accepted; its original retrieval/fallback
remains available and unfinished staging data is retained.

All seven passed actual dense recall, complete-document keyword recall, RRF
fusion, local BGE reranking, source/industry isolation, and a real coordinator
writing task containing registered `[C1]` references. No fallback or degraded
retrieval was used in these acceptance queries. This verifies a small writing
task, not seven complete exported reports.

| Industry | Original chunks | News documents | Keyword index GiB | Saved build/sync seconds | Document keyword upgrade seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| embodied | 1,337,440 | 244,177 | 10.355 | 2354.84 | 241.95 |
| low_altitude | 546,082 | 45,391 | 3.755 | 233.00 | 56.44 |
| sea | 83,981 | 10,279 | 0.473 | 37.00 | 7.16 |
| quantum | 56,601 | 4,903 | 0.231 | 14.34 | 2.61 |
| biology | 20,880 | 2,706 | 0.117 | 5.27 | 1.36 |
| brain | 32,798 | 4,465 | 0.179 | 10.14 | 2.16 |
| material | 70,866 | 13,000 | 0.389 | 23.97 | 5.83 |

Totals: 2,148,648 original chunks, 324,921 news documents, 16,640,118,784 bytes
of published keyword sidecars (about 15.50 GiB). Source vectors were reused,
not copied or re-encoded. Disk totals exclude original databases, models,
AI staging data, and diagnostic artifacts. Saved build/sync timings describe
the last recorded operation, not total development or initial build time.

Detailed evidence, stage counts, writing prompts, references, hashes, exact
sizes, and timings are in the local ignored artifact
`report_generation/outputs/seven_news_hybrid_acceptance.json`.
The compatible BGE embedding output is 768-dimensional, unit-normalized,
and deterministic on repeated CPU inference.

Relevant regression suites passed: 166 retrieval tests, 100 report-RAG tests
(one POSIX-only skip), 24 embodied tests, 14 news tests, 13 coordinator
stability tests, and five citation-coordinator tests. `git diff --check` passed.
Operations and recovery commands: [industry-hybrid-retrieval.md](industry-hybrid-retrieval.md).

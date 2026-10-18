# 产业报告检索评测

`labeling_set.jsonl` 必须经领域人员逐条改为 `approved` 后，才能作为上线评测集。

生成候选集：`python scripts/build_report_retrieval_label_set.py --manifest-dir RAG/vector_db --output evaluation/report_retrieval/labeling_set.jsonl --total 60`。

评测工具默认拒绝未审核数据；仅诊断时可显式加 `--allow-unreviewed`。线上报告检索统一使用 `hybrid_v2`，不再支持 legacy、compare 或自动回退旧库。混合索引故障需修复索引或恢复已验证的 v2 备份。

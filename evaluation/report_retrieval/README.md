# 产业报告检索评测

`labeling_set.jsonl` 必须经领域人员逐条改为 `approved` 后，才能作为上线评测集。

生成候选集：`python scripts/build_report_retrieval_label_set.py --manifest-dir RAG/vector_db --output evaluation/report_retrieval/labeling_set.jsonl --total 60`。

评测工具默认拒绝未审核数据；仅诊断时可显式加 `--allow-unreviewed`。默认线上模式始终是 `legacy`，回滚只需设置 `REPORT_RETRIEVAL_MODE=legacy`。

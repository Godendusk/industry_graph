# 报告质量实施验证

基线包含当前未提交 GraphRAG/Agentic 改动。源代码快照 /tmp/report-quality-baseline-20261016。

入口：确认大纲 coordinator/stream（同步 coordinator）；正文 body/stream（同步 body）；摘要 summary；Word export/word；下载 export/word/download；历史 POST/GET report/history。前端保存 writingTasks/bodySections/review/references。正文当前有序串行，max_workers 不代表正文并行。

baseline.json 只记录历史实际字段，源代码版本未知。海洋最终历史不能代替部分导出文件内容。每项检查对应 cases.json 具体失败；unknown 不等于事实错误或准确率。先离线测试，再新题验证。

实施及真实报告验收见 [acceptance-summary.md](acceptance-summary.md)。最终程序验证见 verification.json。当前内容验收未通过，runs 中结果均为验证稿。

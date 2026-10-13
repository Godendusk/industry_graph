# 动态图谱层级合并验证（2026-10-13）

将 `codex/dynamic-graph-hierarchy` 合入 `main`，保留主分支多产业图谱检索及统筹功能。图谱检索冲突按“当前行业配置 + 动态末级环节”整合；测试使用当前 `_IndustryGraph` 和行业配置接口，补充具身智能五级环节的完整路径、企业及提示词验证。

## 验证结果

使用 `/opt/miniconda3/envs/kunlun/bin/python` 和本机 Node。

| 检查 | 合并前 | 合并后 |
| --- | --- | --- |
| `python -m unittest discover -s tests -q` | 362 项；5 处断言失败、3 处错误、1 项跳过 | 376 项；相同的 5 处断言失败、3 处错误、1 项跳过 |
| `node --test tests/js/*.test.js` | 38 项，35 通过、3 失败 | 45 项，42 通过、相同的 3 项失败 |
| 动态层级 Python 定向测试 | — | 14 项通过 |
| 动态层级 JavaScript 定向测试 | — | 7 项通过 |
| pytest 相关集成测试 | — | 50 项通过 |

pytest 集合包括：`test_industry_config.py`、`test_topic_news_integration.py`、`test_coordinator_stability.py`、`test_report_coordinator_citations.py`、`test_report_rewrite_citations.py`、`test_report_body_citations.py`、`test_word_export_citations.py` 和四个动态图谱 Python 测试文件。

只读加载当前 8 个产业图谱；所有挂接到环节的企业均可通过末级环节找到，没有发现仅挂接内部环节而被遗漏的企业。AI 为 48 个末级环节、527 家企业，具身智能为 43 个末级环节、968 家企业。

2026-08-24 原始微信附件路径已不存在，本次未复验该附件的 113 个末级环节、399 家企业。未执行浏览器人工验收或真实模型报告生成。

## 合并前已有的失败

Python 均在 `tests/test_task_card_agent.py`：

- 三个任务卡测试的模拟返回值耗尽，报 `StopIteration`：行业别名、JSON 重试、资料可用性标志。
- 需求重试测试期待 `model_retry`，实际为 `fallback`：空输出、长度截断、超长或不完整输出。
- 失败原因分类的两个子用例与当前实现不一致。

JavaScript 均在 `tests/js/test_industry_report_navigation.test.js`：

- 具身智能统筹请求测试期待非流式地址，当前实际调用 `/api/report/coordinator/stream`。
- 任务卡备用提示测试期待确认提示，当前实际显示“报告需求已提交”。
- 工作流 DOM 模拟缺少 `querySelector` 方法。

这些失败在合并前后相同，尚未判定所有失败属于产品缺陷还是测试预期过时。本次未修改这些既有行为和失败测试。

主工作区原有的专题资讯检索代码、未跟踪资料库和工具文件未纳入此次合并提交。

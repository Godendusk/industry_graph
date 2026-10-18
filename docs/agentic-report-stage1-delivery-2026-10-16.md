# 产业报告 Agentic RAG 第一阶段交付说明

日期：2026-10-16。第一阶段已实施，第二至第四阶段尚未开始。

## 已实现的行为

章节检索开始时，系统根据报告需求、章节目标、写作重点、时间要求和资料开关生成一至三个子问题。每个子问题记录要查什么、需要哪些原文证据，以及选择普通 Hybrid 检索或图谱辅助检索的原因。

现有协调器仍控制小节并发；小节内部顺序执行子问题。继续复用 Hybrid v2、图谱关键词扩展、图谱关联原文、资料分配与统一引用登记。

- 行业由报告输入继承，计划不能改变行业或开启已关闭的数据源。
- 规划异常、无效结构或输出截断时使用原固定查询，并保留原因；不重试规划模型。
- 多子问题时关闭原有逐查询来源数量补查，避免隐式重复调用；单问题及固定查询回退保留原有至多一次来源数量补查，并记录实际补查查询。这尚不是第二阶段的语义缺口补查。
- 不同查询的候选交替进入合并池，再沿用现有章节资料分配；按已有片段标识去重，保留原文、来源、图谱适用范围和关联信息。
- 证据通过 `agentic_query_refs` 中的 `outline_id/query_id` 对应到检索计划，报告引用仍为原有 `[C数字]`。
- 同步与流式任务都携带 `agentic_retrieval`，包含规划状态、实际查询、工具状态、候选数、诊断和耗时。
- 部分检索失败时保留有效结果并记录 `partial`；全部失败与成功但无命中保持不同状态。
- 写作决策异常时仍保留检索记录。自动合并小节时，来源记录保存在目标的 `merged_agentic_retrievals`；合并或删除说明也保存来源记录。
- 现有前端历史保存完整 `writingTasks`，服务端保存完整报告对象，因此任务中的记录可随报告保存；本阶段没有新增专门的轨迹界面。

## 本次代码范围

新增：

- `report_generation/agentic_rag/__init__.py`
- `report_generation/agentic_rag/schemas.py`：计划结构和允许策略校验。
- `report_generation/agentic_rag/planner.py`：一次结构化模型规划与固定查询回退。
- `report_generation/agentic_rag/executor.py`：顺序执行、候选合并、来源关联和执行记录。
- `tests/test_agentic_report_planner.py`
- `tests/test_agentic_report_executor.py`
- `tests/test_agentic_report_integration.py`
- `tests/test_agentic_report_outline.py`

修改：

- `report_generation/coordinator_agent.py`：两种入口共用章节规划执行；传递时间要求和执行记录。
- `report_generation/outline_adjustments.py`：保留合并、删除小节的执行记录及证据来源关联。
- `tests/test_coordinator_stability.py`：模型桩支持新增规划调用，并核对调用量。
- 四阶段实施规划：更新第一阶段进度。

本次在隔离工作树中带入最新未提交 GraphRAG 代码开发，随后仅将第一阶段增量应用到当前项目，保留其他已有工作区改动。

## 自动化验证

当前项目中运行以下相关回归，结果为 **128 passed，3 subtests passed**：

```sh
LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest \
  tests/test_agentic_report_planner.py \
  tests/test_agentic_report_executor.py \
  tests/test_agentic_report_integration.py \
  tests/test_agentic_report_outline.py \
  tests/test_coordinator_stability.py \
  tests/test_report_coordinator_citations.py \
  tests/test_graph_query_expansion.py \
  tests/test_graph_evidence_retrieval.py \
  tests/test_report_decision_flow.py \
  tests/test_body_agent.py \
  tests/test_report_body_citations.py \
  tests/test_report_task_coordination.py \
  tests/test_report_outline_adjustments.py -q
```

这些测试不调用真实模型，覆盖行业/开关继承、无效计划、规划异常、去重及原文限定保留、部分失败、空命中、同步/流式引用衔接、时间仅存在大纲时的传递、写作决策异常和自动大纲调整后的记录保存。

独立审阅发现并修复两处问题：大纲时间未传入实际查询；自动合并小节丢失来源执行记录。修复均已复核通过。

## 真实章节验证

在当前项目使用本地真实具身智能图谱、索引、检索模型与现有配置的 deepseek-v4-flash，验证“人形机器人减速器企业竞争格局”。输入要求覆盖2024—2026年产品布局、产业链位置及公开订单或产能依据。

| 环节 | 最终复测结果 |
| --- | --- |
| 规划 | `planned`，选择一个图谱辅助联合检索问题 |
| 图谱与外部检索 | 均成功 |
| 分配前候选 | 16个片段 |
| 分配后资料 | 8个证据块、8份参考资料 |
| 正文生成 | 成功，实际使用 C5、C2、C3、C6 四个引用 |
| 端到端耗时 | 约74.95秒，含规划、检索、写作决策、协调与正文生成 |

结果保存在 `report_generation/outputs/agentic-stage1-20261016/`：

- `coordination.json`：完整计划、实际查询、检索状态、证据与参考资料。
- `body.json`：正文及实际引用。
- `chapter.md`：便于阅读的生成小节。
- `summary.json`：运行结果摘要。

真实验证中，现有写作决策模块返回的结构或来源未通过校验，使用备用写作决策后完成正文。警告保留在原始结果中；摘要文件将协调和正文各自警告合并展示，因此同一警告出现两次，并不表示规划器失败了两次。

本次样例验证第一阶段的执行链路和引用衔接，没有证明整体质量优于当前基线，也没有执行第二阶段证据充分性判断或第三阶段事实支持核对。时间要求当前进入查询与执行记录，尚不代表底层执行了硬日期过滤。

## 后续入口

下一阶段将把现有来源数量补查统一为证据缺口驱动的补查，并在资料分配后确认关键支持片段仍然保留。界面进度、专门的证据缺口展示与完整报告对照验收按原计划进入后续阶段。

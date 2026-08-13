# 产业报告 Hybrid RAG 改造总结

## 一句话说明

这次改造的目标，是把**产业报告资料检索**从“单一向量库找相似段落”，升级为“语义检索 + 关键词检索 + 融合排序 + 精排”的可控检索系统。

它只服务于产业报告模块；项目中原有的 `RAG/vector_db/knowledge_base` 仍属于另一套通用知识库 RAG，不能混入产业报告索引。

默认线上行为仍是旧方案（`legacy`），新方案尚未被设为默认。

## 当前总状态

12 个研发任务的代码、单元测试和运维入口已完成。最新全量自动化测试为 **262 通过、2 个可选依赖跳过**。

真实运营验收尚未完成，原因不是代码缺失，而是本机没有可迁移的产业报告旧索引数据：预期的五个历史集合均不存在。模型已下载，但真实 v2 索引、60 条真实标注和三种模式的实际检索验证必须等产业报告源数据到位后执行。

## 12 个任务做了什么

| 任务 | 目的（通俗说法） | 主要改动 | 状态 |
| --- | --- | --- | --- |
| 1. 统一配置与数据结构 | 先让所有模块使用同一套“资料块”和“检索结果”语言 | 新增 `retrieval_core/config.py`、`schemas.py`，定义本地模型/索引路径、检索参数、不可变 Chunk 和候选结果 | 完成 |
| 2. 报告切分 | 把长报告切成既不过大也不丢上下文的小块 | 新增 `retrieval_core/chunker.py`：识别标题、段落、列表、表格；控制长度、重叠、token 上限和稳定 chunk ID | 完成 |
| 3. BM25 词法检索 | 让政策名、企业名、年份、编号这类精确查询更可靠 | 新增 `retrieval_core/lexical_store.py`：SQLite + FTS5、关键词检索、资料类型过滤、相邻块读取 | 完成 |
| 4. Dense 检索与模型管理 | 让语义相近的表述能被召回，同时适配 M4 Air | 新增/加固 `dense_store.py`、`model_manager.py`：Chroma cosine 校验、BGE 本地加载、MPS 失败后一次性回退 CPU | 完成 |
| 5. RRF 融合与精排 | 合并“语义命中”和“关键词命中”，再把最相关的排到前面 | 新增 `fusion.py`、`reranker.py`：RRF、去重、每材料候选上限、reranker 失败保留融合排序 | 完成 |
| 6. 混合检索编排 | 把两路召回、融合、精排变成一个容错流程 | 新增 `pipeline.py`：单路失败仍可返回、阶段耗时/数量/告警、结果深度不可变 | 完成 |
| 7. 报告适配器 | 让报告写作请求变成更聚焦的检索问题，并兼容旧证据格式 | 新增 `report_adapter.py`：章节意图聚焦、资料类型路由、软回退、旧 evidence/context 格式 | 完成 |
| 8. v2 双索引写入器 | 保证 SQLite 和 Chroma 不会一边成功一边悄悄出错 | 新增 `v2_index.py`：双写、状态机、READY 标记、崩溃恢复、跨进程锁、严格 768 维和 ID 审计 | 完成 |
| 9. 索引构建器 | 把旧资料转换为 v2 索引，先看报告再实际写入 | 新增 `build_report_hybrid_index.py`、模型下载脚本：dry-run、旧 Chroma/离线 payload 输入、构建报告和 staging 路径 | 完成（真实数据待验） |
| 10. 三种运行模式 | 可以安全地逐步上线新检索而不是一次性替换 | 修改 `retriever.py`：`legacy`、`compare`、`hybrid_v2`；compare 返回旧结果，v2 失败可显式回退 legacy | 完成（真实索引待验） |
| 11. 增量双写 | 新资料入库时旧索引照常写，新索引可逐步补齐 | 修改 `ingestion.py`：`REPORT_RAG_V2_DUAL_WRITE=1` 才启用；记录 v2 chunk ID 与错误，不影响 legacy 成功 | 完成 |
| 12. 评测与交付 | 用数据判断新检索是否真的更好，并给运维留下操作说明 | 新增评测指标、60 条均衡标注分配器、人工审核保护、评测说明；更新 README | 代码完成，真实验收待数据 |

## 最关键的几项改动

### 1. 两套 RAG 已明确隔离

产业报告 v2 的设计路径是 `RAG/indexes/report_v2/`；通用知识库仍在自己的 `RAG/vector_db/knowledge_base`。两套数据、索引、检索入口和上线节奏不能混用。

这是最重要的边界。否则产业报告引用会混进通用问答材料，结果看似能回答、实际上证据来源不可控。

### 2. 检索从单路向量查询升级为四步流程

```text
聚焦后的报告问题
    ├─ BGE 语义召回（Dense）
    └─ SQLite FTS5 / BM25 关键词召回
              ↓
        RRF 融合、去重
              ↓
       BGE reranker 精排
              ↓
       兼容旧格式的证据块
```

Dense 更擅长“意思相近”，BM25 更擅长名称、年份、政策编号。两者一起用，才能避免单路检索的明显短板。

### 3. v2 索引不是“写完就算成功”

v2 写入器会检查：两边 chunk ID 是否相同、向量是否严格 768 维、实际 SQLite token 是否合规、版本是否一致、READY 文件是否原子发布。并发写入和中途崩溃会留下可诊断状态，而不会错误地标记整个索引可用。

### 4. 新旧切换可回滚

默认模式是 `legacy`。先用 `compare` 观察新旧差异，再在满足评测条件后使用 `hybrid_v2`。如果 v2 初始化、索引或模型出错，结果会记录 `retrieval_fallback=legacy`，而不是静默失败。

## 主要新增/修改文件

- 检索核心：`retrieval_core/config.py`、`schemas.py`、`chunker.py`、`lexical_store.py`、`dense_store.py`、`model_manager.py`、`fusion.py`、`reranker.py`、`pipeline.py`
- 产业报告接入：`report_generation/external_rag/report_adapter.py`、`v2_index.py`、`retriever.py`、`ingestion.py`
- 运维与评测：`scripts/build_report_hybrid_index.py`、`scripts/provision_retrieval_models.py`、`scripts/evaluate_report_retrieval.py`、`scripts/build_report_retrieval_label_set.py`、`evaluation/report_retrieval/README.md`
- 回归测试：`tests/test_retrieval_*.py`、`tests/test_report_rag_*.py`、`tests/test_report_retrieval_evaluation.py`

## 已下载的本地模型

- embedding：`RAG/model_store/bge-base-zh-v1.5`（约 391MB）
- reranker：`RAG/model_store/bge-reranker-base`（约 1.1GB）

它们只会在明确启用 v2 构建或检索时加载；legacy 默认流程不会自动下载模型。

## 真实验收的阻塞与下一步

当前本机检查到：

- `RAG/vector_db` 只有 `knowledge_base`，不是产业报告的五个历史集合；
- `report_generation/vector_db` 为空；
- 因而不能生成真实报告资料的 v2 索引，也不能从真实材料抽样 60 条标注。

需要补充以下任一数据来源：

1. 产业报告旧 Chroma 库的真实路径，且其中包含五类 `report_*_ai` 集合；或
2. 已保存的外部 API JSON/HTML payload 目录；或
3. 五类资料的 manifest 与正文数据。

拿到数据后建议按顺序执行：dry-run → 生成 60 条待审核标注 → 人工审核 → 正式构建 v2 → `compare` 观察 → 离线评测 → 小范围启用 `hybrid_v2`。

## 本次验收的本地副作用

虽然原计划是只读检查，Chroma 打开旧 `RAG/vector_db` 时改动了该目录的 `chroma.sqlite3`，构建器初始化还创建了未完成的 `RAG/indexes/`。这些都是本地未提交文件，未进入 Git；后续应在备份副本上打开旧 Chroma，避免再次触碰历史库。

# 产业报告 Hybrid RAG v2 设计

- 日期：2026-08-10
- 状态：已确认，待实施计划
- 第一期范围：建设共享检索底座，只迁移产业报告外部资料 RAG
- 第二期范围：在第一期验收后迁移通用问答 RAG
- 目标环境：MacBook Air M4，16GB 统一内存，本地运行

## 1. 背景

产业报告外部资料库当前使用 `all-MiniLM-L6-v2` 生成 384 维向量，在五个 Chroma Collection 中分别执行单路 Dense 检索，再按距离合并前十条结果。该方案已经能够跑通，但存在以下问题：

1. embedding 模型偏英文，不适合中文产业、政策和企业资料检索。
2. 报告资料按自然段直接入库，长段落会被 256 token 的旧模型截断，短段落则可能被直接丢弃。
3. 只有 Dense 召回，企业名、政策名、年份、文件编号和行业术语的精确召回能力不足。
4. 没有 reranker，向量距离直接决定最终材料排序。
5. 查询混入大量固定模板词，容易稀释当前章节的真实检索意图。
6. 缺少版本化索引、影子对比、检索评测和安全回滚机制。

本设计将产业报告检索升级为：

```text
聚焦查询
  -> Dense 召回 + BM25 召回
  -> RRF 融合
  -> Cross-Encoder reranker
  -> 报告业务规则与多样性调整
  -> 相邻 Chunk 扩展
  -> evidence_blocks
```

## 2. 目标与非目标

### 2.1 目标

1. 使用 `BAAI/bge-base-zh-v1.5` 提升中文语义召回能力。
2. 让 Dense 与 BM25 基于完全相同的一批 Chunk 和稳定 ID。
3. 使用 SQLite FTS5 和 jieba 实现无需独立搜索服务的本地 BM25。
4. 使用 `BAAI/bge-reranker-base` 对融合候选精排。
5. 保持 `retrieve_external_rag(query, top_k=10)` 的函数签名和主要返回结构不变。
6. 保持 outline、coordinator、body、rewrite、前端和导出模块的业务调用方式不变。
7. 新旧索引并行存在，支持 legacy、compare 和 hybrid_v2 三种模式。
8. 在 M4 Air 16GB 环境中限制模型并发和内存峰值。
9. 建立可重复的离线评测与上线验收流程。

### 2.2 非目标

1. 第一期不迁移通用问答 RAG。
2. 第一期不引入 Elasticsearch、OpenSearch、Milvus 等外部服务。
3. 第一期不使用 BGE-M3 的 sparse 或 multi-vector 能力。
4. 第一期不改变正文生成、报告导出和前端交互。
5. 第一期不删除或覆盖现有 `RAG/vector_db`。
6. 第一期不对 embedding 或 reranker 做领域微调。

## 3. 方案选择

### 3.1 采用方案

采用本地平衡方案：

- Embedding：`BAAI/bge-base-zh-v1.5`
- Dense：Chroma 单 Collection
- Lexical：SQLite FTS5 + jieba
- 融合：Reciprocal Rank Fusion（RRF）
- 精排：`BAAI/bge-reranker-base`
- 运行方式：本地进程内按需加载、全局单例、受控并发

### 3.2 未采用方案

未采用 BGE-M3 + bge-reranker-v2-m3，因为 M4 Air 16GB 无风扇，长时间索引和多个章节并发精排会产生更高的内存与温度压力。未采用 Dense + reranker 的简化方案，因为它不能解决企业名、政策名、年份和编号的精确召回问题。

## 4. 总体架构

```text
report_generation/external_rag/retriever.py
  -> report_adapter
      -> retrieval_core.pipeline
          -> query processor
          -> dense_store
          -> lexical_store
          -> fusion
          -> reranker
          -> neighbor expansion
      -> report evidence adapter
  -> 兼容的 evidence_blocks / rag_context_text
```

### 4.1 共享检索底座

新增 `retrieval_core/`，建议包含：

```text
retrieval_core/
├── config.py
├── schemas.py
├── model_manager.py
├── chunker.py
├── dense_store.py
├── lexical_store.py
├── fusion.py
├── reranker.py
└── pipeline.py
```

职责如下：

- `config.py`：模型路径、索引路径、候选数、模式与功能开关。
- `schemas.py`：Chunk、Candidate、RetrievalResult 等共享数据结构。
- `model_manager.py`：embedding 和 reranker 单例、设备探测、锁和降级。
- `chunker.py`：通用结构化切分接口和 token 上限校验。
- `dense_store.py`：Chroma v2 的读写与查询。
- `lexical_store.py`：SQLite 主表、FTS5、BM25、相邻块读取。
- `fusion.py`：RRF、ID 合并、重复控制。
- `reranker.py`：Cross-Encoder 批量精排。
- `pipeline.py`：完整在线检索编排。

共享底座不知道报告标题、章节模板和五类资料的业务含义。

### 4.2 报告适配层

新增 `report_generation/external_rag/report_adapter.py`，负责：

1. 把外部资料转换成统一 ChunkRecord。
2. 根据报告章节意图设置资料库优先级和时间策略。
3. 将统一检索结果转换回现有 `evidence_blocks`。
4. 保持 `citation_id`、library、title、publish_date、source_address、paragraph_index、vector_id 和 text 等字段兼容。
5. 增加只用于日志和调试的 dense、BM25、RRF、reranker 排名字段。

## 5. 统一数据结构

### 5.1 ChunkRecord

```text
chunk_id
document_id
chunk_index
previous_chunk_id
next_chunk_id
text
embedding_text
search_text
token_count
content_hash
metadata
```

metadata 至少包含：

```text
industry
library
classification_type
classification_name
material_id
title
publish_date
source_address
section_path
content_type
chunker_version
embedding_model
```

### 5.2 ID 规则

```text
external:v2:{library}:{material_id}:c:{chunk_index}:{content_hash_8}
```

Dense 与 BM25 必须使用同一个 `chunk_id`。Manifest 保存完整 `chunk_ids`，不再只保存 `chunk_count`。

## 6. 切分设计

### 6.1 结构识别

HTML 资料提取 h1-h6、p、li、blockquote、表格标题、表头和数据行，并维护当前段落所属的标题路径。研究报告摘要使用相同的句子和长度规则。

### 6.2 长度规则

- 理想正文长度：220-350 个中文字符。
- 软上限：400 字符。
- 原始正文硬上限：450 字符。
- 最小独立 Chunk：80 字符。
- 只有拆分长段落时重叠一个完整句子，重叠最多 60 字符。
- 写入前使用目标 tokenizer 验证 `embedding_text` 不超过 480 tokens。

### 6.3 短段落

少于 80 字符的有效段落不直接删除。它与同一标题层级的上一段或下一段合并。URL、版权、责任编辑、空白和模板噪声仍然过滤。

### 6.4 长段落

依次按标题、自然段、中文句末标点、分号、枚举边界切分，最后才允许按 token 强制切分。不得依赖 embedding 模型自动截断。

### 6.5 三种文本

- `text`：提供给大模型的干净原文。
- `embedding_text`：资料类型、标题、章节路径和正文。
- `search_text`：jieba 分词并加入产业词典后的标题、实体、章节和正文。

### 6.6 表格

表格每行转成“表头：值”的结构化文本，保留表格标题和章节路径，metadata 设置 `content_type=table`。

### 6.7 相邻块

reranker 完成后才扩展相邻块。默认前一块和后一块，每条证据扩展后最多 900 字符；相邻块必须属于同一材料，优先要求相同章节路径。

## 7. 模型与设备

### 7.1 模型目录

```text
RAG/model_store/bge-base-zh-v1.5/
RAG/model_store/bge-reranker-base/
```

旧 `RAG/models/` 保持不动。在线服务不自动下载缺失模型。

### 7.2 Embedding 参数

- 维度：768。
- `normalize_embeddings=True`。
- Query 指令：`为这个句子生成表示以用于检索相关文章：`。
- 文档不加 Query 指令。
- 离线 batch size：16。
- 在线 batch size：1。

### 7.3 Reranker 参数

- batch size：4。
- 单次最多 24 个候选。
- 默认最终输出 10 条。
- Query 控制在 100 tokens 以内。
- Query、标题、章节路径和正文共同进入 Cross-Encoder。

### 7.4 设备与并发

设备选择顺序为 MPS、CPU。首次 MPS 推理必须健康检查；失败后记录日志并在当前进程中固定回退 CPU，不能在每次请求中反复尝试。

embedding 与 reranker 分别使用全局单例。reranker 使用全局容量为 1 的信号量；报告章节可以并发做图谱和关键词查询，但 Cross-Encoder 精排排队执行，避免多章节同时占用模型。

## 8. 索引设计

### 8.1 路径

```text
RAG/indexes/report_v2/
├── chroma/
├── lexical.sqlite3
├── build_report.json
└── READY
```

### 8.2 Chroma

使用单一 Collection：`report_external_v2`。

- HNSW space：cosine。
- metadata 中使用 `library` 区分五类资料。
- 支持按 library、industry 和日期过滤。
- 所有向量必须由同一模型和同一 chunker 版本生成。

### 8.3 SQLite

`lexical.sqlite3` 包含 documents、chunks、chunks_fts 和 index_metadata。

FTS5 字段及初始权重：

- title_tokens：5
- entity_tokens：4
- section_tokens：2
- body_tokens：1

SQLite 同时作为 Chunk 原文、相邻关系和构建 Manifest 的权威记录；Chroma 负责向量及必要 metadata。

### 8.4 READY 条件

只有满足以下条件才写入 READY：

1. SQLite 事务完成。
2. Chroma 写入完成。
3. 两边 `chunk_id` 集合完全一致。
4. Collection 维度为 768。
5. 所有 Chunk token 数合规。
6. 抽样查询通过。
7. build report 无阻断错误。

## 9. 在线检索流程

### 9.1 Query 处理

报告适配器从用户要求、报告标题和当前章节中生成不超过 100 tokens 的聚焦 Query。固定模板中与当前章节无关的“问题、政策、案例、建议”等词不再全部拼入同一个向量查询。

Dense Query 使用 BGE 指令。BM25 Query 使用 jieba 和版本化产业词典；两者来自同一个聚焦意图，但表达形式不同。

### 9.2 默认候选数

- Dense：40。
- BM25：40。
- RRF 常数：60。
- RRF 权重：Dense 1.0，BM25 1.0。
- 融合后进入 reranker：24。
- 最终输出：默认 10，可少于 10。
- 同一材料 reranker 前最多 3 块，最终最多 2 块。

### 9.3 RRF

```text
score = dense_weight / (60 + dense_rank)
      + bm25_weight / (60 + bm25_rank)
```

融合只依赖排名，不直接混加不可比的原始分数。单路失败时允许另一条召回链继续进入 reranker。

### 9.4 业务调整

报告适配器根据章节意图执行轻量调整：

- 政策章节优先 policy 和 speech。
- 企业实践优先 company_case。
- 专家判断优先 expert_view 和 research_report。
- 最新进展可以使用时间衰减，历史分析不使用。
- 资料类型优先是软约束；候选不足时回退全库。
- 不强制用低相关资料补满 top_k。

业务规则不能覆盖明显的 reranker 相关性差异，具体幅度通过评测校准。

## 10. 一致性、增量更新与失败处理

### 10.1 全量构建

第一次构建使用新的 report_v2 目录，不修改旧库。先执行 dry-run，输出材料数、原始段落数、新 Chunk 数、token 分布、拆分数、合并数、表格数、噪声数、重复数和异常数。

正式构建写入临时目录，验证完成后再以目录切换方式发布为 `report_v2`，避免在线服务读到半成品。

### 10.2 增量更新

每份材料先生成完整的新 Chunk 集合，再执行：

1. SQLite 事务写入新 document、chunks 和 FTS。
2. Chroma upsert 新 ID。
3. 删除该材料不再存在的旧 Chroma ID。
4. 核对该材料两边 ID。
5. 成功后更新 manifest 状态。

如果 Chroma 阶段失败，SQLite 事务回滚或将该材料标记为 `inconsistent`，在线检索排除未完成材料，并由修复任务重试。全库 READY 不因单次增量失败被删除，但健康状态必须记录异常。

### 10.3 在线降级

降级顺序：

1. Dense + BM25 + reranker。
2. Dense + BM25，reranker 失败时使用 RRF 排名。
3. Dense 失败时 BM25 + 可用 reranker。
4. BM25 失败时 Dense + 可用 reranker。
5. v2 初始化失败时，在 `hybrid_v2` 模式返回结构化错误；可配置回退 legacy。

默认上线初期允许 v2 失败回退 legacy，并在结果中记录 `retrieval_fallback=legacy`。不能静默失败。

## 11. 发布、对比与回滚

支持三种模式：

- `legacy`：只执行旧检索。
- `compare`：旧检索正常返回，新检索影子执行并记录差异。
- `hybrid_v2`：新检索返回结果，必要时按配置回退旧检索。

发布顺序：

1. 构建并验证 report_v2 索引。
2. legacy 模式部署兼容代码。
3. compare 模式收集真实查询的新旧结果。
4. 离线评测和人工抽查通过。
5. hybrid_v2 小范围启用。
6. 全量切换。

回滚只需把模式改回 legacy 并重启服务，不删除 v2 索引，也不恢复数据库文件。

## 12. 可观测性

每次检索记录：

- retrieval_version 和 mode。
- Query 原文、聚焦 Query 和 library 路由。
- Dense、BM25、RRF、reranker 的候选数和耗时。
- 各候选的分路排名、RRF 排名、reranker 排名和最终排名。
- 设备、模型加载、MPS 回退和信号量等待时间。
- 降级原因和 legacy fallback。
- 最终资料类型分布、材料去重数量和相邻块扩展数量。

日志不得记录 access token 或其他密钥。

## 13. 测试与验收

### 13.1 自动化测试

1. Chunk 边界、短段合并、长段拆分、重叠和 token 上限。
2. 表格转文本和标题路径保留。
3. Chunk ID 稳定性与内容变化。
4. jieba 自定义词典及索引/查询分词一致性。
5. SQLite FTS5 创建、增删改、BM25 排名和过滤。
6. Dense/BM25 ID 集合一致性。
7. RRF 数学结果、单路缺失和去重。
8. reranker 候选上限、批量处理、异常降级。
9. report adapter 返回结构兼容。
10. legacy、compare、hybrid_v2 模式和回滚。
11. MPS 探测与 CPU fallback。
12. 增量更新失败时的一致性状态。

### 13.2 检索评测集

建立至少 60 条真实问题，覆盖：

- 政策名称和文件编号。
- 企业和机构名称。
- 年份、数字、地点和项目名称。
- 同义表达和概念性问题。
- 产业现状、问题、趋势和建议。
- 应优先不同资料类型的问题。
- 无答案和弱相关问题。

每条问题标注相关材料 ID 和理想段落，并记录章节意图。

### 13.3 指标

- Recall@10。
- nDCG@10。
- MRR。
- Top 10 材料级重复率。
- 有答案查询的有效证据覆盖率。
- 无答案查询的低质量材料误入率。
- P50、P95 总检索耗时及各阶段耗时。
- compare 模式中新旧结果的人工胜率。

### 13.4 第一阶段通过条件

1. 新索引所有 Chunk 均不超过 480 embedding tokens。
2. Dense 与 BM25 的 Chunk ID 完全一致。
3. 所有现有报告检索调用和返回结构兼容测试通过。
4. Hybrid v2 的 Recall@10、nDCG@10 不低于 legacy，至少一项有明确提升。
5. 企业名、政策名、年份和编号类查询的人工胜率高于 legacy。
6. reranker 故障时仍能返回 RRF 结果。
7. v2 故障时可以在配置允许下回退 legacy。
8. M4 Air 16GB 上完成真实索引构建和报告检索压力测试，无进程崩溃或内存失控。

性能阈值在基准测试获得真实数据后锁定，不能在测量前虚构固定毫秒数。

## 14. 实施阶段

### 阶段 A：评测与基础数据结构

先建立回归测试、统一 schema、配置和评测样本格式，不接入生产调用。

### 阶段 B：切分与索引构建

实现结构化切分、dry-run、SQLite FTS5、Chroma v2、模型管理和全量索引构建，验证 ID 一致性。

### 阶段 C：在线混合检索

实现聚焦 Query、Dense、BM25、RRF、reranker、去重、相邻扩展和报告适配器。

### 阶段 D：兼容、降级与影子模式

接入现有 `retrieve_external_rag`，实现 legacy、compare、hybrid_v2、日志和 fallback。

### 阶段 E：A/B 评测与切换

运行离线评测、真实查询影子对比和 M4 Air 压力测试，通过验收后再切换 hybrid_v2。

### 阶段 F：第二期准备

总结第一期参数和缺陷，再为通用问答 RAG 单独设计 DOC/DOCX 切分、图谱融合和迁移方案。

## 15. 已确认决策

1. 共享检索底座先建设，产业报告 RAG 第一期接入，通用问答第二期接入。
2. 采用共享核心 + 报告适配器，上层报告模块保持兼容。
3. 使用结构优先、长度兜底、命中后扩展的统一切分。
4. 使用 `bge-base-zh-v1.5`、SQLite FTS5、RRF 和 `bge-reranker-base`。
5. 新索引版本化并与旧索引并行存在。
6. 新 Chroma 使用单一 `report_external_v2` Collection。
7. 默认 Dense 40、BM25 40、RRF 后 24、最终 10。
8. 支持 legacy、compare 和 hybrid_v2。
9. 目标环境为 M4 Air 16GB，reranker 并发固定为 1。

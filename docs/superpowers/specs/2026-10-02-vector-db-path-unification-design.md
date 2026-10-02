# 产业报告向量库路径统一方案

## 1. 背景

当前产业报告系统存在两套向量库路径判断方式：实际检索代码使用 `RAG/vector_db_*`，任务卡的可用性判断仍检查部分旧的 `report_generation/vector_db/*` 路径。结果是人工智能和具身智能的数据库实际存在，但页面显示“外部资料库不可用”。

本方案统一产业报告向量库的配置、可用性判断和检索入口，同时保留问答场景的 `vector_db_QA` 独立管理。

## 2. 目标与范围

### 目标

- 八个产业报告向量库统一位于 `RAG/vector_db_<industry>`。
- 页面显示的资料库状态与实际检索使用的数据库一致。
- 路径只从产业配置读取，减少模块之间的路径分叉。
- 保留传统报告库和专题资讯库的检索差异。

### 范围

纳入产业报告流程的数据库：

- `vector_db_ai`
- `vector_db_embodied`
- `vector_db_low_altitude`
- `vector_db_sea`
- `vector_db_quantum`
- `vector_db_biology`
- `vector_db_brain`
- `vector_db_material`

不纳入本次整理的数据库：

- `vector_db_QA`：继续由问答流程独立使用。

本次不移动已有向量数据，主要统一配置和代码引用。

## 3. 配置设计

`report_generation/industry_config.py` 作为产业报告向量库路径的唯一配置源。每个产业配置包含：

- `vector_db_path`：实际 Chroma 数据目录；
- `rag_type`：`report` 或 `news`；
- `collection_name`：需要指定集合时使用；
- 传统报告库继续保留 `external_column_id`，专题资讯库不依赖该字段。

路径映射如下：

```text
ai             -> RAG/vector_db_ai
embodied       -> RAG/vector_db_embodied
low_altitude   -> RAG/vector_db_low_altitude
sea            -> RAG/vector_db_sea
quantum        -> RAG/vector_db_quantum
biology        -> RAG/vector_db_biology
brain          -> RAG/vector_db_brain
material       -> RAG/vector_db_material
```

## 4. 数据流

### 配置和状态判断

任务卡生成产业候选项时，从产业配置读取 `vector_db_path`，按以下规则判断资料库是否可用：

1. 配置存在有效的 `vector_db_path`；
2. 目录下存在 `chroma.sqlite3`；
3. `rag_type=report` 时，同时要求存在 `external_column_id`；
4. `rag_type=news` 时，数据库文件存在即可判定本地专题库可用。

### 检索分发

- `vector_store.py` 使用配置中的路径访问人工智能报告资料库；
- `embodied_store.py` 使用配置中的路径访问具身智能专题资讯库；
- `topic_news.py` 从配置读取六个专题资讯库的路径和集合名；
- `retriever.py` 根据产业配置分发到报告资料或专题资讯检索逻辑，不再维护第二套数据库路径。

传统报告库和专题资讯库仍保留不同的集合、元数据和检索入口。统一的是数据目录配置，不合并两类资料内容。

## 5. 异常行为

- 数据库目录或 `chroma.sqlite3` 缺失时，页面显示“外部资料库不可用”；
- 检索时发现资料库缺失，返回现有的无资料警告并继续报告生成；
- 系统不通过自动创建空 Chroma 库来掩盖路径配置错误。

## 6. 验证计划

- 检查八个产业的配置路径均指向 `RAG/vector_db_<industry>`；
- 使用现有数据库验证八个产业均能正确报告可用状态；
- 使用不存在的临时路径验证不可用状态；
- 验证 AI、具身智能和六个专题产业进入正确的检索分支；
- 验证 `vector_db_QA` 相关问答流程不受影响；
- 重新打开任务卡，确认下拉框文案和资料源勾选状态与真实数据库一致。

## 7. 不在范围内的事项

- 不重建向量数据库；
- 不合并传统报告库和专题资讯库；
- 不改动 `vector_db_QA` 的目录和问答流程；
- 不引入自动扫描所有目录的动态发现机制。

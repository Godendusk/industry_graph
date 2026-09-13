# 具身智能资讯报告 RAG 实施计划

> **面向智能代理的说明：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 子技能，逐项执行本计划。以下步骤使用复选框（`- [ ]`）进行跟踪。

**目标：** 将最新 100 条具身智能专题资讯摄入一个独立的 768 维 Chroma 集合，并让具身智能报告生成流程通过该集合和具身智能图谱进行检索，同时不改变现有人工智能报告链路。

**架构：** 在 `report_generation/external_rag` 下增加专用的专题资讯 API 客户端和摄入模块。摄入模块通过列表接口获取最新 100 条资讯 ID，通过详情接口获取完整正文，使用本地 `bge-base-zh-v1.5` 模型对 300–500 字符的文本片段生成向量，并写入新的持久化 Chroma 目录 `RAG/vector_db_embodied/`。旧的人工智能链路继续使用现有五个集合；只有 `industry="embodied"` 使用新的直接 Chroma 分支。

**技术栈：** Python `requests`、`sentence-transformers`、`chromadb`、现有报告生成 Agent、现有 `static/data/embodied/graph_data.json`，以及 `unittest`/`pytest`。

---

## 文件职责

- 新建 `industry_graph/report_generation/external_rag/embodied_client.py`：专题列表/详情 HTTP 客户端；从进程环境变量读取 `EMBODIED_ACCESS_TOKEN` 和 `EMBODIED_X_ACCESS_TOKEN`；绝不把凭证写入源代码或清单文件。
- 新建 `industry_graph/report_generation/external_rag/embodied_store.py`：独立 Chroma 路径、集合名称、统一的 embedding 模型路径、片段 ID、向量生成、写入和查询操作。
- 新建 `industry_graph/report_generation/external_rag/embodied_ingestion.py`：获取最新 100 条资讯、获取详情、清洗和切分文本、写入向量，并返回摄入统计信息。
- 修改 `industry_graph/report_generation/external_rag/retriever.py`：接受可选的 `industry` 参数，将具身智能查询分发到独立集合，同时保留现有人工智能查询行为。
- 修改 `industry_graph/report_generation/external_rag/graph_retriever.py`：让图谱路径和返回的行业动态化，同时保留兼容人工智能的包装函数。
- 修改 `industry_graph/report_generation/outline_agent.py`、`coordinator_agent.py` 和 `rewrite_agent.py`：在图谱检索和外部 RAG 检索调用中传递 `industry`。
- 修改 `industry_graph/report_generation/body_agent.py`、`summary_agent.py` 和 `word_export_agent.py`：识别 `embodied` 对应的“具身智能”，使现有报告阶段接受该行业。
- 新建 `industry_graph/tests/test_embodied_news_rag.py`：覆盖 API 请求参数、详情处理、文本切分、upsert ID、检索路由和图谱选择的单元测试。
- 修改 `industry_graph/tests/test_report_rag_modes.py` 及现有报告生成测试：保留人工智能行为，并增加具身智能路由断言。

### 任务 1：增加经过测试的专题资讯 API 客户端

**文件：**
- 新建：`industry_graph/report_generation/external_rag/embodied_client.py`
- 测试：`industry_graph/tests/test_embodied_news_rag.py`

- [ ] **步骤 1：编写客户端失败测试**

使用 mock 的 `requests.post` 测试 `EmbodiedNewsClient.list_news(page_no=1, page_size=100)`。断言请求使用 `/subjectServer/info/subjectPageList` 的 `POST` 方法，并包含 `subjectId="2043590589800853505"`、`pageNo=1`、`pageSize=100`、`status=1`、`isSubject="1"`、`category=1`、空的搜索数组，以及 `column="publishDate"`、`order="desc"`。断言 `get_detail()` 使用 `/subjectServer/info/queryById` 的 `GET` 请求，并携带 `id` 和 `index="subjectdatabase_2026"`。增加业务码非 200 时抛出 `EmbodiedNewsClientError` 的测试，以及缺少 token 环境变量时在发起 HTTP 请求之前抛出明确配置错误的测试。

```python
@patch("report_generation.external_rag.embodied_client.requests.post")
def test_list_news_uses_embodied_subject_payload(self, post):
    post.return_value = fake_response({"code": 200, "result": {"records": [], "total": 0}})
    client = EmbodiedNewsClient(access_token="access", x_access_token="x-access")

    client.list_news(page_no=1, page_size=100)

    payload = post.call_args.kwargs["json"]
    self.assertEqual(payload["subjectId"], "2043590589800853505")
    self.assertEqual(payload["pageNo"], 1)
    self.assertEqual(payload["pageSize"], 100)
    self.assertEqual(payload["column"], "publishDate")
    self.assertEqual(payload["order"], "desc")
```

- [ ] **步骤 2：运行聚焦测试并确认它失败**

在 `industry_graph` 目录下运行：

```bash
pytest -q tests/test_embodied_news_rag.py -k "list_news or detail or token"
```

预期：失败，因为 `embodied_client.py` 和 `EmbodiedNewsClient` 尚不存在。

- [ ] **步骤 3：实现客户端**

定义生产环境 CLB URL、具身智能专题 ID 和 `subjectdatabase_2026` 常量。`EmbodiedNewsClient.__init__` 接受可选的显式 token（用于测试），未传入时从 `EMBODIED_ACCESS_TOKEN` 和 `EMBODIED_X_ACCESS_TOKEN` 读取。构造请求头时加入两个 token，以及 `env=prod`、`environment=prod`、`Content-Type=application/json` 和当前毫秒级 `timeLine`。`list_news()` 发送文档规定的请求体，并设置 `column="publishDate"`、`order="desc"`；`get_detail()` 发送 `id` 和 `index`。解析 JSON 并要求 `code == 200`，然后返回 `result` 对象。将 HTTP、JSON 和业务码错误转换为 `EmbodiedNewsClientError`，错误信息中包含页码或资讯 ID。

- [ ] **步骤 4：运行客户端聚焦测试**

```bash
pytest -q tests/test_embodied_news_rag.py -k "list_news or detail or token"
```

预期：通过。

- [ ] **步骤 5：提交客户端**

```bash
git add report_generation/external_rag/embodied_client.py tests/test_embodied_news_rag.py
git commit -m "feat: add embodied news API client"
```

### 任务 2：增加独立 Chroma 存储和 100 条资讯摄入

**文件：**
- 新建：`industry_graph/report_generation/external_rag/embodied_store.py`
- 新建：`industry_graph/report_generation/external_rag/embodied_ingestion.py`
- 测试：`industry_graph/tests/test_embodied_news_rag.py`

- [ ] **步骤 1：编写存储和摄入失败测试**

使用临时 Chroma 路径和 fake client。断言存储使用 `RAG/vector_db_embodied/`、集合 `embodied_news` 和模型路径 `RAG/model_store/bge-base-zh-v1.5`。断言 ID 稳定，例如 `"source-id:0"`，并检查设计中规定的元数据字段；再次执行 upsert 后，集合数量应保持不变。模拟一页包含两条记录的列表接口，其中一条详情有 HTML/普通文本，另一条正文为空；断言空正文被跳过，成功记录被切分，并且返回统计中包含 `records_seen=2`、`details_succeeded=1`、`skipped=1` 和大于 0 的 `chunks_written`。

```python
def test_ingestion_skips_empty_detail_and_upserts_stable_chunks(self):
    client = FakeEmbodiedClient(records=[record("a"), record("b")], details={
        "a": {"id": "a", "title": "标题", "content": "第一段。第二段。"},
        "b": {"id": "b", "title": "空正文", "content": ""},
    })
    store = FakeEmbodiedStore()

    stats = ingest_latest_news(client=client, store=store, limit=2)

    self.assertEqual(stats["records_seen"], 2)
    self.assertEqual(stats["details_succeeded"], 1)
    self.assertEqual(stats["skipped"], 1)
    self.assertGreater(stats["chunks_written"], 0)
    self.assertEqual(store.ids, ["a:0"])
```

- [ ] **步骤 2：运行聚焦摄入测试并确认它失败**

```bash
pytest -q tests/test_embodied_news_rag.py -k "storage or ingestion or chunk"
```

预期：失败，因为独立存储和摄入函数尚不存在。

- [ ] **步骤 3：实现文本清洗和切分**

在 `embodied_ingestion.py` 中去除 HTML 标签、解码 HTML 实体并统一空白字符；在正文前保留标题和摘要；优先按段落边界切分，再按中文句末标点切分，并尽量组合成 300–500 字符的片段。只有清洗后的正文、摘要和标题合起来都没有可用文本时，才跳过该详情。正文来源依次使用详情接口的 `contentWithTag`、`content`、`summary`。保留 `source_id`、`subject_id`、`title`、`publish_date`、`source`、`url`、`chunk_index` 和 `total_chunks` 等来源元数据。

- [ ] **步骤 4：实现独立存储**

在 `embodied_store.py` 中，将 `chromadb.PersistentClient` 创建在 `PROJECT_ROOT / "RAG" / "vector_db_embodied"`，获取或创建 `embodied_news` 集合，只加载 `RAG/model_store/bge-base-zh-v1.5`，使用归一化向量，并以稳定 ID `{source_id}:{chunk_index}` 调用 `collection.upsert()`。使用同一个模型进行查询，并返回文档、元数据、ID 和距离。不要导入或复用旧的五类资料库集合映射。

- [ ] **步骤 5：实现有边界的摄入**

`ingest_latest_news()` 必须请求一页、`pageSize=100` 的列表数据，使用 API 的发布日期降序，最多处理前 100 条记录；逐条获取详情，单条详情失败后继续处理；列表接口发生网络错误或鉴权失败时立即停止。只有在流程完成且至少写入一个片段时，才返回 `status="success"`；如果已有可用片段但部分详情或写入失败，则返回 `partial_success`；没有写入任何可用片段时返回 `error`。返回 `records_seen`、`details_succeeded`、`skipped`、`chunks_written`、`errors` 和 `collection_count`。

- [ ] **步骤 6：运行存储和摄入测试**

```bash
pytest -q tests/test_embodied_news_rag.py -k "storage or ingestion or chunk"
```

预期：通过。

- [ ] **步骤 7：提交独立摄入功能**

```bash
git add report_generation/external_rag/embodied_store.py report_generation/external_rag/embodied_ingestion.py tests/test_embodied_news_rag.py
git commit -m "feat: ingest embodied news into isolated chroma"
```

### 任务 3：在不改变人工智能检索的前提下增加具身智能路由

**文件：**
- 修改：`industry_graph/report_generation/external_rag/retriever.py`
- 修改：`industry_graph/report_generation/external_rag/__init__.py`
- 测试：`industry_graph/tests/test_embodied_news_rag.py`
- 修改：`industry_graph/tests/test_report_rag_modes.py`

- [ ] **步骤 1：编写路由失败测试**

增加测试，调用 `retrieve_external_rag("具身智能机器人进展", top_k=5, industry="embodied")`，并 mock 具身智能存储查询。断言结果为 `status="success"`、`retrieval_version="embodied_chroma"`，且只包含具身智能集合的结果。增加测试，确认 `industry="ai"` 仍调用现有模式分发器且不会导入具身智能存储；再增加测试，确认 `industry="unknown"` 返回错误，而不是静默回退到人工智能。

```python
def test_embodied_route_queries_only_embodied_collection(self):
    with patch("report_generation.external_rag.retriever.retrieve_embodied_news",
               return_value={"status": "success", "evidence_blocks": []}) as embodied:
        result = retrieve_external_rag("查询", top_k=5, industry="embodied")

    self.assertEqual(result["status"], "success")
    embodied.assert_called_once_with("查询", 5)
```

- [ ] **步骤 2：运行路由测试并确认它失败**

```bash
pytest -q tests/test_embodied_news_rag.py tests/test_report_rag_modes.py
```

预期：失败，因为当前不接受 `industry` 参数，也没有具身智能分支。

- [ ] **步骤 3：实现路由分支**

将公开函数签名改为 `retrieve_external_rag(query, top_k=DEFAULT_TOP_K, industry="ai")`，以保持现有位置参数调用方式兼容。将 `industry="embodied"` 分发到使用 `embodied_store.query_embodied_news` 的直接 Chroma 辅助函数；将 `industry="ai"` 分发到现有 legacy/hybrid 模式逻辑，保持其行为不变；其他值统一返回 `_error_response(f"unsupported industry: {normalized_industry}", normalized_query, normalized_top_k)`。具身智能结果应使用现有 evidence block 结构，并包含 `library="embodied_news"`、来源 ID、标题、日期、来源、URL、文本和距离元数据。

- [ ] **步骤 4：运行路由和回归测试**

```bash
pytest -q tests/test_embodied_news_rag.py tests/test_report_rag_modes.py tests/test_rag_storage_separation.py
```

预期：通过；旧的人工智能模式测试仍能验证原有分发行为。

- [ ] **步骤 5：提交检索路由**

```bash
git add report_generation/external_rag/retriever.py report_generation/external_rag/__init__.py tests/test_embodied_news_rag.py tests/test_report_rag_modes.py
git commit -m "feat: route embodied report retrieval"
```

### 任务 4：路由具身智能图谱，并在报告 Agent 之间传递行业参数

**文件：**
- 修改：`industry_graph/report_generation/graph_retriever.py`
- 修改：`industry_graph/report_generation/outline_agent.py`
- 修改：`industry_graph/report_generation/coordinator_agent.py`
- 修改：`industry_graph/report_generation/rewrite_agent.py`
- 修改：`industry_graph/report_generation/body_agent.py`
- 修改：`industry_graph/report_generation/summary_agent.py`
- 修改：`industry_graph/report_generation/word_export_agent.py`
- 测试：`industry_graph/tests/test_embodied_news_rag.py`

- [ ] **步骤 1：编写 Agent 和图谱失败测试**

mock 图谱加载和检索函数。断言 `retrieve_graph("查询", industry="embodied")` 打开 `static/data/embodied/graph_data.json` 并返回 `industry="embodied"`；断言 `retrieve_graph("查询", industry="ai")` 继续使用人工智能图谱。mock outline、coordinator 和 rewrite 模块中的 `retrieve_external_rag`，断言它们都传递调用者提供的 `industry`。断言每个 Agent 的行业映射都包含 `"embodied": "具身智能"`，并断言具身智能请求不会返回 `unsupported industry`。

- [ ] **步骤 2：运行图谱和 Agent 测试并确认它失败**

```bash
pytest -q tests/test_embodied_news_rag.py
```

预期：失败，因为当前图谱检索固定使用人工智能图谱，Agent 行业映射中也只有 `ai`。

- [ ] **步骤 3：实现动态图谱检索**

将仅支持人工智能的常量替换为明确的图谱文件映射，至少包含 `ai` 和 `embodied`。实现 `retrieve_graph(query, industry="ai")`，根据选定行业的图谱路径执行检索并返回对应行业。保留 `retrieve_ai_graph(query)`，使其成为固定使用 AI 的薄兼容包装函数，以兼容现有调用方和测试。请求不支持的行业时，不得回退到人工智能。

- [ ] **步骤 4：在检索调用中传递行业参数**

修改 outline、coordinator 和 rewrite 的辅助函数签名，接收已经标准化的行业参数。outline 辅助函数保留当前固定的 `top_k=10` 调用；coordinator 和 rewrite 继续使用各自已有的 `top_k` 参数。三者都调用 `retrieve_graph(query, industry=normalized_industry)`；同时分别调用 `retrieve_external_rag(query, top_k=10, industry=normalized_industry)` 或 `retrieve_external_rag(query, top_k=top_k, industry=normalized_industry)`。在六个报告 Agent 的 `SUPPORTED_INDUSTRIES` 映射中加入 `"embodied": "具身智能"`。保持现有模板解析、提示词结构和人工智能默认行为不变。

- [ ] **步骤 5：运行聚焦的 Agent 回归测试**

```bash
pytest -q tests/test_embodied_news_rag.py tests/test_report_rag_modes.py tests/test_report_rag_adapter.py
```

预期：通过。

- [ ] **步骤 6：提交图谱和 Agent 路由**

```bash
git add report_generation/graph_retriever.py report_generation/outline_agent.py report_generation/coordinator_agent.py report_generation/rewrite_agent.py report_generation/body_agent.py report_generation/summary_agent.py report_generation/word_export_agent.py tests/test_embodied_news_rag.py
git commit -m "feat: propagate embodied industry through reports"
```

### 任务 5：执行已授权的 100 条在线摄入，并验证报告检索

**文件：**
- 修改：`industry_graph/report_generation/external_rag/embodied_ingestion.py`，仅在任务 2 尚未提供命令行入口时增加运行日志或 CLI 入口。
- 运行时新建、不提交：`industry_graph/RAG/vector_db_embodied/` 及其中的 Chroma 文件。

- [ ] **步骤 1：在仓库外配置凭证**

在执行摄入的 shell 中读取两个已批准的 token，不回显其内容：

```bash
read -rsp 'accessToken: ' EMBODIED_ACCESS_TOKEN; printf '\n'
export EMBODIED_ACCESS_TOKEN
read -rsp 'X-Access-Token: ' EMBODIED_X_ACCESS_TOKEN; printf '\n'
export EMBODIED_X_ACCESS_TOKEN
```

确认两个变量都没有写入受 Git 跟踪的文件，摄入命令也不会打印它们。

- [ ] **步骤 2：执行 100 条资讯摄入**

使用模块提供的明确摄入入口，传入 `--limit 100` 和 `--page-size 100`。预期输出包含 `records_seen=100`、详情成功/跳过/失败数量、`chunks_written > 0` 和 `collection_count > 0`。如果列表接口返回 401/10001/10002 或发生网络错误，必须停止并返回 `status="error"`；单条详情失败可以返回 `partial_success`。

- [ ] **步骤 3：验证独立数据库的维度和数量**

使用 Chroma 只读打开 `RAG/vector_db_embodied`，断言集合 `embodied_news` 存在，断言其数量等于摄入结果中的 `collection_count`，并使用 `bge-base-zh-v1.5` 查询。查询必须返回 Top 5 结果，查询向量维度为 768，且结果包含具身智能元数据。

- [ ] **步骤 4：验证三个验收问题**

分别使用 `retrieve_external_rag(query, top_k=5, industry="embodied")` 执行以下查询，并检查 Top 5 的标题、日期、来源和片段文本：

```text
具身智能人形机器人有哪些最新进展？
具身智能产业链有哪些核心环节？
具身智能相关政策支持有哪些？
```

预期：结果来自 `embodied_news`，而不是旧的人工智能集合。

- [ ] **步骤 5：验证报告和图谱边界**

使用 `industry="embodied"` 调用报告 outline、coordinator、body、summary 和 export API。确认响应携带 `industry_name="具身智能"`，外部证据来自 `embodied_news`，图谱证据来自 `static/data/embodied/graph_data.json`。再执行一次人工智能检索，确认它仍然使用原有五类资料库路径。

- [ ] **步骤 6：运行完整的相关测试集**

在声称完成之前运行：

```bash
pytest -q tests/test_embodied_news_rag.py tests/test_report_rag_modes.py tests/test_rag_storage_separation.py tests/test_report_rag_adapter.py tests/test_report_rag_ingestion_v2.py tests/test_report_rag_v2_index.py tests/test_retrieval_pipeline.py
```

预期：所有选定测试通过。如果存在无关的既有失败，应单独记录，不要为了掩盖它而修改具身智能实现。

- [ ] **步骤 7：只提交源代码和测试**

```bash
git add report_generation tests
git commit -m "feat: connect embodied news to report generation"
```

生成的 `RAG/vector_db_embodied/` 数据库保持在本地，除非项目现有政策明确要求跟踪向量产物。

## 对照设计文档的自检

- 任务 1、任务 2 和任务 5 覆盖 100 条限制及发布日期降序。
- 任务 2 覆盖独立 Chroma 路径、单一集合、768 维模型、稳定 ID、元数据和 upsert 行为。
- 任务 2 覆盖详情补全、空正文跳过、单条失败继续处理和列表级失败停止。
- 任务 3 覆盖具身智能专用检索、人工智能行为保留和不支持行业报错。
- 任务 4 覆盖行业参数传递、具身智能图谱路由和模板复用。
- 任务 5 覆盖三个验收问题及人工智能链路边界。
- 源代码、测试、清单和提交产物中都不放置凭证。

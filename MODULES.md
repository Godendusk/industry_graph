# 功能模块说明（四大模块）

本文件用于“按模块”说明系统能力：每个模块包含**定位/输入输出/主要代码与函数/使用方法（前端与 API）**，用于交付与验收说明。

> 统一说明：项目内所有大模型调用统一走 `llm_client.py`（`llm = LLMClient()` 单例），由各模块脚本引用。
> 部署、运行与数据准备（含数据格式与存放位置）详见：`DEPLOYMENT.md`。

## 0）产业报告文章溯源

### 0.1 数据关系

- `coordinator` 完成外部资料检索后，按 `library + material_id`（缺失时回退 `vector_id`）分配报告级 `C1...Cn`。
- `writing_tasks[].external_rag_retrieval.evidence_blocks` 保存本节允许使用的编号；`references` 保存报告级去重资料。
- `body_sections[].citation_ids` 只保存正文实际出现且通过本节证据校验的编号。
- 局部重写复用已有编号，新材料从当前最大编号后追加；历史记录缺少 `references` 时按空数组兼容加载。

### 0.2 接口字段

- `POST /api/report/coordinator`：返回带 `citation_id` 的外部证据块和候选 `references`。
- `POST /api/report/body`：请求携带统筹阶段的完整 `references`；响应返回每节 `citation_ids` 以及实际使用的 `references`。
- `POST /api/report/rewrite`：请求和响应携带 `references`；响应返回重写节的 `citation_ids`、更新后的证据块和引用表。
- `POST /api/report/export/word`：请求携带 `references`；Word 只输出正文实际使用的参考资料。

### 0.3 引用边界

正文中的 `[C数字]` 只能引用当前小节证据集合中存在的编号；非法编号会被清理并产生可见 warning。引用校验保证材料可追溯，不自动证明材料充分支持相邻结论。知识图谱依据仅可打开图谱节点，不宣称具有原始文章溯源能力。

---

## 1）基础图谱通过其骨架进行补充

### 1.1 模块定位

- 以现有图谱的产业链骨架（环节 `level=1/2/3` + 关系类型“从属于”）作为稳定结构，在**骨架保持不变**前提下，通过上传业务数据（Excel）自动抽取实体与关系，并挂接到既有骨架上，逐步完善行业知识图谱。

### 1.2 输入 / 输出

- 输入
  - 图谱主库：`static/data/graph_data.json`
  - Excel：至少包含列 `正文`（每行作为一条文本记录）
- 输出（落盘）
  - 合并后的图谱主库仍写回：`static/data/graph_data.json`
  - 导入会话与日志：`uploads/sessions/<session_id>/`（含上传文件、`session.json`、`import_log.json`）

### 1.3 主要代码与函数

- 后端路由：`backend_server.py`
  - 预览导入：`graph_import_upload()` → `POST /api/graph_import/upload`
  - 勾选入图：`graph_import_commit()` → `POST /api/graph_import/commit`
  - 图谱维护：`graph_node_update()`、`graph_node_delete()`、`graph_export()`、`graph_backup()`
  - JSON 导入：`graph_import_json()`、`graph_import_json_replace()`
- 抽取脚本：`graph_import_script.py`
  - 预览阶段入口：`run_import(input_path, master_path, log_path=None)`
  - 主要类：`UltimateExtractor`（`process_data()` 读 Excel、组包、并发 LLM、产出候选）
- 前端可视化与操作
  - 图谱渲染：`static/js/modules/graph_viz.js`
    - 加载主库：`reloadGraphData()`（拉取 `/static/data/graph_data.json`）
    - 仅看骨架：`showSkeletonGraph()`（显示全部“环节”节点及其之间关系）
  - 导入交互：`static/js/modules/graph_import.js`
    - 解析预览：`triggerGraphImport()` → `/api/graph_import/upload`
    - 确认入图：`commitGraphImport()` → `/api/graph_import/commit`

### 1.4 使用方法（前端）

1. 进入“知识图谱”页面
2. 在“数据导入”区域选择 Excel
3. 点击“解析预览”，查看候选节点/关系（默认全选，可手动取消）
4. 点击“确认入图”
5. 点击“刷新图谱”查看最新主库效果

### 1.5 使用方法（API）

- 解析预览：`POST /api/graph_import/upload`
  - `multipart/form-data`：字段 `file`（xlsx）
  - 返回：`session_id` + `data: {nodes:[], links:[]}`（候选 temp_id）
- 确认入图：`POST /api/graph_import/commit`
  - JSON：`{"session_id":"...","nodes":[...temp_id],"links":[...temp_id]}`
  - 返回：`added_nodes` / `added_links`

补充说明：
- 当图谱仅有骨架或规模较小、需要长时间批量扩充时，可采用“冷启动/长时抽取”工具，以支持长任务运行与过程性保存。说明见：`cold_start_extraction/知识图谱自动化抽取工具 (V4.2 Robust) 使用说明.md`。

---

## 2）风险分析（Risk）

### 2.1 模块定位

- 基于当前图谱主库，选定一个 Level 2 环节节点，进行风险传导/结构风险分析，输出可视化图与 LLM 风险报告（Markdown），并在前端渲染、支持导出 PDF。

### 2.2 输入 / 输出

- 输入
  - 图谱主库：`static/data/graph_data.json`
  - 用户选择：`node_name`（Level 2 环节名）
- 输出
  - 图片/中间产物：`static/risk_outputs/<run_id>/...`
  - API 返回：`report`（Markdown）、`images`（`/static/...` URL 列表）、`log`

### 2.3 主要代码与函数

- 后端路由：`backend_server.py`
  - 节点列表：`risk_nodes()` → `GET /api/risk/nodes`
  - 运行分析：`risk_run()` → `POST /api/risk/run`
- 风险分析脚本：`risk_inference/risk.py`
  - `list_level2_nodes(graph_path)`：提取 Level 2 可选节点
  - `run_risk_analysis(node_name, graph_path, output_base)`：主分析流程（生成图片与报告）
- 前端：`static/js/modules/risk.js`
  - `loadRiskNodes()`：加载下拉
  - `runRiskAnalysis()`：触发运行并渲染报告与图片
  - `exportRiskPdf()`：导出“报告+图片”为 PDF

### 2.4 使用方法

- 前端：进入“风险分析” → 选择节点 → “开始分析” → 查看输出 → “导出 PDF”
- API：
  - `GET /api/risk/nodes`
  - `POST /api/risk/run`（JSON：`{"node_name":"算力调度"}`）

---

## 3）政策推演（Policy）

### 3.1 模块定位

- 从政策 Excel 中检索/选择一条政策，结合当前图谱主库进行政策影响推演，输出可视化图与 LLM 推演报告（Markdown），并在前端渲染、支持导出 PDF。

### 3.2 输入 / 输出

- 输入
  - 图谱主库：`static/data/graph_data.json`
  - 政策 Excel：默认 `policy_deduction/policy_data/人工智能政策法规.xlsx`（可在 `backend_server.py` 的 `POLICY_EXCEL_PATH` 修改）
  - 用户选择：`policy_index`
- 输出
  - 图片/中间产物：`static/policy_outputs/<run_id>/...`
  - API 返回：`title`、`report`（Markdown）、`images`（URL 列表）、`log`

### 3.3 主要代码与函数

- 后端路由：`backend_server.py`
  - 列表检索：`policy_list()` → `GET /api/policy/list?keyword=...`
  - 运行推演：`policy_run()` → `POST /api/policy/run`
- 推演脚本：`policy_deduction/Policy_deduction.py`
  - `list_policy_titles(excel_path=...)`：解析 Excel 生成政策标题列表
  - `run_policy_analysis(policy_index, graph_path, excel_path, output_base)`：主流程（生成图片与报告）
- 前端：`static/js/modules/policy_sim.js`
  - `fetchPolicyList()`：预加载列表到内存
  - `renderPolicyList()`：前端内存过滤（减少频繁请求，提升交互响应）
  - `runPolicyAnalysis()`：触发运行并渲染报告与图片
  - `exportPolicyPdf()`：导出“报告+图片”为 PDF

### 3.4 使用方法

- 前端：进入“政策推演” → 搜索并选中政策 → “开始推演” → 查看输出 → “导出 PDF”
- API：
  - `GET /api/policy/list?keyword=长沙`
  - `POST /api/policy/run`（JSON：`{"policy_index": 0}`）

---

## 4）RAG 问答（RAG）

### 4.1 模块定位

- 基于本地向量库（Chroma）检索文档片段，同时拼接知识图谱（`graph_data.json`）子图上下文，调用 LLM 生成结构化 Markdown 答案，前端渲染并支持导出 PDF。

### 4.2 输入 / 输出

- 输入
  - 用户问题：`query`
  - 向量库：`RAG/vector_db/`（Chroma 持久化）
  - 语料：`RAG/raw_docx_files/`（用于构建库）
  - 图谱上下文：`static/data/graph_data.json`
- 输出
  - API 返回：`markdown`（回答）
  - 构建阶段落盘：`RAG/vector_db/`、`RAG/progress.json`

### 4.3 主要代码与函数

- 后端路由：`backend_server.py`
  - `rag_query()` → `POST /api/rag_query`
- RAG 脚本：`RAG/build_vector_db.py`
  - `build_vector_db()`：构建/更新向量库
  - `query_vector_db(query, top_k=...)`：查询入口
  - `KnowledgeGraphHandler.search_relevant_subgraph(query)`：从图谱抽取相关子图上下文
- 前端：`static/js/modules/rag_chat.js`
  - `handleRAGSubmit()`：提交问题并渲染回答
  - `renderMarkdown()` / `ensureMarkdownStyle()`：Markdown 渲染与样式
  - `exportAiPdf(contentId)`：导出单条回复为 PDF

### 4.4 使用方法

- 前端：进入“智能问答” → 输入问题 → 发送 → 查看 Markdown 答案 → 点击“导出PDF”
- API：`POST /api/rag_query`（JSON：`{"query":"智算中心发展现状如何"}`）
- 需要先构建向量库（一次性/按需）：
  - `python RAG/build_vector_db.py --build`

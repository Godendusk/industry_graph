# 项目修改日志

本文档用于记录本项目的修改历史，包括日期、作者、改动的代码范围以及改动内容。

## 2026-08-06

- godendusk

- 改动内容：
  - 初始化项目修改日志文件 `CHANGELOG.md`
  - 新建项目修改日志，用于后续持续记录项目代码变更、修改说明与维护记录。
  - `base.html`
  确认项目应使用 `kunlun` 环境运行，修改地址为：const API_BASE = "http://127.0.0.1:8000", 通过本地运行

  - 删除空库vector_db，上传群内的测试小向量库
    "C:\Users\user\Desktop\Postgraduate\科研\industry_graph-main\report_generation\vector_db"中原有的文件是空壳，替换为微信群内的小向量库，由于gitignore文件的编写，改动不同步到github中，使用前需要自己手动将微信群内的小向量库下载，解压后放到该路径下（完整的百度网盘的向量库应该是同理，小向量库还未进行测试）

## 2026-08-07
- godendusk
切换apikey

## 2026-08-09

- godendusk

- 改动内容：
  - 将产业报告生成扩展至人工智能、具身智能、低空经济、海洋经济、量子科技、生物制造、脑机接口和新材料 8 个产业。
  - 报告生成按产业同时检索对应知识图谱与独立 RAG 向量库，不在产业之间回退或混用资料。
  - 将原人工智能向量库迁移至 `report_generation/vector_db/ai/`，并为其他产业新增同级空目录及后续资料栏目配置位置。
  - 非人工智能产业 RAG 为空时继续使用知识图谱生成报告，并在页面提示当前产业暂无向量资料。

- 主要修改代码：
  - `report_generation/industry_config.py`：新增统一产业配置，集中维护产业名称、图谱路径、向量库路径和外部资料栏目 ID。
  - `report_generation/graph_retriever.py`：将人工智能专用图谱检索改为按产业动态加载，并保留原 AI 检索入口兼容旧调用。
  - `report_generation/external_rag/`：RAG 检索、Chroma 客户端和资料摄入流程增加产业参数，实现向量库按产业隔离及空库 warning。
  - `report_generation/outline_agent.py`、`coordinator_agent.py`、`rewrite_agent.py`：生成大纲、统筹写作任务和正文重写时同时检索当前产业图谱与 RAG。
  - `report_generation/body_agent.py`、`summary_agent.py`、`word_export_agent.py`：扩展产业校验及名称处理，使正文、摘要和 Word 导出支持全部 8 个产业。
  - `static/js/modules/industry_report.js`：移除非 AI 产业限制，补全产业名称、动态报告标题、产业切换重置和 RAG 空库提示。
  - `.gitignore`、`report_generation/vector_db/*/.gitkeep`：保留各产业向量库目录结构，同时继续忽略实际 Chroma 数据文件。
  - `tests/test_report_generation_industries.py`：新增多产业图谱、独立集合、空库提示、摄入配置和禁止跨产业回退测试。

## 2026-08-10

- godendusk

- 改动内容：
  - 为产业报告生成新增 Intent 报告意图解析和 Planner 报告规划两阶段，整体流程调整为“标题与可选需求 → 意图解析 → 报告规划 → 大纲生成”。
  - 报告标题改为必填并始终原样保留，补充需求改为选填；优势分析、布局分析、趋势分析等不同研究任务不再机械套用固定 Word 一级章节模板。
  - Planner 根据研究类型和核心问题拆解 3～6 个研究问题及章节，并为每章生成内容要求、证据要求和产业图谱使用建议。
  - 大纲一级章节改为直接来源于 Planner，二级标题继续适配现有统筹、正文、摘要、改写和 Word 导出流程。
  - Intent 和 Planner 模型输出增加 JSON 清洗、字段校验及一次自动重试；产业图谱或 RAG 不可用时记录 warning，不阻断规划和报告生成。
  - 前端根据标题识别结果自动切换到系统支持的行业，无法映射的行业继续使用无图谱模式；Intent 和 Planner 中间结果写入接口响应、日志及报告历史记录，但默认不在页面展示。

- 主要修改代码：
  - `report_generation/intent_agent.py`：新增报告意图解析、标题保真、意图字段校验和行业映射逻辑。
  - `report_generation/planner_agent.py`：新增研究问题拆解、章节规划、证据要求和产业图谱可用性判断。
  - `report_generation/structured_output.py`：新增模型 JSON 提取、Markdown 清理、文本数组规范化等共享工具。
  - `report_generation/outline_agent.py`：将固定模板大纲改为 Planner 驱动大纲，并按章节生成二级标题。
  - `backend_server.py`：将 `/api/report/outline` 请求调整为 `title`、`user_requirement` 和 `industry`，返回 Intent、Planner 与识别后的行业，并记录中间结果日志。
  - `report_generation/coordinator_agent.py`、`body_agent.py`、`summary_agent.py`、`word_export_agent.py`：增加无图谱、未配置行业场景的非阻断兼容。
  - `static/js/modules/industry_report.js`、`templates/components/industry_report.html`：更新输入契约、流程文案、行业自动切换及历史状态保存。
  - `tests/test_report_intent_planner.py`：新增标题保真、JSON 重试、Planner 约束、大纲适配和新 API 契约测试。


## 2026-08-10

- godendusk

- 改动内容：
  - 修改了前端页面，为outline_agent.py前面新增task_card_agent.py

- 主要修改代码
  - `report_generation/task_card_agent.py`：新增任务卡，在用户输入完原始标题后，llm自动分析标题，匹配相应的产业，自动是生成对应的报告需求，在用户编辑修改，确认后，数据才用于大纲的生成

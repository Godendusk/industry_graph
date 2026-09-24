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

## 2026-09-21

- livictor

- 改动内容：
  - 本次 pull 将本地版本从 `ed6e239` 更新至 `9347b9a`，主要围绕产业报告 Hybrid RAG、引用溯源和报告生成稳定性进行升级。
  - 引入产业报告 Hybrid RAG v2 与 `retrieval_core` 检索核心，支持结构化分块、BM25、向量检索、融合检索和 rerank 流程。
  - 新增报告级 `[C1]`、`[C2]` 引用溯源机制，保存 `references`，并适配网页、Markdown 与 Word 导出。
  - 将 LLM 配置改为 `.env` / 环境变量读取，移除代码中的硬编码密钥，补充 `.env.example` 与部署说明。
  - 优化任务卡、报告需求 fallback、空正文恢复和跨平台报告协调稳定性。
  - 删除仓库内旧 Chroma 向量库二进制文件，改为通过脚本构建和评估索引。
  - 补充 RAG、引用、任务卡、Word 导出和前端报告导航相关测试。

- 主要修改代码：
  - `retrieval_core/`：新增混合检索核心能力。
  - `report_generation/external_rag/`：新增报告 RAG v2 索引、适配、摄入和检索逻辑。
  - `report_generation/citations.py`：新增报告引用编号和资料溯源处理。
  - `llm_client.py`：改为读取本地环境配置，并返回模型调用元数据。
  - `static/js/modules/industry_report.js`：适配报告引用、导航和历史状态恢复。
  - `tests/`：新增和扩展报告 RAG、引用、任务卡、导出与前端交互测试。

## 2026-09-22

- godendusk

- 改动内容：
  - 优化产业报告任务卡交互，报告题目标注必填，报告需求保持可选并由系统自动生成。
  - 将任务卡中的模型识别产业、最终产业方向和资料源选择调整为三列布局，最终产业方向下拉展示全部支持产业及图谱、外部资料库可用状态。
  - 新增“使用产业图谱”“使用外部资料库”勾选项，不可用资料源自动禁用；最终产业方向只决定产业上下文，是否调用资料源由勾选状态决定。
  - 将产业匹配、依据、图谱匹配和外部资料库匹配说明收纳到悬停“说明”中展示。
  - 将自动生成的报告需求改为可直接在分段预览区编辑，底层仍保存纯文本，不改变需求内容质量。
  - 修正外部资料库可用性判断，只有 `.gitkeep` 的占位目录不再算可用资料库，避免量子科技等产业误显示外部资料库可用。
  - 后端统筹写作任务接口支持 `use_graph` 和 `use_external_rag`，取消勾选后跳过对应检索。

- 主要修改代码：
  - `templates/components/industry_report.html`：调整任务卡布局、资料源开关和可编辑报告需求区域。
  - `static/js/modules/industry_report.js`：接入资料源开关、产业可用性展示、说明悬停和需求预览编辑同步。
  - `report_generation/task_card_agent.py`：补充外部资料库可用性字段并修正占位目录判断。
  - `report_generation/coordinator_agent.py`、`backend_server.py`：新增图谱和外部资料库检索开关。
  - `tests/`：补充任务卡可用性、检索跳过和前端请求参数测试。

## 2026-09-24

- godendusk

- 改动内容：
  - 优化产业报告生成流程展示，新增“工作流”智能体区域，按需求理解、大纲生成、统筹任务、正文生成和报告导出展示状态。
  - 新增统筹任务和正文生成 SSE 流式进度，网页端可逐个查看写作任务和正文小节的开始、完成或失败状态。
  - 优化正文生成按钮状态，大纲未生成或未确认生成写作任务时保持置灰；编辑大纲后自动作废已确认状态。
  - 调整报告需求区交互与状态文案，提交按钮移至输入区底部，需求区只显示需求提交相关状态。
  - 修正外部资料库可用性判断，需同时存在 `external_column_id` 和对应 `chroma.sqlite3`。
  - 修复统筹和正文进度分母跳动问题，统一按任务总数展示进度。

- 主要修改代码：
  - `templates/components/industry_report.html`：调整报告需求按钮布局和工作流区域位置。
  - `static/js/modules/industry_report.js`：新增工作流智能体展示、流式进度消费、按钮禁用逻辑和前端状态同步。
  - `report_generation/coordinator_agent.py`、`body_agent.py`、`backend_server.py`：新增统筹任务和正文生成流式接口。
  - `report_generation/task_card_agent.py`：修正外部资料库可用性判定。
  - `tests/`：补充外部资料库判定、统筹流式和正文流式相关测试。

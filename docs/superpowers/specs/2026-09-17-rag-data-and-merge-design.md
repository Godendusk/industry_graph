# RAG 本地数据整理与双边代码合并设计

## 目标

在不上传本地模型、向量数据库、索引和个人交接资料的前提下，整合本地 `main` 的 57 个提交与 `origin/main` 的 3 个提交，并保留双方功能：本地的 Hybrid RAG、具身智能报告和页面导航能力，以及远程的多产业规划与任务卡智能体。

## 当前状态

- 本地 `main` 相对 `origin/main` 领先 57 个提交、落后 3 个提交。
- 当前工作目录还有未提交的具身智能报告前端修改及 3 个对应测试。
- RAG 本地数据约 4.5 GB，主要由模型、Chroma 数据库和检索索引组成，不是代码。
- Git 历史仍跟踪 `RAG/vector_db/` 中 11 个数据库文件；其中 10 个旧索引文件已在本地删除，`chroma.sqlite3` 已被本地数据库更新。
- 已模拟确认双方提交历史在 10 个源码文件上存在内容冲突。

## 本地 RAG 目录规范

最终统一使用以下目录：

```text
RAG/vector_db_ai/        # 人工智能报告向量库，来源于 RAG/vector_db/
RAG/vector_db_embodied/  # 具身智能报告向量库
RAG/vector_db_QA/        # 普通问答向量库，来源于 RAG/vector_db1/
RAG/indexes/             # Hybrid RAG 检索索引
RAG/model_store/         # 本地嵌入模型
```

对应代码路径调整：

- `RAG/build_vector_db.py` 的普通问答库指向 `RAG/vector_db_QA/`。
- `report_generation/external_rag/vector_store.py` 的人工智能报告库指向 `RAG/vector_db_ai/`。
- `report_generation/external_rag/embodied_store.py` 继续使用 `RAG/vector_db_embodied/`。
- 全仓库查找旧路径引用，只修改真实运行路径、测试和必要说明，不增加环境变量、兼容层或迁移框架。

## Git 跟踪规则

共享 `.gitignore` 忽略上述五类本地 RAG 数据目录。Git 历史中已跟踪的旧向量库文件从索引中解除跟踪，仓库记录为删除，但本机数据在重命名后的目录中继续保留。

已经从当前工作目录消失的 10 个旧 HNSW 索引文件不恢复；它们属于旧数据库内部索引，不是源代码或原始交接资料。

以下个人资料只通过 `.git/info/exclude` 在当前克隆中忽略，不写入共享 `.gitignore`：

- `docs/superpowers/plans/2026-09-13-report-source-citations.md`
- `产业报告项目交接文档.md`
- `需求.xlsx`
- `项目交接会议笔记_2026-08-08.md`

## 合并隔离策略

先把当前未提交的 `industry_report.js` 与对应测试作为一组小型本地提交保存，只暂存这两个文件，不包含 RAG 数据、个人资料或当前不完整的 `.gitignore` 修改。

随后从本地 `main` 创建独立整合分支和 Git 工作树，在干净目录中合并 `origin/main`。所有冲突在整合工作树解决，原目录中的 4.5 GB 本地数据在合并期间保持不动。

整合分支完成代码合并和路径规则调整后，再安全地把原目录中的 `RAG/vector_db/` 重命名为 `RAG/vector_db_ai/`，把 `RAG/vector_db1/` 重命名为 `RAG/vector_db_QA/`。移动前后核对目录存在性和大小，不覆盖已有目标目录，不删除数据。

## 冲突解决原则

以下 10 个文件逐一人工合并：

- `report_generation/body_agent.py`
- `report_generation/coordinator_agent.py`
- `report_generation/external_rag/ingestion.py`
- `report_generation/external_rag/retriever.py`
- `report_generation/graph_retriever.py`
- `report_generation/outline_agent.py`
- `report_generation/rewrite_agent.py`
- `report_generation/summary_agent.py`
- `report_generation/word_export_agent.py`
- `static/js/modules/industry_report.js`

解决原则不是整文件选择“本地”或“远程”，而是保留双方职责：

- 保留本地 Hybrid RAG、具身智能数据路由、具身智能报告调用、图谱页面导航与已有检索测试。
- 保留远程多产业意图规划、任务卡智能体、产业配置和相应前后端调用。
- 对 `llm_client.py` 与 `report_generation/external_rag/vector_store.py` 的自动合并结果进行人工复核，因为它们也被双方修改。
- 不在合并过程中进行无关重构。

## 测试策略

冲突全部解决、Git 不再包含冲突标记后再测试。先运行与改动直接相关的最小测试：

1. 前端报告导航和具身智能行业传递测试。
2. 报告生成协调、正文、重写、摘要和导出测试。
3. Hybrid RAG、外部 RAG、存储路径和向量库路由测试。
4. Python 语法检查与 JavaScript 语法检查。

最小测试通过后，再运行项目现有的 Python 测试集和 JavaScript 测试集。需要真实模型或本地数据库的测试使用本机数据目录执行，但测试过程不把这些数据加入 Git。

## 安全与回退

- 不使用 `git reset --hard`、强制推送或递归删除命令。
- 不在原工作目录直接开始冲突合并。
- 数据目录移动前确认来源存在、目标不存在，并记录移动前后容量。
- 整合结果保存在独立分支；测试通过且用户确认前不推送 GitHub。
- 原分支和原工作目录在整合期间可作为本地回退点。

## 完成标准

- 双方功能均保留，10 个源码冲突全部解决。
- RAG 数据目录按新名称可被程序直接读取。
- 模型、数据库、索引和个人资料不会出现在待提交文件中。
- 已跟踪的旧向量数据库文件停止由 Git 管理。
- 定向测试与可运行的完整测试通过。
- 用户确认整合结果后，再决定推送整合分支或创建 Pull Request。

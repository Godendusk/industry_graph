# RAG 本地数据整理与双边代码合并 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不上传本地 RAG 数据和个人资料的前提下，保留本地与远程两侧功能，完成代码合并、RAG 路径重命名和验证。

**Architecture:** 原工作目录继续保存本机约 4.5 GB 的模型、数据库与索引。先在原目录提交本地前端改动，并完成 RAG 重命名、路径调整、忽略和停止跟踪，使当前代码立即适配新路径。随后新建干净 Git 工作树，专门合并 `origin/main` 并逐文件解决冲突；最终将经过验证的整合分支合回原目录，以便测试能直接使用本机 RAG 数据。

**Tech Stack:** Git worktree、Python、Flask、Chroma、SQLite、Node `node:test`、Python `unittest`/`pytest`、Conda `kunlun`。

---

## 文件与目录边界

| 位置 | 责任 |
| --- | --- |
| `RAG/build_vector_db.py` | 普通问答 RAG 的数据库路径 |
| `report_generation/external_rag/vector_store.py` | 人工智能报告 RAG 的数据库路径 |
| `report_generation/external_rag/embodied_store.py` | 具身智能报告 RAG 的数据库和模型路径 |
| `.gitignore` | 所有克隆共享的本地 RAG 数据忽略规则 |
| `.git/info/exclude` | 当前电脑专属的交接资料忽略规则 |
| `static/js/modules/industry_report.js` | 报告页面行业选择、导航及 API 调用 |
| `tests/js/test_industry_report_navigation.test.js` | 报告页面 JavaScript 测试 |

## Task 1: 保存当前未提交的具身智能报告代码

**Files:**

- Modify: `static/js/modules/industry_report.js`
- Modify: `tests/js/test_industry_report_navigation.test.js`
- Verify: 当前工作目录的 `git status`

- [ ] **Step 1: 仅暂存两份源码文件**

```bash
git status --short
git add static/js/modules/industry_report.js tests/js/test_industry_report_navigation.test.js
git diff --cached --name-status
```

预期：暂存区只显示这两个文件；不得包含 `RAG/`、`.gitignore` 或个人文档。

- [ ] **Step 2: 运行前端定向测试**

```bash
node --test tests/js/test_industry_report_navigation.test.js
```

预期：现有导航测试和新增的具身智能行业传递测试通过。

- [ ] **Step 3: 提交已验证的前端代码**

```bash
git commit -m "feat: enable embodied industry reports"
```

预期：生成仅含报告页面代码和测试的本地提交；不执行 `git push`。

## Task 2: 统一原工作目录的 RAG 本地目录与运行路径

**Files:**

- Modify: `.gitignore`
- Modify: `.git/info/exclude`
- Modify: `RAG/build_vector_db.py`
- Modify: `report_generation/external_rag/vector_store.py`
- Verify: `report_generation/external_rag/embodied_store.py`
- Move locally: `RAG/vector_db/` → `RAG/vector_db_ai/`
- Move locally: `RAG/vector_db1/` → `RAG/vector_db_QA/`

- [ ] **Step 1: 写入共享 RAG 忽略规则和本机个人资料忽略规则**

使用 `apply_patch` 在 `.gitignore` 加入：

```gitignore
# Local RAG models, databases, and retrieval indexes (distributed separately)
RAG/vector_db_ai/
RAG/vector_db_embodied/
RAG/vector_db_QA/
RAG/indexes/
RAG/model_store/
```

使用 `apply_patch` 在 `.git/info/exclude` 加入：

```gitignore
docs/superpowers/plans/2026-09-13-report-source-citations.md
产业报告项目交接文档.md
需求.xlsx
项目交接会议笔记_2026-08-08.md
```

预期：共享规则只忽略 RAG 本地数据，不忽略 `RAG/*.py`；个人资料不再显示于 `git status`，且该规则不会被提交。

- [ ] **Step 2: 修改代码运行路径并检查语法**

将两处赋值改为：

```python
# RAG/build_vector_db.py
DB_DIR = BASE_DIR / "vector_db_QA"

# report_generation/external_rag/vector_store.py
VECTOR_DB_DIR = PROJECT_ROOT / "RAG" / "vector_db_ai"
```

然后执行：

```bash
python -m py_compile RAG/build_vector_db.py report_generation/external_rag/vector_store.py
```

预期：`embodied_store.py` 继续使用 `RAG/vector_db_embodied`；修改后 Python 语法检查退出 0。

- [ ] **Step 3: 安全重命名本机数据库目录**

移动前确认来源和目标：

```bash
test -d RAG/vector_db
test -d RAG/vector_db1
test ! -e RAG/vector_db_ai
test ! -e RAG/vector_db_QA
du -sh RAG/vector_db RAG/vector_db1
```

然后执行：

```bash
git mv RAG/vector_db RAG/vector_db_ai
git mv RAG/vector_db1 RAG/vector_db_QA
du -sh RAG/vector_db_ai RAG/vector_db_QA
```

预期：目标目录存在且容量与移动前一致；不移动 `RAG/indexes/`、`RAG/model_store/` 或具身智能数据库。

- [ ] **Step 4: 停止 Git 跟踪数据库文件，保留磁盘数据**

```bash
git rm -r --cached RAG/vector_db_ai RAG/vector_db_QA
git status --short
```

预期：Git 将数据库记录为停止跟踪；磁盘上的两个目录仍存在。若 Git 显示 `RAG/*.py`，立即停止并只处理实际数据库文件。

- [ ] **Step 5: 提交路径和跟踪规则**

```bash
git add .gitignore RAG/build_vector_db.py report_generation/external_rag/vector_store.py
git add -u RAG/vector_db_ai RAG/vector_db_QA
git diff --cached --name-status
git commit -m "chore: keep RAG data local"
```

预期：提交只含代码路径、`.gitignore` 和数据库停止跟踪记录；个人资料与大数据本体不在提交中。

## Task 3: 建立隔离整合工作树

**Files:**

- Create: `/Users/livictor/Desktop/industry/.worktrees/industry_graph/integrate-main/`
- Verify: 原工作目录与整合工作树的分支和状态

- [ ] **Step 1: 确认目标路径不存在且 RAG 规则已保存**

```bash
test ! -e /Users/livictor/Desktop/industry/.worktrees/industry_graph/integrate-main
git status --short
git log --oneline -n 4
```

预期：目标目录不存在；当前工作目录干净（本机大数据已忽略）；日志包含 Task 1 和 Task 2 提交。

- [ ] **Step 2: 从本地 `main` 建立整合分支和工作树**

```bash
git worktree add -b codex/integrate-main \
  /Users/livictor/Desktop/industry/.worktrees/industry_graph/integrate-main \
  main
```

预期：新工作树位于指定目录；原工作目录和 RAG 数据不被修改。

- [ ] **Step 3: 确认整合工作树状态**

```bash
git -C /Users/livictor/Desktop/industry/.worktrees/industry_graph/integrate-main status --short
git -C /Users/livictor/Desktop/industry/.worktrees/industry_graph/integrate-main rev-list --left-right --count main...origin/main
```

预期：工作树干净；相对远程仍只缺少原先的 3 个远程提交，并额外包含 Task 1 与 Task 2 的本地提交。

## Task 4: 合并远程提交并逐文件解决冲突

**Files:**

- Modify: `report_generation/body_agent.py`
- Modify: `report_generation/coordinator_agent.py`
- Modify: `report_generation/external_rag/ingestion.py`
- Modify: `report_generation/external_rag/retriever.py`
- Modify: `report_generation/graph_retriever.py`
- Modify: `report_generation/outline_agent.py`
- Modify: `report_generation/rewrite_agent.py`
- Modify: `report_generation/summary_agent.py`
- Modify: `report_generation/word_export_agent.py`
- Modify: `static/js/modules/industry_report.js`
- Review: `llm_client.py`, `report_generation/external_rag/vector_store.py`

- [ ] **Step 1: 开始普通合并，不自动创建提交**

```bash
git merge --no-commit --no-ff origin/main
git status --short
```

预期：Git 标出冲突文件；不使用 `--ours` 或 `--theirs` 覆盖整文件。

- [ ] **Step 2: 每个冲突块按双方职责人工合并**

保留规则：

```text
本地侧：Hybrid RAG、具身智能数据路由、具身智能报告调用、图谱页内导航。
远程侧：多产业意图规划、任务卡智能体、产业配置、相关前后端调用。
共同规则：保留已有公开函数名和调用链；删除所有冲突标记；不做无关重构。
```

每个文件解决后执行以下针对全部冲突文件的检查和暂存：

```bash
git diff --check -- \
  report_generation/body_agent.py \
  report_generation/coordinator_agent.py \
  report_generation/external_rag/ingestion.py \
  report_generation/external_rag/retriever.py \
  report_generation/graph_retriever.py \
  report_generation/outline_agent.py \
  report_generation/rewrite_agent.py \
  report_generation/summary_agent.py \
  report_generation/word_export_agent.py \
  static/js/modules/industry_report.js
git add \
  report_generation/body_agent.py \
  report_generation/coordinator_agent.py \
  report_generation/external_rag/ingestion.py \
  report_generation/external_rag/retriever.py \
  report_generation/graph_retriever.py \
  report_generation/outline_agent.py \
  report_generation/rewrite_agent.py \
  report_generation/summary_agent.py \
  report_generation/word_export_agent.py \
  static/js/modules/industry_report.js
```

预期：文件没有空白错误且已标记解决。

- [ ] **Step 3: 审核自动合并的共享文件**

```bash
git diff --cc -- llm_client.py report_generation/external_rag/vector_store.py
git diff --check -- llm_client.py report_generation/external_rag/vector_store.py
```

预期：两个文件没有冲突标记；本地 RAG 配置和远程多产业调用均保留。

- [ ] **Step 4: 确认冲突已清零并创建合并提交**

```bash
git diff --check
git diff --name-only --diff-filter=U
git status --short
git commit -m "merge: integrate remote multi-industry report updates"
```

预期：未解决冲突列表为空，生成合并提交；不执行 `git push`。

## Task 5: 将已验证的整合分支合回原工作目录

**Files:**

- Modify: 原工作目录的 `main` 分支历史
- Verify: 本机 RAG 目录保持不变

- [ ] **Step 1: 确认原工作目录保持干净且数据仍在新路径**

```bash
git status --short
test -d RAG/vector_db_ai
test -d RAG/vector_db_QA
du -sh RAG/vector_db_ai RAG/vector_db_QA
```

预期：代码工作目录干净；数据库目录仍在，且容量未变化。

- [ ] **Step 2: 合并整合分支到原目录 `main`**

```bash
git merge --ff-only codex/integrate-main
```

预期：仅快进代码提交；不会写入或删除任何已被忽略的 RAG 数据。

## Task 6: 验证合并结果与本地数据分离

**Files:**

- Test: `tests/js/test_industry_report_navigation.test.js`
- Test: `tests/test_rag_storage_separation.py`
- Test: 报告生成和 Hybrid RAG 的现有测试

- [ ] **Step 1: 运行前端定向测试与语法检查**

```bash
node --test tests/js/test_industry_report_navigation.test.js
node --check static/js/modules/industry_report.js
```

预期：行业导航、具身智能行业传递与 JavaScript 语法通过。

- [ ] **Step 2: 更新路径断言并验证本地 RAG 路由**

更新 `tests/test_rag_storage_separation.py` 中的目录断言为 `vector_db_QA` 与 `vector_db_ai`，然后执行：

```bash
PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_rag_storage_separation -v
PYTHONPATH=. conda run -n kunlun python -m py_compile \
  RAG/build_vector_db.py \
  report_generation/external_rag/vector_store.py \
  report_generation/external_rag/embodied_store.py
```

预期：路径测试能读取本机数据库，语法检查退出 0。

- [ ] **Step 3: 运行合并冲突模块相关的 Python 测试**

```bash
PYTHONPATH=. conda run -n kunlun python -m unittest \
  tests.test_report_rag_modes \
  tests.test_report_rag_adapter \
  tests.test_report_rag_ingestion_v2 \
  tests.test_report_rag_v2_index -v
```

预期：Hybrid RAG、报告适配、写入和索引模块通过；若失败，记录第一个失败测试和错误后，先检查对应的合并调用链。

- [ ] **Step 4: 确认不会上传本地数据和个人资料**

```bash
git status --short
git check-ignore -v \
  RAG/vector_db_ai/chroma.sqlite3 \
  RAG/vector_db_QA/chroma.sqlite3 \
  RAG/indexes \
  RAG/model_store \
  需求.xlsx
```

预期：这些路径均显示为已忽略；待提交区为空或只含必要测试修复的源码。

- [ ] **Step 5: 审查整合分支，不上传远程**

```bash
git log --oneline --decorate origin/main..HEAD
git status --short
```

预期：本地整合分支包含合并、路径整理及必要测试修复提交，工作目录干净；到此停止，等待用户审查后再推送或创建 Pull Request。

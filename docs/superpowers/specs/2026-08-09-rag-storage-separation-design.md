# RAG 存储路径分离设计

## 目标

让通用问答 RAG 与产业报告 RAG 分别读取仓库中已经存在、且 collection 类型正确的 Chroma 持久化目录，避免两个模块互相读取对方的数据。

## 已确认的根因

- 通用问答代码当前读取 `RAG/vector_db/`，但它需要的 `knowledge_base` 实际位于 `RAG/vector_db1/`。
- 产业报告代码当前读取 `report_generation/vector_db/`，但五个 `report_*_ai` collection 实际位于 `RAG/vector_db/`。
- `report_generation/vector_db/` 当前没有 collection 和 embedding，因此报告历史中所有外部 RAG 证据均为空。

## 方案

采用不搬动数据的最小修复：

1. 将通用问答模块的默认 `DB_DIR` 指向 `RAG/vector_db1/`。
2. 将产业报告模块的默认 `VECTOR_DB_DIR` 指向 `RAG/vector_db/`。
3. 添加自动化回归测试，验证：
   - 两套默认目录互不相同；
   - 通用问答目录包含 `knowledge_base`；
   - 报告目录包含五个预期的 `report_*_ai` collection；
   - 两个库都有非零 embedding。

## 不在本次范围内

- 不移动、复制、删除或重建任何 Chroma 数据。
- 不修改 embedding 模型、分块、召回、重排或 Prompt。
- 不处理多产业 collection 建设。
- 不顺带修复鉴权、凭证、413 或报告质量问题。

## 影响文件

- 修改 `RAG/build_vector_db.py`：通用问答数据库默认路径。
- 修改 `report_generation/external_rag/vector_store.py`：报告数据库默认路径。
- 新建 `tests/test_rag_storage_separation.py`：路径和真实 collection 回归测试。

## 验收标准

- 回归测试在修改前因路径错误而失败，在修改后通过。
- 通用问答路径可查到 `knowledge_base`，embedding 数为 26,879。
- 报告路径可查到五个报告 collection，embedding 总数为 39,341。
- Python 源码和前端 JavaScript 基础语法检查保持通过。

# 跨平台统筹任务稳定性修复设计

## 背景

具身智能报告生成到“统筹任务”阶段时，当前实现会按二级标题数量创建线程。一次实际请求包含 20 个二级标题，因此创建了 20 个并发任务。这些任务共享同一个运行在 Apple MPS 上的 SentenceTransformer，并同时调用 `encode()`。macOS 崩溃报告确认故障为 PyTorch MPS/Metal 原生层的 `SIGSEGV`，Flask 进程因此直接退出，前端只显示“写作任务生成失败”。

`resource_tracker` 的 semaphore 提示发生在进程退出清理阶段，不是根因。

## 目标

- 统筹包含大量二级标题时，后端不因共享模型并发访问而崩溃。
- 保持 Windows、macOS 和 Linux 兼容。
- Windows 有 CUDA 时继续使用 CUDA；macOS 可使用 MPS；其他环境回退 CPU。
- 保留图谱检索和远程 LLM 的有限并发，避免把整个统筹流程完全串行化。
- 数据库、模型和索引继续仅保存在本地，不进入 Git。

## 非目标

- 不更换嵌入模型或向量数据库。
- 不引入任务队列、独立推理服务或多进程架构。
- 不改动报告大纲、正文和导出功能的业务规则。
- 不为理论上的冷门平台问题增加兼容层。

## 根因与边界

### 统筹任务并发

`generate_writing_tasks()` 当前使用 `ThreadPoolExecutor(max_workers=len(final_subsections))`。线程数随大纲大小无上限增长。每个任务依次进行图谱检索、外部 RAG 检索和写作提示词生成。

### 共享本地模型

具身智能 RAG 使用进程级缓存的 SentenceTransformer。模型加载已有锁，但加载完成后的 `model.encode()` 没有锁，因此多个统筹线程会同时进入同一个 PyTorch 模型。

### 重复数据库客户端

每次 `query_embodied_news()` 都新建 `EmbodiedNewsStore` 和 Chroma PersistentClient。在一次 20 任务统筹中会短时间创建多个指向同一 24 GB 数据库的客户端，增加资源占用和原生库并发风险。

## 设计

### 1. 限制统筹工作线程

统筹阶段最多使用 3 个工作线程：

```python
worker_count = min(3, len(final_subsections))
```

该值与正文阶段默认并发数保持一致。它不依赖环境变量或操作系统，Windows、macOS 和 Linux 行为一致。

### 2. 串行访问共享嵌入模型

在 `embodied_store.py` 增加独立的推理锁。默认模型的所有 `encode()` 调用，包括查询和摄入，均在锁内执行。锁使用标准库 `threading.Lock`，不使用 Unix 专属同步机制。

设备选择保持现有顺序：

1. CUDA 可用时使用 CUDA；
2. 否则 MPS 可用时使用 MPS；
3. 否则使用 CPU。

锁在所有设备上生效。这样既消除 MPS 并发崩溃，也避免 Windows CUDA 或 CPU 上共享 SentenceTransformer 的并发状态问题。

### 3. 复用具身智能存储实例

`query_embodied_news()` 使用进程级单例 `EmbodiedNewsStore`。首次创建时加锁，之后复用同一个 Chroma 客户端和 collection。

查询操作使用单独的查询锁，覆盖查询向量编码和 `collection.query()`。摄入仍通过现有存储对象执行，但模型编码受同一个推理锁保护。不会使用多进程，也不会依赖文件锁。

### 4. 保持其他阶段的行为

- 图谱检索和远程 LLM 调用仍由最多 3 个统筹线程并发执行。
- 单个二级标题检索失败时继续生成降级写作任务，不让整批失败。
- 正文阶段已有明确的 `max_workers` 上限，不因本次问题调整。
- 摘要和导出阶段不加载具身智能嵌入模型，不做无关修改。

## 错误处理

- Python 层的模型或 Chroma异常继续由现有检索包装转换为 warning 和降级结果。
- 原生层段错误无法由 `try/except` 捕获，因此通过消除不安全并发预防。
- 不自动切换 CPU 重试，因为原生段错误发生时进程已经终止，而且强制 CPU 会让 Windows CUDA 用户无故失去加速。

## 测试设计

### 单元测试

- 断言 20 个二级标题时统筹线程上限为 3。
- 使用会检测并发进入的假模型，多个线程同时查询时断言 `encode()` 实际串行。
- 断言多次 `query_embodied_news()` 复用同一个存储实例。
- 保留 CUDA、MPS、CPU 设备选择测试。
- 保留具身智能行业参数从前端到 coordinator 的路由测试。

### 后端模拟

- 使用替身图谱、RAG 和 LLM，构造 20 个写作任务，验证全部任务完成且顺序稳定。
- 使用本地具身智能模型执行有限次数的并发查询，确认进程不崩溃且返回结构有效。
- 不调用真实远程 LLM 进行批量测试，避免测试结果依赖网络和额度。

### 回归验证

- 报告前端导航和行业参数测试。
- 具身智能 RAG 测试。
- coordinator、Hybrid RAG、摄入和索引测试。
- Python 语法检查与 Git 空白检查。

## 兼容性与交接

代码仅使用 Python 标准线程同步、`pathlib` 和现有依赖。Windows 同事将本地模型与数据库放到既定目录后即可运行：

- `RAG/model_store/bge-base-zh-v1.5/`
- `RAG/vector_db_embodied/`
- `RAG/vector_db_ai/`
- `RAG/vector_db_QA/`

这些目录继续由 `.gitignore` 排除，不随 GitHub 仓库分发。

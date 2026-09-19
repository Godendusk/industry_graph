# 部署、运行与数据准备说明

本文档用于交付与验收场景，说明系统部署、运行方式，以及需要准备的数据、格式与存放位置。

---

## 1. 系统组成

- 后端服务：`backend_server.py`（Flask，端口默认 `8000`）
- 前端页面：`templates/base.html`（通过后端渲染与静态资源提供）
- 图谱主库：`static/data/graph_data.json`（系统读写的唯一主图谱文件）
- 图谱导入（Excel 抽取）：`graph_import_script.py`（通过后端接口驱动）
- 政策推演：`policy_deduction/Policy_deduction.py`
- 风险分析：`risk_inference/risk.py`
- RAG：`RAG/build_vector_db.py`（Chroma 向量库）
- 大模型客户端：`llm_client.py`（统一封装）
- 冷启动/长时抽取（批处理扩充，另行文档说明）：基于“骨架（必需）+ 可选原图谱 + 批量文本/Excel”的批处理抽取脚本，用于图谱规模较小或仅有骨架时的批量扩充场景，支持长时间运行与过程性保存。说明见：`cold_start_extraction/知识图谱自动化抽取工具 (V4.2 Robust) 使用说明.md`。

---

## 2. 运行环境与依赖安装

### 2.1 环境要求

- Python：建议使用 **3.10.19**（已验证可用）
- 操作系统：Windows/macOS/Linux 均可（路径示例以 Windows 为主）

### 2.2 安装依赖

本项目交付以 `environment.yml`（conda）为准。

```bash
conda env create -f environment.yml
conda activate <environment.yml 里的 name>
```

说明：
- 环境名以 `environment.yml` 的 `name:` 为准；如已存在同名环境，可用 `conda env update -f environment.yml --prune` 更新。
- `environment.yml` 未固定 `torch/torchvision` 版本；如需使用 RAG/向量化相关能力（如 `sentence-transformers`），请根据部署机的 CPU/GPU/CUDA 条件选择并安装合适的 PyTorch。

---

## 3. 配置项说明

### 3.1 后端路径配置（`backend_server.py`）

可按实际部署路径调整的主要常量：

- 图谱主库：`GRAPH_DATA_PATH = static/data/graph_data.json`
- 图谱导入会话目录：`IMPORT_SESSION_DIR = uploads/sessions/`
- 政策 Excel：`POLICY_EXCEL_PATH = policy_deduction/policy_data/人工智能政策法规.xlsx`
- 输出目录：
  - 风险输出：`static/risk_outputs/`
  - 政策输出：`static/policy_outputs/`
- 备份目录：`backups/`
- 日志文件：`logs/app.log`

### 3.2 大模型服务配置（本地 `.env`）

系统内所有大模型调用统一通过 `llm_client.py` 发起。不要把密钥写入代码或提交到 Git。先复制示例文件并填入新生成（已轮换）的密钥：

```bash
# macOS / Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

在 `.env` 中配置：

```dotenv
LLM_API_KEY=你的新密钥
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
# LLM_PROXY_URL=http://代理地址:端口
```

修改 `.env` 后重启 Flask 后端。也可以不创建 `.env`，在启动前设置环境变量：

```powershell
# Windows PowerShell
$env:LLM_API_KEY = "你的新密钥"
python backend_server.py
```

```bash
# macOS / Linux
export LLM_API_KEY='你的新密钥'
python backend_server.py
```

`LLM_BASE_URL` 默认值为 `https://api.deepseek.com`，`LLM_MODEL` 默认值为 `deepseek-v4-flash`，`LLM_PROXY_URL` 可选。TLS 证书验证默认开启；除非部署环境另有明确要求，不要关闭它。

### 3.3 前端依赖与 `API_BASE`（`templates/base.html`）

- `API_BASE`：前端请求后端的基础地址，默认 `http://localhost:8000`。如部署到服务器或使用反向代理，请同步修改。
- 前端依赖加载方式：当前页面会从 CDN 加载 Tailwind/ForceGraph/D3/marked/DOMPurify/html2pdf 等库。如部署环境禁止外网访问，需要将这些依赖替换为本地静态资源并调整引用路径。

---

## 4. 数据准备（必需数据、格式、存放位置）

### 4.1 图谱主库（必需）

#### 4.1.1 存放位置

- `static/data/graph_data.json`

说明：根目录下的 `graph_data.json` 可作为示例/参考文件；系统实际运行时默认读取与写回的是 `static/data/graph_data.json`。

#### 4.1.2 格式要求

顶层为 JSON 对象，包含：

- `nodes`: 列表
- `relationships`: 列表

节点结构（最小要求）：

```json
{
  "id": 1,
  "labels": ["环节"],
  "properties": {"name": "算力调度", "level": 2}
}
```

关系结构（最小要求）：

```json
{
  "id": 1001,
  "source": 1,
  "target": 2,
  "type": "从属于",
  "properties": {}
}
```

说明：
- `id/source/target` 可以是整数或字符串，但需在全图谱内可唯一标识节点，并且关系端点必须能在 `nodes` 中找到对应节点。
- 建议在同一图谱主库中保持 `id` 类型一致（例如统一为整数或统一为字符串）。当前系统同时支持多种导入方式，若主库内混用整数/字符串 ID，请确保后续更新/删除接口传入的 `id` 与主库中的实际值保持一致。

#### 4.1.3 产业链骨架要求（用于“骨架保持不变”的增量补全）

系统将以下内容视为“产业链骨架”：

- 骨架节点：`labels` 包含 `"环节"`，且 `properties.level` 为 `1/2/3`，并包含 `properties.name`
- 骨架关系：用于层级从属的关系 `type` 为 `"从属于"`

前端“仅看骨架”按钮即基于上述规则从 `graph_data.json` 动态筛选骨架子图。
说明：
- 增量抽取会在既有骨架上进行对齐与挂接；若主库骨架缺失相应环节（例如缺少可匹配的 L3 环节），该条关系可能无法挂接并被跳过，需先补齐骨架或调整骨架命名/粒度后再导入。

### 4.2 政策数据（必需）

#### 4.2.1 存放位置

- 默认目录：`policy_deduction/policy_data/`
- 默认文件：`policy_deduction/policy_data/人工智能政策法规.xlsx`
- 实际读取路径：由 `backend_server.py` 的 `POLICY_EXCEL_PATH` 指定；若不指定，脚本也会自动寻找 `policy_deduction/policy_data/*.xlsx`

#### 4.2.2 Excel 格式要求

读取规则（由 `policy_deduction/Policy_deduction.py` 实现）：

- 默认读取：Excel 的第一个 sheet
- 标题列：列名包含“标题”（如 `标题`）；若未找到则使用第 1 列
- 内容列：列名包含“内容”或“正文”（如 `内容`/`正文`）；若未找到则使用第 2 列（无第 2 列时回退到第 1 列）

### 4.3 图谱导入业务数据（按需，Excel 上传）

#### 4.3.1 数据来源与存放

- 用户通过前端上传 `.xlsx` 文件
- 系统会保存到：`uploads/sessions/<session_id>/`（会话目录）

#### 4.3.2 Excel 格式要求

- 必须包含列：`正文`
- 每一行 `正文` 作为一条文本记录进入抽取流程；空值或过短内容会被过滤（长度需大于 5）

### 4.4 RAG 知识库（可选）

#### 4.4.1 语料与模型存放位置

- 语料目录：`RAG/raw_docx_files/`（仅 `doc/docx`）
- 向量模型目录：`RAG/models/`（SentenceTransformer 本地模型目录）
说明：
- 若语料包含 `.doc` 文件，`RAG/build_vector_db.py` 会调用外部命令 `antiword` 进行解析；部署环境未安装 `antiword` 时建议仅使用 `.docx`。

#### 4.4.2 向量库生成

首次使用 RAG 前需构建向量库（生成 `RAG/vector_db/`）：

```bash
python RAG/build_vector_db.py --build
```

---

## 5. 启动与验证

### 5.1 启动后端

```bash
python backend_server.py
```

默认访问：
- `http://127.0.0.1:8000/`

### 5.2 基础验证

- 健康检查：`GET /api/health` 返回 `status=ok`
- 图谱页面：进入“知识图谱”可加载 `static/data/graph_data.json`

---

## 6. 常见配置/数据问题定位

- 图谱无法加载：确认 `static/data/graph_data.json` 存在，且包含 `nodes/relationships` 两个列表字段
- 图谱导入无结果：确认上传 Excel 包含 `正文` 列，且内容非空
- 政策列表为空：确认政策 Excel 存在可读 sheet，且标题列/内容列符合规则
- RAG 无法回答：确认已构建 `RAG/vector_db/`，并且 `RAG/models/` 模型可用

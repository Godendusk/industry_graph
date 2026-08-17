import os
import sys
import uuid
import json
import shutil
import requests
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from token_util import token_required
from werkzeug.utils import secure_filename

from graph_import_script import run_import
from RAG.build_vector_db import query_vector_db, query_graph
from report_generation.body_agent import generate_report_bodies
from report_generation.coordinator_agent import generate_writing_tasks
from report_generation.outline_agent import generate_report_outline
from report_generation.rewrite_agent import recommend_rewrite_materials, rewrite_body_section
from report_generation.summary_agent import generate_report_summary
from report_generation.task_card_agent import generate_writing_task_card, generate_report_requirement
from report_generation.word_export_agent import export_report_docx
from risk_inference.risk import list_level2_nodes, run_risk_analysis
from policy_deduction.Policy_deduction import list_policy_titles, run_policy_analysis
# 强制 Windows 控制台使用 UTF-8，避免中文乱码
if sys.platform.startswith("win"):
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
app.config["JSON_AS_ASCII"] = False
#app.config['PROJCT_NAME'] = '/indusgraph'
app.config['PROJCT_NAME'] = ''
@app.context_processor
def inject_static_base():
    return dict(STATIC_BASE=app.config['PROJCT_NAME']+"/static/")

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
IMPORT_SESSION_DIR = os.path.join(UPLOAD_DIR, "sessions")
GRAPH_DATA_PATH = os.path.join(STATIC_DIR, "data", "graph_data.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
RISK_OUTPUT_DIR = os.path.join(STATIC_DIR, "risk_outputs")
POLICY_OUTPUT_DIR = os.path.join(STATIC_DIR, "policy_outputs")
REPORT_HISTORY_DIR = os.path.join(BASE_DIR, "report_generation", "history")
REPORT_HISTORY_FILE = os.path.join(REPORT_HISTORY_DIR, "report_history.json")
# 默认政策 Excel 路径（在模块内部也会自动寻找），可根据需要修改
POLICY_EXCEL_PATH = os.path.join(BASE_DIR, "policy_deduction", "policy_data", "人工智能政策法规.xlsx")
SETTINGS_PATH = os.path.join(STATIC_DIR, "data", "settings.json")

# 产业数据路径映射
INDUSTRY_DATA_PATHS = {
    "ai": os.path.join(STATIC_DIR, "data", "ai", "graph_data.json"),
    "embodied": os.path.join(STATIC_DIR, "data", "embodied", "graph_data.json"),
    "low_altitude": os.path.join(STATIC_DIR, "data", "low_altitude", "graph_data.json"),
    "sea": os.path.join(STATIC_DIR, "data", "sea", "graph_data.json"),
    "quantum": os.path.join(STATIC_DIR, "data", "quantum", "graph_data.json"),
    "biology": os.path.join(STATIC_DIR, "data", "biology", "graph_data.json"),
    "brain": os.path.join(STATIC_DIR, "data", "brain", "graph_data.json"),
    "material": os.path.join(STATIC_DIR, "data", "material", "graph_data.json")
}

# 产业政策Excel文件路径映射
INDUSTRY_POLICY_PATHS = {
    "ai": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "人工智能政策法规.xlsx"),
    "embodied": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "具身智能政策法规.xlsx"),
    "low_altitude": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "低空经济政策法规.xlsx"),
    "sea": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "海洋经济政策法规.xlsx"),
    "quantum": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "量子科技政策法规.xlsx"),
    "biology": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "生物制造政策法规.xlsx"),
    "brain": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "脑机接口政策法规.xlsx"),
    "material": os.path.join(BASE_DIR, "policy_deduction", "policy_data", "新材料政策法规.xlsx")
}

def get_policy_excel_path(industry=None):
    """根据产业获取对应的政策Excel文件路径"""
    if industry and industry in INDUSTRY_POLICY_PATHS:
        path = INDUSTRY_POLICY_PATHS[industry]
        if os.path.exists(path):
            return path
        else:
            print(f"警告：产业政策文件不存在: {path}")
    
    # 默认返回主政策Excel路径
    return POLICY_EXCEL_PATH

def get_graph_data_path(industry=None):
    """根据产业获取对应的图谱数据路径"""
    if industry and industry in INDUSTRY_DATA_PATHS:
        path = INDUSTRY_DATA_PATHS[industry]
        if os.path.exists(path):
            return path
        else:
            print(f"警告：产业数据文件不存在: {path}")
    
    # 默认返回主图谱数据路径
    return GRAPH_DATA_PATH

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(IMPORT_SESSION_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(RISK_OUTPUT_DIR, exist_ok=True)
os.makedirs(POLICY_OUTPUT_DIR, exist_ok=True)
os.makedirs(REPORT_HISTORY_DIR, exist_ok=True)


def log_action(action: str, status: str = "info", detail: str = "", extra: dict = None):
    record = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "status": status,
    }
    if detail:
        record["detail"] = detail
    if extra:
        record["extra"] = extra
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"日志写入失败: {e}")


def read_report_history():
    """读取服务器本地的报告历史，损坏文件按空历史处理。"""
    try:
        with open(REPORT_HISTORY_FILE, "r", encoding="utf-8") as file:
            records = json.load(file)
        return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []
    except FileNotFoundError:
        return []
    except Exception as exc:
        log_action("report_history_read", "error", str(exc))
        return []


def write_report_history(records):
    """原子写入本地历史文件，避免写入中断导致历史文件损坏。"""
    history_path = Path(REPORT_HISTORY_FILE)
    temporary_path = history_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(history_path)


def get_report_history_summaries(records):
    return [
        {
            "id": record.get("id", ""),
            "title": record.get("title", "未命名报告"),
            "createdAt": record.get("createdAt", ""),
            "updatedAt": record.get("updatedAt", ""),
        }
        for record in records
        if record.get("id")
    ]


@app.after_request
def log_api_requests(response):
    """统一记录 API 请求日志（排除静态文件和健康检查）。"""
    try:
        path = request.path
        # 过滤噪声：静态资源与健康检查可以跳过
        if not path.startswith("/static/") and path != "/api/health":
            log_action(
                "http_request",
                status=str(response.status_code),
                extra={
                    "method": request.method,
                    "path": path,
                    "remote": request.remote_addr,
                },
            )
    except Exception:
        pass
    return response

print(f"后端服务已启动")
print(f"静态资源目录: {STATIC_DIR}")


@app.route("/api/health", methods=["GET"])
@token_required
def health_check():
    return jsonify({"status": "ok", "message": "Server is running"})


@app.route("/")
#@token_required
def index():
    return render_template("base.html")


@app.route("/sunburst_screenshot")
#@token_required
def sunburst_screenshot_page():
    """旭日图截图专用页面，接收data_source参数指定图谱数据源"""
    return render_template("components/screenshot.html")


@app.route("/static/<path:filename>")
@token_required
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)


# --- 4. RAG 查询 ---
@app.route("/api/rag_query", methods=["POST"])
@token_required
def rag_query():
    data = request.json or {}
    query = data.get("query")
    industry = data.get("industry", "").strip()

    if not query:
        return jsonify({"status": "error", "message": "Query cannot be empty"}), 400

    try:
        # 如果没有提供产业参数，尝试从全局变量获取
        if not industry:
            industry = getattr(app, 'current_industry', 'ai')
        
        markdown = query_vector_db(query, industry=industry)
        if not markdown:
            return jsonify({"status": "error", "message": "LLM 返回为空或调用失败"}), 500
        return jsonify({"status": "success", "markdown": markdown, "industry": industry})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Report generation: editable writing task~ card ---
# 生成可以编辑的写作任务卡片，供前端展示和修改
@app.route("/api/report/task-card", methods=["POST"])
@token_required
def report_task_card():
    data = request.json or {}  
    title = str(data.get("title") or "").strip() # 用户输入的标题(若无使用默认标题)
    user_requirement = str(data.get("user_requirement") or "").strip() # 用户输入的需求
    page_industry = str(data.get("page_industry") or data.get("industry") or "").strip() # 页面传入的产业参数
    if not title:
        return jsonify({"status": "error", "message": "title cannot be empty"}), 400
    # 生成可编辑的写作任务卡，返回给前端
    result = generate_writing_task_card(
        title=title,
        user_requirement=user_requirement,
        page_industry=page_industry,
    )
    log_action(
        "report_task_card",
        result.get("status", "error"),
        result.get("message", ""),
        {"title": title, "page_industry": page_industry, "task_card": result.get("task_card")},
    )
    if result.get("status") != "success":
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/report/task-card/rewrite-requirement", methods=["POST"])
@token_required
def report_task_card_rewrite_requirement():
    data = request.json or {}
    title = str(data.get("title") or "").strip()
    user_requirement = str(data.get("user_requirement") or "").strip()
    industry = str(data.get("industry") or "").strip()
    industry_name = str(data.get("industry_name") or "").strip()
    if not title:
        return jsonify({"status": "error", "message": "title cannot be empty"}), 400
    if not industry:
        return jsonify({"status": "error", "message": "industry cannot be empty"}), 400

    result = generate_report_requirement(
        title=title,
        user_requirement=user_requirement,
        industry=industry,
        industry_name=industry_name,
    )
    log_action(
        "report_task_card_rewrite_requirement",
        result.get("status", "error"),
        result.get("message", ""),
        {"title": title, "industry": industry, "industry_name": industry_name},
    )
    if result.get("status") != "success":
        return jsonify(result), 400
    return jsonify(result)


# --- Report generation: outline agent ---
# 生成报告大纲，供前端展示和修改
@app.route("/api/report/outline", methods=["POST"])
@token_required
def report_outline():
    # 获取前端POST传过来的json请求体，拿不到就是空字典
    data = request.json or {}
    task_card = data.get("task_card") if isinstance(data.get("task_card"), dict) else None
    if task_card is None:
        return jsonify({"status": "error", "message": "confirmed task_card is required"}), 400

    title = str(task_card.get("selected_title") or "").strip()
    user_requirement = str(task_card.get("report_requirement") or "").strip()
    industry = str(task_card.get("selected_industry") or "").strip()

    # 校验 title 是否为空，如果为空就返回错误响应(前端保证若用户不输入，使用默认标题)
    if not title:
        return jsonify({"status": "error", "message": "title cannot be empty"}), 400
    if not user_requirement:
        return jsonify({"status": "error", "message": "report_requirement cannot be empty"}), 400

    # 调用核心业务函数，生成报告大纲
    # 传入：报告标题、用户需求、所属行业

    result = generate_report_outline(
        title=title,
        user_requirement=user_requirement,
        industry=industry,
        industry_confirmed=task_card is not None,
    )

    # 记录直接大纲生成上下文，便于定位任务卡和输出大纲是否一致。
    log_action(
        "report_direct_outline",
        result.get("status", "error"),
        result.get("message", ""),
        {
            "title": title,
            "industry": industry,
            "task_card": {
                "selected_title": task_card.get("selected_title"),
                "selected_industry": task_card.get("selected_industry"),
                "selected_industry_name": task_card.get("selected_industry_name"),
                "report_requirement": task_card.get("report_requirement"),
            },
            "outline": result.get("outline"),
        },
    )

    # 判断业务返回状态，如果不是success，返回错误json，http码400
    if result.get("status") != "success":
        return jsonify(result), 400

    # 成功，直接把业务结果返回给前端
    return jsonify(result)


# --- Report generation: coordinator agent ---
@app.route("/api/report/coordinator", methods=["POST"])
@token_required
def report_coordinator():
    data = request.json or {}
    user_prompt = str(data.get("user_prompt") or "").strip()
    report_title = str(data.get("report_title") or "").strip()
    industry = str(data.get("industry", "ai") or "").strip()
    outline = data.get("outline")
    top_k = data.get("top_k", 10)

    if not user_prompt:
        return jsonify({"status": "error", "message": "user_prompt cannot be empty"}), 400
    if not report_title:
        return jsonify({"status": "error", "message": "report_title cannot be empty"}), 400
    if not isinstance(outline, list):
        return jsonify({"status": "error", "message": "outline must be an array"}), 400

    result = generate_writing_tasks(
        user_prompt=user_prompt,
        report_title=report_title,
        outline=outline,
        industry=industry,
        top_k=top_k,
    )
    if result.get("status") != "success":
        return jsonify(result), 400
    return jsonify(result)


# --- Report generation: body agent ---
@app.route("/api/report/body", methods=["POST"])
@token_required
def report_body():
    data = request.json or {}
    user_prompt = str(data.get("user_prompt") or "").strip()
    report_title = str(data.get("report_title") or "").strip()
    industry = str(data.get("industry", "ai") or "").strip()
    writing_tasks = data.get("writing_tasks")
    max_workers = data.get("max_workers", 3)

    if not user_prompt:
        return jsonify({"status": "error", "message": "user_prompt cannot be empty"}), 400
    if not report_title:
        return jsonify({"status": "error", "message": "report_title cannot be empty"}), 400
    if not isinstance(writing_tasks, list):
        return jsonify({"status": "error", "message": "writing_tasks must be an array"}), 400

    result = generate_report_bodies(
        user_prompt=user_prompt,
        report_title=report_title,
        writing_tasks=writing_tasks,
        industry=industry,
        max_workers=max_workers,
    )
    if result.get("status") == "error" and not result.get("body_sections"):
        return jsonify(result), 400
    return jsonify(result)


# --- Report generation: server-local report history ---
@app.route("/api/report/history", methods=["GET"])
@token_required
def report_history_list():
    records = read_report_history()
    return jsonify({"status": "success", "items": get_report_history_summaries(records)})


@app.route("/api/report/history/<history_id>", methods=["GET"])
@token_required
def report_history_detail(history_id):
    record = next((item for item in read_report_history() if item.get("id") == history_id), None)
    if not record:
        return jsonify({"status": "error", "message": "history report not found"}), 404
    return jsonify({"status": "success", "report": record})


@app.route("/api/report/history", methods=["POST"])
@token_required
def report_history_save():
    data = request.json or {}
    report = data.get("report")
    if not isinstance(report, dict):
        return jsonify({"status": "error", "message": "report must be an object"}), 400

    records = read_report_history()
    now = datetime.now().isoformat(timespec="seconds")
    history_id = str(report.get("id") or "").strip()[:100] or f"local_report_{uuid.uuid4().hex}"
    saved_report = dict(report)
    saved_report["id"] = history_id
    saved_report["updatedAt"] = now

    existing_index = next((index for index, item in enumerate(records) if item.get("id") == history_id), None)
    if existing_index is not None:
        saved_report["createdAt"] = records[existing_index].get("createdAt") or now
        records[existing_index] = saved_report
    else:
        saved_report["createdAt"] = saved_report.get("createdAt") or now
        records.insert(0, saved_report)

    records = records[:30]
    try:
        write_report_history(records)
    except Exception as exc:
        log_action("report_history_write", "error", str(exc))
        return jsonify({"status": "error", "message": f"failed to save local report history: {exc}"}), 500

    return jsonify({"status": "success", "report": saved_report, "items": get_report_history_summaries(records)})


@app.route("/api/report/history", methods=["DELETE"])
@token_required
def report_history_delete():
    data = request.json or {}
    history_id = str(data.get("id") or "").strip()
    if not history_id:
        return jsonify({"status": "error", "message": "id cannot be empty"}), 400

    records = read_report_history()
    next_records = [item for item in records if item.get("id") != history_id]
    if len(next_records) == len(records):
        return jsonify({"status": "error", "message": "history report not found"}), 404
    try:
        write_report_history(next_records)
    except Exception as exc:
        log_action("report_history_delete", "error", str(exc))
        return jsonify({"status": "error", "message": f"failed to delete local report history: {exc}"}), 500

    return jsonify({"status": "success", "items": get_report_history_summaries(next_records)})


# --- Report generation: summary agent ---
@app.route("/api/report/summary", methods=["POST"])
@token_required
def report_summary():
    data = request.json or {}
    report_title = str(data.get("report_title") or "").strip()
    industry = str(data.get("industry", "ai") or "").strip()
    outline = data.get("outline")
    body_sections = data.get("body_sections")

    if not report_title:
        return jsonify({"status": "error", "message": "report_title cannot be empty"}), 400
    if not isinstance(outline, list):
        return jsonify({"status": "error", "message": "outline must be an array"}), 400
    if not isinstance(body_sections, list):
        return jsonify({"status": "error", "message": "body_sections must be an array"}), 400

    result = generate_report_summary(
        report_title=report_title,
        outline=outline,
        body_sections=body_sections,
        industry=industry,
    )
    if result.get("status") != "success":
        return jsonify(result), 400
    return jsonify(result)


# --- Report generation: Word export agent ---
@app.route("/api/report/export/word", methods=["POST"])
@token_required
def report_export_word():
    data = request.json or {}
    report_title = str(data.get("report_title") or "").strip()
    abstract_text = str(data.get("abstract_text") or "").strip()
    industry = str(data.get("industry", "ai") or "").strip()
    body_sections = data.get("body_sections")

    if not report_title:
        return jsonify({"status": "error", "message": "report_title cannot be empty"}), 400
    if not abstract_text:
        return jsonify({"status": "error", "message": "abstract_text cannot be empty"}), 400
    if not isinstance(body_sections, list):
        return jsonify({"status": "error", "message": "body_sections must be an array"}), 400

    result = export_report_docx(
        report_title=report_title,
        abstract_text=abstract_text,
        body_sections=body_sections,
        industry=industry,
    )
    if result.get("status") != "success":
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/report/export/word/download", methods=["GET"])
@token_required
def report_export_word_download():
    docx_path = str(request.args.get("path") or "").strip()
    if not docx_path:
        return jsonify({"status": "error", "message": "path cannot be empty"}), 400

    project_root = Path(__file__).resolve().parent
    outputs_dir = (project_root / "report_generation" / "outputs").resolve()
    target_path = (project_root / docx_path).resolve()

    if outputs_dir not in target_path.parents or target_path.suffix.lower() != ".docx":
        return jsonify({"status": "error", "message": "invalid docx path"}), 400
    if not target_path.exists():
        return jsonify({"status": "error", "message": "docx file not found"}), 404

    return send_from_directory(
        target_path.parent,
        target_path.name,
        as_attachment=True,
        download_name=target_path.name,
    )


# --- Report generation: rewrite material recommendation ---
@app.route("/api/report/rewrite/materials", methods=["POST"])
@token_required
def report_rewrite_materials():
    data = request.json or {}
    rewrite_prompt = str(data.get("rewrite_prompt") or "").strip()
    report_title = str(data.get("report_title") or "").strip()
    industry = str(data.get("industry", "ai") or "").strip()
    body_section = data.get("body_section")
    top_k = data.get("top_k", 10)

    if not rewrite_prompt:
        return jsonify({"status": "error", "message": "rewrite_prompt cannot be empty"}), 400
    if not report_title:
        return jsonify({"status": "error", "message": "report_title cannot be empty"}), 400
    if not isinstance(body_section, dict):
        return jsonify({"status": "error", "message": "body_section must be an object"}), 400

    result = recommend_rewrite_materials(
        rewrite_prompt=rewrite_prompt,
        report_title=report_title,
        body_section=body_section,
        industry=industry,
        top_k=top_k,
    )
    if result.get("status") == "error":
        return jsonify(result), 400
    return jsonify(result)


# --- Report generation: rewrite body section ---
@app.route("/api/report/rewrite", methods=["POST"])
@token_required
def report_rewrite():
    data = request.json or {}
    rewrite_prompt = str(data.get("rewrite_prompt") or "").strip()
    report_title = str(data.get("report_title") or "").strip()
    industry = str(data.get("industry", "ai") or "").strip()
    body_section = data.get("body_section")
    graph_retrieval = data.get("graph_retrieval") or {}
    selected_external_evidence_blocks = data.get("selected_external_evidence_blocks") or []

    if not rewrite_prompt:
        return jsonify({"status": "error", "message": "rewrite_prompt cannot be empty"}), 400
    if not report_title:
        return jsonify({"status": "error", "message": "report_title cannot be empty"}), 400
    if not isinstance(body_section, dict):
        return jsonify({"status": "error", "message": "body_section must be an object"}), 400
    if not isinstance(graph_retrieval, dict):
        return jsonify({"status": "error", "message": "graph_retrieval must be an object"}), 400
    if not isinstance(selected_external_evidence_blocks, list):
        return jsonify({"status": "error", "message": "selected_external_evidence_blocks must be an array"}), 400

    result = rewrite_body_section(
        rewrite_prompt=rewrite_prompt,
        report_title=report_title,
        body_section=body_section,
        graph_retrieval=graph_retrieval,
        selected_external_evidence_blocks=selected_external_evidence_blocks,
        industry=industry,
    )
    if result.get("status") != "success":
        return jsonify(result), 400
    return jsonify(result)

# --- 6. 图谱导入（上传）---
@app.route("/api/graph_import/upload", methods=["POST"])
@token_required
def graph_import_upload():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "缺少文件字段 file"}), 400

    uploaded = request.files["file"]
    if uploaded.filename == "":
        return jsonify({"status": "error", "message": "文件名为空"}), 400

    # 获取产业参数
    industry = request.form.get("industry", "").strip()
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"数据导入 - 产业: {industry}, 主库路径: {graph_path}")

    filename = secure_filename(uploaded.filename)
    session_id = uuid.uuid4().hex
    session_dir = os.path.join(IMPORT_SESSION_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    saved_path = os.path.join(session_dir, filename)
    uploaded.save(saved_path)

    log_out = os.path.join(session_dir, "import_log.json")

    try:
        # 使用 graph_import_script：读取对应产业的图谱数据作为主库，上传文件作为输入
        master_db, new_items, candidates, log_file = run_import(
            input_path=saved_path,
            master_path=graph_path,
            log_path=log_out
        )

        with open(os.path.join(session_dir, "session.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": session_id,
                    "file": saved_path,
                    "candidates": candidates,
                    "new_items": new_items,
                    "log_file": log_file
                },
                f,
                ensure_ascii=False,
                indent=2
            )

        # 返回候选节点/关系供前端预览
        log_action("graph_import_upload", "success", extra={
            "session_id": session_id,
            "file": filename,
            "industry": industry,
            "nodes": len(candidates.get("nodes", [])),
            "links": len(candidates.get("links", []))
        })
        return jsonify({
            "status": "success",
            "session_id": session_id,
            "data": candidates,
            "new_items": new_items,
            "industry": industry
        })
    except Exception as e:
        log_action("graph_import_upload", "error", detail=str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/graph_import/commit", methods=["POST"])
@token_required
def graph_import_commit():
    data = request.json or {}
    session_id = data.get("session_id")
    node_ids = set(data.get("nodes") or [])
    link_ids = set(data.get("links") or [])
    industry = data.get("industry", "").strip()
    
    if not session_id:
        return jsonify({"status": "error", "message": "缺少 session_id"}), 400

    # 如果没有提供产业参数，尝试从session中获取
    if not industry:
        session_dir = os.path.join(IMPORT_SESSION_DIR, session_id)
        session_file = os.path.join(session_dir, "session.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
                    industry = session_data.get("industry", "")
            except Exception:
                pass
    
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"提交数据导入 - 产业: {industry}, 路径: {graph_path}")

    session_dir = os.path.join(IMPORT_SESSION_DIR, session_id)
    session_file = os.path.join(session_dir, "session.json")
    if not os.path.exists(session_file):
        return jsonify({"status": "error", "message": "session 不存在或已过期"}), 404

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            session_data = json.load(f)
    except Exception as e:
        return jsonify({"status": "error", "message": f"读取 session 失败: {e}"}), 500

    candidates = session_data.get("candidates") or {"nodes": [], "links": []}

    # 读取现有图谱
    graph_data = {"nodes": [], "relationships": []}
    if os.path.exists(graph_path):
        try:
            with open(graph_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    graph_data["nodes"] = loaded.get("nodes", [])
                    graph_data["relationships"] = loaded.get("relationships", [])
        except Exception as e:
            return jsonify({"status": "error", "message": f"读取图谱失败: {e}"}), 500

    existing_nodes = graph_data.get("nodes", [])
    existing_links = graph_data.get("relationships", [])

    # 构建索引：label:name -> node id
    node_index = {}
    for n in existing_nodes:
        label = (n.get("labels") or [""])[0]
        name = n.get("properties", {}).get("name")
        if label and name:
            node_index[f"{label}:{name}"] = n.get("id")

    # 使用整数 ID，避免与原图谱（id 多为 int）混用字符串导致前端/脚本异常
    next_node_int_id = max([n.get("id") for n in existing_nodes if isinstance(n.get("id"), int)] or [-1]) + 1
    next_link_int_id = max([r.get("id") for r in existing_links if isinstance(r.get("id"), int)] or [0]) + 1

    def next_node_id():
        nonlocal next_node_int_id
        nid = next_node_int_id
        next_node_int_id += 1
        return nid

    def next_link_id():
        nonlocal next_link_int_id
        rid = next_link_int_id
        next_link_int_id += 1
        return rid

    def ensure_node(node):
        label = (node.get("labels") or [""])[0]
        name = node.get("properties", {}).get("name")
        if not label or not name:
            return None, False
        key = f"{label}:{name}"
        if key in node_index:
            return node_index[key], False
        new_id = next_node_id()
        node_index[key] = new_id
        new_node = {
            "id": new_id,
            "labels": node.get("labels", []),
            "properties": node.get("properties", {}),
        }
        existing_nodes.append(new_node)
        return new_id, True

    added_nodes = 0
    added_links = 0

    # 处理选中的节点
    temp_to_real = {}
    for n in candidates.get("nodes", []):
        if n.get("temp_id") not in node_ids:
            continue
        real_id, is_new = ensure_node(n)
        if real_id:
            temp_to_real[n.get("temp_id")] = real_id
            if is_new:
                added_nodes += 1

    # 处理选中的关系
    for l in candidates.get("links", []):
        if l.get("temp_id") not in link_ids:
            continue
        src = temp_to_real.get(l.get("source"))
        tgt = temp_to_real.get(l.get("target"))
        if not src or not tgt:
            continue
        new_rel = {
            "id": next_link_id(),
            "source": src,
            "target": tgt,
            "type": l.get("type") or "关联",
            "properties": l.get("properties") or {},
        }
        existing_links.append(new_rel)
        added_links += 1

    # 保存图谱
    try:
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": existing_nodes, "relationships": existing_links}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_action("graph_import_commit", "error", detail=str(e), extra={"session": session_id, "industry": industry})
        return jsonify({"status": "error", "message": f"写入图谱失败: {e}"}), 500

    log_action("graph_import_commit", "success", extra={
        "session": session_id,
        "industry": industry,
        "added_nodes": added_nodes,
        "added_links": added_links
    })
    return jsonify({
        "status": "success",
        "added_nodes": added_nodes,
        "added_links": added_links,
        "industry": industry
    })

# --- 6b. 节点删除：删除节点及其关联关系 ---
@app.route("/api/graph_node_delete", methods=["POST"])
@token_required
def graph_node_delete():
    data = request.json or {}
    node_id = data.get("id")
    industry = data.get("industry", "").strip()
    
    if not node_id:
        return jsonify({"status": "error", "message": "缺少节点 id"}), 400
    
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"删除节点 - 产业: {industry}, 节点ID: {node_id}, 路径: {graph_path}")
    
    try:
        if not os.path.exists(graph_path):
            return jsonify({"status": "error", "message": f"{industry}产业的图谱数据不存在"}), 404
        with open(graph_path, "r", encoding="utf-8") as f:
            g = json.load(f)
        nodes = g.get("nodes", [])
        rels = g.get("relationships", [])
        before_nodes = len(nodes)
        before_rels = len(rels)
        nodes = [n for n in nodes if n.get("id") != node_id]
        rels = [r for r in rels if r.get("source") != node_id and r.get("target") != node_id]
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "relationships": rels}, f, ensure_ascii=False, indent=2)
        log_action("graph_node_delete", "success", extra={
            "id": node_id, 
            "industry": industry,
            "removed_nodes": before_nodes - len(nodes), 
            "removed_relationships": before_rels - len(rels)
        })
        return jsonify({
            "status": "success",
            "removed_nodes": before_nodes - len(nodes),
            "removed_relationships": before_rels - len(rels),
            "industry": industry
        })
    except Exception as e:
        log_action("graph_node_delete", "error", detail=str(e), extra={"id": node_id, "industry": industry})
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 6c. 节点属性更新 ---
@app.route("/api/graph_node_update", methods=["POST"])
@token_required
def graph_node_update():
    data = request.json or {}
    node_id = data.get("id")
    props = data.get("properties")
    industry = data.get("industry", "").strip()
    
    if not node_id or props is None:
        return jsonify({"status": "error", "message": "缺少 id 或 properties"}), 400
    
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"更新节点属性 - 产业: {industry}, 节点ID: {node_id}, 路径: {graph_path}")
    
    try:
        if not os.path.exists(graph_path):
            return jsonify({"status": "error", "message": f"{industry}产业的图谱数据不存在"}), 404
        with open(graph_path, "r", encoding="utf-8") as f:
            g = json.load(f)
        nodes = g.get("nodes", [])
        updated = 0
        for n in nodes:
            if n.get("id") == node_id:
                n["properties"] = props
                updated = 1
                break
        if not updated:
            return jsonify({"status": "error", "message": "未找到节点"}), 404
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": nodes, "relationships": g.get("relationships", [])}, f, ensure_ascii=False, indent=2)
        log_action("graph_node_update", "success", extra={"id": node_id, "industry": industry})
        return jsonify({"status": "success", "updated": 1, "industry": industry})
    except Exception as e:
        log_action("graph_node_update", "error", detail=str(e), extra={"id": node_id, "industry": industry})
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 6. 图谱导出（下载当前 graph_data.json） ---
@app.route("/api/graph_export", methods=["GET"])
@token_required
def graph_export():
    # 获取产业参数
    industry = request.args.get("industry", "").strip()
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"导出图谱 - 产业: {industry}, 路径: {graph_path}")
    
    try:
        if not os.path.exists(graph_path):
            return jsonify({"status": "error", "message": f"{industry}产业的图谱数据不存在"}), 404
        resp = send_from_directory(
            directory=os.path.dirname(graph_path),
            path=os.path.basename(graph_path),
            as_attachment=True
        )
        log_action("graph_export", "success", extra={"industry": industry})
        return resp
    except Exception as e:
        log_action("graph_export", "error", detail=str(e), extra={"industry": industry})
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 6.5 全局设置读写 ---
@app.route("/api/settings", methods=["GET"])
def get_settings():
    """获取全局设置。文件不存在时返回默认值（全部开启）。"""
    default_settings = {
        "chain_panorama_column": {
            "l2": True,
            "l2_ratio": True,
            "l3": True,
            "l3_ratio": True,
            "representative": True
        },
        "chain_panorama_rep_picks": {},
        "chain_panorama_rep_sort": {}
    }
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if "chain_panorama_column" not in settings:
                settings["chain_panorama_column"] = default_settings["chain_panorama_column"]
            if "chain_panorama_rep_picks" not in settings:
                settings["chain_panorama_rep_picks"] = {}
            if "chain_panorama_rep_sort" not in settings:
                settings["chain_panorama_rep_sort"] = {}
        else:
            settings = default_settings
        return jsonify({"status": "success", "data": settings})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/settings", methods=["POST"])
def update_settings():
    """更新全局设置。接收 JSON body，写入 settings.json。"""
    try:
        body = request.get_json(force=True)
        if body is None:
            return jsonify({"status": "error", "message": "请求体为空或非 JSON 格式"}), 400
        # 校验 chain_panorama_column 字段必须为布尔值
        cp = body.get("chain_panorama_column")
        if cp is not None:
            if not isinstance(cp, dict):
                return jsonify({"status": "error", "message": "chain_panorama_column 必须是对象"}), 400
            expected_keys = {"l2", "l2_ratio", "l3", "l3_ratio", "representative"}
            for k in expected_keys:
                if k in cp and not isinstance(cp[k], bool):
                    return jsonify({"status": "error", "message": f"chain_panorama_column.{k} 必须是布尔值"}), 400
        
        # 校验 chain_panorama_rep_picks
        rpp = body.get("chain_panorama_rep_picks")
        if rpp is not None:
            if not isinstance(rpp, dict):
                return jsonify({"status": "error", "message": "chain_panorama_rep_picks 必须是对象"}), 400
            for industry, segments in rpp.items():
                if not isinstance(segments, dict):
                    return jsonify({"status": "error", "message": f"chain_panorama_rep_picks.{industry} 必须是对象"}), 400
                for seg_id, ids in segments.items():
                    if not isinstance(ids, list):
                        return jsonify({"status": "error", "message": f"chain_panorama_rep_picks.{industry}.{seg_id} 必须是数组"}), 400
                    if not all(isinstance(i, (int, float)) for i in ids):
                        return jsonify({"status": "error", "message": f"chain_panorama_rep_picks.{industry}.{seg_id} 必须是数字数组"}), 400
        
        # 校验 chain_panorama_rep_sort
        rps = body.get("chain_panorama_rep_sort")
        if rps is not None:
            if not isinstance(rps, dict):
                return jsonify({"status": "error", "message": "chain_panorama_rep_sort 必须是对象"}), 400
            for industry, segments in rps.items():
                if not isinstance(segments, dict):
                    return jsonify({"status": "error", "message": f"chain_panorama_rep_sort.{industry} 必须是对象"}), 400
                for seg_id, ids in segments.items():
                    if not isinstance(ids, list):
                        return jsonify({"status": "error", "message": f"chain_panorama_rep_sort.{industry}.{seg_id} 必须是数组"}), 400
                    if not all(isinstance(i, (int, float)) for i in ids):
                        return jsonify({"status": "error", "message": f"chain_panorama_rep_sort.{industry}.{seg_id} 必须是数字数组"}), 400
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        # 合并更新：先读取现有设置，再将 body 中的字段合并进去
        existing_settings = {}
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    existing_settings = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing_settings = {}
        # 合并 body 到现有设置中
        existing_settings.update(body)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(existing_settings, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 7. 图谱导入（上传一个或多个 JSON，合并后更新当前图谱） ---
@app.route("/api/graph_import_json", methods=["POST"])
@token_required
def graph_import_json():
    files = request.files.getlist("files")
    if not files:
        # 兼容单文件字段名 file
        single = request.files.get("file")
        if single:
            files = [single]
    if not files:
        return jsonify({"status": "error", "message": "缺少文件字段 file/files"}), 400

    # 获取产业参数
    industry = request.form.get("industry", "").strip()
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"导入图谱JSON - 产业: {industry}, 路径: {graph_path}")

    try:
        # 读现有图谱
        graph_data = {"nodes": [], "relationships": []}
        if os.path.exists(graph_path):
            with open(graph_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    graph_data["nodes"] = loaded.get("nodes", []) or []
                    graph_data["relationships"] = loaded.get("relationships", []) or []

        existing_nodes = graph_data["nodes"]
        existing_links = graph_data["relationships"]

        # 节点索引和 id 生成
        node_index = {}
        for n in existing_nodes:
            label = (n.get("labels") or [""])[0]
            name = n.get("properties", {}).get("name")
            if label and name:
                node_index[f"{label}:{name}"] = n.get("id")

        def next_node_id():
            max_id = 0
            for n in existing_nodes:
                nid = n.get("id", "")
                if isinstance(nid, str) and nid.startswith("n"):
                    try:
                        max_id = max(max_id, int(nid[1:]))
                    except ValueError:
                        pass
            return f"n{max_id + 1}"

        def next_rel_id():
            max_id = 0
            for r in existing_links:
                rid = r.get("id", "")
                if isinstance(rid, str) and rid.startswith("r"):
                    try:
                        max_id = max(max_id, int(rid[1:]))
                    except ValueError:
                        pass
            return f"r{max_id + 1}"

        added_nodes = 0
        added_links = 0

        for uploaded in files:
            if uploaded.filename == "":
                continue
            raw = uploaded.read()
            try:
                content = raw.decode("utf-8")
            except Exception:
                content = raw.decode("utf-8", errors="ignore")
            data = json.loads(content)
            if not isinstance(data, dict) or "nodes" not in data or "relationships" not in data:
                return jsonify({"status": "error", "message": f"{uploaded.filename}: 需包含 nodes 和 relationships"}), 400
            if not isinstance(data.get("nodes"), list) or not isinstance(data.get("relationships"), list):
                return jsonify({"status": "error", "message": f"{uploaded.filename}: nodes/relationships 必须为列表"}), 400

            id_map = {}
            # 先处理节点
            for n in data.get("nodes", []):
                label = (n.get("labels") or [""])[0]
                name = n.get("properties", {}).get("name")
                if not label or not name:
                    continue
                key = f"{label}:{name}"
                if key in node_index:
                    id_map[n.get("id")] = node_index[key]
                    continue
                new_id = next_node_id()
                id_map[n.get("id")] = new_id
                new_node = {
                    "id": new_id,
                    "labels": n.get("labels", []),
                    "properties": n.get("properties", {}),
                }
                existing_nodes.append(new_node)
                node_index[key] = new_id
                added_nodes += 1

            # 再处理关系，使用 id_map 映射端点
            for r in data.get("relationships", []):
                src = id_map.get(r.get("source"))
                tgt = id_map.get(r.get("target"))
                if not src or not tgt:
                    continue
                new_rel = {
                    "id": next_rel_id(),
                    "source": src,
                    "target": tgt,
                    "type": r.get("type") or "关联",
                    "properties": r.get("properties") or {},
                }
                existing_links.append(new_rel)
                added_links += 1

        # 写回合并后的图谱
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": existing_nodes, "relationships": existing_links}, f, ensure_ascii=False, indent=2)

        log_action("graph_import_json", "success", extra={
            "industry": industry,
            "added_nodes": added_nodes,
            "added_links": added_links,
            "total_nodes": len(existing_nodes),
            "total_relationships": len(existing_links)
        })
        return jsonify({
            "status": "success",
            "message": "图谱已更新（合并上传的 JSON）",
            "industry": industry,
            "nodes": len(existing_nodes),
            "relationships": len(existing_links),
            "added_nodes": added_nodes,
            "added_links": added_links
        })
    except json.JSONDecodeError as e:
        log_action("graph_import_json", "error", detail=f"JSON 解析失败: {e}")
        return jsonify({"status": "error", "message": f"JSON 解析失败: {e}"}), 400
    except Exception as e:
        log_action("graph_import_json", "error", detail=str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 8. 图谱导入（覆盖模式：用上传的单个 JSON 覆盖当前图谱） ---
@app.route("/api/graph_import_json_replace", methods=["POST"])
@token_required
def graph_import_json_replace():
    files = request.files.getlist("files")
    if not files:
        single = request.files.get("file")
        if single:
            files = [single]
    if not files:
        return jsonify({"status": "error", "message": "缺少文件字段 file/files"}), 400

    # 获取产业参数
    industry = request.form.get("industry", "").strip()
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"覆盖导入图谱JSON - 产业: {industry}, 路径: {graph_path}")

    uploaded = files[0]
    if uploaded.filename == "":
        return jsonify({"status": "error", "message": "文件名为空"}), 400

    try:
        raw = uploaded.read()
        try:
            content = raw.decode("utf-8")
        except Exception:
            content = raw.decode("utf-8", errors="ignore")
        data = json.loads(content)
        if not isinstance(data, dict) or "nodes" not in data or "relationships" not in data:
            return jsonify({"status": "error", "message": "格式错误：需包含 nodes 和 relationships 字段"}), 400
        if not isinstance(data.get("nodes"), list) or not isinstance(data.get("relationships"), list):
            return jsonify({"status": "error", "message": "格式错误：nodes/relationships 必须为列表"}), 400

        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify({
            "status": "success",
            "message": "图谱已覆盖更新",
            "industry": industry,
            "nodes": len(data.get("nodes", [])),
            "relationships": len(data.get("relationships", []))
        })
    except json.JSONDecodeError as e:
        return jsonify({"status": "error", "message": f"JSON 解析失败: {e}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 9. 图谱备份（保存当前 graph_data.json 到 backups 目录） ---
@app.route("/api/graph_backup", methods=["POST"])
@token_required
def graph_backup():
    # 获取产业参数
    data = request.json or {}
    industry = data.get("industry", "").strip()
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    # 根据产业获取对应的图谱数据路径
    graph_path = get_graph_data_path(industry)
    print(f"备份图谱 - 产业: {industry}, 路径: {graph_path}")
    
    if not os.path.exists(graph_path):
        return jsonify({"status": "error", "message": f"{industry}产业的图谱数据不存在"}), 404
    try:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_name = f"graph_data-{industry}-{ts}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        shutil.copyfile(graph_path, backup_path)
        log_action("graph_backup", "success", extra={"file": backup_name, "industry": industry})
        return jsonify({"status": "success", "file": backup_name, "industry": industry})
    except Exception as e:
        log_action("graph_backup", "error", detail=str(e), extra={"industry": industry})
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 风险分析：获取节点列表 ---
@app.route("/api/risk/nodes", methods=["GET"])
@token_required
def risk_nodes():
    try:
        # 获取产业参数，默认为当前选择的产业
        industry = request.args.get("industry", "")
        if not industry and hasattr(request, 'current_industry'):
            industry = request.current_industry
        if not industry:
            # 从全局变量获取当前产业
            industry = getattr(app, 'current_industry', 'ai')
        
        # 根据产业获取对应的图谱数据路径
        graph_path = get_graph_data_path(industry)
        print(f"风险分析 - 加载产业数据: {industry}, 路径: {graph_path}")
        
        nodes = list_level2_nodes(Path(graph_path))
        return jsonify({"status": "success", "nodes": nodes, "industry": industry})
    except Exception as e:
        log_action("risk_nodes", "error", detail=str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 风险分析：运行分析 ---
@app.route("/api/risk/run", methods=["POST"])
@token_required
def risk_run():
    data = request.json or {}
    node_name = data.get("node_name") or ""
    industry = data.get("industry", "")
    
    if not node_name:
        return jsonify({"status": "error", "message": "缺少 node_name"}), 400
    
    if not industry:
        # 从全局变量获取当前产业
        industry = getattr(app, 'current_industry', 'ai')
    
    try:
        # 根据产业获取对应的图谱数据路径
        graph_path = get_graph_data_path(industry)
        print(f"风险分析运行 - 产业: {industry}, 节点: {node_name}, 路径: {graph_path}")
        
        result = run_risk_analysis(node_name=node_name, graph_path=Path(graph_path), output_base=Path(RISK_OUTPUT_DIR))
        images = result.get("images", [])
        image_urls = []
        for img in images:
            rel = os.path.relpath(img, STATIC_DIR)
            image_urls.append(f"{app.config['PROJCT_NAME']}/static/{rel.replace(os.sep, '/')}")
        return jsonify({
            "status": "success",
            "report": result.get("report", ""),
            "images": image_urls,
            "log": result.get("log", ""),
            "industry": industry
        })
    except Exception as e:
        log_action("risk_run", "error", detail=str(e), extra={"node": node_name, "industry": industry})
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 政策推演：获取政策列表 ---
@app.route("/api/policy/list", methods=["GET"])
@token_required
def policy_list():
    try:
        keyword = request.args.get("keyword", "").strip()
        industry = request.args.get("industry", "").strip()
        
        # 根据产业选择政策Excel文件
        policy_excel_path = get_policy_excel_path(industry) if industry else POLICY_EXCEL_PATH
        
        items = list_policy_titles(excel_path=Path(policy_excel_path))
        if keyword:
            items = [i for i in items if keyword in i["title"]]
        return jsonify({"status": "success", "data": items, "industry": industry})
    except Exception as e:
        log_action("policy_list", "error", detail=str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


# --- 政策推演：运行分析 ---
@app.route("/api/policy/run", methods=["POST"])
@token_required
def policy_run():
    data = request.json or {}
    policy_index = data.get("policy_index")
    industry = data.get("industry", "").strip()
    
    if policy_index is None:
        return jsonify({"status": "error", "message": "未选择政策 (policy_index 缺失)"}), 400
    
    try:
        # 根据产业选择政策Excel文件
        policy_excel_path = get_policy_excel_path(industry) if industry else POLICY_EXCEL_PATH
        
        # 根据产业选择图谱数据文件
        graph_path = get_graph_data_path(industry) if industry else GRAPH_DATA_PATH
        
        result = run_policy_analysis(
            policy_index=int(policy_index),
            graph_path=Path(graph_path),
            excel_path=Path(policy_excel_path),
            output_base=Path(POLICY_OUTPUT_DIR),
        )
        images = []
        for img in result.get("images", []):
            rel = os.path.relpath(img, STATIC_DIR)
            images.append(f"{app.config['PROJCT_NAME']}/static/{rel.replace(os.sep, '/')}")

        log_action("policy_run", "success", extra={"policy_index": policy_index, "industry": industry})
        return jsonify(
            {
                "status": "success",
                "title": result.get("title", ""),
                "report": result.get("report", ""),
                "images": images,
                "log": result.get("log", ""),
                "industry": industry,
            }
        )
    except Exception as e:
        log_action("policy_run", "error", detail=str(e), extra={"policy_index": policy_index})
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/graph/query", methods=["POST"])
@token_required
def graph_query():
    data = request.json or {}
    search_query = data.get("search_query", "").strip()
    industry = data.get("industry", "").strip()
    if not search_query:
        return jsonify({"status": "error", "message": "未输入查询语句"})
    
    return query_graph(search_query, industry);

    
if __name__ == "__main__":
    os.makedirs(STATIC_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=8000, debug=True)

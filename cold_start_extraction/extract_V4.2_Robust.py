import json
import os
import time
import pandas as pd
import re
import traceback
import threading
import signal
import sys
import logging
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# ==================================================
# 0. 运行目录/导入路径兜底（确保不同 IDE/终端一致）
# ==================================================
# 目标：
# - 冷启动相关输入/输出文件：全部固定在脚本同级目录（与 cwd 无关）
# - LLMClient：统一复用项目根目录的 llm_client.py（避免被本目录同名文件遮蔽）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# --- Windows 控制台编码兜底 ---
# 部分中文 Windows 默认编码为 GBK，遇到 emoji/特殊符号会触发 UnicodeEncodeError。
# 这里将 stdout/stderr 设为 UTF-8 并用 replace 兜底，避免日志/打印导致任务失败。
if os.name == "nt":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


try:
    from rapidfuzz import process as fuzz_process
    from rapidfuzz import fuzz
except ImportError:
    print("❌ 请先安装 rapidfuzz: pip install rapidfuzz")
    exit()

# --- 导入你的 LLM 客户端 ---
# 注意：项目根目录已被插入 sys.path 的最前面，确保优先导入根目录的 llm_client.py。
from llm_client import LLMClient

# ==================================================
# 1. 全局配置与常量
# ==================================================

INPUT_SEGMENT_MAPPING = os.path.join(_SCRIPT_DIR, "segment_mapping_input.json")
INPUT_EXCEL_FILE = os.path.join(_SCRIPT_DIR, "new_data_upload.xlsx")
OUTPUT_GRAPH_FILE = os.path.join(_SCRIPT_DIR, "full_industry_knowledge_graph.json")
FAILED_LOG_FILE = os.path.join(_SCRIPT_DIR, "failed_records.json")
CHECKPOINT_FILE = os.path.join(_SCRIPT_DIR, "processing_checkpoint.json")  # <<< 断点状态文件 >>>
SYSTEM_LOG_FILE = os.path.join(_SCRIPT_DIR, f"system_run_{datetime.now().strftime('%Y%m%d_%H%M')}.log")

# --- 性能配置 ---
MAX_WORKERS_PIPELINE = 10     
MAX_CHARS_PER_BATCH = 5000   
MAX_RETRIES = 3               
RETRY_DELAY = 2               
SAVE_INTERVAL = 5             # 每处理 5 个 Batch 保存一次
# --- 去重阈值 ---
FUZZY_MATCH_HIGH = 85.0
FUZZY_MATCH_LOW = 60.0

# --- 实体与关系定义 (保持不变) ---
ENTITY_SCHEMA = {
    "企业实体": ["公司名称", "正式名称", "成立时间", "注册地区", "国内外", "注册资本（万元）", "最新市值", "最新营收", "最新研发投入", "企业介绍"],
    "产品实体": ["产品名称", "所属企业", "所属环节", "国内外", "发布时间", "状态", "产品介绍"],
    "投资实体": ["投资事件标题", "投资发生地点", "环节", "采购发生时间", "投资金额万元", "投资状态", "投资方名称", "被投企业名称"],
    "交易实体": ["采购标题", "采购省份", "采购内容描述", "采购发生的时间", "采购金额万元", "采购方名称", "中标方名称", "对应的AI产业环节"],
    "舆情实体": ["事件标题", "发生地点", "事件内容 ", "时间", "涉及企业", "对应产业环节"]
}

RELATION_TYPES = {
    "REL_SUBSEG": "从属于", "REL_OPERATES": "参与环节", "REL_ALIGNS": "产品对应环节",
    "REL_OWNS": "拥有产品", "REL_INVEST_SEG": "涉及环节", "REL_INVEST_FROM": "投资方",
    "REL_INVEST_TO": "被投资方", "REL_OPINION_SEG": "对应环节", "REL_OPINION_COMP": "涉及企业",
    "REL_TRADE_SEG": "涉及环节", "REL_TRADE_BUYER": "采购方", "REL_TRADE_SELLER": "中标方"
}

LABEL_MAPPING = {
    "企业实体": "公司", "产品实体": "产品", "投资实体": "投资",
    "交易实体": "交易", "舆情实体": "舆情"
}

# ==================================================
# 2. 日志与工具函数
# ==================================================

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(SYSTEM_LOG_FILE, encoding='utf-8'),
        logging.StreamHandler() # 输出到控制台
    ]
)
logger = logging.getLogger(__name__)

def retry_with_backoff(max_retries=3, delay=2):
    """API重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    wait_time = delay * (2 ** (retries - 1))
                    logger.warning(f"⚠️ API调用失败: {e}. 重试 {retries}/{max_retries}，等待 {wait_time}秒...")
                    time.sleep(wait_time)
            logger.error(f"❌ API调用在 {max_retries} 次重试后彻底失败。")
            raise Exception(f"Max retries exceeded for {func.__name__}")
        return wrapper
    return decorator

def normalize_name_v3(name, label=""):
    if not name: return ""
    name = str(name).strip()
    name = name.replace(' ', '').replace('-', '').replace('_', '').upper()
    if label == "公司":
        for suffix in ['公司', '有限', '责任', '股份', '集团', '控股']:
            name = name.replace(suffix, '')
    elif label == "产品":
        for suffix in ['芯片', '产品']:
            name = name.replace(suffix, '')
    return name

def clean_json_text(text):
    if not text: return None
    text = text.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if match: return match.group(1)
        return text.replace("```json", "").replace("```", "")
    return text

def get_primary_key(label):
    if label == "公司": return "公司名称"
    if label == "产品": return "产品名称"
    return "name"

# ==================================================
# 3. Prompt 定义 (融合详细业务规则版)
# ==================================================

# Step 1: NER (实体识别)
# 融合了：负面清单、通用词过滤、同义词归一化
PROMPT_STEP1_NER = """
你是一名AI产业链数据清洗与实体识别专家。请扫描文本，提取以下 5 类关键实体：
["公司", "产品", "投资", "交易", "舆情"]

**【严格提取约束】(违反将被惩罚)：**

1. **通用词过滤**：
   - ❌ 严禁提取通用名词，如：“互联网公司”、“科技巨头”、“人工智能技术”、“未来”、“算力”、“数字化转型”。
   - ✅ 只提取**专有名词**，如：“腾讯科技”、“混元大模型”、“H100芯片”。

2. **名称归一化**：
   - 遇到简称或别名，请尽量转换为全称（如“中兴”->“中兴通讯”）。
   - 不提取长度小于 2 个字的词。

3. **【交易实体】特别负面清单 (关键)**：
   - ✅ **提取**：具体的**招投标项目**、**政府采购**、**签署的合同**（需有明确买卖双方或项目名）。
   - ❌ **严禁提取**：
     - **财务数据**：“营收100亿”、“净利润增长50%”、“算力占比20%”。
     - **统计数据**：“市场份额全球第二”、“发货量突破1亿”。
     - **泛指描述**：“获得客户认可”、“进入核心供应链”。

4. **【舆情实体】与【投资实体】**：
   - 舆情必须是具体的突发事件或新闻（如“XX公司被立案调查”）。
   - 投资必须有明确的投融资行为（如“XX获得A轮融资”）。

【输出格式】：
严格的 JSON 列表，不要包含任何属性：
[
    {{"name": "腾讯科技", "label": "公司"}},
    {{"name": "混元大模型", "label": "产品"}},
    {{"name": "某政务云采购项目", "label": "交易"}}
]

【文本】：
{text}
"""

# Step 2: 仲裁 (保持逻辑，增强对齐判定)
# Step 2: AI 仲裁 / 去重 (深度优化版)
# 对应你原来的 DEDUP 逻辑
PROMPT_ARBITRATE = """
你是一名知识图谱去重专家。请判断【对象A】和【对象B】在宏观产业图谱中是否应该被**合并**为同一个节点。

**请根据【类别】采用不同的判定策略：**

1.  **当类别是【环节】或【概念】时 -> 策略：激进合并 (Aggressive)**
    * ✅ **合并（修饰差异）**：如“AI技术”=“人工智能技术”、“算力建设”=“算力基础设施”。
    * ✅ **合并（包含关系）**：如果图谱不需要过细，将“智算中心建设”合并入“智算中心”。
    * ✅ **合并（场景=设备）**：如“智慧家庭”=“智能家居终端”。
    * ❌ **不合并**：完全不同的领域（如“自动驾驶” vs “智能医疗”）。

2.  **当类别是【公司】时 -> 策略：标准归一化**
    * ✅ **合并**：忽略后缀（“有限责任公司”、“集团”），忽略地域前缀（如果指代同一总公司）。
    * ✅ **合并**：全称与简称（“中兴” = “中兴通讯”）。
    * ❌ **不合并**：明显的母子公司区分（如果文本强调了特定子公司的独立行为），或完全不同的公司。

3.  **当类别是【产品】时 -> 策略：适度保守**
    * ✅ **合并**：别名（“文心一言” = “ERNIE Bot”）。
    * ❌ **不合并**：明显的代际差异（“GPT-3.5” vs “GPT-4” 应保留差异，除非是为了归类到“GPT系列”）。

**最终判定：**
如果两者核心语义相同，指代同一个现实世界实体或同一类业务概念，返回 `true`。

【类别】: {category}
【对象A】: {name_a}
【对象B】: {name_b}

【返回格式】:
JSON: {{"is_same": true}} 或 {{"is_same": false}}
"""


# Step 3A: 属性补全 (深度优化版)
# 对应你原来的 SYSTEM_PROMPT_STEP2_BASE
PROMPT_STEP3_ATTR = """
你是一名产业数据分析师。根据提供的【文本】和【待补全实体列表】，提取详细属性。

**核心填充原则（严格遵守）：**

1.  **事实优先与推断标注**：
    * 优先从文本中提取属性。
    * **常识补全**：仅允许对**静态事实**（如企业注册地、成立大致年份、所属行业）进行常识推断。
    * **强制标注**：凡是使用常识补全的字段，**必须**在值后面加上 `(推断)`。例如：`"注册地区": "北京(推断)"`。
    * ❌ **禁止推断动态数据**：严禁编造或推断“最新营收”、“投资金额”、“交易金额”等动态数值。如果文中没说，必须填 `"未明确"`。
2.  **【环节实体】清洗**：
    * 如果实体是“AI”、“未来”、“数字化”等宏观泛指词，不要填充属性，视为无效。

【待补全实体列表】:
{entity_list_json}

【Schema 定义】:
{schema_json}

【文本参考】:
{text}

【输出格式】:
JSON 列表，包含完整的 properties。请确保与输入列表中的实体一一对应。
示例：
[
    {{
        "公司名称": "腾讯科技", 
        "成立时间": "1998年(推断)", 
        "注册地区": "深圳(推断)", 
        "最新营收": "未明确" 
    }}
]
"""

# Step 3B: 关系抽取
# 融合了：原子性约束、环节颗粒度控制
PROMPT_STEP3_REL = """
你是一名知识图谱关系抽取工程师。
我将提供一段文本和一个【已知实体列表】（包含了ID和名称）。
请提取这些实体之间、或实体与【产业链环节】之间的关系。

**【核心约束】(必须遵守)：**

1. **环节颗粒度匹配**：
   - 如果实体涉及【产业链环节】，必须关联到字典中**最具体的细分环节**（Level 3）。
   - ❌ 禁止关联到宏观环节（如“上游基础层”），除非无法找到更细分的。

2. **关系原子性 (禁止合并)**：
   - 如果一家公司发布了 3 个产品，必须输出 **3 条独立的 "拥有产品" 关系**。
   - ❌ 严禁将多个产品名合并在一条关系中。

3. **证据确凿**：
   - 只有在文本中明确提到两个实体有交互（如供应、投资、从属）时才提取。

【环节字典参考】(请优先匹配这里面的三级环节):
{segment_context}

【已知实体列表】:
{nodes_context}

【允许的关系类型】:
"从属于", "参与环节", "产品对应环节", "拥有产品", "涉及环节", "投资方", "被投资方", "对应环节", "涉及企业", "采购方", "中标方"

【输出格式】：
JSON 列表: 
[
    {{"source": "腾讯", "target": "大模型训练", "type": "参与环节"}},
    {{"source": "腾讯", "target": "混元大模型", "type": "拥有产品"}}
]

【文本】：
{text}
"""
# (这里仅做示例占位，实际代码请确保这里有完整Prompt字符串)
if len(PROMPT_STEP1_NER) < 50: PROMPT_STEP1_NER = "{text}"
if len(PROMPT_ARBITRATE) < 50: PROMPT_ARBITRATE = "{name_a} {name_b}"
if len(PROMPT_STEP3_ATTR) < 50: PROMPT_STEP3_ATTR = "{text}"
if len(PROMPT_STEP3_REL) < 50: PROMPT_STEP3_REL = "{text}"


# ==================================================
# 4. 核心处理类 (UltimateExtractor)
# ==================================================

class UltimateExtractor:
    def __init__(self):
        self.llm = LLMClient()
        self.lock = threading.RLock()
        
        self.graph = {"nodes": [], "relationships": []}
        self.node_name_index = {} 
        self.label_name_cache = {lbl: [] for lbl in list(LABEL_MAPPING.values()) + ["环节"]}
        self.node_id_map = {}
        
        self.current_max_id = -1
        self.rel_max_id = 0
        self.segment_map = {}

        # 错误记录列表
        self.failed_batches = []
        
        # <<< 新增：断点状态管理 >>>
        self.processed_batch_ids = set()
        self._load_checkpoint()
        
        # 注册信号处理 (Ctrl+C 保存)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        self.initialize_graph()

    def _load_checkpoint(self):
        """<<< 新增 >>> 加载已完成的 Batch ID"""
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.processed_batch_ids = set(data)
                logger.info(f"🔄 发现断点记录：已完成 {len(self.processed_batch_ids)} 个批次")
            except Exception as e:
                logger.error(f"⚠️ 读取断点文件失败: {e}，将重新开始处理。")
        else:
            logger.info("🆕 未发现断点记录，准备全新开始。")

    def _save_checkpoint(self):
        """<<< 新增 >>> 保存当前完成进度"""
        try:
            temp_ckpt = CHECKPOINT_FILE + ".tmp"
            with open(temp_ckpt, 'w', encoding='utf-8') as f:
                json.dump(list(self.processed_batch_ids), f)
            if os.path.exists(CHECKPOINT_FILE):
                os.remove(CHECKPOINT_FILE)
            os.rename(temp_ckpt, CHECKPOINT_FILE)
        except Exception as e:
            logger.error(f"❌ 保存进度断点失败: {e}")

    def _signal_handler(self, sig, frame):
        logger.warning("\n🛑 接收到中断信号! 正在尝试紧急保存数据...")
        self.save_graph()     # 这也会保存 checkpoint
        self.save_failed_log()
        sys.exit(0)

    def initialize_graph(self):
        logger.info("⚙️ 初始化系统 (V3.2 With Resumable)...")
        if os.path.exists(OUTPUT_GRAPH_FILE):
            try:
                with open(OUTPUT_GRAPH_FILE, 'r', encoding='utf-8') as f:
                    self.graph = json.load(f)
                logger.info(f"   > 加载已有图谱: {len(self.graph['nodes'])} 节点")
            except Exception as e:
                logger.error(f"   > 加载图谱失败: {e}")
        
        if self.graph['nodes']:
            ids = [n['id'] for n in self.graph['nodes']]
            self.current_max_id = max(ids) if ids else -1
            rel_ids = [r.get('id', 0) for r in self.graph['relationships'] if isinstance(r.get('id'), int)]
            self.rel_max_id = max(rel_ids) if rel_ids else 0

            for node in self.graph['nodes']:
                nid = node['id']
                lbl = node['labels'][0]
                props = node['properties']
                name = props.get('name') or props.get('公司名称') or props.get('产品名称') or props.get('名称')
                self.node_id_map[nid] = node
                if name:
                    norm_name = normalize_name_v3(name, lbl)
                    self.node_name_index[f"{lbl}:{norm_name}"] = nid
                    if lbl in self.label_name_cache:
                        self.label_name_cache[lbl].append(name)
        
        self._build_segment_skeleton()

    def _build_segment_skeleton(self):
        logger.info("🏗️ 正在构建产业链骨架...")
        if not os.path.exists(INPUT_SEGMENT_MAPPING):
            logger.warning("⚠️ 找不到 segment_mapping_input.json，跳过骨架构建")
            return

        with open(INPUT_SEGMENT_MAPPING, 'r', encoding='utf-8') as f:
            self.segment_map = json.load(f)

        count_seg = 0
        for seg1_name, l2_dict in self.segment_map.items():
            s1_id = self._get_or_create_segment_node(seg1_name, "1")
            if isinstance(l2_dict, dict):
                for seg2_name, seg3_list in l2_dict.items():
                    s2_id = self._get_or_create_segment_node(seg2_name, "2")
                    self._create_relationship_if_not_exist(s2_id, s1_id, RELATION_TYPES["REL_SUBSEG"])
                    if isinstance(seg3_list, list):
                        for seg3_name in seg3_list:
                            s3_id = self._get_or_create_segment_node(seg3_name, "3")
                            self._create_relationship_if_not_exist(s3_id, s2_id, RELATION_TYPES["REL_SUBSEG"])
                            count_seg += 1
        logger.info(f"✅ 骨架构建完成。覆盖 {count_seg} 个细分环节。")

    def _get_or_create_segment_node(self, name, level):
        norm_name = normalize_name_v3(name, "环节")
        key = f"环节:{norm_name}"
        if key in self.node_name_index: return self.node_name_index[key]
        
        with self.lock:
            if key in self.node_name_index: return self.node_name_index[key]
            self.current_max_id += 1
            new_id = self.current_max_id
            node = {
                "id": new_id,
                "labels": ["环节"],
                "properties": {"name": name, "level": level}
            }
            self.graph["nodes"].append(node)
            self.node_id_map[new_id] = node
            self.node_name_index[key] = new_id
            self.label_name_cache["环节"].append(name)
            return new_id

    def _create_relationship_if_not_exist(self, src, tgt, rtype):
        for r in self.graph["relationships"]:
            if r["source"] == src and r["target"] == tgt and r["type"] == rtype:
                return
        self.rel_max_id += 1
        rel = {"id": 1000000000 + self.rel_max_id, "source": src, "target": tgt, "type": rtype}
        self.graph["relationships"].append(rel)

    # --- 增强的查询方法 ---
    @retry_with_backoff(max_retries=MAX_RETRIES, delay=RETRY_DELAY)
    def _safe_query_llm(self, prompt, **kwargs):
        """带自动重试的LLM调用"""
        return self.llm.query(prompt, **kwargs)

    def process_data(self):
        logger.info(f"🚀 开始处理数据: {INPUT_EXCEL_FILE}")
        if not os.path.exists(INPUT_EXCEL_FILE):
             logger.error("❌ 输入文件不存在")
             return

        try:
            df = pd.read_excel(INPUT_EXCEL_FILE)
        except Exception as e:
            logger.error(f"❌ 读取 Excel 失败: {e}")
            return
            
        df = df[df['正文'].notna() & (df['正文'].astype(str).str.len() > 5)]
        
        # --- 组包逻辑 ---
        # 注意：为了保证 Batch ID 的一致性，即使是断点续传，也必须重新生成完整的 batches 列表
        # 这样 ID 0 永远对应前 5000 字符。
        batches = []
        current_batch = []
        current_len = 0
        batch_counter = 0
        
        for _, row in df.iterrows():
            text = str(row['正文'])
            if current_len + len(text) > MAX_CHARS_PER_BATCH:
                batches.append({"id": batch_counter, "text": "\n\n--- ITEM ---\n\n".join(current_batch)})
                batch_counter += 1
                current_batch = [text]
                current_len = len(text)
            else:
                current_batch.append(text)
                current_len += len(text)
        if current_batch:
            batches.append({"id": batch_counter, "text": "\n\n--- ITEM ---\n\n".join(current_batch)})
            
        # --- <<< 核心修改：过滤掉已完成的 Batch >>> ---
        total_batches_count = len(batches)
        pending_batches = [b for b in batches if b['id'] not in self.processed_batch_ids]
        skipped_count = total_batches_count - len(pending_batches)
        
        logger.info(f"📦 数据总批次: {total_batches_count}")
        if skipped_count > 0:
            logger.info(f"⏭️  [断点续传] 已跳过 {skipped_count} 个已处理批次，剩余 {len(pending_batches)} 个待处理。")
        else:
            logger.info(f"🆕 全量处理模式")

        if not pending_batches:
            logger.info("✅ 所有任务已在之前的运行中完成！")
            return

        # --- Pipeline ---
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_PIPELINE) as executor:
            future_to_batch = {executor.submit(self._pipeline_process_safe, b): b['id'] for b in pending_batches}
            
            completed_in_this_run = 0
            
            # 进度条仅显示本次需要处理的
            with tqdm(total=len(pending_batches), desc="Processing", unit="batch") as pbar:
                for future in as_completed(future_to_batch):
                    batch_id = future_to_batch[future]
                    completed_in_this_run += 1
                    
                    try:
                        future.result() 
                        pbar.update(1)
                        
                        # 定期保存 (包括 Checkpoint)
                        if completed_in_this_run % SAVE_INTERVAL == 0:
                            self.save_graph()
                            
                    except Exception as e:
                        logger.error(f"Batch {batch_id} 主线程捕获异常: {e}")
        
        self.save_graph()
        self.save_failed_log()
        logger.info("✨ 所有任务处理完成。")

    def _pipeline_process_safe(self, batch_data):
        """异常捕获包装层"""
        batch_id = batch_data['id']
        text = batch_data['text']
        try:
            self._pipeline_process(text)
            
            # <<< 新增：成功后更新内存中的状态 >>>
            with self.lock:
                self.processed_batch_ids.add(batch_id)
                
        except Exception as e:
            err_msg = traceback.format_exc()
            logger.error(f"❌ Batch {batch_id} 处理失败，已跳过。错误: {str(e)}")
            with self.lock:
                self.failed_batches.append({
                    "batch_id": batch_id,
                    "error": str(e),
                    "traceback": err_msg,
                    "data_preview": text[:200]
                })

    def _pipeline_process(self, text):
        """核心业务逻辑 (使用 _safe_query_llm)"""
        
        # Step 1: NER
        # 使用 safe_query 替代直接 query
        res = self._safe_query_llm(PROMPT_STEP1_NER.format(text=text), temperature=0.0, max_tokens=4096)
        
        try:
            raw_entities = json.loads(clean_json_text(res))
        except:
            return 

        if not isinstance(raw_entities, list) or not raw_entities:
            return

        # Step 2: 去重 (Logic kept same)
        with self.lock:
            snapshot = {k: v.copy() for k, v in self.label_name_cache.items()}
        
        existing_map = {} 
        new_entities = [] 
        
        for ent in raw_entities:
            name = ent.get('name')
            label = ent.get('label')
            if not name or not label: continue
            
            norm = normalize_name_v3(name, label)
            key = f"{label}:{norm}"
            
            found_id = None
            with self.lock:
                if key in self.node_name_index:
                    found_id = self.node_name_index[key]
            
            if found_id:
                existing_map[name] = found_id
                continue
                
            candidates = snapshot.get(label, [])
            match_res = fuzz_process.extractOne(name, candidates, scorer=fuzz.ratio) if candidates else None
            
            is_dup = False
            tgt_name = None
            
            if match_res:
                best_name, score, _ = match_res
                if score > FUZZY_MATCH_HIGH:
                    is_dup = True
                    tgt_name = best_name
                elif score > FUZZY_MATCH_LOW:
                    if self._ai_arbitrate(label, name, best_name):
                        is_dup = True
                        tgt_name = best_name
            
            if is_dup and tgt_name:
                with self.lock:
                    tgt_key = f"{label}:{normalize_name_v3(tgt_name, label)}"
                    if tgt_key in self.node_name_index:
                        existing_map[name] = self.node_name_index[tgt_key]
                continue
            
            new_entities.append(ent)

        # Step 3: 占位
        final_new_nodes = []
        temp_new_ids = {} 
        
        with self.lock:
            for ent in new_entities:
                self.current_max_id += 1
                new_id = self.current_max_id
                lbl = ent['label']
                name = ent['name']
                
                norm = normalize_name_v3(name, lbl)
                self.node_name_index[f"{lbl}:{norm}"] = new_id
                self.label_name_cache[lbl].append(name)
                
                pk = get_primary_key(lbl)
                node = {
                    "id": new_id,
                    "labels": [lbl],
                    "properties": {pk: name} 
                }
                self.graph["nodes"].append(node)
                self.node_id_map[new_id] = node
                
                final_new_nodes.append(node)
                temp_new_ids[name] = new_id

        # Step 4: 并行补全
        full_map = {**existing_map, **temp_new_ids}
        nodes_ctx = [{"name": k, "id": v} for k, v in full_map.items()]
        seg_ctx = json.dumps(self.segment_map, ensure_ascii=False)
        if len(seg_ctx) > 3000: seg_ctx = seg_ctx[:3000] + "..."

        with ThreadPoolExecutor(max_workers=2) as sub_exec:
            f_attr = sub_exec.submit(self._extract_attrs, text, final_new_nodes)
            f_rel = sub_exec.submit(self._extract_rels, text, seg_ctx, nodes_ctx)
            
            attrs_res = f_attr.result()
            rels_res = f_rel.result()

        # Step 5: 写入
        with self.lock:
            for nid, props in attrs_res.items():
                if nid in self.node_id_map:
                    self.node_id_map[nid]["properties"].update(props)
            
            for rel in rels_res:
                if rel['source'] in self.node_id_map and rel['target'] in self.node_id_map:
                     self._create_relationship_if_not_exist(rel['source'], rel['target'], rel['type'])
        time.sleep(0.1) 
        pass 

    def _extract_attrs(self, text, nodes):
        if not nodes: return {}
        e_list = [{"name": n['properties'].get(get_primary_key(n['labels'][0])), "label": n['labels'][0]} for n in nodes]
        prompt = PROMPT_STEP3_ATTR.format(
            entity_list_json=json.dumps(e_list, ensure_ascii=False),
            schema_json=json.dumps(ENTITY_SCHEMA, ensure_ascii=False),
            text=text
        )
        # 使用 safe_query
        res = self._safe_query_llm(prompt, temperature=0.1, max_tokens=4096)
        
        ret_map = {}
        try:
            data = json.loads(clean_json_text(res))
            if isinstance(data, list):
                for item in data:
                    name = item.get("公司名称") or item.get("产品名称") or item.get("name")
                    for n in nodes:
                        n_name = n['properties'].get(get_primary_key(n['labels'][0]))
                        if n_name == name:
                            ret_map[n['id']] = item
                            break
        except: pass
        return ret_map

    def _extract_rels(self, text, seg_ctx, nodes_ctx):
        prompt = PROMPT_STEP3_REL.format(
            segment_context=seg_ctx,
            nodes_context=json.dumps(nodes_ctx, ensure_ascii=False),
            text=text
        )
        # 使用 safe_query
        res = self._safe_query_llm(prompt, temperature=0.0, max_tokens=4096)
        
        rels = []
        try:
            data = json.loads(clean_json_text(res))
            if isinstance(data, list):
                for item in data:
                    s_name = item.get("source")
                    t_name = item.get("target")
                    rtype = item.get("type")
                    
                    sid = None
                    for n in nodes_ctx:
                        if n['name'] == s_name: 
                            sid = n['id']
                            break
                    
                    tid = None
                    for n in nodes_ctx:
                        if n['name'] == t_name:
                            tid = n['id']
                            break
                    if tid is None:
                        t_key = f"环节:{normalize_name_v3(t_name, '环节')}"
                        with self.lock:
                            if t_key in self.node_name_index:
                                tid = self.node_name_index[t_key]
                    
                    if sid is not None and tid is not None:
                        rels.append({"source": sid, "target": tid, "type": rtype})
        except: pass
        return rels

    def _ai_arbitrate(self, cat, n_a, n_b):
        try:
            prompt = PROMPT_ARBITRATE.format(category=cat, name_a=n_a, name_b=n_b)
            # 仲裁也使用重试，但减少tokens
            res = self._safe_query_llm(prompt, temperature=0.0, max_tokens=512)
            d = json.loads(clean_json_text(res))
            return d.get("is_same", False)
        except: return False

    def save_graph(self):
        """
        线程安全的保存方法：
        1. 获取锁，快速创建内存快照 (Deep Copy 消耗太大，这里用 List Shallow Copy 即可)
        2. 释放锁，让后台线程继续跑
        3. 将快照写入硬盘
        """
        temp_file = OUTPUT_GRAPH_FILE + ".tmp"
        
        # --- 关键修改：加锁并创建快照 ---
        # 这一步非常快，只会阻塞处理线程几毫秒
        with self.lock:
            graph_snapshot = {
                "nodes": list(self.graph["nodes"]), 
                "relationships": list(self.graph["relationships"])
            }
            node_count = len(graph_snapshot["nodes"])
            rel_count = len(graph_snapshot["relationships"])
            # 顺便获取锁的时候，把 checkpoint 也存了
            self._save_checkpoint() 
        # -------------------------------

        # 此时锁已释放，后台线程可以继续处理数据，我们在主线程慢慢写文件
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(graph_snapshot, f, ensure_ascii=False, indent=2)
            
            # 原子替换：防止写入一半断电导致文件损坏
            if os.path.exists(OUTPUT_GRAPH_FILE):
                os.remove(OUTPUT_GRAPH_FILE)
            os.rename(temp_file, OUTPUT_GRAPH_FILE)
            
            # (可选) 如果不想刷屏，可以将 logger.info 改为 debug
            # logger.info(f"💾 [实时保存] 已更新图谱 (Nodes: {node_count}, Rels: {rel_count})")
        except Exception as e:
            logger.error(f"❌ 保存文件时发生致命错误: {e}")

    def save_failed_log(self):
        """保存失败的记录到单独文件"""
        if self.failed_batches:
            logger.warning(f"⚠️ 有 {len(self.failed_batches)} 个Batch处理失败，详情写入 {FAILED_LOG_FILE}")
            try:
                # 追加模式或重写模式，视需求而定，这里用重写方便查最新
                with open(FAILED_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.failed_batches, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"❌ 写入失败日志出错: {e}")

if __name__ == "__main__":
    extractor = UltimateExtractor()
    extractor.process_data()

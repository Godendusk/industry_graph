import json
import os
import time
import pandas as pd
import re
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- 高性能模糊匹配库 ---
try:
    from rapidfuzz import process as fuzz_process
    from rapidfuzz import fuzz
except ImportError:
    print("❌ 请先安装 rapidfuzz: pip install rapidfuzz")
    exit()

# --- 导入你的 LLM 客户端 ---
from llm_client import LLMClient

# ==================================================
# 1. 全局配置与常量 (保留原始 Prompt)
# ==================================================

# 路径将由 run_import 传入
INPUT_EXCEL_FILE = "uploads/new_data_upload.xlsx"
GRAPH_FILE = "static/data/graph_data.json"
LOG_FILE = "processing_log_v3.json"

# --- 性能配置 ---
MAX_WORKERS_PIPELINE = 10     # 并发 Batch 数
MAX_CHARS_PER_BATCH = 10000   # 动态 Batch 字符限制 (约 5k tokens)

# --- 去重阈值 ---
FUZZY_MATCH_HIGH = 85.0
FUZZY_MATCH_LOW = 60.0

# --- 实体与关系定义 (保持原版) ---
ENTITY_SCHEMA = {
    "企业实体": ["公司名称", "正式名称", "成立时间", "注册地区", "国内外", "注册资本（万元）", "最新市值", "最新营收", "最新研发投入", "企业介绍"],
    "产品实体": ["产品名称", "所属企业", "所属环节", "国内外", "发布时间", "状态", "产品介绍"],
    "投资实体": ["投资事件标题", "投资发生地点", "环节", "采购发生时间", "投资金额万元", "投资状态", "投资方名称", "被投企业名称"],
    "交易实体": ["采购标题", "采购省份", "采购内容描述", "采购发生的时间", "采购金额万元", "采购方名称", "中标方名称", "对应的AI产业环节"],
    "舆情实体": ["事件标题", "发生地点", "事件内容 ", "时间", "涉及企业", "对应产业环节"]
}

RELATION_TYPES = {
    "REL_SUBSEG": "从属于",       # (环节3) -> (环节2)
    "REL_OPERATES": "参与环节",   # (公司) -> (环节3)
    "REL_ALIGNS": "产品对应环节", # (产品) -> (环节3)
    "REL_OWNS": "拥有产品",       # (公司) -> (产品)
    "REL_INVEST_SEG": "涉及环节", # (投资) -> (环节3)
    "REL_INVEST_FROM": "投资方",  # (投资) -> (公司)
    "REL_INVEST_TO": "被投资方",  # (投资) -> (公司)
    "REL_OPINION_SEG": "对应环节",# (舆情) -> (环节3)
    "REL_OPINION_COMP": "涉及企业",# (舆情) -> (公司)
    "REL_TRADE_SEG": "涉及环节",  # (交易) -> (环节3)
    "REL_TRADE_BUYER": "采购方",  # (交易) -> (公司)
    "REL_TRADE_SELLER": "中标方"  # (交易) -> (公司)
}

LABEL_MAPPING = {
    "企业实体": "公司", "产品实体": "产品", "投资实体": "投资",
    "交易实体": "交易", "舆情实体": "舆情"
}

# ==================================================
# 2. Prompt 定义 (保持原文)
# ==================================================

# Step 1: NER (实体识别)
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
    {"name": "腾讯科技", "label": "公司"},
    {"name": "混元大模型", "label": "产品"},
    {"name": "某政务云采购项目", "label": "交易"}
]

【文本】：
{text}
"""

# Step 2: 仲裁 / 去重
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
JSON: {"is_same": true} 或 {"is_same": false}
"""

# Step 3A: 属性补全
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
    {
        "公司名称": "腾讯科技", 
        "成立时间": "1998年(推断)", 
        "注册地区": "深圳(推断)", 
        "最新营收": "未明确" 
    }
]
"""

# Step 3B: 关系抽取
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

【输出格式】:
JSON 列表: 
[
    {"source": "腾讯", "target": "大模型训练", "type": "参与环节"},
    {"source": "腾讯", "target": "混元大模型", "type": "拥有产品"}
]

【文本】:
{text}
"""

# ==================================================
# 3. 辅助函数
# ==================================================

def normalize_name_v3(name, label=""):
    """V2 原版名称清洗规则"""
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


def fill_prompt(template: str, **values) -> str:
    """
    安全填充 Prompt：只替换 `{key}` 占位符，不使用 str.format()，
    以避免 Prompt 内示例 JSON 的 `{}` 被当成 format 占位符导致 KeyError。
    """
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def get_primary_key(label):
    if label == "公司": return "公司名称"
    if label == "产品": return "产品名称"
    return "name"


# ==================================================
# 4. 核心处理类 (Ultimate Fusion)
# ==================================================

class UltimateExtractor:
    def __init__(self, graph_path: Path, excel_path: Path, preview_only: bool = True):
        self.llm = LLMClient()
        self.lock = threading.RLock()

        self.graph_path = graph_path
        self.excel_path = excel_path
        self.preview_only = preview_only

        # 图谱数据
        self.graph = {"nodes": [], "relationships": []}

        # 索引
        self.node_name_index = {}
        self.label_name_cache = {lbl: [] for lbl in list(LABEL_MAPPING.values()) + ["环节"]}
        self.node_id_map = {}

        self.current_max_id = -1
        self.rel_max_id = 0

        # 环节字典
        self.segment_map = {}

        # 预览模式候选结构（供前端勾选）
        self.candidate_nodes = []
        self.candidate_links = []
        self._temp_index = {}  # label:name -> temp_id
        self.base_nodes_len = 0
        self.base_rels_len = 0

        self.initialize_graph()

    def initialize_graph(self):
        print("⚙️ 初始化系统 (合并入图)...")
        # 1. 加载已有图谱
        if self.graph_path.exists():
            try:
                with open(self.graph_path, 'r', encoding='utf-8') as f:
                    self.graph = json.load(f)
                print(f"   > 加载已有图谱: {len(self.graph.get('nodes', []))} 节点")
            except Exception as e:
                print(f"   > 加载图谱失败: {e}")

        # 2. 重建索引
        if self.graph.get('nodes'):
            ids = [n['id'] for n in self.graph['nodes'] if 'id' in n]
            if ids:
                try:
                    self.current_max_id = max(int(x) for x in ids if isinstance(x, (int, str)))
                except Exception:
                    self.current_max_id = max(self.current_max_id, len(ids))
            rel_ids = [r.get('id', 0) for r in self.graph.get('relationships', []) if isinstance(r.get('id'), int)]
            self.rel_max_id = max(rel_ids) if rel_ids else 0

            for node in self.graph['nodes']:
                nid = node.get('id')
                labels = node.get('labels', [])
                props = node.get('properties', {})
                name = props.get('name') or props.get('公司名称') or props.get('产品名称') or props.get('名称')
                self.node_id_map[nid] = node
                if labels and name:
                    lbl = labels[0]
                    norm_name = normalize_name_v3(name, lbl)
                    self.node_name_index[f"{lbl}:{norm_name}"] = nid
                    if lbl in self.label_name_cache:
                        self.label_name_cache[lbl].append(name)

        # 3. 构建环节骨架：从现有图谱抽取 L1/L2/L3 和从属关系
        self._build_segment_skeleton_from_graph()

        # 4. 记录基线长度（用于预览 delta）
        self.base_nodes_len = len(self.graph.get("nodes", []))
        self.base_rels_len = len(self.graph.get("relationships", []))

    def _build_segment_skeleton_from_graph(self):
        print("🏗️ 从图谱抽取产业链骨架...")
        nodes = self.graph.get("nodes", [])
        links = self.graph.get("relationships", [])
        id_to_level = {}
        id_to_name = {}
        for n in nodes:
            if "环节" in n.get("labels", []):
                props = n.get("properties", {}) or {}
                lvl = str(props.get("level") or "").strip()
                id_to_level[n.get("id")] = lvl
                id_to_name[n.get("id")] = props.get("name") or props.get("AI产业环节")

        l1_children = {}
        l2_children = {}
        for rel in links:
            if rel.get("type") != RELATION_TYPES["REL_SUBSEG"]:
                continue
            child = rel.get("source")
            parent = rel.get("target")
            c_lvl = id_to_level.get(child)
            p_lvl = id_to_level.get(parent)
            if c_lvl == "2" and p_lvl == "1":
                l1_children.setdefault(parent, set()).add(child)
            if c_lvl == "3" and p_lvl == "2":
                l2_children.setdefault(parent, set()).add(child)

        segment_map = {}
        for l1_id, l2_set in l1_children.items():
            l1_name = id_to_name.get(l1_id)
            if not l1_name:
                continue
            segment_map.setdefault(l1_name, {})
            for l2_id in l2_set:
                l2_name = id_to_name.get(l2_id)
                if not l2_name:
                    continue
                l3_list = []
                for l3_id in l2_children.get(l2_id, []):
                    l3_name = id_to_name.get(l3_id)
                    if l3_name:
                        l3_list.append(l3_name)
                segment_map[l1_name][l2_name] = l3_list
        self.segment_map = segment_map
        print(f"✅ 骨架抽取完成：L1 {len(segment_map)}")

    def _ensure_temp_node(self, label, name, props=None):
        if not label or not name:
            return None
        key = f"{label}:{name}"
        if key in self._temp_index:
            temp_id = self._temp_index[key]
            if props:
                for n in self.candidate_nodes:
                    if n.get("temp_id") == temp_id:
                        n_props = n.get("properties", {}) or {}
                        n_props.update({k: v for k, v in (props or {}).items() if v is not None})
                        n["properties"] = n_props
                        break
            return temp_id

        temp_id = f"tmp_{len(self._temp_index) + 1}"
        self._temp_index[key] = temp_id
        self.candidate_nodes.append(
            {
                "temp_id": temp_id,
                "labels": [label],
                "properties": {"name": name, **(props or {})},
            }
        )
        return temp_id

    def build_candidates_from_delta(self):
        self.candidate_nodes = []
        self.candidate_links = []
        self._temp_index = {}

        nodes_all = self.graph.get("nodes", []) or []
        rels_all = self.graph.get("relationships", []) or []
        new_nodes = nodes_all[self.base_nodes_len :]
        new_rels = rels_all[self.base_rels_len :]

        def label_name_props(node):
            labels = node.get("labels", []) or []
            label = labels[0] if labels else ""
            props = node.get("properties", {}) or {}
            name = (
                props.get("name")
                or props.get("公司名称")
                or props.get("产品名称")
                or props.get("名称")
                or props.get("AI产业环节")
            )
            props2 = dict(props)
            if name and "name" not in props2:
                props2["name"] = name
            return label, name, props2

        id_to_temp = {}

        # 1) 新关系两端都入候选（即使是已存在节点，commit 也能映射）
        for rel in new_rels:
            for endpoint in ("source", "target"):
                node_id = rel.get(endpoint)
                if node_id in id_to_temp:
                    continue
                node_obj = self.node_id_map.get(node_id)
                if not node_obj:
                    continue
                lbl, nm, pr = label_name_props(node_obj)
                tmp = self._ensure_temp_node(lbl, nm, pr)
                if tmp:
                    id_to_temp[node_id] = tmp

        # 2) 新节点补齐（可能没有关系）
        for node_obj in new_nodes:
            node_id = node_obj.get("id")
            if node_id in id_to_temp:
                continue
            lbl, nm, pr = label_name_props(node_obj)
            tmp = self._ensure_temp_node(lbl, nm, pr)
            if tmp:
                id_to_temp[node_id] = tmp

        # 3) 候选关系（用 temp_id）
        for idx, rel in enumerate(new_rels, start=1):
            src_tmp = id_to_temp.get(rel.get("source"))
            tgt_tmp = id_to_temp.get(rel.get("target"))
            if not src_tmp or not tgt_tmp:
                continue
            self.candidate_links.append(
                {
                    "temp_id": f"link_{idx}",
                    "source": src_tmp,
                    "target": tgt_tmp,
                    "type": rel.get("type") or "关联",
                    "properties": rel.get("properties") or {},
                }
            )

        return {
            "nodes": self.candidate_nodes,
            "links": self.candidate_links,
            "summary": {"new_nodes": len(new_nodes), "new_relationships": len(new_rels)},
        }

    # ==================================================
    # 5. 动态 Batch 流程
    # ==================================================
    def process_data(self):
        print(f"🚀 开始处理数据: {self.excel_path}")
        df = pd.read_excel(self.excel_path)
        df = df[df['正文'].notna() & (df['正文'].astype(str).str.len() > 5)]

        batches = []
        current_batch = []
        current_len = 0

        for _, row in df.iterrows():
            text = str(row['正文'])
            if current_len + len(text) > MAX_CHARS_PER_BATCH:
                batches.append("\n\n--- ITEM ---\n\n".join(current_batch))
                current_batch = [text]
                current_len = len(text)
            else:
                current_batch.append(text)
                current_len += len(text)
        if current_batch:
            batches.append("\n\n--- ITEM ---\n\n".join(current_batch))

        print(f"📦 数据已重组为 {len(batches)} 个 Batch。启动 Pipeline...")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS_PIPELINE) as executor:
            futures = [executor.submit(self._pipeline_process, b_txt) for b_txt in batches]
            for future in as_completed(futures):
                try:
                    future.result()
                    print("   ✅ Batch 完成")
                except Exception as e:
                    print(f"   ❌ Batch 异常: {e}")
                    traceback.print_exc()

        if self.preview_only:
            self.build_candidates_from_delta()
        else:
            self.save_graph()

    def _pipeline_process(self, text):
        # Step 1: NER
        res = self.llm.query(fill_prompt(PROMPT_STEP1_NER, text=text), temperature=0.0, max_tokens=4096)
        try:
            raw_entities = json.loads(clean_json_text(res))
        except Exception:
            return
        if not isinstance(raw_entities, list) or not raw_entities:
            return

        # Step 2: 去重 (Hybrid)
        with self.lock:
            snapshot = {k: v.copy() for k, v in self.label_name_cache.items()}

        existing_map = {}  # name -> id
        new_entities = []

        for ent in raw_entities:
            name = ent.get('name')
            label = ent.get('label')
            if not name or not label:
                continue

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

        # Step 3: 创建新节点
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
                self.graph.setdefault("nodes", []).append(node)
                self.node_id_map[new_id] = node

                final_new_nodes.append(node)
                temp_new_ids[name] = new_id

        # Step 4: 属性 + 关系
        full_map = {**existing_map, **temp_new_ids}
        nodes_ctx = [{"name": k, "id": v} for k, v in full_map.items()]
        seg_ctx = json.dumps(self.segment_map, ensure_ascii=False)
        if len(seg_ctx) > 3000:
            seg_ctx = seg_ctx[:3000] + "...(truncated)"

        with ThreadPoolExecutor(max_workers=2) as sub_exec:
            f_attr = sub_exec.submit(self._extract_attrs, text, final_new_nodes)
            f_rel = sub_exec.submit(self._extract_rels, text, seg_ctx, nodes_ctx)
            attrs_res = f_attr.result()
            rels_res = f_rel.result()

        with self.lock:
            for nid, props in attrs_res.items():
                if nid in self.node_id_map:
                    self.node_id_map[nid]["properties"].update(props)

            for rel in rels_res:
                if rel['source'] in self.node_id_map and rel['target'] in self.node_id_map:
                    self._create_relationship_if_not_exist(rel['source'], rel['target'], rel['type'])

    def _extract_attrs(self, text, nodes):
        if not nodes:
            return {}
        e_list = [{"name": n['properties'].get(get_primary_key(n['labels'][0])), "label": n['labels'][0]} for n in nodes]
        prompt = fill_prompt(
            PROMPT_STEP3_ATTR,
            entity_list_json=json.dumps(e_list, ensure_ascii=False),
            schema_json=json.dumps(ENTITY_SCHEMA, ensure_ascii=False),
            text=text,
        )
        res = self.llm.query(prompt, temperature=0.1, max_tokens=4096)

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
        except Exception:
            pass
        return ret_map

    def _extract_rels(self, text, seg_ctx, nodes_ctx):
        prompt = fill_prompt(
            PROMPT_STEP3_REL,
            segment_context=seg_ctx,
            nodes_context=json.dumps(nodes_ctx, ensure_ascii=False),
            text=text,
        )
        res = self.llm.query(prompt, temperature=0.0, max_tokens=4096)

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
        except Exception:
            pass
        return rels

    def _ai_arbitrate(self, cat, n_a, n_b):
        try:
            prompt = fill_prompt(PROMPT_ARBITRATE, category=cat, name_a=n_a, name_b=n_b)
            res = self.llm.query(prompt, temperature=0.0, max_tokens=512)
            d = json.loads(clean_json_text(res))
            return d.get("is_same", False)
        except Exception:
            return False

    def _create_relationship_if_not_exist(self, src, tgt, rtype):
        for r in self.graph.get("relationships", []):
            if r["source"] == src and r["target"] == tgt and r["type"] == rtype:
                return
        self.rel_max_id += 1
        rel = {
            "id": 1000000000 + self.rel_max_id,
            "source": src,
            "target": tgt,
            "type": rtype
        }
        self.graph.setdefault("relationships", []).append(rel)

    def save_graph(self):
        print(f"💾 保存图谱... 节点: {len(self.graph['nodes'])} / 关系: {len(self.graph['relationships'])}")
        with open(self.graph_path, 'w', encoding='utf-8') as f:
            json.dump(self.graph, f, ensure_ascii=False, indent=2)


def run_import(input_path: str, master_path: str, log_path: str | None = None):
    """
    两步流程（上传预览 -> 前端勾选 -> commit 合并）：
    - upload 阶段调用本函数，返回 candidates（temp_id 节点/关系）供前端预览勾选
    - commit 阶段由 backend 根据 candidates + 勾选结果写入 graph_data.json
    """
    excel_path = Path(input_path)
    g_path = Path(master_path)

    extractor = UltimateExtractor(g_path, excel_path, preview_only=True)
    extractor.process_data()

    nodes_all = extractor.graph.get("nodes", []) or []
    rels_all = extractor.graph.get("relationships", []) or []
    new_nodes = nodes_all[extractor.base_nodes_len :]
    new_rels = rels_all[extractor.base_rels_len :]

    new_items = {
        "summary": {
            "new_nodes": len(new_nodes),
            "new_relationships": len(new_rels),
        }
    }

    candidates = {
        "nodes": extractor.candidate_nodes,
        "links": extractor.candidate_links,
    }

    log_file = log_path or LOG_FILE
    if log_path:
        try:
            Path(log_path).write_text(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "input_path": str(excel_path),
                        "master_path": str(g_path),
                        "new_items": new_items,
                        "candidate_nodes": len(candidates.get("nodes", [])),
                        "candidate_links": len(candidates.get("links", [])),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    # 兼容 backend_server.py 旧写法：master_db, new_items, candidates, log_file
    return extractor.graph, new_items, candidates, str(log_file)


if __name__ == "__main__":
    run_import(INPUT_EXCEL_FILE, GRAPH_FILE, None)

# -*- coding: utf-8 -*-
"""
RAG 构建与查询脚本（精简版）
- doc/docx 语料向量化
- 查询时融合知识图谱
- 大模型回答输出为 Markdown + 简单 HTML 预览
"""
import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any

from tqdm import tqdm
from sentence_transformers import SentenceTransformer
import chromadb
from docx import Document
import torch

from llm_client import llm

# ============ 路径与配置 ============
BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "raw_docx_files"      # 知识库目录（仅含 doc/docx）
DB_DIR = BASE_DIR / "vector_db"                  # Chroma 数据库存放目录
PROGRESS_FILE = BASE_DIR / "progress.json"       # 已处理文件记录
GRAPH_FILE = BASE_DIR.parent / "static" / "data" / "ai" / "graph_data.json"
MODEL_PATH = BASE_DIR / "models"                 # 本地向量模型路径
OUTPUT_MD = BASE_DIR / "output.md"
OUTPUT_HTML = BASE_DIR / "output.html"

CHUNK_MIN_LEN = 10
TOP_K = 5
BATCH_SIZE = 128
CONTEXT_WINDOW = 5



# ===== 检查 GPU =====
def check_gpu():
    return torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")


DEVICE = check_gpu()


# ===== 句子切分 =====
def split_into_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text)
    sents = re.split(r'(?<=[。！？!?])\s*', text)
    return [s.strip() for s in sents if len(s.strip()) > CHUNK_MIN_LEN]


# ===== 读取 docx / doc =====
def extract_docx_text(path: Path) -> str:
    try:
        doc = Document(path)
        return "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        print(f"⚠️ 无法读取 DOCX：{path}，错误：{e}")
        return ""


def extract_doc_text(path: Path) -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["antiword", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            print(f"⚠️ antiword 处理失败：{result.stderr}")
            return ""
        return result.stdout.strip()
    except Exception as e:
        print(f"⚠️ 无法读取 DOC：{path}，错误：{e}")
        return ""


def get_full_file_text(file_path: Path) -> str:
    if str(file_path).lower().endswith(".docx"):
        return extract_docx_text(file_path)
    if str(file_path).lower().endswith(".doc"):
        return extract_doc_text(file_path)
    return ""


# ===== 进度文件 =====
def load_progress() -> Dict[str, Any]:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {}


def save_progress(progress: Dict[str, Any]):
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


# ===== 知识图谱处理 =====
class KnowledgeGraphHandler:
    def __init__(self, json_path: Path):
        self.nodes = {}
        self.relationships = []
        self.adj_list = {}
        self.load_graph(json_path)

    def load_graph(self, path: Path):
        if not path.exists():
            print(f"⚠️ 知识图谱文件不存在：{path}")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                self.nodes[node["id"]] = node
            for rel in data.get("relationships", []):
                self.relationships.append(rel)
                src, tgt = rel["source"], rel["target"]
                self.adj_list.setdefault(src, []).append(rel)
                self.adj_list.setdefault(tgt, []).append(rel)
            print(f"📈 知识图谱已加载：{len(self.nodes)} 个节点 {len(self.relationships)} 条关系")
        except Exception as e:
            print(f"❌ 知识图谱加载失败：{e}")

    def _is_relevant_node(self, node_name: str, query: str) -> bool:
        if not node_name:
            return False
        n_name = node_name.lower().strip()
        n_query = query.lower().strip()
        if n_name in n_query:
            return True
        if n_query in n_name and len(n_query) > 1:
            return True
        node_chars = set(n_name)
        if not node_chars:
            return False
        coverage = len(node_chars & set(n_query)) / len(node_chars)
        return coverage >= (1.0 if len(n_name) <= 4 else 0.75)

    def search_relevant_subgraph(self, query: str) -> str:
        matched_ids = [
            nid for nid, node in self.nodes.items()
            if self._is_relevant_node((node.get("properties") or {}).get("name", ""), query)
        ]
        if not matched_ids:
            return "【知识图谱】未在图谱中找到与查询明显相关的实体节点。\n"

        MAX_NODES = 10
        results = []
        for nid in matched_ids[:MAX_NODES]:
            node = self.nodes[nid]
            props = node.get("properties", {}) or {}
            node_name = props.get("name", "未知节点")
            labels = ",".join(node.get("labels", []))
            props_str = ", ".join([f"{k}:{v}" for k, v in props.items() if k != "name" and v not in ("未明确", "")])
            desc = f"实体: {node_name} (类型: {labels})"
            if props_str:
                desc += f", 属性: [{props_str}]"

            rels_desc = []
            for rel in self.adj_list.get(nid, []):
                is_src = rel["source"] == nid
                tid = rel["target"] if is_src else rel["source"]
                t_node = self.nodes.get(tid)
                if t_node:
                    t_name = t_node.get("properties", {}).get("name", "未知")
                    rel_type = rel.get("type", "关联")
                    rels_desc.append(f"{'-->' if is_src else '<--'}[{rel_type}]{t_name}")
            if rels_desc:
                desc += "\n    关联: " + "; ".join(rels_desc)
            results.append(desc)

        return "【知识图谱检索结果】\n" + "\n\n".join(results) + "\n"


# ===== 构建向量数据库 =====
def build_vector_db(industry: str = None):
    model = SentenceTransformer(str(MODEL_PATH), device=DEVICE)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    
    # 根据产业选择集合名称
    collection_name = "knowledge_base"
    if industry:
        collection_name = f"knowledge_base_{industry}"
    
    collection = client.get_or_create_collection(name=collection_name)
    progress = load_progress()

    # 根据产业选择知识库目录
    knowledge_dir = KNOWLEDGE_DIR
    if industry:
        industry_dir = KNOWLEDGE_DIR / industry
        if industry_dir.exists():
            knowledge_dir = industry_dir
            print(f"📁 使用产业特定知识库目录: {industry_dir}")
        else:
            print(f"⚠️ 产业 {industry} 的知识库目录不存在，使用默认目录")

    all_files = []
    for root, _, files in os.walk(knowledge_dir):
        for f in files:
            if f.lower().endswith((".doc", ".docx")):
                all_files.append(Path(root) / f)

    unique_files = {}
    for p in all_files:
        name = p.name
        if name not in unique_files:
            unique_files[name] = p
        else:
            print(f"⚠️ 检测到重复文件名：{name}，已跳过 {p}")

    file_list = list(unique_files.keys())
    print(f"📚 检测到 {len(file_list)} 个唯一文件（仅 doc/docx，去重后）")

    for file_name in tqdm(file_list, desc="Processing files"):
        if progress.get(file_name, False):
            print(f"⏩ 跳过已处理：{file_name}")
            continue
        file_path = unique_files[file_name]
        text = get_full_file_text(file_path)
        sents = split_into_sentences(text)
        if not sents:
            print(f"⚠️ 文件为空或无有效句子：{file_name}")
            progress[file_name] = True
            save_progress(progress)
            continue

        all_chunks = sents
        metadatas = [{"file_name": file_name, "sentence_index": i} for i in range(len(sents))]
        ids = [f"{file_name}_sent_{i}" for i in range(len(sents))]

        embeddings = model.encode(all_chunks, show_progress_bar=True, batch_size=BATCH_SIZE, device=DEVICE)
        collection.add(
            ids=ids,
            documents=all_chunks,
            metadatas=metadatas,
            embeddings=embeddings.tolist()
        )
        progress[file_name] = True
        save_progress(progress)

    print(f"✅ 向量化完成，数据库已保存到：{DB_DIR.resolve()}，集合：{collection_name}")

# ===== 查询 =====
def query_vector_db(query: str, top_k=TOP_K, industry: str = None) -> str:
    model = SentenceTransformer(str(MODEL_PATH), device=DEVICE)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    
    # 根据产业选择集合名称
    collection_name = "knowledge_base"
    # 目前只有一个集合，所以直接使用默认集合
    # if industry:
    #     collection_name = f"knowledge_base_{industry}"
    
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        # 如果产业特定的集合不存在，使用默认集合
        print(f"⚠️ 产业 {industry} 的向量数据库集合不存在，使用默认集合")
        collection = client.get_collection("knowledge_base")

    # 根据产业选择图谱文件
    if industry == "ai":
        graph_file = BASE_DIR.parent / "static" / "data" / "ai" / "graph_data.json"
    elif industry == "embodied":
        graph_file = BASE_DIR.parent / "static" / "data" / "embodied" / "graph_data.json"
    elif industry == "low_altitude":
        graph_file = BASE_DIR.parent / "static" / "data" / "low_altitude" / "graph_data.json"
    elif industry == "sea":
        graph_file = BASE_DIR.parent / "static" / "data" / "sea" / "graph_data.json"
    elif industry == "quantum":
        graph_file = BASE_DIR.parent / "static" / "data" / "quantum" / "graph_data.json"
    elif industry == "biology":
        graph_file = BASE_DIR.parent / "static" / "data" / "biology" / "graph_data.json"
    elif industry == "brain":
        graph_file = BASE_DIR.parent / "static" / "data" / "brain" / "graph_data.json"
    elif industry == "material":
        graph_file = BASE_DIR.parent / "static" / "data" / "material" / "graph_data.json"
    else:
        graph_file = GRAPH_FILE

    kg_handler = KnowledgeGraphHandler(graph_file)
    graph_context = kg_handler.search_relevant_subgraph(query)

    q_emb = model.encode([query], device=DEVICE)[0]
    results = collection.query(query_embeddings=[q_emb], n_results=top_k * 5)

    unique_results = []
    seen_ids = set()
    if results.get("documents"):
        for doc, meta, score, idx in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
                results["ids"][0]):
            if idx not in seen_ids:
                seen_ids.add(idx)
                unique_results.append({"document": doc, "metadata": meta, "score": score, "id": idx})
            if len(unique_results) >= top_k:
                break

    context_list = []
    for i, result in enumerate(unique_results, 1):
        meta = result["metadata"]
        file_path = KNOWLEDGE_DIR / meta["file_name"]
        sent_idx = meta["sentence_index"]
        full_text = get_full_file_text(file_path)
        if not full_text:
            continue
        sents = split_into_sentences(full_text)
        start = max(0, sent_idx - CONTEXT_WINDOW)
        end = min(len(sents), sent_idx + CONTEXT_WINDOW + 1)

        context_str = []
        for pos, sent in enumerate(sents[start:end], start=start):
            mark = "▶ " if pos == sent_idx else ""
            context_str.append(f"{mark}[{pos}] {sent}")
        context_list.append(
            f"【文档片段{i}（来自 {meta['file_name']}）】\n" +
            " ".join(context_str) + "\n"
        )

    system_prompt = """你是一名产业分析助手。请结合【文档知识库】和【知识图谱数据】回答用户问题：
1. 优先使用知识图谱中的实体关系梳理结构与关联。
2. 使用文档片段补充事实与细节。
3. 若二者冲突，请在回答中指出。
4. 结构化输出，条理清晰。"""

    final_context = (
        f"{graph_context}\n"
        f"========================\n"
        f"【文档检索结果】\n"
        f"{''.join(context_list)}"
    )
    user_prompt = f"用户的问题是：{query}\n\n以下是检索到的参考信息：\n{final_context}"

    # --- 大模型调用 ---
    try:
        content = llm.query(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0,
            max_tokens=3000,
        )
        return content or ""
    except Exception as e:
        print(f"\n❌大模型调用失败：{e}")
        return ""

def query_graph(query: str, industry: str = None) -> str:
    # 根据产业选择图谱文件
    if industry == "ai":
        graph_file = BASE_DIR.parent / "static" / "data" / "ai" / "graph_data.json"
    elif industry == "embodied":
        graph_file = BASE_DIR.parent / "static" / "data" / "embodied" / "graph_data.json"
    elif industry == "low_altitude":
        graph_file = BASE_DIR.parent / "static" / "data" / "low_altitude" / "graph_data.json"
    elif industry == "sea":
        graph_file = BASE_DIR.parent / "static" / "data" / "sea" / "graph_data.json"
    elif industry == "quantum":
        graph_file = BASE_DIR.parent / "static" / "data" / "quantum" / "graph_data.json"
    elif industry == "biology":
        graph_file = BASE_DIR.parent / "static" / "data" / "biology" / "graph_data.json"
    elif industry == "brain":
        graph_file = BASE_DIR.parent / "static" / "data" / "brain" / "graph_data.json"
    elif industry == "material":
        graph_file = BASE_DIR.parent / "static" / "data" / "material" / "graph_data.json"
    else:
        graph_file = GRAPH_FILE

    kg_handler = KnowledgeGraphHandler(graph_file)
    graph_context = kg_handler.search_relevant_subgraph(query)
    return graph_context


# ===== 主程序入口 =====
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="重建向量数据库（GPU 加速）")
    parser.add_argument("--query", type=str, help="输入查询语句")
    parser.add_argument("--industry", type=str, choices=["ai", "embodied", "low_altitude", "sea", "quantum", "biology", "brain", "material"], help="产业类型：ai / embodied / low_altitude / sea / quantum / biology / brain / material")
    args = parser.parse_args()

    if args.build:
        build_vector_db(args.industry)
    elif args.query:
        query_vector_db(args.query, industry=args.industry)
    else:
        print("用法示例：")
        print("  python build_vector_db.py --build")
        print("  python build_vector_db.py --build --industry ai")
        print("  python build_vector_db.py --query 智算中心发展现状如何")
        print("  python build_vector_db.py --query 具身智能发展现状 --industry embodied")



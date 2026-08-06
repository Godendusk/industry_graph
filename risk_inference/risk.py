import json
import os
import time
import platform
from pathlib import Path
import io
import sys
import contextlib

import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from llm_client import llm

class SpecializedChainRiskEngine:
    def __init__(self, json_path):
        self.json_path = json_path
        # 使用无向图加载原始结构(因为包含关系可能双向查询)，但在传播时会有逻辑方向
        self.G = nx.Graph()
        self.l1_nodes = {}  # {node_id: name} (上/中/下)
        self.l2_map = {}  # {name: node_id} (分析入口)
        self.l2_to_l1 = {}  # {l2_id: l1_id}  (归属关系)

        self._load_graph()
        self._build_hierarchy_map()

    def _load_graph(self):
        """加载图谱并建立基础索引"""
        print(f">>> [系统] 正在加载图谱: {self.json_path}")
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for node in data.get('nodes', []):
                n_id = node['id']
                props = node.get('properties', {})
                labels = node.get('labels', [])
                name = props.get('name', str(n_id))

                self.G.add_node(n_id, labels=labels, **props)
                if "环节" in labels:
                    level = props.get('level')
                    if (level == 2 or str(level) == "2"):
                        self.l2_map[name] = n_id

                    # 建立索引：Level 1 (上中下游)
                    if level == 1 or str(level) == "1":
                        self.l1_nodes[n_id] = name


            for rel in data.get('relationships', []):
                self.G.add_edge(rel['source'], rel['target'], type=rel['type'])

            print(f">>> 图谱加载完毕。L1节点: {len(self.l1_nodes)}, L2环节: {len(self.l2_map)}")

        except Exception as e:
            print(f"加载失败: {e}")
            raise

    def _build_hierarchy_map(self):
        """
        预处理：建立 L2 -> L1 的归属关系。
        因为图谱中 source-target 是包含关系，Level 1 应该连接 Level 2。
        """
        for l2_name, l2_id in self.l2_map.items():
            neighbors = self.G.neighbors(l2_id)
            for nb in neighbors:
                if nb in self.l1_nodes:
                    self.l2_to_l1[l2_id] = nb
                    break
            # 如果没找到直连，可能需要两层跳跃（视具体图结构而定），这里暂定直连

    def get_node_name(self, n_id):
        return self.G.nodes[n_id].get('name', str(n_id))

    # ==========================================
    # 核心功能 1: 微观穿透
    # ==========================================
    def analyze_internal_composition(self, l2_id):
        """
        微观生态分析。
        涵盖多条路径：
        1. L2 -> Product <- Company (直连产品)
        2. L2 -> L3 -> Product <- Company (细分环节产品)
        3. L2 -> Company (直连公司，解决产品节点缺失问题)
        4. L2 -> L3 -> Company (L3直连公司，解决产品节点缺失问题)
        """
        stats = {
            "l3_count": 0, "l3_details": [],
            "product_count": 0, "product_examples": [],
            "company_count": 0, "company_examples": set(),
            "risk_score": 0, "risk_reason": ""
        }

        # 用于去重的集合
        all_products = set()
        all_companies = set()

        # 辅助函数：给定产品ID，查找其归属公司
        # exclude_ids: 排除来源路径上的节点（如 L2 或 L3），防止回环
        def find_companies_for_product(prod_id, exclude_ids):
            # Company -> Product (在无向图中查找 Product 的邻居)
            p_neighbors = self.G.neighbors(prod_id)
            for p_nb in p_neighbors:
                if p_nb in exclude_ids: continue

                c_data = self.G.nodes[p_nb]
                c_labels = c_data.get('labels', [])

                if "公司" in c_labels or "Company" in c_labels or "企业" in c_labels:
                    all_companies.add(c_data.get('name'))

        # 辅助函数：直接查找公司节点
        def find_companies_directly(node_id, exclude_ids):
            neighbors = self.G.neighbors(node_id)
            for nb in neighbors:
                if nb in exclude_ids: continue
                
                nb_data = self.G.nodes[nb]
                nb_labels = nb_data.get('labels', [])
                
                if "公司" in nb_labels or "Company" in nb_labels or "企业" in nb_labels:
                    all_companies.add(nb_data.get('name'))

        # === 遍历 L2 的一级邻居 ===
        neighbors = list(self.G.neighbors(l2_id))

        for nb in neighbors:
            nb_data = self.G.nodes[nb]
            nb_labels = nb_data.get('labels', [])
            nb_level = str(nb_data.get('level', ''))

            # --- 路径 1: 发现 L3 子环节 ---
            if nb_level == '3':
                stats["l3_count"] += 1
                stats["l3_details"].append(self.get_node_name(nb))

                # 深入 L3 找产品
                l3_neighbors = self.G.neighbors(nb)
                has_product = False
                for l3_nb in l3_neighbors:
                    if l3_nb == l2_id: continue  # 排除回指

                    l3_nb_data = self.G.nodes[l3_nb]
                    if "产品" in l3_nb_data.get('labels', []) or "Product" in l3_nb_data.get('labels', []):
                        has_product = True
                        prod_name = self.get_node_name(l3_nb)
                        all_products.add(prod_name)
                        # 查找公司 (排除 L3)
                        find_companies_for_product(l3_nb, exclude_ids={nb, l2_id})
                
                # 如果 L3 没有产品节点，直接查找 L3 连接的公司
                if not has_product:
                    find_companies_directly(nb, exclude_ids={l2_id})

            # --- 路径 2: 发现 L2 直连产品 ---
            elif "产品" in nb_labels or "Product" in nb_labels:
                prod_name = self.get_node_name(nb)
                all_products.add(prod_name)
                # 查找公司 (排除 L2)
                find_companies_for_product(nb, exclude_ids={l2_id})
            
            # --- 路径 3: 发现 L2 直连公司 ---
            elif "公司" in nb_labels or "Company" in nb_labels or "企业" in nb_labels:
                all_companies.add(nb_data.get('name'))

        # 汇总统计
        stats["product_count"] = len(all_products)
        stats["product_examples"] = list(all_products)[:5]
        stats["company_count"] = len(all_companies)
        stats["company_examples"] = list(all_companies)[:5]

        return stats

    # ==========================================
    # 核心功能 2: 宏观传播 (基于 L1 逻辑流向)
    # ==========================================
    def simulate_macro_propagation(self, start_l2_id):
        """
        模拟风险在产业链层级间的传递。
        逻辑流向：上游 -> 中游 -> 下游
        """
        if start_l2_id not in self.l2_to_l1:
            return {"error": "无法确定该环节所属的产业链层级(L1)"}

        my_l1_id = self.l2_to_l1[start_l2_id]
        my_l1_name = self.l1_nodes[my_l1_id]  # 例如 "上游基础层"

        # 定义层级顺序 (假设名称包含关键字)
        # 你需要根据实际 L1 节点名称修改这里的映射逻辑
        tier_order = {
            "上游": 1, "基础": 1,
            "中游": 2, "技术": 2,
            "下游": 3, "应用": 3
        }

        # 确定当前层级数字
        current_tier = 0
        for key, val in tier_order.items():
            if key in my_l1_name:
                current_tier = val
                break

        if current_tier == 0:
            return {"error": f"无法识别层级顺序: {my_l1_name}"}

        # 寻找受影响的目标层级 (Current -> Downstream)
        affected_tiers = []  # 存储受影响的 L1 ID
        for nid, name in self.l1_nodes.items():
            for key, val in tier_order.items():
                if key in name and val > current_tier:  # 严格下游
                    affected_tiers.append((nid, name))
                    break

        # 收集受影响的 L2 环节
        impact_result = {
            "source_tier": my_l1_name,
            "downstream_tiers_names": [x[1] for x in affected_tiers],
            "impacted_l2_nodes": []
        }

        # 遍历所有 L2，如果在受影响的 L1 下，则加入风险列表
        for l2_name, l2_id in self.l2_map.items():
            owner_l1 = self.l2_to_l1.get(l2_id)
            if owner_l1:
                # 检查 owner_l1 是否在受影响的 tiers 列表中
                for aff_id, aff_name in affected_tiers:
                    if owner_l1 == aff_id:
                        # 计算传播强度 (距离越远衰减)
                        # 这里简单处理：只要是下游，Risk=1.0 * 衰减
                        impact_result["impacted_l2_nodes"].append(l2_name)

        return impact_result

    # ==========================================
    # 核心功能 3: 整合数据
    # ==========================================
    def get_full_risk_profile(self, l2_name):
        if l2_name not in self.l2_map:
            return None

        l2_id = self.l2_map[l2_name]

        # 1. 内部微观分析
        internal = self.analyze_internal_composition(l2_id)

        # 2. 外部宏观传播
        external = self.simulate_macro_propagation(l2_id)

        return {
            "name": l2_name,
            "internal": internal,
            "external": external
        }


# ==========================================
# LLM 报告生成
# ==========================================
def generate_risk_report(data):
    """根据包含关系和层级流向生成报告"""

    internal = data['internal']
    external = data['external']

    prompt = f"""
    你是一位产业链安全分析师。请基于以下知识图谱数据，分析环节【{data['name']}】的风险及其影响。

    【1. 环节自身结构风险分析 (基于微观包含关系)】
    - 所属层级：{external.get('source_tier', '未知')}
    - **风险原因**：{internal['risk_reason']}
    - **生态体量**：
        - 包含细分环节(L3)数量：{internal['l3_count']} 个
        - 关联产品数量：{internal['product_count']} 个 (示例: {', '.join(internal['product_examples'])})
        - 关联企业数量：{internal['company_count']} 家 (示例: {', '.join(list(internal['company_examples']))})

    *分析逻辑：若产品/企业极少，说明该环节高度依赖少数实体，一旦断供则无替代品。*

    【2. 风险传播推演 (基于宏观产业链流向)】
    - **传播方向**：从 [{external.get('source_tier', '未知')}] 向下游扩散。
    - **波及范围**：预计将冲击下游层级 [{', '.join(external.get('downstream_tiers_names', []))}]。
    - **具体受影响的下游环节列表**：
      {', '.join(external.get('impacted_l2_nodes', [])[:20])} ... (等共 {len(external.get('impacted_l2_nodes', []))} 个环节)

    【报告生成要求】
    请以 Markdown 格式输出：
    ### 一、 风险诊断概述
    结合产品数量和企业数量论述该节点的结构风险。

    ### 二、 产业链传导模拟
    描述如果不进行干预，风险将如何从上游向下游传导？请明确指出受影响的下游产业群（列举几个具体的受影响L2环节名称）。

    ### 三、 应对策略
    针对该环节的特点（如：是产品太少导致的高风险，还是企业垄断导致的高风险），给出具体的强链补链建议。
    """

    print(f"\n>>> [LLM] 正在请求分析报告: {data['name']} ...")
    try:
        result = llm.query(user_prompt=prompt)
        if result is None:
            return f"报告生成失败：LLM 调用返回空结果，请检查模型服务或日志。"
        return result
    except Exception as e:
        return f"报告生成错误: {e}"


# ==========================================
# 3. 结果管理与可视化模块
# ==========================================
class ResultManager:
    @staticmethod
    def setup_fonts():
        """配置中文字体"""
        sys_os = platform.system()
        fonts = ['SimHei', 'Microsoft YaHei'] if sys_os == 'Windows' else \
            ['Arial Unicode MS', 'PingFang SC'] if sys_os == 'Darwin' else \
                ['WenQuanYi Micro Hei', 'SimHei']
        plt.rcParams['font.sans-serif'] = fonts
        plt.rcParams['axes.unicode_minus'] = False

    @staticmethod
    def save_and_visualize(node_name, risk_data, llm_report, output_base=None):
        """保存报告并绘制可视化图表（左侧统计，右侧拓扑图）

        :param output_base: 输出根目录，默认为当前工作目录。
        :return: {"report_path": str, "images": [str]}
        """

        # 1. 创建目录 (保持不变)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_dir = Path(output_base) if output_base else Path(".")
        folder = base_dir / f"风险报告_{node_name}_{timestamp}"
        folder.mkdir(parents=True, exist_ok=True)

        # 2. 保存 TXT
        report_path = folder / f"{node_name}_分析报告.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(llm_report if llm_report is not None else "报告内容为空，LLM 调用可能失败，请检查日志。")

        # 3. 绘图
        ResultManager.setup_fonts()
        internal = risk_data['internal']
        external = risk_data['external']

        fig, axes = plt.subplots(1, 2, figsize=(16, 8))  # 稍微调高一点高度
        fig.suptitle(f"产业链风险可视化：{node_name}", fontsize=18, fontweight='bold')

        # --- 左图：微观生态 (保持不变) ---
        ax1 = axes[0]
        items = ['关联企业', '关联产品', '细分环节(L3)']
        counts = [internal['company_count'], internal['product_count'], internal['l3_count']]

        bars = ax1.barh(items, counts, color=['#66c2a5', '#fc8d62', '#8da0cb'], height=0.5)
        ax1.set_title("内部生态韧性指标", fontsize=14)
        ax1.set_xlabel("数量")
        ax1.grid(axis='x', linestyle='--', alpha=0.3)

        for bar in bars:
            width = bar.get_width()
            ax1.text(width + 0.1, bar.get_y() + bar.get_height() / 2,
                     f'{int(width)}', va='center', fontsize=11)

        risk_color = 'red' if internal['risk_score'] >= 4 else 'orange' if internal['risk_score'] == 3 else 'green'


        # --- 右图：风险传导网络 (修正版) ---
        ax2 = axes[1]

        impact_list = external.get('impacted_l2_nodes', [])
        total_impact = len(impact_list)

        # 1. 构建可视化图对象
        G_vis = nx.DiGraph()

        # 添加中心节点
        G_vis.add_node(node_name, color='#ff4d4d', size=3000, label=node_name)

        # 选取 Top 节点 (防止节点过多)
        display_limit = 15
        show_nodes = impact_list[:display_limit]

        # 添加下游节点和边
        if not show_nodes:
            # 如果没有下游数据，显示提示文本
            ax2.text(0.5, 0.5, "未检测到明显的直接下游传导风险",
                     ha='center', va='center', fontsize=12, color='gray')
            ax2.axis('off')
        else:
            for target in show_nodes:
                # 避免自环（虽然逻辑上不应该有）
                if target != node_name:
                    G_vis.add_node(target, color='#4da6ff', size=1500, label=target)
                    G_vis.add_edge(node_name, target)

            # 2. 布局算法：使用 spring_layout (力导向) 替代 shell_layout
            # k参数控制节点间距，iterations控制迭代次数
            pos = nx.spring_layout(G_vis, seed=42, k=0.5, iterations=50)

            # 3. 提取绘图属性 (确保顺序一致)
            # 获取当前图中所有节点的列表
            all_nodes = list(G_vis.nodes())
            node_colors = [G_vis.nodes[n]['color'] for n in all_nodes]
            node_sizes = [G_vis.nodes[n]['size'] for n in all_nodes]

            # 4. 绘制 (显式传入 nodelist)
            nx.draw_networkx_nodes(G_vis, pos, ax=ax2,
                                   nodelist=all_nodes,  # <--- 关键修改：显式指定节点列表
                                   node_color=node_colors,
                                   node_size=node_sizes,
                                   alpha=0.9,
                                   edgecolors='white',  # 增加描边让节点更清晰
                                   linewidths=1.5)

            nx.draw_networkx_edges(G_vis, pos, ax=ax2,
                                   edge_color='gray',
                                   alpha=0.6,
                                   arrows=True,
                                   arrowstyle='-|>',
                                   arrowsize=20,
                                   width=1.5,
                                   node_size=node_sizes)  # 传入node_size以正确计算箭头终点

            # 标签绘制 (稍微调小字号以适应更多节点)
            nx.draw_networkx_labels(G_vis, pos, ax=ax2,
                                    font_family=plt.rcParams['font.sans-serif'][0],
                                    font_size=9,
                                    font_color='white',
                                    font_weight='bold')

            # 设置标题和边距
            title_suffix = f" (Top {len(show_nodes)}/{total_impact} 展示)" if total_impact > len(show_nodes) else ""
            ax2.set_title(f"风险传导路径模拟{title_suffix}", fontsize=14)

            # 关键：增加边距，防止节点画在边界外
            ax2.margins(0.2)
            ax2.axis('off')

        # 4. 保存
        img_path = folder / f"{node_name}_风险图谱.png"
        plt.tight_layout()
        plt.savefig(img_path, dpi=300)
        plt.close()

        print(f">>> [保存成功] 报告: {report_path}")
        print(f">>> [保存成功] 图表: {img_path}")
        return {
            "report_path": str(report_path),
            "images": [str(img_path)]
        }
        return {
            "report_path": report_path,
            "images": [img_path]
        }
# ==========================================
# 主运行逻辑
# ==========================================
def main():
    json_path = 'graph_data.json'  # 你的文件路径
    engine = SpecializedChainRiskEngine(json_path)

    print("\n>>> 已识别的 Level 2 环节：")
    stages = list(engine.l2_map.keys())
    for i, s in enumerate(stages[:]):  # 只打印前15个
        print(f"{i + 1}. {s}")

    # 模拟选择
    try:
        idx = int(input("\n请输入序号进行分析: ")) - 1
        target = stages[idx]
    except:
        target = stages[0]

    # 执行分析
    print(f"\n正在分析 [{target}] ...")
    risk_data = engine.get_full_risk_profile(target)

    if not risk_data:
        print("分析失败，数据异常。")
        return

    # 生成报告
    report = generate_risk_report(risk_data)
    print("\n" + "=" * 30)
    print(report)

    ResultManager.save_and_visualize(target, risk_data, report)


if __name__ == "__main__":
    main()


# --- 便于后端调用 ---
def list_level2_nodes(graph_path: Path) -> list:
    engine = SpecializedChainRiskEngine(str(graph_path))
    return list(engine.l2_map.keys())


def run_risk_analysis(node_name: str, graph_path: Path, output_base: Path) -> dict:
    """
    运行风险分析，返回报告文本、图片路径和日志。
    图片输出到 output_base/<节点>_<时间戳>/ 下。
    """
    engine = SpecializedChainRiskEngine(str(graph_path))
    if node_name not in engine.l2_map:
        raise ValueError(f"未找到环节：{node_name}")

    buf = io.StringIO()

    class Tee(io.TextIOBase):
        def __init__(self, *streams):
            self.streams = streams

        def write(self, s):
            for st in self.streams:
                try:
                    st.write(s)
                except Exception:
                    pass
            return len(s)

        def flush(self):
            for st in self.streams:
                try:
                    st.flush()
                except Exception:
                    pass

    tee = Tee(sys.stdout, buf)
    with contextlib.redirect_stdout(tee):
        print(f"\n正在分析 [{node_name}] ...")
        risk_data = engine.get_full_risk_profile(node_name)
        if not risk_data:
            print("分析失败，数据异常。")
            raise RuntimeError("分析失败，数据异常。")
        report = generate_risk_report(risk_data)
        print("\n" + "=" * 30)
        print(report)

    # 输出目录
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = "".join([c for c in node_name if c.isalnum() or c in ("_", "-", " ")]) or "risk"
    out_dir = output_base / f"{safe_name}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = ResultManager.save_and_visualize(node_name, risk_data, report, output_base=out_dir)

    return {
        "report": report,
        "images": res.get("images", []),
        "log": buf.getvalue()
    }

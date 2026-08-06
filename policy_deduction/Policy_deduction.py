import json
import pandas as pd
import time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import re
import os
import sys
from collections import defaultdict
from pathlib import Path
from llm_client import llm  # 假设你已经配置好了这个模块


# ==========================================
# 1. 图谱构建与全量加载 (核心修改)
# ==========================================
class KnowledgeGraphHandler:
    def __init__(self, file_path):
        self.file_path = file_path
        self.G = nx.Graph()  # 使用无向图以方便双向遍历
        self.level2_map = {}  # {name: node_id} 映射
        self.l1_nodes = {}  # {node_id: name} 存储上中下游节点
        self.load_graph()

    def load_graph(self):
        """加载 JSON 数据并构建 NetworkX 图对象"""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 1. 添加节点
            nodes = data.get('nodes', [])
            for node in nodes:
                n_id = node['id']
                props = node.get('properties', {})
                labels = node.get('labels', [])

                # 提取关键属性
                name = props.get('name')

                # 存入图
                self.G.add_node(n_id, labels=labels, **props)

                if "环节" in labels:
                    level = props.get('level')
                    if (level == 2 or str(level) == "2"):
                        self.level2_map[name] = n_id

                    # 建立索引：Level 1 (上中下游)
                    if level == 1 or str(level) == "1":
                        self.l1_nodes[n_id] = name

            # 2. 添加边 (关系)
            relationships = data.get('relationships', [])
            for rel in relationships:
                source = rel['source']
                target = rel['target']
                r_type = rel['type']
                self.G.add_edge(source, target, type=r_type)

            print(f"图谱构建完成！包含节点 {self.G.number_of_nodes()} 个，边 {self.G.number_of_edges()} 条。")
            print(f"识别到 Level 2 环节节点 {len(self.level2_map)} 个。")

        except Exception as e:
            print(f"图谱加载失败: {e}")

    def get_level2_names(self):
        return list(self.level2_map.keys())

    def trace_impact_chain(self, affected_l2_names):
        """
        核心推演逻辑：
        输入：受影响的 L2 环节名称列表
        输出：详细的推演数据（包含L1归属、L3细节、产品数、公司数）
        """
        impact_details = {}

        for l2_name in affected_l2_names:
            if l2_name not in self.level2_map:
                continue

            l2_id = self.level2_map[l2_name]

            # --- 1. 向上找 Level 1 (上中下游) ---
            # 逻辑：遍历邻居，找到 level=1 的节点
            chain_position = "未知层级"
            neighbors = list(self.G.neighbors(l2_id))
            for nb_id in neighbors:
                if nb_id in self.l1_nodes:
                    chain_position = self.l1_nodes[nb_id]
                    break

            # --- 2. 向下找 Level 3 -> 产品 -> 公司 ---
            l3_nodes = []
            products = set()
            companies = set()

            # 辅助函数：直接查找公司节点
            def find_companies_directly(node_id, exclude_ids):
                neighbors = self.G.neighbors(node_id)
                for nb in neighbors:
                    if nb in exclude_ids: continue
                    
                    nb_data = self.G.nodes[nb]
                    nb_labels = nb_data.get('labels', [])
                    
                    if "公司" in nb_labels or "Company" in nb_labels or "企业" in nb_labels:
                        companies.add(nb_data.get('name'))

            # 遍历 L2 的邻居找 L3
            for nb_id in neighbors:
                node_data = self.G.nodes[nb_id]
                # 判断是否为 L3 环节 (根据 label 或 level)
                is_l3 = "环节" in node_data.get('labels', []) and \
                        (node_data.get('level') == 3 or str(node_data.get('level')) == "3")

                if is_l3:
                    l3_nodes.append(node_data['name'])

                    # --- 深入找产品 ---
                    l3_neighbors = self.G.neighbors(nb_id)
                    has_product = False
                    for prod_id in l3_neighbors:
                        prod_data = self.G.nodes[prod_id]
                        # 假设产品节点的标签包含 "产品"
                        if "产品" in prod_data.get('labels', []):
                            has_product = True
                            products.add(prod_data['name'])

                            # --- 深入找公司 ---
                            prod_neighbors = self.G.neighbors(prod_id)
                            for comp_id in prod_neighbors:
                                comp_data = self.G.nodes[comp_id]
                                # 假设公司节点的标签包含 "公司" 或 "企业"
                                if "公司" in comp_data.get('labels', []) or "企业" in comp_data.get('labels', []):
                                    companies.add(comp_data['name'])
                    
                    # 如果 L3 没有产品节点，直接查找 L3 连接的公司
                    if not has_product:
                        find_companies_directly(nb_id, exclude_ids={l2_id})

            # --- 3. 直接查找 L2 连接的公司（解决产品节点缺失问题）---
            for nb_id in neighbors:
                nb_data = self.G.nodes[nb_id]
                nb_labels = nb_data.get('labels', [])
                if "公司" in nb_labels or "Company" in nb_labels or "企业" in nb_labels:
                    companies.add(nb_data.get('name'))

            impact_details[l2_name] = {
                "chain_position": chain_position,  # 上中下游
                "l3_count": len(l3_nodes),
                "l3_examples": l3_nodes[:3],  # 仅存前3个用于展示
                "product_count": len(products),
                "product_list": list(products),
                "company_count": len(companies),
                "company_list": list(companies)
            }

        return impact_details


# ==========================================
# 2. LLM 分析 (保持原逻辑，微调Prompt)
# ==========================================
def construct_prompt(title, content, all_stages):
    stages_str = "、".join(all_stages)
    prompt = f"""
    你需要扮演一位资深的产业政策分析师。

    【任务】
    分析给定的“政策法规”内容，判断该政策会影响“产业链环节列表”中的哪些具体环节。

    【输入数据】
    1. 政策标题：{title}
    2. 政策内容片段：
    {content[:4000]}... 

    3. 候选产业链环节列表（Level 2）：
    [{stages_str}]

    【输出要求】
    请只输出一个 JSON 列表（无Markdown标记），包含：
    - "stage_name": 受影响环节名称。
    - "impact_score": 影响力评分 (1-5整数)。
    - "correlation": 相关性评分 (1-5整数)。
    - "reason": 简短理由。

    若无影响返回 []。
    """
    return prompt


def analyze_policy_with_llm(title, content, all_stages):
    # 此处保持您原有代码逻辑，为节省篇幅略去重试代码
    # ... (使用原来的 analyze_policy_with_llm 代码) ...
    sys_prompt = "你是一个只输出 JSON 格式结果的助手。不要输出任何解释性文字。"
    usr_prompt = construct_prompt(title, content, all_stages)

    # 模拟 LLM 返回 (调试时使用，实际运行时请替换为真实调用)
    # return [{"stage_name": all_stages[0], "impact_score": 5, "correlation": 4, "reason": "测试"}]

    try:
        result = llm.query(system_prompt=sys_prompt, user_prompt=usr_prompt)
        if not result: return []
        text = result.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except Exception as e:
        print(f"LLM调用异常: {e}")
        return []


# ==========================================
# 3. 增强版可视化与统计输出
# ==========================================
def visualize_deep_impact(policy_title, llm_results, graph_handler, output_base=None):
    """
    修改说明：
    1. [移除] 移除了原有的 NetworkX 拓扑图。
    2. [新增] 增加了 '政策影响热力图' (Heatmap)。
    3. [新增] 引入 '箱线图' (Boxplot) 分析产业链各段的得分分布。
    4. [报告] 将统计计算结果（如产业链分布占比）写入 TXT 报告。
    """
    import os
    import platform
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib import cm
    from matplotlib.colors import Normalize

    # --- 0. 环境配置：防乱码 ---
    sys_str = platform.system()
    if sys_str == 'Windows':
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
    elif sys_str == 'Darwin':
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC']
    else:
        plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei']
    plt.rcParams['axes.unicode_minus'] = False

    if not llm_results:
        print("无有效分析结果，跳过绘图。")
        return {"images": [], "report_path": None, "output_dir": None}

    # --- 1. 创建保存目录 ---
    safe_title = "".join([c for c in policy_title if c.isalnum() or c in (' ', '_', '-')]).strip() or "policy"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    base_dir = Path(output_base) if output_base else Path(".")
    output_dir = base_dir / f"{safe_title}_推演结果_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- 2. 数据处理与聚合计算 ---
    affected_names = [item['stage_name'] for item in llm_results]
    deep_data = graph_handler.trace_impact_chain(affected_names)

    plot_data = []
    for item in llm_results:
        name = item['stage_name']
        if name not in deep_data: continue
        d = deep_data[name]
        plot_data.append({
            'name': name,
            'score': item['impact_score'],
            'correlation': item['correlation'],
            'position': d['chain_position'],  # 上中下游
            'companies': d['company_count'],
            'products': d['product_count'],
            'reason': item.get('reason', '无')
        })

    if not plot_data: return
    df = pd.DataFrame(plot_data)

    # [计算核心指标] 按产业链位置分组统计
    # 统计：环节数量、总影响力分数、总关联企业数
    group_stats = df.groupby('position').agg({
        'name': 'count',
        'score': 'sum',
        'companies': 'sum',
        'products': 'sum'
    }).rename(columns={'name': 'count', 'score': 'total_score', 'companies': 'total_comp', 'products': 'total_prod'})

    # 计算百分比（用于饼图和报告）
    total_score_sum = group_stats['total_score'].sum()
    group_stats['score_ratio'] = group_stats['total_score'] / total_score_sum if total_score_sum > 0 else 0

    # --- 3. 生成详细文字报告 (含计算结果) ---
    report_path = output_dir / f'{safe_title}_详细推演报告.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write(f"【政策推演报告】 {policy_title}\n")
        f.write(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")

        f.write("一、 产业链分布统计分析 (计算结果)\n")
        f.write("-" * 40 + "\n")
        for pos, row in group_stats.iterrows():
            f.write(f"【{pos}】:\n")
            f.write(f"  - 受波及环节数：{row['count']} 个\n")
            f.write(f"  - 累计影响力得分：{row['total_score']} 分 (占比 {row['score_ratio']:.1%})\n")
            f.write(f"  - 涉及市场规模(企业)：{row['total_comp']} 家\n")
            f.write(f"  - 涉及技术广度(产品)：{row['total_prod']} 种\n")
            f.write("\n")

        f.write("二、 核心环节详细数据\n")
        f.write("-" * 40 + "\n")
        # 按影响力排序
        for idx, row in df.sort_values('score', ascending=False).iterrows():
            f.write(f">>> 环节名称：{row['name']} ({row['position']})\n")
            f.write(f"    评分：影响力 {row['score']} / 相关性 {row['correlation']}\n")
            f.write(f"    数据：关联企业 {row['companies']} 家 / 产品 {row['products']} 种\n")
            f.write(f"    理由：{row['reason']}\n\n")

    print(f">>> [保存] 包含计算数据的文字报告已保存: {report_path}")

    # --- 4. 绘图一：多维特征热力图 (Heatmap) ---
    # 目的：在一个图里展示多个维度的归一化数据，方便横向对比
    plt.figure(figsize=(14, 8))

    # 取 Top 15 环节
    top_df = df.sort_values('score', ascending=False).head(15).copy()

    # 数据归一化 (Min-Max Scaling) 以便在热力图中展示
    cols_to_plot = ['score', 'correlation', 'companies', 'products']
    col_labels = ['影响力评分', '政策相关度', '关联企业数', '产品种类数']

    heatmap_data = top_df[cols_to_plot].values
    # 简单的归一化处理：(x - min) / (max - min)
    norm_data = (heatmap_data - heatmap_data.min(axis=0)) / (heatmap_data.max(axis=0) - heatmap_data.min(axis=0) + 1e-5)

    plt.imshow(norm_data, aspect='auto', cmap='YlGnBu')

    # 设置轴标签
    plt.xticks(range(len(col_labels)), col_labels, fontsize=12)
    plt.yticks(range(len(top_df)), top_df['name'], fontsize=12)

    # 在格子里填具体数值
    for i in range(len(top_df)):
        for j in range(len(col_labels)):
            val = heatmap_data[i, j]
            # 颜色深的地方字变白
            text_color = "white" if norm_data[i, j] > 0.6 else "black"
            plt.text(j, i, int(val), ha="center", va="center", color=text_color, fontsize=10)

    plt.title(f"《{policy_title}》\n核心环节多维特征热力图 (Top 15)", fontsize=16)
    plt.colorbar(label='相对强度 (归一化)')
    plt.tight_layout()

    save_path_1 = output_dir / '1_多维特征热力图.png'
    plt.savefig(save_path_1, dpi=300)
    plt.close()
    print(f">>> [保存] 热力图已保存: {save_path_1}")

    # --- 5. 绘图二：产业链结构化看板 ---
    fig, axes = plt.subplots(2, 2, figsize=(18, 12))
    plt.subplots_adjust(hspace=0.4, wspace=0.3)
    fig.suptitle(f"《{policy_title}》产业链结构化分析看板", fontsize=20)

    # 子图1：影响力分布 (环形图) - 使用计算后的数据
    ax1 = axes[0, 0]
    if not group_stats.empty:
        # 环形图
        wedges, texts, autotexts = ax1.pie(
            group_stats['total_score'],
            labels=group_stats.index,
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.85,
            colors=['#ff9999', '#66b3ff', '#99ff99', '#ffcc99']
        )
        # 画个白圈变成环形
        centre_circle = plt.Circle((0, 0), 0.70, fc='white')
        ax1.add_artist(centre_circle)
        ax1.set_title("产业链各层级影响力占比 (总分)", fontsize=14)

    # 子图2：得分分布 (箱线图 Boxplot)
    # 展示上中下游的得分波动情况（是普遍高分，还是个别高分？）
    ax2 = axes[0, 1]
    positions = df['position'].unique()
    box_data = [df[df['position'] == pos]['score'].values for pos in positions]

    ax2.boxplot(box_data, labels=positions, patch_artist=True,
                boxprops=dict(facecolor="#45B7D1", alpha=0.6))
    ax2.set_title("各层级环节得分分布 (Boxplot)", fontsize=14)
    ax2.set_ylabel("影响力评分")
    ax2.grid(axis='y', linestyle='--', alpha=0.3)

    # 子图3：相关性 vs 规模 (散点图)
    ax3 = axes[1, 0]

    # [优化步骤1] 数据抖动 (Jittering)
    # 原因：评分通常是整数(1,2,3,4,5)，会导致很多点完全重合。
    # 方案：给坐标增加微小的随机噪声，将点在视觉上错开。
    jitter_strength = 0.15  # 抖动幅度
    # 创建临时绘图数据，不修改原始 df
    plot_df = df.copy()
    plot_df['x_jitter'] = plot_df['score'] + np.random.uniform(-jitter_strength, jitter_strength, size=len(plot_df))
    plot_df['y_jitter'] = plot_df['correlation'] + np.random.uniform(-jitter_strength, jitter_strength,
                                                                     size=len(plot_df))

    scatter = ax3.scatter(plot_df['x_jitter'], plot_df['y_jitter'],
                          s=plot_df['companies'] * 20 + 50,
                          c=plot_df['products'], cmap='coolwarm', alpha=0.7, edgecolors='gray')

    ax3.set_title("影响力矩阵 (点位置含微量抖动以防重叠)", fontsize=14)
    ax3.set_xlabel("影响力评分")
    ax3.set_ylabel("政策相关度")
    plt.colorbar(scatter, ax=ax3, label='涉及产品种类数')

    # [优化步骤2] 智能标签避让
    # 尝试使用 adjustText 库，如果用户环境没装，则回退到普通标注
    target_rows = plot_df.sort_values('companies', ascending=False).head(8)  # 稍微多标几个，取Top 8
    texts = []

    # 先生成所有 text 对象
    for idx, row in target_rows.iterrows():
        # 文本稍微偏离一点点点心，方便 adjust_text 计算
        t = ax3.text(row['x_jitter'], row['y_jitter'], row['name'], fontsize=9, fontweight='bold')
        texts.append(t)

    try:
        from adjustText import adjust_text
        # 使用箭头连接文字和点，彻底解决重叠
        adjust_text(texts, ax=ax3,
                    arrowprops=dict(arrowstyle='->', color='gray', lw=0.5),
                    force_points=0.2, force_text=0.5)
        print(">>> [成功] 已启用 adjustText 进行智能标签避让。")
    except ImportError:
        print(">>> [提示] 未检测到 adjustText 库，标签可能仍有部分重叠。")
        print(">>> 建议安装: pip install adjustText")
        # 如果没有库，保持原样（因为上面已经 add_text 了，这里不需要额外操作）
        pass

    # 子图4：企业聚集度 Top 10 (柱状图)
    ax4 = axes[1, 1]
    top_comp = df.sort_values('companies', ascending=False).head(10)
    bars = ax4.bar(top_comp['name'], top_comp['companies'], color='#FF6B6B')
    ax4.set_title("受影响环节 - 企业聚集度排行", fontsize=14)
    ax4.set_ylabel("关联企业数量")
    ax4.tick_params(axis='x', rotation=30)
    # 柱子上标数字
    for bar in bars:
        height = bar.get_height()
        ax4.text(bar.get_x() + bar.get_width() / 2., height,
                 '%d' % int(height), ha='center', va='bottom', fontsize=9)

    save_path_2 = output_dir / '2_产业链结构看板.png'
    plt.savefig(save_path_2, dpi=300)
    plt.close()
    print(f">>> [保存] 结构看板已保存: {save_path_2}")

    return {
        "output_dir": str(output_dir),
        "report_path": str(report_path),
        "images": [str(save_path_1), str(save_path_2)],
        "group_stats_df": group_stats,
        "detail_df": df,
    }


# ==========================================
# 4. 主程序
# ==========================================
def main():
    graph_path = './graph_data.json'
    policy_path = './policy_data/人工智能政策法规.xlsx'

    # 1. 初始化图谱处理器
    print(">>> [Step 1] 正在构建全量知识图谱...")
    kg = KnowledgeGraphHandler(graph_path)
    level2_stages = kg.get_level2_names()

    if not level2_stages:
        print("未提取到环节节点，请检查图谱文件。")
        return

    # 2. 读取政策
    print(f">>> [Step 2] 读取政策文件...")
    try:
        df = pd.read_excel(policy_path, sheet_name='政策法规-人工智能（按全文搜）')
    except Exception as e:
        print(f"Excel读取失败: {e}")
        return

    # 3. 交互选择
    print("\n>>> 可选政策：")
    for i, t in enumerate(df['标题'].head(10)):  # 只列出前10个防止刷屏
        print(f"{i + 1}. {t}")

    try:
        idx = int(input("\n请输入编号: ")) - 1
        title = df.iloc[idx]['标题']
        content = str(df.iloc[idx]['内容'])
    except:
        print("输入错误")
        return

    # 4. LLM 分析 (第一层：定性分析)
    print(f"\n>>> [Step 3] AI正在分析《{title}》对 {len(level2_stages)} 个环节的影响...")
    llm_res = analyze_policy_with_llm(title, content, level2_stages)

    # 5. 图谱推演 (第二层：定量穿透)
    print(f"\n>>> [Step 4] 正在进行产业链图谱穿透推演...")
    visualize_deep_impact(title, llm_res, kg)


if __name__ == "__main__":
    main()


# ============================================================
# 便于后端调用的封装函数
# ============================================================
def generate_markdown_report(policy_title, group_stats, detail_df, output_dir: Path):
    """
    功能：调用 LLM 对统计结果进行深度研判，生成 Markdown 格式报告并保存。
    """
    print(f"\n>>> [Step 5] 正在调用大模型生成深度研判报告 (Markdown)...")

    # 1. 数据序列化
    stats_str = group_stats.to_string() if group_stats is not None else ""
    top_nodes = detail_df.sort_values('score', ascending=False).head(10) if detail_df is not None else None
    top_nodes_str = ""
    if top_nodes is not None and not top_nodes.empty:
        top_nodes_str = top_nodes[['name', 'position', 'score', 'correlation', 'companies', 'products', 'reason']]\
            .to_string(index=False)

    # 2. 构建 Prompt
    system_prompt = "你是一位精通产业链动力学与宏观政策的资深分析师。请根据提供的数据生成一份专业的Markdown格式研报。"
    user_prompt = f"""
    【任务目标】
    根据《{policy_title}》的产业链推演数据，撰写一份深度分析报告。
    请不要简单罗列数字，而是要分析数据背后的**传导机制**、**产业集聚效应**和**潜在机遇/风险**。

    【输入数据 1：产业链分布统计】
    {stats_str}
    (解释：position=产业链位置, count=受影响环节数, total_score=总影响力, total_comp=涉及企业总数, total_prod=涉及产品数)

    【输入数据 2：Top 10 核心受影响环节】
    {top_nodes_str}

    【输出格式要求】
    请输出标准的 Markdown 内容，结构如下：
    # 《{policy_title}》产业链深度研判报告

    ## 1. 宏观影响综述
    (分析政策对上/中/下游的整体分布偏好，判断政策的着力点是属于“技术驱动型(上游)”还是“应用落地型(下游)”？)

    ## 2. 关键节点穿透分析
    (挑选2-3个最具代表性的环节，结合'reason'和'companies'数据，分析为何这些环节成为了政策传导的枢纽？)

    ## 3. 产业集聚与市场机会
    (基于'total_comp'企业数量，分析市场热度最高的领域。哪里是红海？哪里是潜在的蓝海？)

    ## 4. 总结与建议
    (简短的结语)
    """

    try:
        if output_dir is None:
            print(">>> [警告] output_dir 为空，跳过 Markdown 报告生成。")
            return None
        report_content = llm.query(system_prompt=system_prompt, user_prompt=user_prompt)
        if not report_content:
            print("LLM 返回为空，跳过报告生成。")
            return None

        clean_content = report_content.replace("```markdown", "").replace("```", "").strip()
        safe_title = re.sub(r"[\\\\/:*?\"<>|]+", "_", str(policy_title)).strip()
        safe_title = re.sub(r"\\s+", " ", safe_title)
        if len(safe_title) > 80:
            safe_title = safe_title[:80].rstrip()
        filename = f"{safe_title}_深度研判报告.md"
        save_dir = Path(output_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / filename
        save_path.write_text(clean_content, encoding="utf-8")
        print(f">>> [保存] AI深度研判报告已生成: {save_path}")
        return str(save_path)
    except Exception as e:
        print(f"报告生成失败: {e}")
        return None


def _find_excel_path():
    """自动寻找 policy_data 下的 xlsx 文件"""
    base = Path(__file__).parent / "policy_data"
    for p in base.glob("*.xlsx"):
        return p
    return None


def list_policy_titles(excel_path=None, sheet_name=None, limit=200):
    """
    返回政策标题列表（带 index）。
    limit 用于避免返回过多数据，默认 200 条。
    """
    excel = Path(excel_path) if excel_path else _find_excel_path()
    if not excel or not excel.exists():
        raise FileNotFoundError("找不到政策 Excel 文件")

    xls = pd.ExcelFile(excel)
    sheet = sheet_name or xls.sheet_names[0]
    df = xls.parse(sheet)

    # 寻找标题列
    title_col = None
    for col in df.columns:
        if "标题" in str(col):
            title_col = col
            break
    if title_col is None:
        title_col = df.columns[0]

    titles = []
    for idx, val in df[title_col].head(limit).items():
        title = str(val).strip()
        if title:
            titles.append({"id": int(idx), "title": title})
    return titles


def run_policy_analysis(policy_index: int, graph_path: Path, excel_path=None, sheet_name=None, output_base: Path = None):
    """
    后端统一调用：
    - policy_index: Excel 行索引
    - graph_path: 图谱 JSON 路径
    - excel_path: 政策 Excel 路径
    - output_base: 输出根目录（会在里面创建子文件夹）
    """
    excel = Path(excel_path) if excel_path else _find_excel_path()
    if not excel or not excel.exists():
        raise FileNotFoundError("找不到政策 Excel 文件")
    graph_path = Path(graph_path)
    if not graph_path.exists():
        raise FileNotFoundError(f"找不到图谱文件: {graph_path}")

    # 读政策
    xls = pd.ExcelFile(excel)
    sheet = sheet_name or xls.sheet_names[0]
    df = xls.parse(sheet)

    # 识别列
    title_col = None
    content_col = None
    for col in df.columns:
        col_str = str(col)
        if title_col is None and "标题" in col_str:
            title_col = col
        if content_col is None and ("内容" in col_str or "正文" in col_str):
            content_col = col
    if title_col is None:
        title_col = df.columns[0]
    if content_col is None:
        content_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    if not (0 <= policy_index < len(df)):
        raise IndexError(f"policy_index 超出范围: {policy_index}")

    title = str(df.iloc[policy_index][title_col]).strip()
    content = str(df.iloc[policy_index][content_col]).strip()

    # 准备图谱
    kg = KnowledgeGraphHandler(str(graph_path))
    level2_stages = kg.get_level2_names()

    from contextlib import redirect_stdout
    import io

    buf = io.StringIO()
    with redirect_stdout(buf):
        print(f">>> [Step 1] 构建全量图谱完成，Level2 节点 {len(level2_stages)} 个")
        print(f">>> [Step 2] 正在分析《{title}》对环节的影响...")
        llm_res = analyze_policy_with_llm(title, content, level2_stages)
        print(f">>> LLM 返回 {len(llm_res)} 条环节影响结果")
        print(f">>> [Step 3] 正在生成可视化与报告...")
        vis_res = visualize_deep_impact(title, llm_res, kg, output_base=output_base)
        # 追加：生成深度研判 Markdown 报告
        try:
            md_path = generate_markdown_report(title, vis_res.get("group_stats_df"), vis_res.get("detail_df"), Path(vis_res.get("output_dir")))
            vis_res["md_report_path"] = md_path
        except Exception as e:
            print(f">>> [警告] Markdown 报告生成失败: {e}")

    log_text = buf.getvalue()

    report_path = Path(vis_res.get("md_report_path") or vis_res.get("report_path") or "")
    report_text = ""
    if report_path.exists():
        try:
            report_text = report_path.read_text(encoding="utf-8")
        except Exception:
            report_text = ""

    images = []
    for p in vis_res.get("images", []):
        path_obj = Path(p)
        if path_obj.exists():
            images.append(str(path_obj))

    return {
        "title": title,
        "report": report_text,
        "images": images,
        "log": log_text,
        "output_dir": vis_res.get("output_dir"),
    }

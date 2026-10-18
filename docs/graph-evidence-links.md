# 图谱事实与产业报告证据链接

GraphRAG 第一阶段使用图谱引导现有 Hybrid RAG。图谱不复制原文，只通过现有的 `material_id`、`document_id` 和 `chunk_id` 指向产业报告资料库中的证据片段。

每个产业图谱旁边可放置一个可选的 `graph_evidence_links.json`：

```text
static/data/<industry>/graph_data.json
static/data/<industry>/graph_evidence_links.json
```

映射文件格式：

```json
{
  "version": 1,
  "links": [
    {
      "element_type": "node",
      "id": 101,
      "evidence_refs": [
        {
          "material_id": "company_case_001",
          "document_id": "company_case_001",
          "chunk_id": "external:company_case:company_case_001:p:03"
        }
      ]
    },
    {
      "element_type": "relationship",
      "source": 101,
      "target": 205,
      "type": "生产",
      "evidence_refs": [
        {
          "material_id": "company_case_001",
          "chunk_id": "external:company_case:company_case_001:p:03"
        }
      ]
    }
  ]
}
```

映射是多对多的：一个图谱关系可以由多个资料片段支持，一个资料片段也可以支持多个图谱事实。未绑定证据的图谱关系仍然可以用于产业链结构和检索线索，但不能直接作为外部资料引用。

图谱检索结果会在 `evidence_blocks[*].graph_evidence_refs` 和实体的 `evidence_refs` 中携带这些引用。当前没有创建虚构映射；需要根据真实资料片段逐条确认后再填入 sidecar 文件。

优先绑定以下关系：

1. 企业 → 参与环节
2. 企业 → 生产/提供 → 产品
3. 产品 → 应用于 → 产业环节
4. 政策 → 影响 → 产业环节

`vector_id` 是向量库实现细节，不作为图谱证据链接的主键。重建索引时应保持 `chunk_id` 的语义稳定。

## 已接入报告链路

统筹阶段先执行原有图谱检索与 Hybrid RAG，再按图谱返回的证据链接精确读取片段。候选合并按 chunk ID 去重，并使用现有 reranker 对原始章节查询重排，然后进入报告材料分配与 `[C数字]` 引用注册。

- AI 使用 `RAG/indexes/report_v2/lexical.sqlite3`。
- 专题资讯始终按 ID 只读读取当前产业 Chroma SQLite 的文本记录，不使用可能过期的词法副本，不启动 Chroma 客户端、不修改原库。
- `material_id`、`document_id`、`library`（提供时）及产业范围必须匹配实际记录。
- 最多读取 40 条链接；缺失片段、标识不符或精排失败会记录 `graph_*` 告警。
- 没有链接时完全复用原有检索结果，不额外加载模型。
- 节点提及和关系支持是两种语义。实体结果中的 `node_evidence_refs` 和 `relationship_evidence_refs` 分别保留两类链接；联合召回不意味着节点资料支持所有关系。
- chunk ID 在现有索引内可定位；重新切分后可能改变，失效链接需重新绑定，读取器会报告缺失，不自动猜测替代片段。

## 本机样本与审核

截至 2026-10-15，具身智能正式映射 `static/data/embodied/graph_evidence_links.json` 包含 49 个实体提及链接、42 条关系支持链接，共 101 条元素–chunk 引用，对应 60 个原始 chunk。关系只绑定图中已有的“参与环节”边；不会因实体名称出现就证明其全部关系。

本轮按用户授权开展 AI 辅助来源审核：250 条候选引用中，47 条通过、164 条不纳入本轮证据、34 条待补充来源，5 条沿用已有节点引用。59 条引用读取了完整原始 chunk，其余为候选摘要筛选；每条阅读层级和理由保存在 `evaluation/graph_evidence/embodied_stage1_review.json`，阅读版为 `embodied_stage1_ai_review_2026-10-15.md`。通过表示原文支持所述范围，并不表示已联网独立认证新闻事实；原有 25 条链接保留，不算本轮重新审核。

本轮的真实本地加载与精确取文验证覆盖电机、控制器、力觉/触觉传感器、电池、人形整机和应用案例，身份告警为零；相关回归 30 项通过。验证记录为 `evaluation/graph_evidence/embodied_stage1_ai_review_validation_2026-10-15.json`。该验证不包含 LLM 选环节、Hybrid 重排或整篇报告生成。该早期验证时加载器尚未完整传递审核限定；2026-10-15 阶段四已补齐 sidecar → 图谱加载器 → 候选合并 → 引用注册 → 写作上下文的 `review_method`、`review_note`、`evidence_scope`，并覆盖多关联及原 Hybrid 已召回同一 chunk 的情况。

`evaluation/graph_evidence/embodied_candidates_2026-10-14.json` 和同名 Markdown 是扫描前 5,000 个片段生成的候选审核材料。候选默认 `verification_status: pending`，不会进入检索。确认后将所选记录改为 `approved`，合并到图谱旁的映射文件；不要用候选文件直接覆盖已审核映射。

生成更多候选（输出路径必须不存在，以保护已有审核记录）：

```bash
python scripts/build_graph_evidence_links.py --industry embodied --scan-limit 5000 --output evaluation/graph_evidence/new_candidates.json
```

候选生成只匹配非骨架节点的完整名称，且名称不少于 4 字符；短名称、别名和未扫描的片段未覆盖。文本里出现名称只表示实体提及，关系支持需要阅读原句确认。这个工具不会将共现、分类理由或行业理由自动转换为关系证据。

## 2026-10-14 历史验收

完整记录见 `evaluation/graph_evidence/acceptance_20261014/acceptance_notes.md`。五个真实问题中，新增保留片段数为1、1、1、2、0；实际基线回退legacy_news，另有同reranker控制组，不能作为纯Hybrid质量提升结论。三节正文与摘要生成成功，引用10份资料，其中4个图谱关联候选所属资料被引用。引用追踪是资料级，不是片段级。Word导出成功，内置渲染器中文显示异常，尚未通过视觉排版验收。

## 2026-10-15 阶段四与阶段五验收

阶段四结论为 `runnable_quality_followup`。新映射下五问三路检索与三章六节完整报告真实运行，全部章节使用 embodied / embodied_news / hybrid_v2，无回退、Hybrid错误或身份告警。30个章节材料实例对应23个唯一chunk；统筹阶段注册21份资料，正文最终保留20份参考资料；四个图谱关联证据块进入章节材料。引用按资料注册，不能据此推断关联chunk中的所有事实被采用。

原始正文和摘要经AI辅助原文审阅，发现局部范围外推、日期归属及财务口径问题，保留原稿并完成12条最小修订；50组正文与12组摘要断言复审后未发现未解决的证据范围问题。结论针对修订后的报告，不证明自动生成结果可免审发布。Word导出成功、无引用警告，内置渲染中文不可见，记录为 `exported_visual_qa_limited`。技术原始评测不足、政策缺原始条款和跨章重复列为质量跟进。结果见 `evaluation/graph_evidence/embodied_stage4_report_acceptance_2026-10-15.json` 与同名Markdown；最终报告见 `embodied_stage4_outputs/report.md`。

阶段五提取 `report_generation/graph_evidence_contract.py` 的三个纯函数，由现有GraphEvidenceIndex实际复用。审核字段可为空；历史无显式状态不伪造approved，显式pending/rejected仍过滤。节点提及不升级为关系支持，关系身份须完整。同chunk且身份无显式冲突时补全可选身份并合并限定；显式冲突保留供原库解析器告警。已有产业配置、图旁sidecar发现和动态终端判断继续复用。图谱关键词候选通过现有 `rag_type=news` 配置路由到各自词法索引，AI报告资料库保持跳过。

生物制造试点为 `pilot_passed`，仅终端47“新塑料-不可降解”和凯赛生物节点266。完整阅读4个定向chunk，启用3条实体–chunk绑定，一条既有参与关系因不可降解分类证据不足保持pending。三个真实问题均使用 biology / biology_news / hybrid_v2，无回退、错误或身份告警；图谱证据分别保留2、1、3条，限定进入上下文。相对原Hybrid新增均为0，这证明有限复制与限定传播可用，不证明召回质量提升或全行业迁移完成。结果见 `evaluation/graph_evidence/stage5_pilot_biology_2026-10-15.json` 与同名Markdown。

共享契约接入后的相关回归为153 passed、32 subtests passed，日志见 `evaluation/graph_evidence/stage45_20261015/final_regression.log`。


## 复查修正记录

本次复查补正S2.2段首：未来市场预测不再写作当前部署增长，也不扩展到商业服务部署现状；正文修改累计13条（E13），A026覆盖段首预测限定。A034的审阅引用字段由C2修为C12，与正文及原chunk一致。修订前产物保留为`*.before_review_fixes.*`，最初模型原稿仍保留。

代码已限制graph_matches只使用本次实际通过身份校验且在40条读取上限内的引用；同chunk有效实体引用不会恢复被拒绝的关系标注，下行与祖先路径均有回归覆盖。

`--stage report`现调用大纲智能体，按三章报告模板执行大纲、统筹、正文、摘要和Word导出并保存各阶段产物；`--stage export-report`只导出已保存的正文/摘要，不调用生成模型。原始验收报告确实运行过；本次未重新运行完整在线生成，新入口用离线编排测试验证，已真实执行export-report并重新渲染。Word中文仍不可见，视觉验收状态保持受限。


### 重跑完整验收流程

在项目根目录运行，并使用新的输出目录以保留已有审阅结果：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /opt/miniconda3/envs/kunlun/bin/python -u scripts/run_graph_evidence_acceptance.py --stage report --output-dir evaluation/graph_evidence/stage4_replay_20261015 --artifact-python /Users/livictor/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 > evaluation/graph_evidence/stage4_replay_20261015.log 2>&1
```

生成结果仍需来源审阅，脚本不把生成/导出成功等同于来源与视觉验收通过。模型输出不会保证逐字复现历史报告。对已修订的报告仅重新导出：

```bash
/opt/miniconda3/envs/kunlun/bin/python scripts/run_graph_evidence_acceptance.py --stage export-report --output-dir evaluation/graph_evidence/embodied_stage4_outputs --artifact-python /Users/livictor/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
```

本次修复相关回归为161 passed、35 subtests passed，日志为`evaluation/graph_evidence/stage45_20261015/review_fixes_regression.log`。已保存的具身六节与biology三问按新解析语义离线回查均无身份告警，图谱关联与历史产物一致。

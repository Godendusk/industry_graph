# 阶段5 生物制造有限试点

状态：pilot_passed。

已有industry_config biology graph_path/vector_db_path/collection_name=biology_news/rag_type=news，_IndustryGraph自动读取图旁sidecar，GraphHierarchy决定终端，无需重复配置字段。

完整阅读source_candidates.json中的4个原文chunk；启用其中3个entity_mention，不把未明确不可降解的产品原文提升为relationship_support。

启用3个企业节点–chunk绑定，1个既有关系绑定保持pending。真实调用retrieve_external_rag、retrieve_industry_graph、augment_with_graph_evidence；未使用mock。

## 问题1
凯赛生物在新塑料-不可降解环节有哪些生物基聚酰胺产品？请区分企业产品原文与图谱关系线索。

图谱：success；选择环节：新塑料-不可降解；原Hybrid：hybrid_v2；回退：None；错误：None。
最终保留图谱绑定片段2个；相对基线新增0个。
验收：{"retrieval_ok": true, "version": "hybrid_v2", "fallback": null, "hybrid_error": null, "identity_warning_count": 0, "curation_note_count": 2, "failure_reasons": []}

## 问题2
新塑料-不可降解环节中，凯赛生物的生物基聚酰胺工程塑料与连续纤维增强复合材料有哪些产品证据？

图谱：success；选择环节：新塑料-不可降解；原Hybrid：hybrid_v2；回退：None；错误：None。
最终保留图谱绑定片段1个；相对基线新增0个。
验收：{"retrieval_ok": true, "version": "hybrid_v2", "fallback": null, "hybrid_error": null, "identity_warning_count": 0, "curation_note_count": 1, "failure_reasons": []}

## 问题3
凯赛生物生物基聚酰胺有哪些汽车轻量化应用展示？HG/T 6364-2025标准报道说了什么？聚焦新塑料-不可降解环节。

图谱：success；选择环节：新塑料-不可降解；原Hybrid：hybrid_v2；回退：None；错误：None。
最终保留图谱绑定片段3个；相对基线新增0个。
验收：{"retrieval_ok": true, "version": "hybrid_v2", "fallback": null, "hybrid_error": null, "identity_warning_count": 0, "curation_note_count": 3, "failure_reasons": []}

## 范围与限制
仅一个终端环节及一家企业的有限试点，不代表全产业迁移完成。
企业来源中的首创、性能及低碳声称未独立核实；展会展示不等同于订单或规模落地。
图谱新增保留数量仅描述检索行为，不作为质量提升结论。

规格复审后修复同chunk的可选身份合并，并保留显式身份冲突供resolver校验。回归65 passed、7 subtests passed，覆盖sidecar与inline实际入口。本试点全部approved refs身份完整一致，修复不改变已保存真实检索结果，无需再次调用模型。

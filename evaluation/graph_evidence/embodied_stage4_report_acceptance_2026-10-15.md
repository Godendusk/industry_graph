# 具身智能 GraphRAG 阶段四验收

结论：`runnable_quality_followup`。大纲、章节检索、正文、摘要和 Word 导出真实运行完成。阶段五的证据边界门允许进入小范围生物制造试点。

报告为《具身智能产业发展报告》，三章六节，统筹阶段注册21份资料，正文最终保留20份参考资料，30个章节证据实例对应23个唯一chunk。六节均为embodied / embodied_news / hybrid_v2，无legacy回退、hybrid_error或身份告警，四个图谱关联证据块进入章节材料。正式映射保持49个节点链接、42条关系链接、101条引用，对应60个chunk。

## 证据与写作审阅

原始生成结果保留为 `embodied_stage4_outputs/report_bodies.raw.json`、`report_summary.raw.json`、`report.raw.md`。初审发现局部范围外推、网页日期混同报告发布日期、毛利率口径及编辑问题，共完成12条最小修改。50组正文和12组摘要断言经原chunk审阅复核，当前没有未解决的来源边界问题，四类系统性成熟度越界未见。引用均存在且可在本节定位；23个chunk在原库回查正文一致。AI辅助来源审阅不等于外部事实认证。

最终报告为 `embodied_stage4_outputs/report.md`；逐事实记录为 `stage45_20261015/source_review.json`，修改记录为 `embodied_stage4_outputs/report_editor_changes.json`。摘要不显示C符合既有产品规则，其事实来源由审阅记录经正文追踪。

## 验证与限制

阶段四相关回归127 passed、25 subtests passed。新修复保留父link默认/ref优先及多节点、关系、已有Hybrid重复chunk的全部选中限定；验收器按实际graph_matches检查，不要求同chunk未选中关联的备注。

Word导出成功、无引用告警；内置渲染器生成25页，首页中文不可见而拉丁字母及数字可见，状态为`exported_visual_qa_limited`。OOXML中文及修订存在，不代表视觉验收通过。本轮不交付可视排版已合格的承诺。

材料偏研究解读及转载，政策缺原始条款，技术缺统一评测，跨章存在可控重复。因此不记为passed，也不宣称原始自动生成版本可以免审发布。图谱候选进入重排不保证最终留存，资料级引用也不单独证明具体chunk中的所有关系被使用。


## 复查修正记录

本次复查补正S2.2段首：未来市场预测不再写作当前部署增长，也不扩展到商业服务部署现状；正文修改累计13条（E13），A026覆盖段首预测限定。A034的审阅引用字段由C2修为C12，与正文及原chunk一致。修订前产物保留为`*.before_review_fixes.*`，最初模型原稿仍保留。

代码已限制graph_matches只使用本次实际通过身份校验且在40条读取上限内的引用；同chunk有效实体引用不会恢复被拒绝的关系标注，下行与祖先路径均有回归覆盖。

`--stage report`现调用大纲智能体，按三章报告模板执行大纲、统筹、正文、摘要和Word导出并保存各阶段产物；`--stage export-report`只导出已保存的正文/摘要，不调用生成模型。原始验收报告确实运行过；本次未重新运行完整在线生成，新入口用离线编排测试验证，已真实执行export-report并重新渲染。Word中文仍不可见，视觉验收状态保持受限。

本次修复相关回归为161 passed、35 subtests passed，日志为`evaluation/graph_evidence/stage45_20261015/review_fixes_regression.log`。已保存的具身六节与biology三问按新解析语义离线回查均无身份告警，图谱关联与历史产物一致。

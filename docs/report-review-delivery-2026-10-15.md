# 报告审查 Agent 阶段交付说明

## 交付范围

在既有报告生成链路上增强正文审查、摘要一致性核对及最终调整提示。生成结果定位为人工审阅稿，不能保证无需人工核对即可发布。

- 全文检查同节及跨节的重复事实、数字、案例与结论；保留具有不同分析用途的资料复用。
- 以正文逐字引文定位，程序编号授权片段；编辑模型只提供编号和替换文字，程序保留授权片段之外的文字与全部标题。
- 拒绝定位歧义、保留冲突、无效编号、重叠补丁、未知引用和新增明显异常相邻标点；失败保留原文并提示。
- 一次全文检查、受影响小节各一次编辑、一次原问题复核；识别未执行片段，复核发现信息损失时按节恢复原文。
- 传入有预算限制的已引用证据与日期，证据不足只提示，不做全面联网事实核验。
- 摘要保留深度思考，增加基于最终正文的一致性核对；失败保留生成摘要。摘要调整提示进入前端历史和导出。

本提交不包含图谱扩展、检索重构、向量库、环境配置或原始模型调用数据。

## 真实验证

2026-10-15 使用 deepseek-v4-flash 对三份既有真实报告原稿复测审查链路。本次固定原稿验证不重新生成正文或摘要。

|方向|保留小节|采用修改小节|最终状态|
|---|---:|---:|---|
|具身智能|8/8|5|partial|
|低空经济|8/8|7|partial|
|量子科技|8/8|4|partial|

最终27次调用均正常结束，无输出截断。16个采用修改小节用保存的实际补丁重新拼接，正文逐字一致。具身智能原稿的独有企业“南网科技”在修改后保留。

提交前对只含本次暂存内容、其余文件来自HEAD的独立副本执行回归：Python 71项、前端JavaScript 68项全部通过。覆盖正文审查、摘要、报告流程、局部重写、引用、Word导出及前端调整提示；不依赖工作区未提交的图谱和检索改动。

## 已知限制

片段外逐字保留不保证片段内部语义无损。真实样本仍存在：

- 低空报告部分分类及商业闭环判断重复，压缩不充分。
- 量子报告把湖北“计划设立基金”弱化为已有资本通道；部分图谱能力边界限定被替换为不等价的财务披露限定。
- 具身智能仍有机械回指；证据提示可能提醒正文未采用的数据，造成噪声。
- 摘要核对不能纠正正文已经包含的所有错误，字数目标仍可能超出。

`partial`、核对失败及待核实说明必须保留，不能解释为自动质量验收通过。后续优先改进替换前后事实状态、证据边界和句间衔接的语义核对，不扩大为反复整篇重写。

## 验证方式

使用项目Python环境执行：

```sh
LLM_API_KEY='' python -m pytest tests/test_report_review_agent.py tests/test_summary_agent.py tests/test_report_review_flow.py tests/test_report_rewrite_citations.py tests/test_report_review_export.py tests/test_body_agent.py tests/test_report_body_citations.py tests/test_report_citations.py tests/test_word_export_citations.py tests/test_word_export_agent.py tests/test_report_decision_flow.py -q
node --test tests/js/test_industry_report_review.test.js tests/js/test_industry_report_citations.test.js tests/js/test_industry_report_template.test.js tests/js/test_industry_report_navigation.test.js
```

这些回归不调用真实模型，用于验证流程及确定性约束；内容质量依据上面的真实样本对照。

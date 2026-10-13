# 审查接入后的重复代码清理

用户已同意精简重复维护，保留检索、分工、引用和审查职责；不删除前文避重，不扩大为全面重构。

核对结论：正文和重写已共享 build_prior_context。审查使用实际正文段落定位，与事实摘录用途不同，无须合并。前端重写已自动采用，但仍经 pendingRewrite 传递结果，并残留未调用的对比渲染和采用前编辑流程。

实施范围：
1. 提取阶段无关的复用与内容保留规则，供正文、重写、审查引用；各阶段证据和输出格式约束保留。
2. 重写成功结果直接传入 applyIndustryReportRewrite，明确目标小节；去掉 pendingRewrite、旧对比渲染、采用前编辑函数及相关模板文案。
3. 保留成功结果的引用、焦点词、审查说明、摘要失效和历史保存；请求失败不得修改原文。

验证：先补充自动采用、失败保留、目标小节限定的前端回归和共享规则提示回归；确认失败后实施。更新旧测试以覆盖当前手动编辑入口，保留引用清洗断言。最后运行 Python 全量、相关 Node 测试、JS 语法和 diff 格式检查。

不新增模型调用，不关闭摘要思考，不改变生成顺序，不提交或推送。

## 实施结果

已移除 pendingRewrite、renderIndustryReportRewritePreview、updateIndustryReportPendingRewriteText 和 acceptIndustryReportRewrite。请求成功直接调用 applyIndustryReportRewrite(data, section.outline_id)，引用、焦点词、审查说明和历史保存沿原采用逻辑保留。模板改为重写状态与自动更新说明。

COMMON_REUSE_RULES 由正文/重写的 REUSE_RULES 和审查提示共用；检索、分工、引用、前文选择、审查段落索引保持原职责。没有新增模型调用。

验证：Python 全量 506 passed、1 skipped、162 子测试通过。报告引用/审查前端测试21项通过。JS语法及git diff --check通过。全前端测试57项通过、3项失败，涉及 test_industry_report_navigation.test.js 中旧统筹路由预期、备用需求提示、DOM模拟缺少querySelector；本轮未修改对应业务函数，未在本轮扩大处理范围。未运行新的真实模型报告或页面验收，未提交/推送。

## 后续：提交前修复前端三项失败

按用户授权修复：统筹测试更新为 /api/report/coordinator/stream 并读取 SSE 完成事件，验证产业与写作任务状态；布局测试补齐 querySelector 与 dataset；任务卡提交阶段将本次响应 warnings 传入成功提示函数，遇到 report_requirement_fallback 展示后端确认提示，否则保留正常成功提示。不将历史警告复用到后续阶段。

最新验证：前端全量61项通过、0失败；Python全量506 passed、1 skipped、162子测试通过；JavaScript语法和git diff --check通过。前述3项失败已解决。未提交或推送。

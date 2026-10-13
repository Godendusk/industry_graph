# 报告工作树合入本地main记录

2026-10-13按用户授权，在industry_graph-fact-reuse的codex/report-fact-reuse分支合入本地main。

原HEAD为e8131b5，快进至1256bd4，包含186ffe1“统筹agent功能丰富”及动态图谱层级合并提交。未合入远程81ae22e正文分组并行提交，未复制原目录尚未提交的专题资讯接入修改。

合入前，已将tracked差异及untracked文件备份至/Users/livictor/Desktop/industry/report-merge-backup-20261013，并保留名为report-before-main-integration-20261013的Git stash。快进后恢复原改动，没有文本冲突。自动合并产生决策并发与前节依赖的逻辑冲突，已在普通/SSE两入口恢复逐节串行决策，检索并发参数、归一化上限、丰富检索query及动态图谱功能保留。相应稳定性测试保留并发检索断言，将决策阶段断言更新为串行及完整前节传递；测试mock返回新增决策字段。网页并发参数说明同步为“统筹检索并发数”。

验证：kunlun定向141项Python测试通过，24项JavaScript测试通过；JavaScript语法检查与git diff --check通过。覆盖报告决策、协调、普通/SSE、正文、重写、资料分配、引用、历史、动态层级检索/导入/风险及展示。未宣称全仓库测试通过，未调用真实模型或重复生成报告。

业务改动保留未提交，未创建新提交或推送。原main及其未提交RAG代码、向量库、压缩包保留。决策超限、图谱输出截断和专题资料接入问题未在本轮修复。

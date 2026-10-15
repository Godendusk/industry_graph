# 报告审查 Agent 真实样本验证实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 本轮在当前会话按顺序执行，无需新建聊天或派发子 Agent。

**Goal:** 使用当前生产模型配置验证三份固定报告的审查与摘要核对，再通过一份新报告验证完整生成链路，依据实际内容决定是否需要修正代码。

**Architecture:** 固定原稿回放与新报告全链路分开运行。前者隔离审查能力变化，后者验证真实检索、正文、审查、摘要与 Markdown 交付。模型复核结果作为线索，人工逐节对照决定是否存在误删、遗漏或无依据改写。

**Tech Stack:** 现有 Python 后端、DeepSeek 配置、pytest、Node 测试、JSON 实验记录及 Markdown 报告。

---

## 工作目录与边界

- 代码目录：`/Users/livictor/Desktop/industry/industry_graph`。
- 固定输入：`/Users/livictor/Desktop/industry/report-review-evaluation-20261014/{embodied,low_altitude,quantum}/before-review.json`；同目录 `input.json`、`coordinator.json` 提供标题、大纲与行业信息。
- 新建实验目录：`/Users/livictor/Desktop/industry/report-review-validation-20261015/`。若已存在，则新建带本地启动时间后缀的目录，保留旧结果。
- 新建实验脚本：实验目录下 `run_fixed_reviews.py`、`run_fresh_report.py`。实验脚本不进入生产模块。
- 结果：各方向保存 `input-manifest.json`、`after-review.json`、`summary.json`、`calls.json`、`人工对照.md`、`报告.md`；批次保存 `验证结论.md`。
- 本轮只新增计划和实验产物；仅在复现明确缺陷后修改对应生产模块和测试。不重构检索，不清理现有未提交文件，不修改 `.env`，不提交或推送。
- 保留所有标题和小节；允许必要的正文合并、压缩和短句回指，保留独有事实、分析、限定及有效引用。最终 Markdown 必须包含调整与待核实提示。
- 摘要保留现有深度思考配置。证据不足时提示，不补造事实，不扩大为全面联网核验。

## Task 1：建立可比的实验输入与调用条件

**Read:** `llm_client.py`、`report_generation/review_agent.py`、`report_generation/summary_agent.py`，以及三个方向的固定输入。

- [x] 记录代码 HEAD、相关文件的现有改动清单、启动时间、当前模型名称、API 主机、SDK 超时及重试设置；不记录 API 密钥或认证头。不创建哈希或指纹。
- [x] 确认三个原稿包含 `body_sections`、`writing_tasks`、`report_title`、`user_prompt`、`references`，并从原实验元数据读取摘要所需大纲；缺失时明确记录，禁止凭空重建原实验事实。
- [x] 使用当前 `.env` 配置发出一次仅回答 OK 的最小请求。该检查检测服务是否仍无正文返回；若失败，停止依赖模型的任务并保存失败阶段，避免重跑长报告。模型不在 `/models` 列表本身不作为不可用结论，以实际生成结果为准。
- [x] 配置实验进程每次请求 120 秒超时、禁用 SDK 隐式重试，每个方向审查加摘要合计最多 15 分钟；不覆盖模型名，不改生产默认超时。总时限在独立子进程外控制，超时终止该实验进程并保留已写入记录。15 分钟是实验等待上限，不代表业务性能目标。
- [x] 每次模型调用结束即写入阶段、耗时、finish_reason、输出与错误；每个阶段结束即保存结果。日志仅留本地，不提交仓库。

## Task 2：串行回放三份原稿的正文审查与摘要

**Existing entry points:** `review_report_bodies(*, body_sections, writing_tasks, report_title, user_prompt, references)`；`generate_report_summary(report_title, outline, body_sections, industry, template_path)`。

- [x] 创建 `run_fixed_reviews.py`，按 embodied、low_altitude、quantum 顺序启动独立实验进程，直接调用上述入口，使用 `/Users/livictor/Desktop/industry/industry_graph/产业链报告模板.docx`。不重新检索或重新生成原稿正文。
- [x] 调用审查前保存输入清单；调用完成后立即保存完整审查返回对象，包括正文、调整说明、warnings、review 和 verification。
- [x] 以审查最终返回的正文生成摘要，保存摘要结果、`summary_review`、摘要调整说明与 warnings。若审查未完成，明确标注摘要基于保留的正文，不把它记为修正成功。
- [x] 汇总正文与摘要两阶段的调整说明和未解决问题，渲染三份完整 Markdown，附参考资料。无提示时写明本次未产生调整提示；不隐藏失败状态。
- [x] 记录模型调用数、阶段耗时、原稿与成稿字数、小节数量和被修改小节。字数与修改范围只帮助定位，不据此评分或设定压缩率目标。
- [x] 任一方向遇到服务异常时保留结果，做一次最小请求区分服务异常；最小请求失败则停止余下模型实验。若最小请求成功，继续其他方向，将该报告保留为待定位失败，不无限重试。

## Task 3：逐节对照与质量判断

**Create:** 三个方向各自的 `人工对照.md`；批次 `验证结论.md`。

- [x] 先阅读原稿与审查结果，再查看 Agent 的问题与复核记录，避免只复述其自评。对每个被改小节记录具体原文、成稿片段、修改目的，以及独有事实/分析/限定是否保留。
- [x] 阅读未被修改的小节，判断明显跨节重复是否被漏掉。允许同一资料服务于不同论证，不把共享 citation_id 直接判为重复。
- [x] 低空经济：对照 S4.2 与其他章节的“成熟场景推广、成长场景放量、培育场景试点”，判断各处是否承担不同分析任务，是否仍重复整套分类。
- [x] 量子科技：逐处阅读“承接前节所述”及类似回指，确认能够独立理解、指向清楚，且没有通过删除分析制造表面去重。
- [x] 具身智能：逐节检查修改是否必要；对“标准体系已发布”与“安全评测体系缺失”核对对象、时间、适用范围。区分真正矛盾与不同层级表述；只对证据实际支持的疑点提出结论。
- [x] 对每条证据 warning 阅读所指引用和展示片段，区分确有问题、片段不足以判断、提示不成立。来源缺日期或片段截断时不得断言完整资料不存在相应事实。
- [x] 摘要逐句对照最终正文，检查新增结论、统计口径、计划/预测/已实现状态和“待验证”等限定。确认没有思考过程泄漏或引用代号残留，且保持深度思考开启。
- [x] 在结论中直接说明各报告是否可交付及具体保留问题，不用综合评分表；将“调用完成”“模型复核通过”“人工内容判断”分开陈述。

## Task 4：仅修正真实复现的缺陷

**Conditional modify:** `report_generation/review_agent.py`、`report_generation/summary_agent.py`、`static/js/modules/industry_report.js`。

**Conditional tests:** `tests/test_report_review_agent.py`、`tests/test_summary_agent.py`、`tests/js/test_industry_report_review.test.js`，根据实际失败涉及的模块选择。

- 本次不适用：Task 3 发现了真实缺陷，按以下步骤实施小范围修正。
- [x] 若发现复核漏掉误删、错误来源提示、摘要无依据改写或提示丢失，将实际输入片段整理为最小可复现案例，先运行现有函数确认失败。
- [x] 在对应测试文件加入能区分正确与错误行为的失败测试，再实施最小修改。具体测试与补丁由已确认的失败决定，在发现失败后补充到本计划，不预设未知缺陷的修法。
- [x] 对修改的功能运行对应测试，再运行相关回归；若有失败则定位解决。涉及提示展示时才运行前端测试，未改 JavaScript 则不重复语法检查。

相关后端回归命令（用于检测审查修正破坏正文、摘要、引用或导出，失败时修正对应回归再进入真实验证）：

```bash
LLM_API_KEY='' /opt/miniconda3/envs/kunlun/bin/python -m pytest tests/test_report_review_agent.py tests/test_summary_agent.py tests/test_report_review_flow.py tests/test_report_rewrite_citations.py tests/test_report_review_export.py tests/test_body_agent.py tests/test_report_body_citations.py tests/test_report_citations.py tests/test_word_export_citations.py tests/test_word_export_agent.py tests/test_report_decision_flow.py -q
```

涉及前端提示时：

```bash
node --test tests/js/test_industry_report_*.test.js
node --check static/js/modules/industry_report.js
```

- [x] 修改后只回放受影响样本确认效果，并检查已识别的问题是否解决及是否误删内容。仍失败时如实记录，不循环改写报告直到形式通过。

## Task 5：一份新报告的真实完整链路

**Create:** 实验目录下 `run_fresh_report.py` 与 `fresh_ai/` 结果目录。

- [x] 使用“人工智能产业链与国资央企参与路径研判”作为新方向，沿用原实验八小节大纲和研究约束，输入来自旧 `run_reports.py` 中的人工智能配置；仅复用任务定义，不复用其缓存检索包装。
- [x] 调用当前真实统筹与检索入口，开启图谱和外部向量库，记录各节实际检索结果及失败/降级提示。若向量库为空或未接入，定位并明确说明，不将缓存资料视作本次真实检索成功。
- [x] 顺序运行统筹、正文生成、审查、摘要生成及摘要核对，保存各阶段产物和事件。全链路设置独立进程 45 分钟总上限，阶段及时落盘；不运行 Word 导出，本轮交付 Markdown。
- [x] 核对新报告的章节完整性、引用与来源、明显重复、摘要限定和最终调整说明。发现错误时沿用 Task 4 的最小复现与修正方式；外部服务失败则记录阶段和保留内容，不宣称链路通过。

## Task 6：交付与收口

- [x] 交付三份固定原稿修正版、一份新方向报告及一份验证结论，报告缺失时提供实际失败原因，不使用占位报告替代成功产物。
- [x] 验证结论列明真实运行模型、耗时、内容层面的具体改善、未解决问题、代码是否改动和对应测试结果。对尚未证明的效果明确保留判断。
- [x] 若代码有修正，在本计划补充实际修改文件与失败案例；不把历史测试通过写成本轮新结果。
- [x] 按实际产物更新任务勾选状态，向用户提供可点击文件链接和下一步建议。未经用户要求不提交或推送。

## 执行记录：基线复现与最小修正

2026-10-15，当前生产模型 `deepseek-v4-flash` 最小请求正常。固定样本在同一模型下串行回放，具身和量子全文检查均返回 `finish_reason=length`，耗尽 5000 tokens，无法解析完整审查结果；低空正文完成但仍漏掉 S4.2 同节场景分层的多次完整列举。低空摘要核对返回 `length` 且可见内容为空，耗尽 12000 tokens。

据此收敛修正范围：

1. `review_agent.py`：全文审查输出预算改为 12000，仍只检查一次、每节最多改写一次；提示先检查同节再检查跨节，同一事实合并为一个问题；区分写作决策与实际正文；已明确的证据限定不重复提示。不新增相似度机制或循环改写。预算和提示改动用真实样本回放验证，不增加只匹配提示文本的测试。
2. `summary_agent.py`：摘要核对仅遇到截断时，以现有 16000 token 预算重试一次；保留 high 深度思考。连接错误不重试，再次截断保留原摘要并输出失败提示。
3. `tests/test_summary_agent.py`：新增“截断后完成修正”“重试仍截断保留原文”“连接失败不重试”三个行为测试；修改前两项按预期失败，修改后相关 22 项及计划指定后端回归 56 项通过。

实验原始记录保存于 `/Users/livictor/Desktop/industry/report-review-validation-20261015/`。基线完成后归档至其 `baseline/` 子目录，修正后的回放另存于方向子目录，禁止覆盖基线。真实效果仍待回放与逐节对照确认。


追加复现：具身回放存在指定S4.2未产生任何修改、模型仍判全部解决的情况。为此新增确定性检查：指定小节正文与原文完全相同，即使模型称已解决，也补记该项未执行并输出提示，不额外调用模型。新增测试修改前按预期失败，修改后计划指定后端回归57项通过。本轮未改前端，未重复前端测试。保存真实模型输出的离线回放证实：具身23个issue、低空5个issue涉及未修改小节，正文不变，提示已补充；issue有重复，不能作为独立缺陷数量。

连接中断记录单独归档。低空摘要两次生成连接失败，量子在恢复后成功完成正文与摘要核对。成功返回与内容验收分别判断，新人工智能报告正在用真实图谱/向量库执行完整链路。


## 最终执行结果

三份固定样本及一份新AI链路完成，四份均保留8个小节、摘要与最终提示。新AI真实图谱/向量检索8节成功，无统筹降级，链路427.5秒；正文审查状态仍partial，人工内容验收未通过，原因详见实验目录验证结论。低空最终摘要复用同一固定样本此前成功生成版本并对照本轮正文重新核对，来源及连接失败如实记录。摘要核对修正数分别为具身4、低空5、量子4、新AI5。

新增未修改判断的提示去重也由失败测试复现后修正；最终后端57项通过，修改文件diff检查通过。本轮没有改前端或.env，没有提交/推送。具身独有实例误删、低空同节分层复述、量子计划属性与机械回指、新AI主体归属遗漏等问题继续保留为下一轮真实失败样本，不宣称审查质量已完成验收。

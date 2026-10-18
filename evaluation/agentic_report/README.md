# Agentic 产业报告离线验收

本目录定义固定输入与人工核对方式；尚未运行真实模型时，不应将测试通过或脚本运行成功描述为质量提升。

## 对照定义

- baseline：固定章节问题调用当前 `_retrieve_candidates_once`，仍使用 Hybrid v2、GraphRAG 原文关联和关键词候选；在脚本当前进程中临时替换章节检索入口。
- agentic：原样调用生产章节规划、证据评估、一次有界补查和资料分配流程。
- 两侧使用相同模型配置、固定大纲、资料库、top_k、写作流程、重复审阅、声明核对、摘要及 Word 导出。因此这是检索策略及其证据约束的全链路收益对照，不能把全部差异归因于单个规划器，也不代表第三阶段声明核对的单独收益。
- 不恢复生产 compare/legacy 模式，不修改生产检索入口，不生成新索引，不拉取资讯，不写入来源资料。重复审阅和 claim verifier 两侧均启用。

`cases.json` 含具身智能与生物制造两个固定五节小报告，分别覆盖概述、产业链、政策、竞争格局、数据不足。它们作为已经固定的验收大纲输入，脚本不再次调用大纲模型；这不是“质量已获人工确认”的声明。数据不足场景要求核对当前尚未结束的2026全年企业排名和份额，观察是否承认资料与时间限制，而非强行要求产生一个确定答案。

## 执行

从实施代码所在工作区执行，`--project-root` 指向含 `.env`、现有 Chroma、词法索引、本地 embedding/reranker 和摘要模板的资料项目。先做小节对照，再做两份完整报告：

```sh
python scripts/evaluate_agentic_report.py \
  --project-root /Users/livictor/Desktop/industry/industry_graph \
  --output-dir evaluation/agentic_report/runs/sections-20261016 \
  --cases embodied-overview embodied-chain embodied-policy embodied-competition embodied-insufficient \
          biology-overview biology-chain biology-policy biology-competition biology-insufficient \
  --max-workers 1

python scripts/evaluate_agentic_report.py \
  --project-root /Users/livictor/Desktop/industry/industry_graph \
  --output-dir evaluation/agentic_report/runs/reports-20261016 \
  --cases embodied-report biology-report --max-workers 1
```

可通过 `--industries embodied` 限定行业。未传 `--cases` 时运行所选行业的完整报告。`--max-calls 120` 是每个 case、每个对照侧的应用 LLM 调用上限；预算耗尽会记录失败，不会继续发起新模型调用。实际 HTTP 重试由既有 LLM 客户端控制，该数字不包含客户端内部重试，也不是 tokens 或费用限额。

同一进程每个 case 先跑 baseline 再跑 agentic，本地 embedding/reranker 缓存保持复用。首侧可能承担冷加载，所以应结合逐阶段耗时解读，不能把首次冷加载开销算成策略效率差异。写作模型沿用 `.env` 与当前客户端配置；脚本只保存模型名称和模型文件路径，不保存 `.env`、API key、请求头或提示词日志。底层既有客户端可能写自己的运行日志，沿用项目原行为。

中断后给相同命令追加 `--resume`。必须使用相同配置、输入及未变更的原资料元数据与固定副本；否则拒绝复用。脚本从 manifest 回读固定副本路径，从各侧 data_copy.json 回读独立运行副本路径，不重新接回原数据库。升级到副本运行前的旧输出不能续跑，应使用新目录。已成功完成且前序均复用的阶段会跳过，首个重跑阶段后的旧检查点全部失效并重算。每次运行的模型调用记录单独保存，累计成本需汇总 `calls_attempt_*.json`，不能只读取最新一次。续跑后的总耗时只表示本次进程耗时；此前阶段耗时见首次运行结果与调用记录。若确认要更换输入或资料，应使用新的输出目录。

## 结果与失败处理

每个 `case/arm/` 保存：

- `request.json`：完整固定任务与大纲。
- `coordination.json`：生产协调结果，包括计划、实际查询、补查、证据、引用与未解决限制。
- `body.json`：生产审阅后的最终正文、声明核对、资料引用和调整提示；额外按 outline_id 携带协调结果的 evidence_pack/merged_evidence_packs 以供既有导出接口读取。
- `summary.json`、`export.json` 与 Word：最终正文对应的摘要及导出结果。
- `data_copy.json`、`data/`：当前侧独立运行副本及来源、实际复制机制；数据库内部写入限定在这里。
- `result.json`、`failure.json`：每阶段耗时及失败位置，失败阶段返回体仍保存；失败时不继续摘要或导出。
- `calls_attempt_*.json`：每次调用的阶段、模型、耗时、prompt/completion tokens、失败状态；tokens 缺失单独计数，不把未知用量称为零成本。`calls.json` 是当次阶段进度检查点，不用于跨续跑累计。
- `retrieval_attempt_*.json`：章节实际检索次数、工具调用明细和耗时。工具明细含图谱、Hybrid、关键词、图谱原文关联；底层读取量与候选数见 coordination 内既有诊断。

顶层 `manifest.json` 保存配置、fixed_data 固定副本路径与元数据、复制机制，以及原来源文件名、大小、mtime；每个对照侧之后与整个运行结束再次保存元数据。快照范围包括两个行业的完整向量目录、词法索引目录、图谱及其证据 sidecar，不计算哈希。来源文件有新增、移除、大小或mtime变化便停止后续对照，并返回非零退出状态；不要将该次结果作为相同资料快照的验收。

真实试跑确认 Chroma `PersistentClient` 启动读取会改变 SQLite 的 mtime，因而脚本现在不会用原数据库初始化客户端。它先把所选行业的 graph_data.json、graph_evidence_links.json、完整 vector 目录与 lexical 目录复制到 output/fixed_data；每个 case 的每侧再从此固定副本创建独立 data/ 副本。Mac 使用 APFS `cp -cRp` COW 克隆（`-p` 保留词法索引所需mtime）；其他平台使用普通 `shutil.copytree/copy2`。脚本在复制前输出实际机制、来源与目标，并把机制记入 manifest/data_copy.json；Mac克隆失败会报错，不会悄悄退化为大规模普通复制。副本只含所选行业资料，不复制模型、.env或摘要模板。

词法 READY 标记包含数据库绝对路径，因此每份副本仅重定位其 source 字段；其他签名、revision和资料正文保持不变。模型、.env和摘要模板仍从 --project-root 读取。Chroma 的既有按行业缓存按真实 data_root 分组隔离，baseline 与 Agentic 同名行业不会复用另一侧的数据库客户端。本地 embedding/reranker 保持共用缓存。各运行副本的 SQLite 内部mtime变化不参与原资料稳定性判定；原资料仍在首次复制前后、每侧结束与整个运行结束严格比较元数据。fixed_data 本身不供 Chroma打开，续跑也检查其未变更。

检索返回 error 不会当成“正常零资料”继续。真实零命中仍可进入数据不足写作；是否诚实披露限制必须人工检查。模型核对结果不是人工验收答案。`generated_pending_human_review` 只代表链路产物生成，未声明内容正确。

## 人工核对

复制 `human_review_template.md` 到具体 run 目录，填写核对人、时间、逐条来源引用与判断。既要记录改善，也要记录退步；不按证据条数、模型自报信心或覆盖百分比宣称通过。关键声明出现新增无依据事实时，修正相关生产实现后重跑受影响 case。

离线测试不消耗模型：

```sh
python -m pytest -q tests/test_agentic_report_flow.py
```

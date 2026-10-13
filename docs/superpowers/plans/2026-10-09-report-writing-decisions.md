# 产业报告结构化写作决策与全报告协调实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking。用户已于后续消息授权按照本计划实施；不自动提交、推送或真实模型调用。

**Goal:** 用简短结构化决策替代长任务书，逐节传递分工，并通过一次有长度预算的全报告协调减少重复展开及预定结论越界。

**Architecture:** 保留检索、分配、登记引用、顺序正文流程。新纯模块负责决策合同、备用、分工记录和正文指令；新协调模块负责一次模型调用及有效调整。coordinator_agent连接两者，普通和SSE入口共享生成/协调逻辑，最终任务通过现有网页和历史路径保存。

**Tech Stack:** Python、现有LLMClient与structured_output、Flask API/SSE、原生JavaScript、pytest/unittest与Node test；本机conda kunlun。

---

## 0. 执行前提与范围

先读 `docs/superpowers/specs/2026-10-09-report-writing-decisions-design.md`。执行工作树为 `/Users/livictor/Desktop/industry/industry_graph-fact-reuse`，分支codex/report-fact-reuse，已含上一轮未提交改动。不得从HEAD另开干净目录而丢掉上一轮实现。

- [x] 运行两个目录的 `git status --short`，读取新增相关差异，保留上一轮变更及原目录的RAG/build_vector_db.py、external_rag/retriever.py、向量库、压缩包、tools和其他测试。检查目的是发现实施期间新增改动；若相关文件已变更，以实际差异调整方案，不能覆盖。
- [x] 仅在用户要求执行后修改代码；仅在用户要求提交时显式列出代码和测试文件提交，不使用git add .，不提交实际运行结果/凭据/向量库/压缩包。
- [x] 以下所有单元测试mock模型，先断言目标失败再修复；不用base环境。真实验收单独授权，不沿用此前“一次真实运行”授权自动再跑。

已有基线：59项Python定向检查通过，JS引用10项通过。JS导航已有两项失败：仍预期非流式统筹接口、需求备用提示不一致。实施若碰到这两项，核对与此前记录相同后报告，不为交差改掉断言或扩展本期范围。

## 1. 文件与职责

| 文件（相对工作树） | 操作与职责 |
|---|---|
| report_generation/writing_decisions.py | 新建：决策验证、备用、正文提示编排、简短分工记录、串行单节决策调用 |
| report_generation/task_coordination.py | 新建：压缩协调输入、一次协调调用、调整应用和诊断 |
| report_generation/coordinator_agent.py | 修改：接入此前分工、统一结束协调，替换长任务书生成；保留检索分配 |
| report_generation/body_agent.py | 修改：有决策时重建最终指令，旧任务使用原prompt |
| static/js/modules/industry_report.js | 修改：协调进度、最终任务替换、现有状态显示与诊断保存 |
| tests/test_report_writing_decisions.py | 新建：合同、长度、备用、分工和提示测试 |
| tests/test_report_task_coordination.py | 新建：协调成功/失败/部分有效/预算测试 |
| tests/test_report_coordinator_citations.py、tests/test_coordinator_stability.py | 修改：普通/SSE集成、调用次数、警告汇总和原资料不变 |
| tests/test_report_body_citations.py、tests/js/test_industry_report_citations.test.js | 修改：正文最终决策及旧任务、网页事件与历史保存 |
| tests/fixtures/report_writing_decisions_20261007.json、tests/test_report_repetition_replay.py | 新fixture和回放：真实重叠材料、决策前后输入可追溯 |

backend_server.py原则上不改：已有接口透传统筹返回对象；执行时核对，无须新增endpoint。不增加通用Agent框架，不拆分无关代码。

## 2. 数据合同、预算与方法

writing_task保留原title、outline_id、检索、材料、warnings及writing_system_prompt；新增writing_decision。模型单节输出顶层即以下对象，不再输出writing_system_prompt或整段结论：

```json
{
  "section_question": "既有组织资源如何转化为具身智能协作能力？",
  "evidence_uses": [
    {"topic": "中国移动具身智能产业联盟", "basis": "external", "citation_ids": ["C14"], "use": "分析组织载体的潜在用途", "support_limit": "成立事实不能证明协作成效"}
  ],
  "content_scope": {
    "full_exposition": [],
    "carry_over": [{"topic": "联盟成员和三项任务", "section_id": "S3.1", "use": "一句承接组织基础"}]
  },
  "judgment_limits": ["缺少项目实施结果，不下协作已经成功的结论"]
}
```

basis取external或graph；external的citation_ids必须非空且全部属于当前分配材料；graph允许空数组、且当前graph_retrieval成功，use/support_limit受统一“图谱只支持关系”规则约束，不把图谱当外部引用。允许evidence_uses为空（无证据或备用），不能因此编造材料。限制最多4个用途、3个完整展开对象、3个承接对象、3个判断边界；question<=100字符，topic<=60，use/support_limit/单条limit<=120。全决策compact JSON（ensure_ascii=False,separators=(',',':')）<=1000字符；超限拒绝不截断。

full_exposition是具体对象名称的字符串数组；carry_over是示例所示对象数组；judgment_limits是字符串数组。四项字段必须存在，evidence_uses/content_scope中的列表可以为空；support_limit允许空字符串，不机械添加警告。question、topic、use必须非空。

carry_over.section_id可以是全篇大纲中的后节，不能是自身或不存在的小节。程序验证结构和来源资格，不能验证语义真假；不使用标题相似度合并、不做哈希/评分。

新模块所有计划中的调用名：

```python
# writing_decisions.py
compact_json(value) -> str
validate_decision(value, task, outline_ids) -> dict  # 返回规范化副本，失败raise ValueError
fallback_decision(task) -> dict
render_decision_prompt(decision) -> str
build_prior_ledger(tasks) -> str
request_decision(task, user_prompt, report_title, outline_context, previous_tasks, outline_ids) -> dict
# request_decision返回decision/status/warnings；仅一次llm.query_result

# task_coordination.py
build_coordination_payload(tasks) -> dict
apply_coordination_changes(tasks, changes, outline_ids) -> tuple[list, list, list, list]
# tuple为新tasks、changed_ids、rejected_ids、warnings
coordinate_writing_tasks(tasks) -> tuple[list, dict, list]
# tuple为最终tasks、coordination诊断、warnings
```

常量：MAX_DECISION_CHARS=1000、MAX_PRIOR_LEDGER_CHARS=8000、MAX_COORDINATION_INPUT_CHARS=24000。初始值是实施参数，真实复测记录实际大小和耗时；不承诺固定秒数。协调预算计算整个payload实际JSON，system_prompt保持固定短文本，不能把漏算的需求/原文另塞入user_prompt。

### Task 1：实现结构、验证和简短正文指令

**Files:** 新writing_decisions.py；新tests/test_report_writing_decisions.py。

- [x] 写纯函数失败测试。检测缺字段/错误编号/自承接/过长输出；出现这些失败时应备用，而不是把无效指令送给正文。

```python
import copy
import pytest
from report_generation import writing_decisions as wd

def task():
    return {'outline_id':'S3.2','title':'资源禀赋','graph_retrieval':{'status':'skipped'},
            'external_rag_retrieval':{'evidence_blocks':[{'citation_id':'C14','text':'联盟成立'}]}}

def decision():
    return {'section_question':'组织资源如何转化？',
            'evidence_uses':[{'topic':'中国移动具身智能产业联盟','basis':'external',
              'citation_ids':['C14'],'use':'分析组织载体','support_limit':'成立不证明成效'}],
            'content_scope':{'full_exposition':[], 'carry_over':[
              {'topic':'联盟成员','section_id':'S3.1','use':'短句承接'}]},
            'judgment_limits':['不据行业短板评价央企群体能力']}

def test_decision_retains_qualified_evidence_and_scope():
    d=wd.validate_decision(decision(),task(),{'S3.1','S3.2'})
    assert d['evidence_uses'][0]['citation_ids']==['C14']
    assert wd.validate_decision(d,task(),{'S3.1','S3.2'})==d

@pytest.mark.parametrize('fault',['foreign_citation','self_scope','missing_question','long_use'])
def test_invalid_decision_is_rejected(fault):
    d=decision()
    if fault=='foreign_citation': d['evidence_uses'][0]['citation_ids']=['C99']
    if fault=='self_scope': d['content_scope']['carry_over'][0]['section_id']='S3.2'
    if fault=='missing_question': d.pop('section_question')
    if fault=='long_use': d['evidence_uses'][0]['use']='长'*121
    with pytest.raises(ValueError): wd.validate_decision(d,task(),{'S3.1','S3.2'})
```

- [x] Run `conda run --no-capture-output -n kunlun python -m pytest -q -p no:cacheprovider tests/test_report_writing_decisions.py`，新模块缺失时失败。
- [x] 实现compact_json及validate_decision：按上述合同显式检查dict/list/string、字符和条数；规范化空白、列表精确去重；对未知顶层字段拒绝，避免模型把旧长prompt混入新合同。不用兼容新旧模型输出的双解析。深拷贝，保证不改原task和证据。
- [x] 实现render_decision_prompt与fallback_decision，核心输出内容如下；各数组遍历输出短行，不把原文传入formatter：

```python
COMMON_DECISION_RULES = '''围绕本节问题作答，自行组织自然段，不预设必须得出的结论。
已展开背景通常短句承接，同一资料允许支持不同分析用途。
无新增分析或证据不足时允许缩短，必要时说明现有公开材料不足以判断。
原始材料是事实依据；任务书和前节分工记录不是事实证据。
只能使用当前材料真实的[C数字]；未列为重点的当前证据也可用于符合本节问题的新分析。
区分事实、分析和待验证条件，不把建议反推为现实问题，不把行业短板套到央企群体。
图谱只证明记录的产业关系，不证明技术水平、经营状况或实施成效。'''

def fallback_decision(task):
    return {'section_question':f"围绕“{task['title']}”回答本节问题。",
            'evidence_uses':[], 'content_scope':{'full_exposition':[], 'carry_over':[]},
            'judgment_limits':['仅据当前材料判断；证据不足则说明，不预设排名、成功成效或群体能力结论。']}
```

备用问题过长时保留通用“回答当前二级标题的问题”，标题本来已在正文user_prompt，不截断事实。render_decision_prompt包含四段决策和COMMON_DECISION_RULES，不包含固定三段材料清单；REUSE_RULES仍由body追加。
- [x] 补测graph用途仅在图谱成功时可用、无证据空列表合法、决策整体超限、formatter不复制当前证据全文、备用同结构且允许缩短。Run纯函数测试，预期全部通过。

### Task 2：串行单节决策与此前分工记录

**Files:** writing_decisions.py、coordinator_agent.py、tests/test_report_writing_decisions.py、tests/test_report_coordinator_citations.py。

- [x] 写失败测试：两节调用第二节必须看到第一节编号、问题、完整展开对象和用途，不能看到其原始材料或判断结论；前节安排不能被描述成证据。

```python
from unittest.mock import patch
from llm_client import LLMQueryResult

def test_prior_ledger_is_arrangement_not_evidence():
    previous=task() | {'outline_id':'S3.1','writing_decision':decision()}
    previous['external_rag_retrieval']['evidence_blocks'][0]['text']='不可进入记录的原文'
    ledger=wd.build_prior_ledger([previous])
    assert 'S3.1' in ledger and '分析组织载体' in ledger
    assert '不可进入记录的原文' not in ledger
    assert '不据行业短板评价央企群体能力' not in ledger

def test_single_model_call_has_decision_contract_and_prior_ledger():
    response=LLMQueryResult(content=wd.compact_json(decision()),finish_reason='stop')
    with patch.object(wd.llm,'query_result',return_value=response) as call:
        r=wd.request_decision(task(),'需求','标题','S3.1 布局\nS3.2 资源',[],{'S3.1','S3.2'})
    assert r['status']=='generated' and call.call_count==1
    assert 'writing_system_prompt' not in r['decision']
    assert call.call_args.kwargs['extra_body']=={'thinking':{'type':'disabled'}}
```

- [x] Run任务书测试，预期新接口未实现或不传记录失败。
- [x] build_prior_ledger序列化每节 `{outline_id, section_question, full_exposition, evidence_uses:[{topic,use}]}`。带固定前缀“此前写作安排，不是事实证据；以全篇大纲选择最适合的小节，允许把完整展开留给后节；冲突交最终协调”。不传judgment_limits、引用原文、长prompt；超过8000时raise ValueError。
- [x] request_decision构造单节提示，包含需求/标题/全篇大纲、本节图谱和RAG上下文、ledger及JSON合同，要求决策约400—600字符。强调不重复两份材料清单、不预设“央企弱/机制未打通/成功案例”等结论。调用如下：

```python
result = llm.query_result(user_prompt=decision_user_prompt,
    system_prompt='你是产业报告小节写作决策生成器。只返回规定JSON，不写正文。',
    max_tokens=3000, reasoning_effort=None,
    extra_body={'thinking':{'type':'disabled'}},
    extra_log_info=f"report_generation.writing_decisions outline={task['outline_id']}")
```

空/length/error/解析/验证/ledger超限时不重试，返回fallback_decision及warning：stage=writing_prompt_generation、outline_id、reason（empty/length/model_error/invalid_decision/prior_budget），不输出密钥；沿用parse_json_object。
- [x] 修改 `_build_writing_task_from_retrieval` 增加previous_tasks、outline_ids参数，先构造完整task（尤其当前mapped evidence），调用request_decision，保存writing_decision与writing_prompt_status，render指令。focus_terms_for_task以决策topic候选列表进行现有grounding，再接引号回退，不直接信任未grounding的topic。
- [x] 普通和SSE for循环均传递 `writing_tasks[:index]` 和全outline_ids；提前失败路径 `_writing_task_unhandled_error_response`也构造结构备用并render。删除新任务所用旧 `_generate_writing_system_prompt` / `_fallback_writing_system_prompt` 长清单逻辑，相关mock改为request_decision，不保留第二条模型输出路径。
- [x] 合并task warnings形成report warnings，避免当前普通与SSEwarning_groups引用差异漏掉单节fallback警告。更新稳定性测试mock；补测length、空、invalid JSON、不完整字段/引用超限均只一次调用，备用记录也传给后节，failed retrieval不编造证据。Run决策、统筹、稳定性测试，预期全通过。

### Task 3：一次全报告协调与输入预算

**Files:** 新task_coordination.py、新tests/test_report_task_coordination.py。

- [x] 写失败测试：payload不能含原材料/graph实体/raw_output/旧prompt，只含outline和decision、allowed_citation_ids；超预算不得调用，length/异常不得重试。

```python
from report_generation import task_coordination as tc
from report_generation import writing_decisions as wd
from unittest.mock import patch
from llm_client import LLMQueryResult

def test_review_payload_has_no_raw_evidence_or_long_prompt():
    t=task() | {'writing_decision':decision(),'writing_system_prompt':'旧长任务书'}
    t['external_rag_retrieval']['evidence_blocks'][0]['text']='原始材料全文'
    payload=tc.build_coordination_payload([t])
    text=wd.compact_json(payload)
    assert '原始材料全文' not in text and '旧长任务书' not in text
    assert payload['sections'][0]['allowed_citation_ids']==['C14']

def test_budget_skips_call_and_preserves_tasks():
    tasks=[task() | {'writing_decision':decision()}]
    with patch.object(tc,'MAX_COORDINATION_INPUT_CHARS',10), patch.object(tc.llm,'query_result') as call:
        final,meta,warnings=tc.coordinate_writing_tasks(tasks)
    assert not call.called and final==tasks
    assert meta['status']=='skipped_budget' and warnings
```

- [x] Run `conda run --no-capture-output -n kunlun python -m pytest -q -p no:cacheprovider tests/test_report_task_coordination.py`，预期缺新模块失败。
- [x] payload内容 `{outline:[{outline_id,parent_title,title}], sections:[{outline_id,decision,allowed_citation_ids}]}`；不要额外传report需求/全文，只按大纲协调已有决策。检查compact_json长度>24000时跳过且warning，保留全部tasks，不静默截掉章节。
- [x] 模型系统提示包含：选择最适合完整介绍的小节；其余承接或新用途；取消缺证据的预定结论、允许缩短；不强制每节新观点；不改大纲/材料/编号；不是原文事实核验。只输出以下结构：

```json
{"changes":[{"outline_id":"S3.2","reason":"布局节已完整介绍成员，本节转向转化条件", "decision":{"section_question":"资源怎样转化？","evidence_uses":[],"content_scope":{"full_exposition":[],"carry_over":[{"topic":"联盟成员和任务","section_id":"S3.1","use":"短句承接"}]},"judgment_limits":["没有实施结果，不判断协同成效"]}}]}
```

每个调整携带完整四字段，reason非空<=160字符；顶层只能changes数组，无调整返回[]。应用层只一次query_result（max_tokens=5000、reasoning_effort=None、thinking disabled、extra_log_info=report_generation.task_coordination）。输入超预算0次。网络SDK原有重试不改。
- [x] 调整应用按outline_id查找原task，用Task1验证方法校验新decision；引用资格按原材料，不按旧evidence_uses（可以改变当前已选证据的用途）。不允许给无graph资料的任务添加graph用途。重复outline_id调整全部拒绝该ID、未知ID拒绝，其他有效调整继续；完整新decision替换后重建prompt和grounded focus，不改材料数组。
- [x] 顶层/changes类型无效、模型失败、length、空输出保留原tasks并warning；部分无效status=partial，有效全应用status=completed。不再做语义评分或第二次协调。metadata固定：status（completed/partial/failed/skipped_budget）、input_chars、elapsed_seconds、changed_outline_ids、rejected_outline_ids。valid changes=[]算完成，无变更。
- [x] 加成功、empty changes、一个有效一个foreign C、重复ID、空reason、错误顶层、模型异常/length等测试；断言原task未被原地改、选中材料逐字段不变、C编号不变、invalid项有warning；Run新测试，预期通过。

### Task 4：普通及SSE统一结束协调

**Files:** coordinator_agent.py、tests/test_report_coordinator_citations.py、tests/test_coordinator_stability.py。

- [x] 写失败集成测试：两节mock顺序决策、一次mock协调，普通与SSE最终任务相同，最终prompt反映协调改动；最终completed不能提前发出。
- [x] 在普通返回前调用coordinate_writing_tasks；在SSE最后一个task_completed之后、最终completed之前调用。SSE原task_completed可以显示初稿，但新增coordination_started/coordination_completed事件（status、metadata、warnings，不重复发送全材料）；最终completed必须发送完整最终writing_tasks及coordination。

```python
# 普通结束阶段
writing_tasks, coordination, review_warnings = coordinate_writing_tasks(writing_tasks)
warnings = [w for t in writing_tasks for w in t.get('warnings', [])] + review_warnings
# 回包在原字段之外增加coordination

# SSE结束阶段
# task_completed仍为单节初稿；客户端必须等待最终completed才允许正文
event_queue.put({'event':'coordination_started','status':'started'})
writing_tasks, coordination, review_warnings = coordinate_writing_tasks(writing_tasks)
event_queue.put({'event':'coordination_completed', 'coordination':coordination,
                  'warnings':review_warnings})
# 原completed写入最终writing_tasks、coordination与完整warnings
```

代码块第二段放进现有producer结束阶段，保持其函数内缩进。fallback_count仍按单节writing_prompt_status统计，即使协调修正备用任务也不改写其生成来源；另存decision_review_status（unchanged/adjusted）只表示是否改动，不能冒充事实审查成功。
- [x] 正常19节mock验证调用上下文：19次writing_decisions+1次task_coordination；图谱调用另外计，不把总请求说成20。决策失败仍保留19节，协调失败仍能正文，无追加单节调用。测试所有资料citation登记发生在单节决策前。
- [x] 更新现有统筹测试对新增事件和mock接口的预期，保留分配、补检索、references稳定、失败warnings等原断言。Run统筹与稳定性测试，预期通过。

### Task 5：正文采用最终决策，历史任务仍可用

**Files:** body_agent.py、tests/test_report_body_citations.py。

- [x] 写失败测试：task包含协调后writing_decision和旧冲突prompt时，正文实际system_prompt只用render_decision_prompt(final_decision)，不含旧“第二段重列联盟成员”；当前原始资料仍完整出现在user_prompt。

```python
from report_generation import body_agent

def test_final_decision_overrides_stale_prompt():
    t=task() | {'writing_decision':decision(),
      'writing_system_prompt':'旧安排：第二段重列联盟成员',
      'parent_level1_id':'S3','parent_level1_title':'布局',
      'graph_retrieval':{'status':'skipped','graph_context_text':''}}
    t['external_rag_retrieval']['rag_context_text']='[C14] 原始材料'
    with patch.object(body_agent.llm,'query_result',return_value=LLMQueryResult(content='组织载体分析[C14]。',finish_reason='stop')) as call:
        r=body_agent.generate_body_section(t,'需求','标题')
    assert r['status']=='success'
    assert '旧安排' not in call.call_args.kwargs['system_prompt']
    assert '组织资源如何转化' in call.call_args.kwargs['system_prompt']
    assert '[C14] 原始材料' in call.call_args.kwargs['user_prompt']
```

- [x] body选择规则：有writing_decision则render；旧任务无该字段则现有writing_system_prompt。新字段存在但损坏时返回section error+具体warning，不静默执行过期旧prompt；渲染器检查合同形状，证据和全篇编号验证已在统筹完成，body不重复模型审查。
- [x] 保留原正文重试、实际前文build_prior_context和引用清洗；不另用“计划将写”的内容代替实际前文，不因content_scope而删除当前evidence_blocks。
- [x] 补旧任务无字段正常生成、协调后的focus词来自最终decision、跨来源事实避重、当前材料引用资格不变的测试。局部重写不自动套任务书：已有用户指令/材料路径保持，测试不要求它自动重新协调全报告。Run正文、重写引用及body_agent测试，预期通过。

### Task 6：网页协调状态、最终任务与历史诊断

**Files:** industry_report.js、tests/js/test_industry_report_citations.test.js。

- [x] 写JS入口失败测试：task_completed初稿后，coordination_started仍处统筹busy阶段；coordination_completed显示完成/部分调整/跳过原因；最终completed替换tasks，历史保存最终decision和coordination，不保存仅初稿状态。
- [x] 在workspace初始化/reset/history_record/history_load添加coordination（默认null）；writingTasks现有对象保留全字段，不重造只有prompt的对象。
- [x] handleIndustryReportCoordinatorStreamEvent增两分支，沿用现有状态UI：

```javascript
if (eventName === "coordination_started") {
    setIndustryReportStage("coordinator", "正在协调全报告小节分工");
    return event;
}
if (eventName === "coordination_completed") {
    industryReportWorkspace.coordination = event.coordination;
    appendIndustryReportWarnings(event.warnings);
    setIndustryReportStage("coordinator", industryReportCoordinationText(event.coordination));
    return event;
}
```

新增industryReportCoordinationText(meta)：completed“分工协调完成：调整N节”；partial“分工协调部分完成：调整N节，保留M节原决策”；failed“分工协调失败，保留逐节决策”；skipped_budget“分工协调输入超预算，未调用模型，保留逐节决策”。最终完成状态保留该摘要和原fallback_count；普通返回路径也接收coordination。不把partial显示成全篇审阅通过。
- [x] 原task_completed进度文字改“初稿任务已生成”，所有任务初稿完成不触发正文，现有prepare await stream completed边界保留。旧history无coordination保持null，无后台调用。
- [x] Run `node --test tests/js/test_industry_report_citations.test.js`，预期新增协调、历史、旧任务与原引用测试通过。`node --check static/js/modules/industry_report.js`检测新增分支语法错误；失败则修语法，不扩大UI改造。

### Task 7：真实材料回放与一次真实质量验收准备

**Files:** 新fixture、tests/test_report_repetition_replay.py、本文执行记录。

- [x] 从 `/Users/livictor/Desktop/industry/report-validation-20261007/coordinator.json`裁取S1.1/S1.3/S3.1/S3.2/S3.4/S4.4/S5.2的标题、编号、已选evidence_blocks、图谱是否成功。剔除raw_output/完整图谱/配置；保留材料原文用于离线观察。人工写的决策必须标明synthetic_decision，不冒充真实模型输出。
- [x] mock S3.1完整介绍联盟、S3.2资源用途、S5.2协同建议，assert后节ledger包含分工不含原文，协调把成员列表仅留布局节、S4.4不安排“机制未打通”预定结论。该测试验证传递与最终指令，不证明模型生成质量。真实融资句仍由已有repetition_context回放覆盖。
- [x] 最终定向命令：

```bash
conda run --no-capture-output -n kunlun python -m pytest -q -p no:cacheprovider tests/test_report_writing_decisions.py tests/test_report_task_coordination.py tests/test_report_coordinator_citations.py tests/test_coordinator_stability.py tests/test_report_body_citations.py tests/test_body_agent.py tests/test_report_rewrite_citations.py tests/test_report_repetition_context.py tests/test_report_repetition_replay.py tests/test_material_allocator.py tests/test_report_citations.py tests/test_word_export_citations.py
node --test tests/js/test_industry_report_citations.test.js
node --check static/js/modules/industry_report.js
git diff --check
```

这些检查分别检测合同/预算/调用次数、普通SSE一致、最终指令、旧报告、资料与引用回归、网页保存和格式错误；失败则修对应路径。已知导航两项原有失败在实施记录保留，不宣称全仓库通过。通过后不无理由扩大检查。
- [x] 独立代码审阅仅本期差异，关注预算漏算、协调前后任务串用、warnings漏汇总和资料丢失；实际问题修复后只复测受影响检查。未经授权不提交/合并。
- [ ] 用户授权真实复测后，在新结果目录沿用原19节需求/大纲、模型/资料开关，完整保存候选、初稿决策、前节ledger、协调payload与响应、最终decisions、正文、warnings及各阶段耗时。单独记录协调input_chars、prompt_tokens、completion_tokens、结束原因与变更小节数。不加入原历史，不覆盖20261007记录，不额外生成摘要/审稿调用。
- [ ] 人工对照：联盟成员任务是否只完整介绍一次而其他节有新用途；融资比例是否不再完整重铺；500AI场景是否不变成具身智能项目及数据接口；政策建议是否不反推现状；图谱名单是否不转成技术水平评价；证据不足节是否真的缩短。未达到则定位初稿决策/协调决策/正文执行哪层错误，不因status成功宣告完成，不自动加审稿循环。

## 3. 完成报告须明确的边界

- 报告程序结构校验通过，不代表事实核验；协调看不到原文，不能承诺纠正所有证据误读。
- 新增一次协调应用层调用；无需增加每节重写调用。耗时用实测说明，不承诺因任务书变短总体更快。
- 历史旧任务继续原路径，不迁移、不收费回补。方案C同源处理、图谱截断和[ C10]格式问题另行讨论。
- 每完成一项在本计划勾选，记录实际测试计数、真实运行是否获授权及完成状态、未解决限制。业务代码实施与真实质量验收分别报告，不混用“已完成”。

## 4. 计划自审记录

2026-10-09已按已确认设计核对覆盖：四字段合同→Task1；串行分工→Task2；一次协调与预算/部分有效应用→Task3；普通与SSE收敛及warnings→Task4；最终正文与旧任务→Task5；网页进度及历史→Task6；真实回放与验收→Task7。未留下未定接口或待补方案。代码示例中的task()/decision()为Task1测试数据工厂，在需要的测试模块内定义相同最小数据，不作为生产公共接口。

计划编写时仅新建本文与配套设计，未修改业务代码。后续用户授权实施后的记录见下文。

## 5. 实施记录（2026-10-09）

代码及离线流程验收已完成；真实模型质量验收待另行授权。所有修改保留在codex/report-fact-reuse工作树，未提交、合并或推送。原目录的RAG代码、向量库、压缩包和其他未提交内容未改动。

- 新增writing_decisions.py、task_coordination.py；普通/SSE接入串行决策及一次有预算的协调，正文使用最终结构决策，旧任务沿用原提示。网页等待最终任务并保存协调诊断。
- 新增test_report_decision_flow.py及真实材料裁取fixture（7节、70个已选片段）。fixture中的synthetic_decision明确为人工构造；mock回放验证联盟完整介绍留在S3.1、其他节改为不同用途，以及组织机制不预设结论，资料逐字段不变。这不证明真实模型会遵循。
- 调用次数测试确认19节为19次单节决策+1次协调，无图谱模型调用的mock条件下总计20次；真实图谱检索调用另外计算。
- 规格审阅发现协调期间可以手动保存初稿历史，已禁用按钮并阻止该保存入口；正文完成后的silent保存不受影响。
- 代码审阅发现删除中间章节/小节再添加会生成重复编号，新增编号改为当前最大后缀加一，不重排原编号。已有重复任务编号时协调0次调用，保留原任务并明确warning，防止调整串用。相关回归先复现失败再修复。
- 集成中修正协调模块错误新建LLMClient的问题：使用与单节决策及既有流程相同的配置实例，不额外改变模型配置。

最终验证：kunlun Python定向115项通过；Node引用/协调/历史测试17项通过；JavaScript语法检查和git diff --check通过。最终Python命令为Task7所列命令加tests/test_report_decision_flow.py；所有模型请求被mock，未产生真实生成费用。未宣称全仓库测试通过；已有导航两项基线失败未在本期重跑或修改。

本期未运行真实报告，未测真实耗时和token消耗；未验证真实正文重复改善幅度。真实验收沿用Task7待办中的新结果目录、过程保存和人工对照要求，不增加全文审稿调用。图谱截断、同源资料识别及[ C10]格式问题继续独立处理。

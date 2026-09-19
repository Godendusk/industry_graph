# Task-Card Reliability and LLM Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover report task cards when model output is empty or truncated without losing a valid card, and remove LLM credentials from tracked source.

**Architecture:** JSON task-card generation and requirement generation stay separate. The requirement generator will use a bounded prompt, retry only itself once, then supply an editable fallback plus warning. An additive metadata result exposes completion reason/token usage while existing `llm.query()` callers keep receiving strings.

**Tech Stack:** Python 3.10, Flask, OpenAI SDK, `unittest`, Node test runner, `python-dotenv`.

---

## File structure

- `llm_client.py`: metadata-bearing model responses and environment/TLS configuration.
- `report_generation/task_card_agent.py`: concise output validation, targeted retry, fallback warning.
- `backend_server.py`: task-card action log metadata.
- `static/js/modules/industry_report.js`: fallback warning presentation.
- `tests/test_task_card_agent.py`: task-card empty/truncated/retry/fallback tests.
- `tests/test_llm_client_configuration.py`: response metadata and environment tests.
- `tests/js/test_industry_report_navigation.test.js`: fallback UI tests.
- `.env.example`, `environment.yml`, `DEPLOYMENT.md`: local setup documentation.

### Task 1: Add model completion metadata

**Files:**

- Modify: `llm_client.py:1-207`
- Create: `tests/test_llm_client_configuration.py`

- [x] **Step 1: Write the failing metadata tests**

```python
def test_query_result_exposes_empty_content_and_length_reason(self):
    client = _client_with_fake_completion(
        content=None, finish_reason="length", prompt_tokens=400, completion_tokens=1800
    )
    result = client.query_result("需求", system_prompt="系统", max_tokens=900)
    self.assertEqual(result.content, "")
    self.assertEqual(result.finish_reason, "length")
    self.assertEqual(result.completion_tokens, 1800)

def test_query_keeps_the_existing_string_contract(self):
    self.assertEqual(_client_with_fake_completion("正文", "stop").query("需求"), "正文")
```

- [x] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_llm_client_configuration.LLMQueryResultTest -v`

Expected: FAIL because `query_result()` is absent. It proves task-card code cannot currently distinguish an empty visible response from a completion stopped at its output limit.

- [x] **Step 3: Implement the additive response type**

```python
@dataclass(frozen=True)
class LLMQueryResult:
    content: str
    finish_reason: str
    prompt_tokens: int | None
    completion_tokens: int | None
    error_message: str = ""

def query_result(self, user_prompt: str, system_prompt: str | None = None, **kwargs) -> LLMQueryResult:
    # Reuse the current OpenAI request and exception path.
    # Convert message.content None to "" and copy choices[0].finish_reason/usage.
    # Log completion reason, token use, and visible character count only.

def query(self, user_prompt: str, system_prompt: str | None = None, **kwargs) -> str | None:
    return self.query_result(user_prompt, system_prompt, **kwargs).content or None
```

Keep provider-specific handling in the shared path. API/configuration failure fills `error_message`, rather than looking like a normal empty result.

- [x] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_llm_client_configuration.LLMQueryResultTest -v`

Expected: PASS; requirement generation can now classify the failure from the 14:19 log.

- [x] **Step 5: Commit**

Run: `git add llm_client.py tests/test_llm_client_configuration.py && git commit -m "feat: expose LLM completion metadata"`

### Task 2: Retry only requirement generation and preserve valid task cards

**Files:**

- Modify: `report_generation/task_card_agent.py:15-122,310-337`
- Create: `tests/test_task_card_agent.py`

- [x] **Step 1: Write failing empty/truncated-output tests**

```python
def test_retries_empty_visible_requirement_once(self):
    with patch("report_generation.task_card_agent.llm.query_result", side_effect=[
        _result("", "stop"),
        _result("围绕具身智能产业分析沪深上市公司股价与市值变化。", "stop"),
    ]) as query:
        result = generate_report_requirement("具身智能投资状况", "关注沪深上市公司", "embodied", "具身智能")
    self.assertEqual(result["source"], "model_retry")
    self.assertEqual(query.call_count, 2)

def test_retries_length_limited_incomplete_requirement_once(self):
    with patch("report_generation.task_card_agent.llm.query_result", side_effect=[
        _result("围绕具身智能产业分析沪深上市公司的估值与关键", "length"),
        _result("围绕具身智能产业分析沪深上市公司股价与市值变化。", "stop"),
    ]):
        result = generate_report_requirement("具身智能投资状况", "关注沪深上市公司", "embodied", "具身智能")
    self.assertEqual(result["source"], "model_retry")
    self.assertEqual(result["report_requirement"][-1], "。")
```

- [x] **Step 2: Run the classification tests to verify they fail**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_task_card_agent.ReportRequirementTest -v`

Expected: FAIL. The current function makes one call, uses 1800 tokens, and accepts any nonempty partial text; the observed text ended at `关键`.

- [x] **Step 3: Write the failing valid-card preservation test**

```python
def test_keeps_valid_card_after_two_requirement_failures(self):
    with patch("report_generation.task_card_agent.llm.query_result", side_effect=[
        _result(VALID_TASK_CARD_JSON, "stop"), _result("", "stop"), _result("", "stop"),
    ]) as query:
        result = generate_writing_task_card("具身智能投资状况", "关注沪深上市公司", "embodied")
    self.assertEqual(result["status"], "success")
    self.assertEqual(result["task_card"]["selected_industry"], "embodied")
    self.assertIn("关注沪深上市公司", result["task_card"]["report_requirement"])
    self.assertEqual(result["warnings"][0]["code"], "report_requirement_fallback")
    self.assertEqual(query.call_count, 3)
```

- [x] **Step 4: Run the preservation test to verify it fails**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_task_card_agent.TaskCardTest.test_keeps_valid_card_after_two_requirement_failures -v`

Expected: FAIL. The current nested retry regenerates the JSON task card and then returns an error, losing valid industry/title selections.

- [x] **Step 5: Implement bounded requirement validation, retry, and fallback**

```python
REPORT_REQUIREMENT_MAX_ATTEMPTS = 2
REPORT_REQUIREMENT_MAX_TOKENS = 900
REPORT_REQUIREMENT_MIN_CHARS = 40
REPORT_REQUIREMENT_MAX_CHARS = 520

def _requirement_failure_reason(result: LLMQueryResult) -> str:
    text = clean_text(result.content)
    if result.error_message:
        return "llm_request_failed"
    if not text:
        return "empty_visible_content"
    if result.finish_reason == "length" or len(text) > REPORT_REQUIREMENT_MAX_CHARS:
        return "truncated"
    if len(text) < REPORT_REQUIREMENT_MIN_CHARS or text[-1] not in "。！？!?":
        return "incomplete"
    return ""

def _fallback_report_requirement(title: str, user_requirement: str, industry_name: str) -> str:
    focus = user_requirement or f"分析{title}"
    return f"围绕{industry_name}产业，{focus}。请明确研究对象、时间范围、核心分析维度、数据口径与不纳入范围，并将该产业作为后续图谱和资料检索上下文。"
```

Change the prompt to one 180–360 Chinese-character paragraph, final `。`, maximum four dimensions. Preserve priority `用户原始需求 > 产业方向 > 原始标题`. Retry `llm.query_result()` once with a concise correction instruction; second failure returns fallback with `source="fallback"` and warning code `report_requirement_fallback`. Do not accept known truncated output.

- [x] **Step 6: Separate JSON retry from requirement retry**

```python
# Complete current two-attempt JSON parse/normalization before requirement generation.
task_card["report_requirement"] = requirement_result["report_requirement"]
task_card["report_requirement_source"] = requirement_result["source"]
return {"status": "success", "task_card": task_card, "warnings": requirement_result["warnings"]}
```

Malformed JSON still receives one JSON retry. Once JSON is valid, requirement failure no longer regenerates or discards it.

- [x] **Step 7: Run task-card tests and commit**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_task_card_agent -v`

Expected: PASS; failures identify an output-classification, retry-boundary, or fallback regression.

Run: `git add report_generation/task_card_agent.py tests/test_task_card_agent.py && git commit -m "fix: recover task cards from incomplete requirements"`

### Task 3: Show fallback status to the user and in logs

**Files:**

- Modify: `backend_server.py:251-264,280-294`
- Modify: `static/js/modules/industry_report.js:536-565,699-731`
- Modify: `tests/js/test_industry_report_navigation.test.js`

- [x] **Step 1: Write failing UI tests**

```javascript
test("task-card fallback remains editable and tells the user to confirm it", async () => {
    const { context, calls } = loadReportScript();
    // Mock task-card success with a card plus the exact fallback warning object below.
    await context.submitIndustryReportRequirement();
    assert.match(calls.statuses.at(-1).message, /可编辑基础需求/);
});

test("industry-change fallback warning is visible", async () => {
    const { context, calls } = loadReportScript();
    // Mock rewrite success with the same exact warning object.
    await context.handleIndustryReportSelectedIndustryChange();
    assert.match(calls.statuses.at(-1).message, /可编辑基础需求/);
});
```

Both mocks use this complete warning payload:

```javascript
{ stage: "report_requirement", code: "report_requirement_fallback", reason: "empty_visible_content", message: "模型未返回完整报告需求，已生成可编辑基础需求，请确认后继续。" }
```

- [x] **Step 2: Run UI tests to verify they fail**

Run: `node --test tests/js/test_industry_report_navigation.test.js`

Expected: FAIL because task-card success has a generic message and industry rewrite ignores `data.warnings`.

- [x] **Step 3: Propagate warnings and record non-sensitive metadata**

```javascript
const fallback = (data.warnings || []).find(item => item?.code === "report_requirement_fallback");
appendIndustryReportWarnings(data.warnings);
setIndustryReportStatus(
    fallback ? fallback.message : "请检查并编辑写作任务卡，然后生成大纲",
    fallback ? "info" : "success",
);
```

Apply to initial task-card creation and industry-change rewrite; keep card fields enabled. Backend action logs read `task_card.report_requirement_source` for initial creation and `result.source` for rewrite, plus warning codes; never raw model text.

- [x] **Step 4: Run UI tests and commit**

Run: `node --test tests/js/test_industry_report_navigation.test.js`

Expected: PASS; user sees fallback context and can edit before outline generation.

Run: `git add backend_server.py static/js/modules/industry_report.js tests/js/test_industry_report_navigation.test.js && git commit -m "fix: surface task-card requirement fallbacks"`

### Task 4: Move LLM settings out of source control

**Files:**

- Modify: `llm_client.py:1-70,207-216`
- Modify: `environment.yml`
- Create: `.env.example`
- Modify: `DEPLOYMENT.md:58-69`
- Test: `tests/test_llm_client_configuration.py`

- [ ] **Step 1: Complete the external prerequisite**

The key owner revokes/regenerates the currently exposed DeepSeek and Doubao keys in provider consoles. Removing literals does not erase Git history, copied logs, or screenshots. Do not commit a new key, `.env`, terminal output containing one, or key-bearing test data.

- [x] **Step 2: Write failing environment/TLS tests**

```python
def test_client_reads_environment_and_verifies_tls_by_default(self):
    values = {"LLM_API_KEY": "test-key", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "test-model"}
    with patch.dict(os.environ, values, clear=True), patch("llm_client.httpx.Client") as http_client, patch("llm_client.OpenAI"):
        client = LLMClient()
    self.assertEqual(client.model, "test-model")
    self.assertTrue(http_client.call_args.kwargs["verify"])

def test_missing_key_returns_configuration_error_before_request(self):
    with patch.dict(os.environ, {}, clear=True):
        result = LLMClient(api_key="").query_result("需求")
    self.assertEqual(result.error_message, "LLM_API_KEY is not configured")
```

- [x] **Step 3: Run configuration tests to verify they fail**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_llm_client_configuration.LLMEnvironmentConfigurationTest -v`

Expected: FAIL because the current module embeds credentials and the singleton uses `verify_ssl=False`.

- [x] **Step 4: Implement environment-only configuration**

```python
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
DEFAULT_API_KEY = os.getenv("LLM_API_KEY", "").strip()
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash").strip()
DEFAULT_PROXY_URL = os.getenv("LLM_PROXY_URL", "").strip() or None
```

Remove every credential literal and commented alternative. Use normal TLS verification for the singleton. A missing key returns an explicit metadata error before any API request. Add `python-dotenv` to `environment.yml`; `.env` is already ignored. Create:

```dotenv
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
# LLM_PROXY_URL=
```

- [x] **Step 5: Update deployment guide, verify, and commit**

Update `DEPLOYMENT.md`: copy `.env.example` to `.env`, paste a newly rotated key, restart Flask, document PowerShell and macOS/Linux environment-variable alternatives, and state TLS verification is on by default.

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_llm_client_configuration -v`

Expected: PASS; no tracked source secret and missing key cannot contact the provider.

Run: `git add llm_client.py environment.yml .env.example DEPLOYMENT.md tests/test_llm_client_configuration.py && git commit -m "fix: load LLM settings from local environment"`

### Task 5: Full verification and manual acceptance

**Files:**

- No new production files.

- [x] **Step 1: Run the focused regression suite**

Run: `PYTHONPATH=. conda run -n kunlun python -m unittest tests.test_task_card_agent tests.test_llm_client_configuration tests.test_direct_outline_json_recovery tests.test_report_rag_modes tests.test_embodied_news_rag tests.test_coordinator_stability -v && node --test tests/js/test_industry_report_navigation.test.js`

Expected: all tests pass. Failures identify task-card recovery, shared LLM-client compatibility, industry routing, or warning-display regressions.

- [ ] **Step 2: Manually accept the original failing request after a newly rotated key is configured**

Submit title `具身智能投资状况`, requirement `具身智能企业近几年在沪深两市的股价变化，特别是具身智能行业的龙头企业发展`, page industry `embodied`.

Expected: normal output is concise and ends with `。`; automated mocks prove empty/truncated output instead yields explicit editable fallback. Both paths send nonempty `report_requirement` to the unchanged outline endpoint.

## Self-review

- Empty visible output, request failure, length/incomplete output, malformed JSON, and valid-card/failed-requirement paths are separate and testable.
- Valid JSON is retained; known truncation is never silently accepted; fallback is editable and disclosed.
- `llm.query()` remains compatible; metadata is additive. No OS-specific path, RAG-data action, migration framework, checksum, or feature flag is added.

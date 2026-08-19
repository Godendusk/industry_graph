# 已生成报告“打开图谱”同页导航设计

## 1. 背景与问题

产业报告正文和局部重写资料区都会展示“打开图谱”链接。当前链接带有 `target="_blank"`，点击后会在新标签页重新加载完整应用。应用登录凭证只从当前标签页的 `sessionStorage` 读取；新标签页无法可靠继承该凭证，因此初始化图谱时的请求会进入缺少 token 或 401/403 分支，并被重定向到登录站点。

同一应用内的侧栏“知识图谱”入口使用 `switchView('graph')` 在当前页面切换，不触发重新加载，所以不存在重复登录问题。现有 `view=graph&subview=graph&node=...&industry=...` 路由参数及节点聚焦逻辑本身可用。

## 2. 目标与验收标准

### 2.1 目标

- 用户已登录并打开已生成报告时，点击任一“打开图谱”应在当前页面直接进入力导向图谱视图。
- 图谱应切换到报告对应产业，并聚焦资料对应的图谱节点。
- 导航过程不得新建标签页、重新加载应用或要求用户再次登录。
- 地址栏应更新为可表达当前图谱位置的路由 URL，但不得包含 token、用户信息等敏感数据。

### 2.2 验收标准

1. 报告正文资料卡中的“打开图谱”不含 `target="_blank"`，点击后调用同页导航。
2. 局部重写资料区中的“打开图谱”采用相同行为。
3. 导航设置 `pendingGraphSubView = 'graph'` 和目标节点 ID，再调用现有 `switchView('graph')`。
4. 有效产业值通过现有 `setCurrentIndustryFromRoute()` 切换，图谱加载对应产业数据源。
5. 地址栏更新为 `?view=graph&subview=graph&node=<id>&industry=<industry>`，不发生页面刷新。
6. 原标签页的 `sessionStorage` 登录态保持不变。
7. 直接访问上述 URL 时，现有 `handleInitialAppRoute()` 仍能正常进入并聚焦图谱。
8. 没有节点 ID 时不渲染“打开图谱”入口。

## 3. 方案比较

### 方案 A：当前页面内切换（采用）

链接保留正常 `href`，但点击时由前端函数拦截，在当前页面设置图谱状态、更新地址栏并调用 `switchView('graph')`。

优点：

- 复用现有登录上下文和已加载资源，不跨标签传递凭证。
- 改动集中在报告前端，风险和回归范围最小。
- 地址栏仍可表达图谱位置，保留刷新和复制链接的语义。
- 与侧栏进入图谱的现有工作模式一致。

代价：

- 用户离开报告视图后需要通过侧栏恢复报告视图；报告数据仍保留在当前页面内存中。

### 方案 B：保留新标签页并复制 `sessionStorage`（不采用）

在打开新标签页后尝试通过 `window.opener`、`postMessage` 或预先创建窗口复制 token。

不采用原因：现代浏览器对 `_blank`/`noopener` 的隔离行为不一致；实现依赖弹窗策略和跨窗口时序，同时扩大凭证暴露面。

### 方案 C：把 token 放入 URL 或临时票据（不采用）

将凭证或一次性票据附加到图谱 URL，新页面据此恢复会话。

不采用原因：直接 token 会泄露到浏览历史、日志和 Referer；一次性票据则需要新增后端交换、过期和重放防护，超出本问题所需范围。

## 4. 详细设计

### 4.1 导航入口

两个报告资料渲染位置继续输出语义化 `<a>` 元素：

- `href` 使用现有 `buildIndustryReportGraphLink(nodeId)` 生成，作为可复制地址和 JavaScript 不可用时的回退。
- 删除 `target="_blank"`。
- 增加 `onclick="return openIndustryReportGraph(...)"`；返回 `false` 时阻止浏览器执行完整页面导航。
- 节点 ID 在写入内联 JavaScript 前继续使用现有 `escapeIndustryReportJs()` 转义。

### 4.2 同页导航函数

在 `static/js/modules/industry_report.js` 新增 `openIndustryReportGraph(nodeId)`，职责仅限报告到图谱的导航编排：

1. 将节点 ID 规范化为字符串；空值返回 `true`，允许默认链接行为。
2. 读取报告工作区产业；为空时回退到当前产业。
3. 若 `switchView` 不可用，返回 `true`，让浏览器使用 `href` 回退。
4. 调用现有 `setCurrentIndustryFromRoute(industry)`，保持产业选择 UI 与数据源一致。
5. 设置 `window.pendingGraphSubView = 'graph'`。
6. 设置 `window.pendingGraphFocusNodeId = normalizedNodeId`。
7. 通过 `window.history.replaceState()` 把地址栏更新为现有图谱 URL；该操作不刷新页面，也不会写入一个无法被现有应用 `popstate` 逻辑恢复的历史记录。
8. 调用 `switchView('graph')`。现有图谱逻辑加载数据、切换到力导向视图，并调用 `focusPendingGraphNodeFromUrl()` 聚焦节点。
9. 返回 `false`，阻止 `<a>` 的默认导航。

该函数不读取、复制、修改或序列化 token。

### 4.3 数据流

```text
报告资料卡点击
  -> openIndustryReportGraph(nodeId)
  -> 同步产业选择
  -> 写入 pendingGraphSubView / pendingGraphFocusNodeId
  -> history.replaceState(无刷新、不新增历史记录)
  -> switchView('graph')
  -> loadGraphDataForSunburst()
  -> switchToGraph()
  -> focusPendingGraphNodeFromUrl()
  -> focusOnNode(nodeId)
```

整个链路保留在同一个 browsing context 中，因此原有 `sessionStorage` 登录态持续有效。

### 4.4 异常与回退

- 节点 ID 缺失：沿用现有行为，不展示链接。
- 导航函数或 `switchView` 不可用：返回 `true`，浏览器按 `href` 在当前标签页打开图谱 URL。
- `history.replaceState` 不可用：仍执行同页视图切换；地址栏不更新，但核心功能不受影响。
- 图谱数据加载失败：沿用现有图谱错误日志和状态显示，本次不改鉴权与数据加载策略。

## 5. 测试设计

新增基于 Node.js 内置 `node:test` 和 `vm` 的前端单元测试，不引入 npm 依赖：

1. 加载真实 `industry_report.js`，用最小浏览器上下文替身执行脚本。
2. 验证正文资料卡生成的链接不含 `_blank`，包含同页导航处理器和正确路由参数。
3. 验证局部重写资料行同样不含 `_blank`。
4. 调用真实 `openIndustryReportGraph()`，验证：
   - 返回 `false`；
   - 产业同步函数被调用；
   - pending 子视图和节点 ID 正确；
   - `history.replaceState` 收到正确 URL；
   - `switchView('graph')` 被调用；
   - `sessionStorage` 中的 token 未被改写。
5. 验证缺少 `switchView` 时返回 `true`，保留链接回退能力。
6. 运行项目现有 Python 测试套件，确认报告后端和检索模块无回归。

## 6. 改动范围

### 新增

- `tests/js/test_industry_report_navigation.test.js`：报告到图谱导航的浏览器逻辑单元测试。

### 修改

- `static/js/modules/industry_report.js`：增加同页导航函数，调整两处“打开图谱”链接。

### 不修改

- `static/js/main.js` 中的全局 token 拦截器和现有路由解析。
- `token_util.py` 的后端鉴权开关。
- 图谱加载、渲染、节点聚焦算法。
- 报告生成、历史记录和导出逻辑。

仓库中存在硬编码 token、后端鉴权提前返回及生产/本地 API 配置不一致等独立风险。这些问题需要单独的鉴权整改任务，不能与本次 P0 导航修复混合，以免扩大部署风险。

## 7. 发布、验证与回滚

### 发布前验证

- Node 前端导航测试全部通过。
- `kunlun` 环境下现有 Python 测试全部通过。
- 静态检查确认报告脚本中两处“打开图谱”均无 `_blank`。

### 线上验收步骤

1. 登录系统并打开一份已生成报告。
2. 展开正文中的知识图谱资料，点击“打开图谱”。
3. 确认仍在当前标签页、没有登录跳转，且进入正确产业和节点。
4. 返回报告，打开局部重写弹窗并推荐资料，再次验证“打开图谱”。
5. 复制地址栏图谱 URL，在已登录的同一标签页访问，确认路由仍可定位节点。

### 回滚

本次只有一个生产脚本文件发生行为改动。若上线异常，回滚该提交即可恢复原链接行为；不涉及数据库、后端接口或数据迁移。

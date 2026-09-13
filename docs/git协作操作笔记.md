# Git 协作操作笔记

这份笔记记录本项目目前讨论过的 Git 基础概念和多人协作流程，适合在不熟悉 Git 时按步骤查阅。

## 一、先理解几个名字

可以把 Git 想成项目的“版本档案系统”：每次提交都是一个可追踪的版本，分支则是从某个版本分出去的一条独立开发路线。

| 名称 | 通俗解释 |
| --- | --- |
| 本地仓库 | 电脑上的项目和 Git 记录 |
| `main` | 本地的主分支，通常代表正式代码 |
| `origin` | GitHub 远程仓库的简称，不是一个分支 |
| `origin/main` | GitHub 上的主分支在本地的记录 |
| 功能分支 | 为一个功能或修复单独创建的分支 |
| `commit` | 给当前修改保存一个明确版本，并写下这次修改的说明 |
| `push` | 把本地已经提交的版本上传到 GitHub |
| Pull Request（PR） | 请求团队审核“把我的分支合并到主分支” |
| `pull` | 把远程仓库的新提交下载并合并到本地当前分支 |

`origin` 只是远程仓库的名字，所以不能说“合并到 origin”。准确说法通常是“推送到 `origin/我的分支`”或“合并到 GitHub 的 `main`”。

## 二、当前项目的状态

我们已经完成并合并到本地 `main` 的两类工作：

1. RAG 链路升级。
2. 报告页面“打开图谱”时的登录状态问题修复。

本地 `main` 已经包含这些提交，但当时还没有推送到 GitHub。因此它们当时处于：

```text
电脑上的 main：已包含
GitHub 上的 main：尚未包含
```

另外，工作区里还存在一些未提交的 RAG 改动。未提交的文件不属于任何 `commit`，也不会因为执行 `push` 自动上传。

查看当前情况：

```bash
git status
git log --oneline --decorate -10
```

看到 `M` 表示已修改文件，`D` 表示已删除文件，`??` 表示 Git 尚未跟踪的新文件。

## 三、推荐的多人协作流程

### 1. 先同步本地 `main`

开始新工作前，先进入项目目录：

```bash
cd /Users/livictor/Desktop/industry/industry_graph
```

确认自己在主分支：

```bash
git switch main
```

再把 GitHub 上别人已经提交的内容同步下来：

```bash
git pull origin main
```

如果本地有未提交改动，先不要随意执行切换、合并或清理操作。应先判断这些改动属于哪个功能，必要时先提交或暂存。

### 2. 从 `main` 创建自己的功能分支

例如要开发“报告图谱跳转”功能：

```bash
git switch -c my-current-work
```

这条命令会创建分支并立即切换过去。 `feature/` 不是 Git 强制要求，只是团队常见的命名习惯：

```text
feature/hybrid-rag
fix/report-login
docs/git-guide
```

下面的名字也完全有效：

```text
my-current-work
rag-and-login
2026-08-project-update
```

重要的是分支名能说明用途、不要使用空格，并遵守团队约定。

### 3. 在功能分支上开发并提交

在新分支中修改代码、运行相关测试。先查看修改：

```bash
git status
git diff
```

确认后，把需要提交的文件加入暂存区：

```bash
git add path/to/file.py
git add path/to/test_file.py
```

也可以加入当前目录下所有改动，但使用前必须确认没有把临时文件、模型文件或别人的工作一起加入：

```bash
git add .
```

创建提交：

```bash
git commit -m "fix: describe the change"
```

一次提交最好只表达一个相对完整的事情。例如：

```text
feat: add hybrid report retrieval
fix: keep report graph navigation in current session
test: add graph navigation tests
```

`commit` 只保存到本地，不会自动出现在 GitHub 上。

### 4. 把功能分支推送到 GitHub

第一次上传这个分支：

```bash
git push -u origin my-current-work
```

其中：

- `origin` 是 GitHub 仓库的简称。
- `my-current-work` 是本地功能分支名。
- `-u` 会记住两者的对应关系。

以后在同一个分支继续提交后，只需：

```bash
git push
```

推送后，GitHub 上会出现同名的远程分支，其他协作者才能看到你的提交。

### 5. 创建 Pull Request

打开 GitHub 项目页面，选择创建 Pull Request，并确认：

```text
来源（source）：my-current-work
目标（target）：main
```

意思是“请审核我在 `my-current-work` 中的修改，审核后考虑合并到 `main`”。PR 描述中应说明：

- 做了什么修改；
- 为什么需要修改；
- 运行了哪些测试；
- 是否有已知限制。

### 6. 审核并合并

协作者可以在 PR 页面查看文件差异、评论代码、检查测试结果。审核通过后，具有权限的人点击合并按钮，功能分支的提交才会进入 GitHub 的 `main`。

“批准（Approve）”和“合并（Merge）”可能是两个不同动作：批准代表审核者认可，是否自动合并取决于项目设置，很多项目仍需要单独点击 Merge。

### 7. 把合并结果同步回本地

GitHub 合并后，本地 `main` 不会自动变化。回到本地主分支并同步：

```bash
git switch main
git pull origin main
```

如果功能分支已经完成，可以删除本地分支：

```bash
git branch -d my-current-work
```

是否删除 GitHub 上的远程分支由团队习惯决定。确认不再需要后可以删除：

```bash
git push origin --delete my-current-work
```

## 四、已提交和未提交的区别

这是最容易混淆的地方：

```text
修改文件 → git add → git commit → git push
工作区      暂存区       本地仓库      GitHub
```

- 只修改文件：改动在工作区。
- `git add`：把指定改动放入暂存区，准备提交。
- `git commit`：保存到本地 Git 历史。
- `git push`：上传已经提交的内容。

因此，未提交的改动不会被 `push` 上传。若要上传，必须先确认文件内容，再 `add` 和 `commit`。

## 五、直接推送 `main` 可以吗

技术上可以：

```bash
git switch main
git push origin main
```

这会把本地 `main` 中已经提交、但 GitHub 尚未拥有的提交直接发布到 GitHub 的 `main`。但多人项目通常不推荐这样做，因为：

- 没有 Pull Request 审核环节；
- 其他人的工作可能还没有被考虑进去；
- 出问题时不容易定位是哪批修改造成的；
- 主分支可能被半成品或未经测试的代码影响。

如果本地 `main` 已经有一批完整且经过测试的提交，也可以先从它创建一个分支，再通过 PR 发布：

```bash
git switch main
git switch -c my-current-work
git push -u origin my-current-work
```

然后创建 `my-current-work -> main` 的 PR。

## 六、常用检查命令

查看当前分支和未提交改动：

```bash
git status
```

查看本地分支：

```bash
git branch
```

查看远程分支：

```bash
git branch -r
```

查看最近提交：

```bash
git log --oneline --decorate -10
```

查看本地比 GitHub 多出的提交：

```bash
git log --oneline origin/main..main
```

查看 GitHub 比本地多出的提交：

```bash
git log --oneline main..origin/main
```

查看某次提交改了哪些文件：

```bash
git show --stat <commit-id>
```

## 七、最简记忆版

```text
同步 main
→ 创建自己的分支
→ 在自己的分支修改
→ add
→ commit
→ push 到 origin/自己的分支
→ 创建 Pull Request
→ 他人审核并 Merge 到 GitHub main
→ 本地 switch main
→ pull origin main
```

一句话总结：

> `main` 是公共正式版本，功能分支是个人工作区，`origin` 是 GitHub，`push` 是上传，PR 是请求审核，Merge 才是进入 GitHub 主分支。

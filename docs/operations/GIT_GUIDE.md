# Git 常用操作速查

## 核心概念（先理解这个）

Git 把文件存在 **4 个区域**，工作流程就是文件在这四个区域之间流转：

```
工作区 (改代码)
  ↓ git add
暂存区 (挑好要提交的文件)
  ↓ git commit
本地仓库 (.git 目录)
  ↓ git push
远程仓库 (GitHub)
```

- **工作区** — 你正在编辑的文件，改完还没存到 Git
- **暂存区** — `git add` 后，文件排队等待 commit
- **本地仓库** — `git commit` 后，改动正式记录在案
- **远程仓库** — `git push` 后，上传到 GitHub，别人能看到

---

## 日常高频命令

```bash
# ── 查看状态 ──
git status                # 看看改了什么、哪些没提交
git log --oneline -10     # 看最近 10 条提交记录

# ── 提交改动 ──
git add .                 # 把所有改动加入暂存区
git commit -m "改了什么"   # 提交到本地仓库
git push                  # 推送到 GitHub

# ── 拉取别人/自己在别处的改动 ──
git pull                  # 把 GitHub 上的新东西拉到本地

# ── 分支操作 ──
git branch                    # 查看所有分支
git branch 新功能名            # 创建新分支
git switch 新功能名            # 切换到那个分支
git switch -c 新功能名         # 创建 + 切换一步到位
git merge 分支名               # 把指定分支合并到当前分支

# ── 撤销操作 ──
git restore 文件名           # 撤销工作区的改动（还没 add 的）
git restore --staged 文件名  # 取消暂存（add 了但还没 commit）
git revert HEAD              # 撤销最近一次 commit（安全，保留历史）
```

---

## 典型工作流

### 日常改代码
```bash
# 1. 开始工作前，同步最新代码
git pull

# 2. 改代码...

# 3. 看看改了什么
git status

# 4. 添加并提交
git add .
git commit -m "修复：双均线策略的买入信号计算错误"

# 5. 上传到 GitHub
git push
```

### 开发新功能（用分支隔离）
```bash
# 1. 从主分支拉一条新分支
git switch -c feature/加MACD策略

# 2. 在新分支上改代码、提交...
git add .
git commit -m "添加 MACD 策略基础框架"

# 3. 开发完成，切回主分支合并
git switch master
git merge feature/加MACD策略

# 4. 推送到 GitHub
git push

# 5. 删除已经合并的功能分支（可选）
git branch -d feature/加MACD策略
```

---

## 分支模型（推荐）

```
master (main)  ← 稳定可用的代码，只合并不直接改
  ├── feature/xxx  ← 新功能开发
  ├── fix/xxx      ← 修 bug
  └── refactor/xxx ← 重构
```

一条原则：**永远不要在 master 上直接改代码**，开分支改完再合并回来。

---

## 常见场景速查

| 场景 | 命令 |
|------|------|
| 我改错了，想回到上次 commit 的状态 | `git restore .` |
| commit 信息写错了 | `git commit --amend -m "新的信息"` |
| 我忘了切分支，在 master 上改了一堆 | `git switch -c 新分支名`（先创建分支保存） |
| 想看某个文件的历史改动 | `git log -- 文件路径` |
| GitHub 上别人更新了，我 push 冲突 | `git pull` 先拉下来解决冲突再 push |
| 暂时不想提交但又要切分支 | `git stash` 暂存，回来用 `git stash pop` 恢复 |

---

## .gitignore 是什么

`.gitignore` 文件里写的路径会被 Git 忽略，不会上传到 GitHub。通常忽略：

- 密码/Token 等配置文件（如 `config.yaml`）
- 虚拟环境目录（`venv/`, `.venv/`）
- Python 缓存（`__pycache__/`）
- IDE 配置文件（`.idea/`, `.vscode/`）
- 数据文件和生成结果（`*.csv`, `*.html`）

---

## 进阶：等你熟悉了再看

```bash
git rebase master          # 把你的分支接到 master 最新处（比 merge 干净）
git cherry-pick 提交哈希    # 只把某一条 commit 拿过来
git reset --hard HEAD~1    # 彻底删掉最近一次 commit（危险⚠️ 无法恢复）
git reflog                  # 查看所有 HEAD 移动记录（救命用）
```

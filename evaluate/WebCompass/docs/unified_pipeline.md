# 统一数据构造 Pipeline

## 核心思路

一次 agent 生成过程，同时产出三类数据：**Generate**、**Edit**、**Repair**。

agent 在 Docker 中生成网页时，通过 CLAUDE.md 指令要求其在关键节点 git commit。生成完成后，脚本自动解析 git 历史，提取三类数据。

```
                          ┌─────────────────────────────────────┐
                          │         Docker 容器内 agent          │
                          │                                     │
  query (text/image/video)│  1. git init                        │
  ────────────────────────▶  2. 写代码 → 可运行 → git commit     │
                          │     "CHECKPOINT: 实现导航栏"          │
                          │  3. 发现bug → 修复 → git commit      │
                          │     "BUGFIX: 修复按钮点击无响应"       │
                          │  4. 继续开发 → git commit             │
                          │     "CHECKPOINT: 添加响应式布局"       │
                          │  5. ... 最终完成                      │
                          └─────────┬───────────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────────────────────────┐
                          │     data_pipeline/edit_from_git.py   │
                          │     解析 git log → 自动分类提取       │
                          └─────────┬───────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │ Generate │   │   Edit   │   │  Repair  │
              │ 最终版本  │   │ 相邻     │   │ BUGFIX   │
              │ + query   │   │ CHECKPOINT│  │ commit前 │
              │ = 一条数据│   │ 之间的diff│  │ 的代码   │
              └──────────┘   │ = 一条数据│  │ = 一条数据│
                             └──────────┘   └──────────┘
```

## 三类数据的提取逻辑

### Generate 数据
- **来源**: agent 最终输出的完整网页 + 原始 query
- **格式**: 与 `webcompass_samples/text-generation/694.json` 对齐
- **字段**: `instance_id`, `problem_statement` (checklist), `instruction`, `src_code` (空), `dst_code` (最终代码)
- **已有实现**: `create_traj.sh` 中 Step 1 生成网页，Step 2 验证

### Edit 数据
- **来源**: 相邻 CHECKPOINT commit 之间的 diff
- **提取**: commit_N 的文件 = `src_code`，用 LLM 根据 diff 生成自然语言 edit description
- **格式**: 与 `webcompass_samples/editing/` 对齐
- **字段**:
  ```json
  {
    "instance_id": "xxx_edit_0",
    "task": "edit",
    "task_type": ["Add Navigation Bar"],
    "description": [{"task_type": "...", "description": "..."}],
    "src_code": [{"path": "index.html", "code": "..."}],
    "dst_code": [],
    "label_modified_files": ["index.html", "style.css"]
  }
  ```

### Repair 数据
- **来源**: BUGFIX commit 的**前一个版本**（即有 bug 的代码）
- **提取**: 反转 diff 理解 bug 是什么，用 LLM 生成 bug report（只描述问题，不透露修复方案）
- **格式**: 与 `webcompass_samples/repair/` 对齐
- **字段**:
  ```json
  {
    "instance_id": "xxx_repair_0",
    "task": "repair",
    "task_type": ["Sizing Proportion"],
    "description": [{"task_type": "...", "description": "修复 header logo 尺寸变形..."}],
    "src_code": [{"path": "index.html", "code": "有bug的代码"}],
    "dst_code": []
  }
  ```

## agent 端配置

### Docker CLAUDE.md 中需要添加的指令

在 agent 的 CLAUDE.md 中加入以下规则，使 agent 在生成过程中自动产生 git commit：

```markdown
# Git Commit 规则

在开发过程中，你必须遵循以下 git commit 规则：

1. 项目开始时执行 `git init && git add -A && git commit -m "CHECKPOINT: initial setup"`
2. 每完成一个可运行的功能模块时，执行：
   `git add -A && git commit -m "CHECKPOINT: [简要描述完成了什么]"`
   例如: "CHECKPOINT: 实现响应式导航栏"
3. 每次修复 bug 后，执行：
   `git add -A && git commit -m "BUGFIX: [简要描述修复了什么]"`
   例如: "BUGFIX: 修复移动端菜单无法展开的问题"
4. 不要把多个功能挤在一个 commit 里，每个独立功能或修复都应该单独 commit
5. commit message 必须以 CHECKPOINT: 或 BUGFIX: 开头，后面用中文或英文描述均可
```

### create_traj.sh 集成点

在 `create_traj.sh` 的 Step 1 之前，需要在 WORKING_DIR 中初始化 git：

```bash
# 在 Step 1 之前
cd ${WORKING_DIR}
git init
git config user.email "agent@webcompass.dev"
git config user.name "WebCompass Agent"
```

在 Step 1 完成后（Step 2 之前），运行数据提取：

```bash
# Step 1.5: 提取 edit/repair 数据
python -m data_pipeline.edit_from_git \
    --repo_dir ${WORKING_DIR} \
    --output_edit ${TASK_OUTPUT_DIR}/edit_data.jsonl \
    --output_repair ${TASK_OUTPUT_DIR}/repair_data.jsonl \
    --base_id ${INSTANCE_ID}
```

## 数据提取脚本

### `data_pipeline/edit_from_git.py`

已实现，核心逻辑：

1. **读取 git log**，按时间正序排列所有 commit
2. **分类 commit**:
   - message 以 `CHECKPOINT:` 开头 → 标记为 checkpoint
   - message 以 `BUGFIX:` / `FIX:` 开头 → 标记为 bugfix
   - 其他 → 标记为 other（也可作为 edit 数据使用）
3. **提取 edit 数据**: 每对相邻的 (checkpoint/other) commit → 一条 edit 数据
4. **提取 repair 数据**: 每个 bugfix commit → 一条 repair 数据（src_code 是修复前的代码）
5. **调用 LLM**: 根据 diff 生成自然语言描述
   - edit: "在导航栏下方添加一个轮播图组件，支持自动播放..."
   - repair: "页面在移动端加载时，导航栏按钮无法点击..."

```bash
# 用法
python -m data_pipeline.edit_from_git \
    --repo_dir /path/to/agent/output \
    --output_edit output/edit.jsonl \
    --output_repair output/repair.jsonl
```

## 完整工作流

```
1. 准备 query（text / image / video 三种来源）
       │
       ▼
2. Docker 容器启动 agent
   - create_traj.sh 执行
   - CLAUDE.md 中包含 git commit 规则
   - agent 生成网页，自动 commit 中间状态
       │
       ▼
3. 提取三类数据
   - Generate: 最终代码 + query → generate JSONL
   - Edit: edit_from_git.py 解析 CHECKPOINT commits → edit JSONL
   - Repair: edit_from_git.py 解析 BUGFIX commits → repair JSONL
       │
       ▼
4. 渲染验证（validate_render.py）
   - 验证最终生成的网页能否正确渲染
   - 验证每个 CHECKPOINT 版本是否可运行
       │
       ▼
5. 产出 JSONL 文件，格式对齐 webcompass_samples/
```

## 数据量估算

假设每个 query 的 agent 生成过程平均产生：
- 3-5 个 CHECKPOINT commits → 2-4 条 edit 数据
- 1-2 个 BUGFIX commits → 1-2 条 repair 数据
- 1 条 generate 数据

则 **1 个 generate query 可以产出约 4-7 条训练数据**（1 generate + 2-4 edit + 1-2 repair）。

## 已实现的相关代码

| 文件 | 功能 | 状态 |
|------|------|------|
| `data_pipeline/edit_from_git.py` | 从 git 历史提取 edit/repair 数据 | 已实现并测试 |
| `data_pipeline/validate_render.py` | Playwright 渲染验证 | 已实现并测试 |
| `data_pipeline/common.py` | 共享工具（LLM 调用、文件操作） | 已实现 |
| `generation/evaluation/agents/claude_code_web_coding/create_traj.sh` | Docker agent 执行入口 | 已有，需集成 git init 和数据提取 |

## 待集成的改动

1. **修改 create_traj.sh**: 在 Step 1 前加 git init，在 Step 1 后加 edit_from_git.py 调用
2. **修改 agent CLAUDE.md**: 加入 git commit 规则（CHECKPOINT/BUGFIX 约定）
3. **在 Docker 镜像中安装 data_pipeline 依赖**: gitpython, openai, python-dotenv

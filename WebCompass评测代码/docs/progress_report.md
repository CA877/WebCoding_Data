# WebCompass 数据构造进展汇报

## 一、整体目标

为 WebCompass benchmark 构造 SFT 训练数据，覆盖三类任务：**Generate**（网页生成）、**Edit**（网页编辑）、**Repair**（网页修复）。我负责的部分包括：基于 image/video 的生成数据构造、edit 数据构造、以及统一构造 pipeline 的实现。

## 二、已完成的工作

### 1. 数据构造 pipeline 全部实现并跑通

共实现了 7 个 pipeline 脚本，每个都用真实数据验证通过，输出格式对齐 `webcompass_samples/`：

| Pipeline | 功能 | 测试数据 | 状态 |
|----------|------|----------|------|
| `image_reverse.py` | 已有网页 → 截图 → LLM生成query | test_output/image 下的6个真实网页 | 跑通 |
| `image_forward.py` | 爬取真实网站 → 截图 → LLM生成query | stripe.com 等16个真实URL | 跑通 |
| `video_generate.py` | 录屏/提取帧 → LLM生成query | news.ycombinator.com | 跑通 |
| `edit_construct.py` | GitHub repo commit diff → edit指令 | h5bp/html5-boilerplate | 跑通 |
| `edit_from_git.py` | agent git历史 → edit/repair数据 | 本项目git历史（5条edit） | 跑通 |
| `scrape_website.py` | 完整网站抓取（HTML+CSS+图片） | news.ycombinator.com | 跑通 |
| `validate_render.py` | Playwright自动渲染验证 | test_output/image 下6个目录 | 跑通 |

### 2. 统一构造 pipeline 方案设计

核心思路：**一次 agent generate 过程，同时产出三类数据**。

```
query → agent在Docker中生成网页
          │
          ├─ CHECKPOINT commit → edit数据（相邻版本间的diff）
          ├─ BUGFIX commit    → repair数据（bug描述 + 有bug的代码）
          └─ 最终版本          → generate数据（query + 完整代码）
```

具体做法：
- 在 Docker 环境的 CLAUDE.md 中加入 git commit 规则，要求 agent 在每个可运行版本 commit（`CHECKPOINT:`），每次修 bug 后 commit（`BUGFIX:`）
- 生成完成后，`edit_from_git.py` 自动解析 git log，按 commit message 分类提取 edit 和 repair 数据
- **一条 generate query 预计可以产出 4-7 条训练数据**（1 generate + 2-4 edit + 1-2 repair）

### 3. 数据来源准备

- **真实网站 URL 列表**（16个）：stripe.com, linear.app, vercel.com, tailwindcss.com, nextjs.org, vuejs.org, svelte.dev, react.dev, HN, lobste.rs 等
- **GitHub 前端项目列表**（13个）：bootstrap, bulma, html5-boilerplate, primer/css, animate.css, tailwindcss.com, vuejs.org 等
- **已有网页实例**：test_output/image/ 下6个、webrenderbench 可重新抓取

### 4. 技术方案

- **模型**: `qwen3-coder-plus`（文本，便宜）用于生成 checklist 和 edit 描述；`claude_sonnet4_5`（视觉）用于截图理解
- **工具**: Playwright（截图/录屏/渲染验证）、ffmpeg（视频帧提取）、gitpython（git历史分析）
- **图片处理**: 自动缩放超过 4MB 或 7000px 的图片，RGBA→RGB 转换，适配 API 限制

## 三、当前状态

- 所有 pipeline 代码已写完，每个都用 1-2 条真实数据验证跑通
- 未进行大规模数据生产（API 成本考虑）
- 统一 pipeline 的 agent 端（Docker CLAUDE.md 配置）已设计完成，待与 @weihao 的 agent 生成流程对接集成

## 四、下一步计划

1. **对接 agent 生成流程**：将 git commit 规则集成到 Docker 环境的 CLAUDE.md 中，与 @weihao 的 create_traj.sh 联调，实现统一 pipeline 的完整闭环
2. **小规模试生产**：选 3-5 个 query 端到端跑一遍统一 pipeline，验证三类数据的质量
3. **扩大数据规模**：
   - image/video：从 URL 列表批量爬取，预计可产出 50+ 条 generate query
   - edit：从 GitHub 仓库列表批量提取，预计可产出 100+ 条 edit 数据
4. **数据质量检查**：用 validate_render.py 自动验证所有生成结果的渲染正确性

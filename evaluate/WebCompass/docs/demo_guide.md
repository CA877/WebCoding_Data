# 0422


## Demo 1: 基于图像的 Generate 数据构造（正向 vs 逆向）

**展示什么**: 两种方式从图像自动生成 query，区别在于是否有 ground truth。

**核心对比**:

| | 正向（爬取真实网站） | 逆向（已有源码） |
|---|---|---|
| **输入** | 一个 URL（如 stripe.com） | 一个网页源码目录 |
| **有无 ground truth** | 无（只有 query） | 有（源码就是答案） |
| **用途** | 评测 / 无监督 | 有监督 SFT 训练 |
| **数据来源** | 互联网上任何网站，量大 | 已有的网页项目，量有限 |

**怎么展示**:

**正向 — stripe.com 示例**:
1. 打开 pipeline 自动截取的三端截图：
   ```
   data_pipeline/output/screenshots_forward/fwd_0_stripe_com/
   ├── screenshot_desktop.png
   ├── screenshot_mobile.png
   └── screenshot_tablet.png
   ```
2. 打开生成的 JSONL，展示 LLM 自动生成的 instruction（一份完整网页设计文档）+ 10 条 checklist：
   ```
   data_pipeline/output/image_forward_real.jsonl
   ```

**逆向 — 已有网页示例**:
1. 在浏览器打开原始网页 `test_output/image/1/index.html`
2. 展示输出：`data_pipeline/output/image_reverse_real.jsonl`
   - 同样生成了 instruction + checklist
   - 但**原始源码直接作为 ground truth**，agent 评测时可以对比

**可选现场演示**（约 30 秒）：
```bash
source venv/bin/activate
python -m data_pipeline.image_forward \
    --urls_file data_pipeline/input/urls.txt \
    --output data_pipeline/output/demo.jsonl \
    --mode code --limit 1
```

**要点**: 正向量大但没答案，逆向有答案但依赖已有数据。两种互补使用。

---

## Demo 2: 视频生成 — 自动录屏 Hacker News

**展示什么**: 自动访问网站录屏（包含滚动和点击交互），提取关键帧，生成 query。

**怎么展示**:

1. 播放录屏视频（1MB 左右，很短）：
   ```
   data_pipeline/output/recordings/5bd6e8f9ee6279d0a4d79abb07f05863.webm
   ```

2. 展示提取的关键帧（28 帧）：
   ```
   data_pipeline/output/frames/vid_news_ycombinator_com/
   frame_0001.jpg ~ frame_0028.jpg
   ```

3. 展示生成的 query（Hacker News 设计文档 + 10 条 checklist）：
   ```
   data_pipeline/output/video_generate_real.jsonl
   ```

**要点**: 与 image 的区别 — video 的 query 会描述交互行为（滚动后内容变化、点击跳转等），不仅仅是静态外观。

---

## Demo 3: Edit 数据构造 — 从 GitHub 真实项目提取

**展示什么**: clone 真实 GitHub 前端项目，从 commit diff 自动生成 edit 任务。

**怎么展示**:

1. 展示输出：
   ```
   data_pipeline/output/edit_construct_real.jsonl
   ```
   - instance_id: `html5-boilerplate_15bf5543_0`
   - task_type: `Remove ESLint Configuration`
   - description: LLM 根据 diff 生成的自然语言编辑指令
   - src_code: parent commit 时的 14 个前端文件
   - label_modified_files: `.eslintrc.js`

2. 展示 GitHub 仓库列表（13 个真实项目）：
   ```
   data_pipeline/input/github_repos.txt
   ```
   包括 bootstrap、bulma、html5-boilerplate、animate.css 等

**要点**: 数据来自真实开发者的真实代码变更，不是人造数据。

---

## Demo 4: 统一 Pipeline — 一次生成产出三类数据

**展示什么**: agent 生成网页时通过 git commit 记录中间状态，自动提取 generate + edit + repair 三类数据。

**怎么展示**:

1. 展示 `edit_from_git.py` 从本项目 git 历史中提取的 5 条 edit 数据：
   ```
   data_pipeline/output/edit_from_git.jsonl
   ```

2. 画一下流程图讲解统一 pipeline：
   ```
   query → agent 生成网页（Docker）
             │
             ├─ CHECKPOINT commit → edit 数据
             ├─ BUGFIX commit    → repair 数据
             └─ 最终版本          → generate 数据
   ```

3. 展示 CLAUDE.md 中给 agent 的 git commit 规则（让 agent 自动按约定 commit）

**要点**: 一条 generate query 预计可以产出 4-7 条训练数据。数据利用率高。

---

## Demo 5: 渲染验证 — 自动检测生成网页质量

**展示什么**: 自动验证生成的网页是否能正确渲染，输出详细报告。

**怎么展示**:

1. 展示验证报告：
   ```
   data_pipeline/output/render_report.jsonl
   ```
   已验证 test_output/image 下 6 个网页目录：
   ```
   [FAIL] test_output/image/1    | body=89  | JS errors=1 | buttons=1 links=0
   [FAIL] test_output/image/106  | body=0   | JS errors=0 | buttons=0 links=0
   [FAIL] test_output/image/107  | body=142 | JS errors=4 | buttons=1 links=13
   [FAIL] test_output/image/109  | body=528 | JS errors=3 | buttons=1 links=5
   [FAIL] test_output/image/114  | body=2875| JS errors=7 | buttons=0 links=20
   [FAIL] test_output/image/115  | body=872 | JS errors=2 | buttons=0 links=8
   ```
   - FAIL 原因：这些网页引用了外部资源（CDN 上的 CSS/JS），离线渲染时 404
   - 说明渲染验证工具是有效的，能准确发现问题

2. 展示验证截图：每个目录下自动生成了 `_validation_screenshot.png`

**要点**: 这个工具可以用于批量检查 agent 生成的网页质量，替代部分人工检查。

---

## Demo 6: 网站完整抓取 — webrenderbench 数据补全

**展示什么**: 完整抓取一个网站的 HTML + CSS + 图片资源，可以离线渲染。

**怎么展示**:

1. 展示 Hacker News 抓取结果：
   ```
   data_pipeline/output/scraped/hackernews/
   ├── index.html        ← 完整渲染后的 HTML
   ├── resources/         ← CSS 等资源
   └── screenshots/       ← 三端截图
   ```

2. 在浏览器中打开 `index.html`，展示可以离线正常渲染

**要点**: 用于 webrenderbench 数据补全 — 之前只有截图没有完整源码，现在可以重新抓取。

---

## 汇报建议的展示顺序

1. 先讲**统一 pipeline 的整体思路**（Demo 4 的流程图部分），让老师有全局观
2. 然后展示 **Demo 1**（image 正向 vs 逆向对比，一张表讲清区别）
3. 展示 **Demo 2**（video 录屏，播放 webm 最直观）
4. 展示 **Demo 3**（edit，从真实 GitHub 项目提取）
5. 最后展示 **Demo 5 渲染验证**作为质量保障手段
6. 如果时间允许，当场跑一个 `image_forward` 给老师看实际效果

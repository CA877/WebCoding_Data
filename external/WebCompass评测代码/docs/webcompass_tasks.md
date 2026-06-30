# WebCompass 七类任务总览

## 任务构造方案与数据来源

| # | 任务 | 数量 | 输入 | 输出 | 数据来源 | 用了 WebRenderBench? |
|---|---|---|---|---|---|---|
| 1 | **Text-Guided Generation** | 123 | 文本描述（web design doc） | 完整网页代码 | WebGen-Bench + ArtifactsBench + BigCode Arena + V0 showcase → 去重聚类采样 → LLM 扩写成设计文档 | **否** |
| 2 | **Vision-Guided Generation** | 109 | 多张网页截图 | 复现网页代码 | ① WebRenderBench 网页 → 解析子页面 → Playwright 多页截图 ② V0/Figma 动态网页 → 手动提取关键帧序列 | **是** |
| 3 | **Video-Guided Generation** | 94 | 交互录屏视频 | 复现网页代码 | V0 + Figma 动态网页 → 人工规划浏览路径 → 手动录屏 | **否** |
| 4 | **Text-Guided Editing** | 300 | 源码 + 文本编辑指令 | code patch | 50 个 WebRenderBench 精选原型 → 按 16 种 editing type 生成编辑需求 | **是** |
| 5 | **Vision-Guided Editing** | 300 | 源码 + 截图 + 编辑指令 | code patch | 同上，额外提供截图 | **是** |
| 6 | **Diagnostic Repair** | 300 | 源码 + bug 文本描述 | code patch | 同上 50 个原型 → LLM 注入 11 种 defect → 生成有 bug 的代码 | **是** |
| 7 | **Visual-Diagnostic Repair** | 300 | 源码 + 截图 + bug 描述 | code patch | 同上，额外提供截图 | **是** |

**备注**：
- Editing + Repair（任务 4-7）共用同一批原型：WebRenderBench → 长度筛选(32k-64k) → GPT-4o 打分(≥9/10，剩 81 个) → 人工精选 **50 个** → 扩展为单页/多页版本
- Vision-Guided Generation 也用了 WebRenderBench，但方式不同：拿网页截多页截图作为输入
- Text Generation 和 Video Generation 完全不涉及 WebRenderBench

---

## 三种 Generation 任务的 SFT 数据收集方案

### 1. Text-Guided Generation

**任务定义**：给定文本描述（web design document），模型生成完整网页代码。

**WebCompass 的做法**：从 WebGen-Bench / ArtifactsBench / BigCode Arena / V0 收集 query，去重后 LLM 扩写为结构化设计文档（页面内容 + 交互行为 + 视觉外观）。

**我们的 SFT 数据收集方案**：

| 方案 | 说明 | 数据格式 | 是否有 ground truth |
|---|---|---|---|
| **A. 逆向构造（推荐）** | 已有高质量网页源码 → LLM 根据源码生成 web design document 作为 query → 源码作为 ground truth | query + ground truth code | ✅ 有 |
| **B. Query 改写扩增** | 收集 WebGen-Bench 等现有 query → Gemini/Qwen 改写扩增，提升难度和多样性 → agent 生成 ground truth | query + agent-generated code | ✅ 有（agent 生成） |

**逆向构造的网页源码来源**：
- WebRenderBench（去掉 WebCompass 用到的，避免测试集泄漏）
- GitHub 高星前端项目（awesome-css、awesome-landing-page 等收集的项目）
- V0 showcase 公开的网页项目
- 手工收集的高质量网站 → `scrape_website.py` 完整抓取

**已有 pipeline**：`data_pipeline/image_reverse.py`（截图 → LLM 生成 query），可复用其中 LLM 生成 query 的逻辑，改为读源码生成 text description 而非从截图生成。

---

### 2. Vision-Guided Generation

**任务定义**：给定网页截图（多张），模型生成与截图视觉一致的网页代码。

**WebCompass 的做法**：
- WebRenderBench 网页 → 解析 `index.html` 中的子页面 URL → Playwright 截多页截图 + JS overlay 标注子页面位置
- V0/Figma 动态网页 → 手动提取关键帧（捕捉状态变化）

**我们的 SFT 数据收集方案**：

| 方案 | 说明 | 数据格式 | 是否有 ground truth |
|---|---|---|---|
| **A. 逆向构造（推荐）** | 已有网页源码 → Playwright 截图（desktop/tablet/mobile 三端 + 子页面） → 截图作为 query，源码作为 ground truth | screenshots + ground truth code | ✅ 有 |
| **B. 动态关键帧** | 交互式网页 → 操作不同状态 → 截取关键帧序列（如 hover 前后、弹窗打开前后） | keyframe sequence + ground truth code | ✅ 有 |

**逆向构造的网页源码来源**：
- WebRenderBench（去除 WebCompass 重叠部分）
- GitHub 前端项目的 demo/docs 页面
- 手工抓取的真实网站（`scrape_website.py`）

**已有 pipeline**：`data_pipeline/image_reverse.py` — 已实现 Playwright 三端截图 + LLM 生成 query + checklist，可直接使用。

**与 Text Generation 的区别**：query 是截图而非文本描述，评测时关注视觉还原度。

---

### 3. Video-Guided Generation

**任务定义**：给定网页交互录屏视频，模型生成与视频中展示的外观和交互行为一致的网页代码。

**WebCompass 的做法**：从 V0 和 Figma 手动选择有丰富动态行为的网页 → 人工规划浏览路径 → 手动录屏（覆盖所有交互功能）。

**我们的 SFT 数据收集方案**：

| 方案 | 说明 | 数据格式 | 是否有 ground truth |
|---|---|---|---|
| **A. 逆向构造（推荐）** | 已有交互式网页源码 → Playwright 自动录屏（滚动 + 点击交互） → 提取关键帧 → 视频/帧序列作为 query，源码作为 ground truth | video/frames + ground truth code | ✅ 有 |
| **B. 人工录屏增强** | 对复杂交互网页，人工规划浏览路径并录屏（比自动录屏覆盖更多交互场景） | video + ground truth code | ✅ 有 |

**逆向构造的网页源码来源**：
- 需要有丰富交互行为的网页（纯静态页面不适合 video 任务）
- V0 showcase 中的交互式项目
- GitHub 上带动画/交互的前端 demo
- CodePen / CodeSandbox 上的交互式示例

**已有 pipeline**：`data_pipeline/video_generate.py` — 已实现 Playwright 自动录屏 + ffmpeg 提取关键帧 + LLM 生成 query，已用 Hacker News 测试跑通。

**关键挑战**：自动录屏的交互覆盖度有限（脚本只做滚动 + 随机点击），复杂交互（如拖拽、表单填写、多步流程）需要更智能的交互策略或人工录屏。

---

## 通用注意事项

1. **避免测试集泄漏**：所有使用 WebRenderBench 的方案，必须先下载 WebCompass 数据集，提取其使用的网页 ID/域名，建立黑名单，确保 SFT 训练数据与 WebCompass 测试集无重叠
2. **数据质量验证**：所有生成的网页需通过 `validate_render.py` 进行渲染验证
3. **成本控制**：优先使用 `qwen3-coder-plus`（便宜）生成 query/checklist，`claude_sonnet4_5`（贵）仅用于需要视觉理解的步骤

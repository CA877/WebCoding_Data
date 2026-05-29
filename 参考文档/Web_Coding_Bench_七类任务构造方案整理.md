# WebCompass / Web Coding Bench 七类任务构造方案整理


## 1. 总体设计

WebCompass 将输入模态和任务类型组合成七类任务。

| 任务族 | 任务类别 | 输入 | 期望输出 | 规模 |
| --- | --- | --- | --- | --- |
| Generation | Text-Guided Generation | 文本文档 | 完整可运行 Web 仓库 | 123 |
| Generation | Vision-Guided Generation | 多张网页截图 | 复现截图外观与功能的完整 Web 仓库 | 109 |
| Generation | Video-Guided Generation | 录屏视频 / 关键动态过程 | 复现视频中外观、交互、动画的完整 Web 仓库 | 94 |
| Editing | Text-Guided Editing | Web 仓库 + 文本编辑指令 | search/replace 形式代码补丁 | 300 |
| Editing | Vision-Guided Editing | Web 仓库 + 当前截图 + 编辑指令/视觉参考 | search/replace 形式代码补丁 | 300 |
| Repair | Diagnostic Repair | 有缺陷 Web 仓库 + 文本问题描述 | 修复缺陷的 search/replace 补丁 | 300 |
| Repair | Visual-Diagnostic Repair | 有缺陷 Web 仓库 + 当前缺陷截图 + 目标截图 + 问题描述 | 修复缺陷的 search/replace 补丁 | 300 |

总任务数为 **1526**。每个任务标注 `Easy / Medium / Hard`，依据包括功能复杂度、交互组件数量、视觉设计复杂度。

难度分布来自论文 Figure 2：

| 任务类别 | Easy | Medium | Hard | Total |
| --- | ---: | ---: | ---: | ---: |
| Text-Guided Generation | 33 | 48 | 42 | 123 |
| Vision-Guided Generation | 34 | 30 | 45 | 109 |
| Video-Guided Generation | 37 | 44 | 13 | 94 |
| Text-Guided Editing | 118 | 114 | 68 | 300 |
| Vision-Guided Editing | 118 | 114 | 68 | 300 |
| Diagnostic Repair | 90 | 120 | 90 | 300 |
| Visual-Diagnostic Repair | 90 | 120 | 90 | 300 |

## 2. 七类任务的构造方案

### 2.1 Text-Guided Generation

**任务定义**：输入是目标网页的文本规格说明，覆盖三部分：页面内容、交互行为、视觉外观。模型需要输出完整可运行的 Web 项目仓库。

**数据来源**：

- WebGen-Bench：人工构造 query。
- ArtifactsBench：多页面类别和严格过滤后的样本。
- BigCode Arena：真实用户请求。
- V0 高质量 Web showcase：AI IDE 产生的高质量网页案例。

**构造流程**：

1. 汇总多来源 query，形成初始 query pool。
2. 用 **BGE-M3** 对 query embedding。
3. 用 **k-means** 聚类去冗余，得到候选集合。
4. 用 LLM 为每条 query 标注类别和难度；每条 query 做 5 次独立标注，最终取 majority vote。
5. 按类别和难度做 stratified sampling，得到 123 条文本生成任务。
6. 对日常真实请求中的欠规格问题，用 LLM 扮演产品经理，将 query 改写成结构化 Web design document。

**结构化设计文档要求**：

- `page content`：页面内容、信息架构、模块组成。
- `interaction behaviors`：用户动作、状态流转、反馈、异常状态等。
- `visual appearance`：颜色、布局、字体、组件风格、响应式要求等。

**关键设计理由**：真实用户 query 往往约束不足，模型输出差异会很大，不利于自动评测。改写成结构化设计文档可以降低主观性，同时保留真实需求的应用场景。

### 2.2 Vision-Guided Generation

**任务定义**：输入是一组网页截图。截图不仅展示内容、布局和视觉风格，也尽量体现交互功能。模型需要生成完整 Web 仓库，使外观和功能匹配截图。

**截图集合分两类**：

- 主页面 + 子页面截图：测试多页面复现、页面依赖关系和导航结构。
- 浏览过程中的状态变化截图 / keyframes：测试动态状态和交互变化。

**构造流程**：

1. 以 **WebRenderBench** 中视觉复杂网页为基础，因为普通截图数据集 UI 过于简单。
2. WebRenderBench 通常每个网站只有一张截图，因此做增强：
   - 解析 `index.html` 中引用的子页面 URL。
   - 随机选择 2 个子页面。
   - 用 Playwright 捕获子页面截图。
3. 为了显式测试多页面依赖，在主页面截图上注入 JavaScript overlay，用彩色 bounding boxes 标注子页面链接位置。
4. 针对网络不稳定、动态加载导致的截图瑕疵，先做多轮 LLM verification，过滤空白、资源缺失、布局损坏等问题。
5. 最后人工检查，保留高质量样本。
6. 另从 V0 和 Figma 的真实动态页面中手动抽取关键帧，补充静态截图无法表达的状态变化。

**注意**：正文 2.2.2 末尾提到“multi-page screenshots + dynamic keyframe sequences together constitute the Video-Guided Generation test set”，但按任务定义和附录 A.6，更合理的理解是：多页面截图属于 Vision-Guided Generation，动态关键帧是介于图像和视频之间的动态视觉输入补充；真正 Video-Guided Generation 由录屏构成。

### 2.3 Video-Guided Generation

**任务定义**：输入是包含多步用户交互的屏幕录制视频。模型需要生成外观、交互和动画都与视频一致的完整 Web 仓库。

**数据来源**：

- V0 中具有丰富动态效果的网页。
- Figma 中具有交互/动效的页面或原型。

**构造流程**：

1. 人工选择具有丰富动态行为的网页，覆盖不同应用类别。
2. 标注者先自由探索网页，理解所有可交互功能。
3. 标注者规划完整 exploration path，确保录制路径覆盖关键交互。
4. 按规划路径浏览并录制屏幕视频。
5. 视频重点覆盖静态截图难表达的信息：
   - 动画时序。
   - hover/click/scroll 等触发状态。
   - 多步 workflow。
   - 页面状态迁移。
   - loading、反馈、过渡、micro-interaction。

**模型提示词细节**：

- 要求先做 temporal sequence analysis：理解帧序列、动画 timing/easing、状态迁移。
- 要求抽取视觉设计：颜色、字体、间距、阴影、圆角、透明度、层级。
- 要求分析 layout：Flex/Grid/positioning、响应式断点、组件层次。
- 要求分析 interaction pattern：button 状态、触发器、状态管理、反馈。
- 实现侧要求语义化 HTML、CSS variables、现代布局、60fps 动画、`requestAnimationFrame`、debounce/throttle、事件委托和清理。

### 2.4 Text-Guided Editing

**任务定义**：输入为一个已有 Web code repository 和文本编辑指令。模型输出代码补丁，使修改后网页满足指令。

**原型来源**：Editing 和 Repair 共用一批高质量 Web prototypes。原型来自 WebRenderBench test set。

**原型筛选流程**：

1. **长度过滤**：
   - 所有代码文件总字符数限制在 32k 到 64k。
   - 单个文件不超过 48k 字符。
   - 目标是保留中大型多文件前端项目的协调复杂度，同时避免太小无难度、太大导致上下文截断。
2. **自动质量打分**：
   - 用 GPT-4o 做 10 分制 code review。
   - 保留得分 `>= 9` 的候选，得到 81 个 candidates。
3. **人工筛选与扩展**：
   - 人工选出 50 个高质量 prototypes。
   - 每个 prototype 保留单页版本。
   - 额外扩展成多页版本，添加额外页面、跨页导航和共享资源。

**编辑任务构造流程**：

1. 从 clean/executable prototype 出发，作为 source website。
2. 从 16 类预定义编辑操作中选择任务类型。
3. 为每类任务聚合/编写新增或增强需求。
4. 需求描述明确说明“要改成什么”，包括：
   - UI 更新。
   - 交互流程。
   - 状态反馈。
5. 刻意不泄漏实现细节，例如：
   - class name。
   - selector。
   - 精确 CSS value。
   - 具体 DOM 结构。
6. source website + requirements 组成 text-guided editing instance。

**输出格式**：

模型必须输出 XML 风格 search/replace block：

```xml
<search_replace path="path/to/file">
<search>
exact text to find in the original file
</search>
<replace>
replacement text with the modification applied
</replace>
</search_replace>
```

新建文件时 `<search></search>` 为空，`replace` 放完整文件内容。`search` 必须与原文件完全一致，包括空格和缩进；一个 block 只能有一组 search/replace；一次响应内完成所有修改。

### 2.5 Vision-Guided Editing

**任务定义**：输入包含当前网页截图、对应 Web 仓库和编辑指令。模型输出补丁，使编辑后页面满足指令或视觉参考。

**与 Text-Guided Editing 的共性**：

- 使用同一批 single-page / multi-page prototypes。
- 使用同一套 16 类编辑操作。
- 输出同样是 search/replace patch。
- 指令同样遵循“说明目标，不泄漏实现方法”原则。

**额外输入**：

- 当前状态截图：`Current State Screenshots`。
- 论文描述中说 Vision-Guided variants additionally supply a reference screenshot in lieu of or alongside textual instruction；提示词附录中展示的是“当前状态截图 + 任务描述”，本地样例中也包含 `src_screenshot` 字段。

**构造意图**：

- 测试模型从截图理解当前 UI 状态的能力。
- 测试视觉信息和代码仓库上下文对齐能力。
- 比纯文本编辑更接近真实前端开发中的“看图改页面 / 对着当前页面改”的场景。

### 2.6 Diagnostic Repair

**任务定义**：输入为有缺陷的 Web 仓库和文本问题描述。模型输出代码补丁，修复描述中的问题。

**核心思想：reverse construction**。

Repair 不从真实 bug 直接收集，而是从一个 clean prototype 反向注入可解释、可观察、可逆的前端缺陷。

**构造流程**：

1. 以 clean Web prototype 作为 destination / target website。
2. 用 LLM 注入来自 11 类 repair defect type 的缺陷，生成 faulty source website。
3. 模型任务是把 faulty source 修回 clean destination。
4. 生成自然语言 repair instruction，只给模糊诊断提示：
   - 提示潜在 defect type 或底层问题。
   - 不完整描述 bug。
   - 不泄漏具体实现位置、selector 或 CSS 值。
5. 为每个 repair instance 保留精确 text-level search/replace annotation。
6. 该 annotation 是 defect-injection edits 的严格逆操作。

**这样设计的好处**：

- 有唯一、可运行的正确目标。
- source 到 destination 的转换可复现。
- 可以自动验证和定位错误。
- 可避免真实 bug 数据中常见的目标不唯一、描述模糊、不可复现问题。

**缺陷生态有效性**：

11 类缺陷不是随意选的。作者分析了 200+ 个 V0 社区提交及对应 GitHub Issues，抽取高频前端反模式和 bug 类型，例如 Occlusion、Overflow、Loss of Interactivity。

### 2.7 Visual-Diagnostic Repair

**任务定义**：输入为有缺陷 Web 仓库、当前缺陷截图、目标状态截图和问题描述。模型输出补丁，修复仓库。

**与 Diagnostic Repair 的共性**：

- 同样采用 clean prototype -> LLM 注入缺陷 -> faulty source 的 reverse construction。
- 同样使用 11 类 repair defect type。
- 同样保留 ground-truth inverse search/replace patch。
- 同样要求模型不能修超过指定数量的问题：提示词中写明 `You have only {N} issues to fix, and you cannot fix more than {N} issues.`

**额外输入**：

- Current State Screenshots：显示 defective state。
- Target State Screenshots：显示 expected result。

**构造意图**：

- 测试视觉诊断能力：模型需要看出当前截图哪里坏了。
- 测试视觉目标对齐能力：模型需要向 target screenshot 靠近。
- 比文本修复更接近真实的“截图报 bug / 截图验收修复”流程。

## 3. 三套 taxonomy

### 3.1 Generation 的 15 个应用域

1. E-commerce & Fintech
2. Enterprise & Productivity
3. Social & Communication
4. Data Science & Analytics
5. Content Creation & Multimedia
6. Entertainment & Streaming
7. Game Development & Gaming
8. Education & Learning
9. Simulation & Scientific Modeling
10. Infrastructure & System Management
11. DevTools & Engineering
12. Logic & Workflow Visualization
13. Location Services & Transit
14. Information & Personal Branding
15. Lifestyle & Niche Utilities

### 3.2 Editing 的 16 个操作类型

论文将 16 类编辑任务分成四组。

**Complex Components**

1. Data Table：排序、分页、过滤、行选择、行内编辑。
2. Rich Text Editor：WYSIWYG、格式工具栏、链接/图片插入、表单同步输出。
3. Drag & Drop Interface：拖拽项、drop zone 反馈、跨容器重排、状态持久化。
4. Tree View：嵌套展开/折叠、级联选择、搜索过滤。

**Frontend-Backend Integration**

5. Real-time Dashboard：实时更新 metric cards、动画数字、sparkline charts。
6. Infinite Scroll：滚动触发 lazy loading、skeleton placeholder、end-of-content 状态。
7. Async Form Validation：debounced server-side validation、inline status、submit gating。
8. File Upload with Progress：拖放上传、单文件进度条、队列管理、取消。

**Advanced Animations**

9. Parallax Scrolling：多层差速滚动、viewport-triggered fade/scale。
10. Page Transitions：SPA 内容视图间 fade/slide/zoom enter/exit 动画。
11. Particle Effects：canvas 粒子系统、物理、鼠标交互、连接线。
12. Skeleton Loading：与内容结构匹配的 shimmer placeholder 和平滑 reveal。

**Business Scenarios**

13. Shopping Cart：数量控制、实时总价、localStorage 持久化。
14. User Authentication：登录、注册、找回密码、校验、认证状态管理。
15. Multi-step Wizard：步骤条、每步校验、跨步数据持久化、review summary。
16. Notification Center：通知下拉、未读 badge、分类 alerts、mark-as-read。

### 3.3 Repair 的 11 个缺陷类型

**Visual Layout**

1. Occlusion：z-index 或定位错误导致元素遮挡重要内容。
2. Crowding：margin/padding 不足或被移除，元素过于拥挤。
3. Text Overlap：文本容器尺寸或定位错误，导致文字与其他元素重叠。
4. Alignment：元素偏离网格或 sibling 对齐关系。
5. Color & Contrast：文本和背景对比不足，影响可读性。
6. Overflow：内容超出固定容器且缺少 overflow 处理。
7. Sizing/Proportion：尺寸或宽高比异常，元素被拉伸/压缩。

**Semantic Correctness**

8. Semantic Error：语义 HTML 被替换为非语义元素，例如 `h1` 变成 `div`。
9. Nesting Error：非法 HTML 嵌套，例如 `a` 内嵌 `a`、`p` 内嵌 `div`。

**Interactive Usability**

10. Loss of Interactivity：交互元素被 `disabled`、`pointer-events: none` 等阻断。
11. Missing Attributes：移除必要属性，例如 `alt`、`aria-label`。

## 4. 质量控制

WebCompass 对所有任务做三层质量控制。

**自动检查**

- 所有代码仓库必须能在 headless Chromium 中 compile/render，且无 fatal error。
- Editing 和 Repair 的 patch 必须能干净应用到 source repository。
- Repair 的 search/replace annotation 必须是 defect-injection edits 的精确逆操作。

**LLM 辅助筛选**

- 对 requirements 和 screenshots 做多轮质量检查。
- Vision-Guided Generation：检查截图是否完整，是否有空白区域、资源缺失、网络导致的 broken layout。
- Editing / Repair：检查自然语言指令是否清晰、不泄漏实现细节、与底层代码修改一致。

**人工审核**

- 检查任务描述的正确性和完整性。
- 检查截图和视频视觉质量。
- 检查 Easy/Medium/Hard 难度是否合适。
- 检查 requirements 与 ground-truth patch 是否对齐。
- 不合格样本会被修订或丢弃。

## 5. 评测方案和输出约束

### 5.1 Generation：Agent-as-a-Judge

Generation 输出是完整网站，开放性强，单靠静态 diff 或截图相似度不够。因此论文用 Agent-as-a-Judge：

1. **Checklist generation**：LLM 根据任务生成固定 checklist，包含 task、operation sequence、expected result、criteria、max score。生成后 checklist 保持不变，防止循环评价。
2. **Browser interaction**：评测 agent 在 headless Chromium 中打开网站，通过 MCP/Chrome DevTools 执行点击、输入、滚动、导航等操作，记录 DOM、console logs、screenshots。
3. **Adaptive code verification**：agent 为每个 checklist item 合成 JavaScript tests，检查 DOM 状态、CSS 属性和交互行为；若实现细节不同，只允许适配 selector/ID，不允许改行为断言。
4. **Evidence-grounded scoring**：每项基于截图、测试结果、console logs 等硬证据打分。

三个防偏机制：

- checklist immutable。
- selector-only adaptation。
- 每个分数必须有可审计证据。

Generation 模型输出要求是纯 Markdown，每个文件按以下格式给出：

````markdown
# path/to/file.ext
```ext
<full file content>
```
````

Vision-Guided Generation 额外要求包含 `README.md`，说明最简单本地运行方式；必须能通过 static server 运行，优先 Vite 或纯静态文件。

### 5.2 Editing / Repair：LLM-as-a-Judge

Editing 和 Repair 都是局部 patch，解空间更受约束，因此使用 checklist-guided LLM-as-a-Judge。

流程：

1. 将模型生成的 search/replace patch 应用到 source repo。
2. 丢弃无法应用的 block。
3. 在 headless Chromium 中启动修改后项目。
4. 截取 before/after screenshots。
5. 对 Editing，judge 接收：
   - task instruction。
   - generated patch。
   - original UI screenshot。
   - modified UI screenshot。
   - build/runtime logs。
6. 对 Repair，judge 额外接收：
   - defect description。
   - ground-truth code modification。
   - before-fix screenshot。
   - after-fix screenshot。
   - ground-truth fixed screenshot。
7. 每个子任务从 Execution、Interactivity、Aesthetics 三个维度 0-10 打分，并输出 JSON。

### 5.3 三个统一评分维度

- **Execution**：项目能否构建/启动/运行，patch 语法和应用位置是否正确，是否有运行时错误。
- **Interactivity**：原有或需求中的交互是否可用，是否保留功能，是否有回归。
- **Aesthetics**：视觉质量、布局、颜色、字体、间距、与原风格或 target reference 的一致性。

### 5.4 失败处理

Generation 中常有级联失败，论文定义了 fallback：

- **Complete build failure**：项目无法编译或启动，Interactivity 和 Aesthetics 设为 0，只给 Execution 有意义分数。
- **Partial rendering failure**：部分页面/组件渲染失败，Execution 按比例扣分；Aesthetics 在可见部分评分，若完全不可见则 0；Interactivity 只评 reachable components。
- **Runtime crash**：初始渲染后交互中崩溃，Execution 和 Aesthetics 基于初始渲染评分；Interactivity 只评可测试子集，不可测项为 0。

## 6. 对复现/扩展数据构造的启发

1. **不要只补齐表格**：每类任务都应服务一个明确能力假设，例如“模型是否能从视觉状态恢复交互逻辑”“模型是否能在不泄漏 selector 的情况下做仓库级编辑”。
2. **生成任务要降低欠规格性**：真实 query 可以保留，但最好转成结构化 design doc，否则自动评测会被主观创意污染。
3. **编辑任务要描述目标，不描述实现**：指令里避免 class、selector、CSS 精确数值，逼近真实需求。
4. **修复任务适合 reverse construction**：先有 clean target，再注入可逆缺陷，比直接收集真实 bug 更容易保证唯一答案和可验证性。
5. **视觉任务需要多阶段过滤**：截图/视频最容易被网络和动态加载污染，LLM 过滤只能做初筛，最后仍需要人工看。
6. **评测必须运行网页**：Web 开发能力不能只看代码或单张图，交互、状态流、console/network 错误都要纳入。
7. **patch 格式要严格**：search/replace 能让编辑和修复任务可自动应用、可定位失败，也方便构造 ground truth。

# 14 个前端 / Web Coding Benchmark 调研与 Query 覆盖设计报告

日期：2026-08-20

## 0. 结论先行

这 14 个 benchmark 不能被简单理解为 14 类“生成网站的文本 query”。它们实际覆盖五种不同的评价对象：

1. **从零生成**：WebCompass Generate、ArtifactsBench、WebGen-Bench，以及 Vision2Web 的分层网站开发任务。
2. **视觉还原**：Design2Code、Web2Code、Flame-React-Eval、DesignBench Generate、Vision2Web L1/L2、ComUIBench。
3. **增量开发与修复**：WebCompass Edit/Repair、DesignBench Edit/Repair/Compile Repair、FullFront Interaction Authoring/Code Refinement、Flame 的 multi-image update。
4. **长程与需求交互**：FronTalk、InteractWeb-Bench，以及多页 WebGen/Vision2Web。
5. **前端感知与理解**：WebUIBench、FullFront Perception QA、Web2Code WUB。

因此，“全面覆盖 query”不能只做一个文本字段。至少要维护以下五种原生任务包：

| 任务包 | 必需字段 | 不能省略的原因 |
|---|---|---|
| Text Generate | `instruction` | 适合 ArtifactsBench、WebGen-Bench、WebCompass Text Generate |
| Visual Generate | `instruction + screenshot(s) + viewport/resource manifest` | 单靠文字无法训练真实截图还原、响应式变化和跨页视觉一致性 |
| Edit | `current project + change request + current/target evidence + preservation contract` | Edit 的核心不只是实现新要求，还包括不破坏非目标区域 |
| Repair | `faulty project + failure evidence + expected behavior/visual oracle` | 只有“请修复”无法训练根因定位，也无法区分修复与重写 |
| Dialogue/Agent | `history + current state + latent requirements/test slots + allowed actions` | FronTalk 的遗忘、InteractWeb-Bench 的主动澄清不能压成单轮最终需求 |

如果当前目标只是扩充 **Generate-only 文本 query**，它可以有效覆盖 ArtifactsBench、WebGen-Bench 和 WebCompass Text Generate 的一部分能力，但不能据此声称覆盖了全部 14 个 benchmark。尤其不能把截图 benchmark 的视觉信息“脑补”为文字，也不能把多轮 benchmark 合并成最终状态后仍标注为 FronTalk/InteractWeb-Bench 原生覆盖。

## 1. 需要先校正的边界

### 14 榜的原生 Edit 任务核对（2026-09-05）

**当前重点：WebCompass 与 DesignBench。** 另外保留 WebUIBench 的元素级编辑、FullFront 的视觉完善、Flame 的版本更新实验、FronTalk 的连续开发作为不同粒度的补充来源。FrontendBench 是此前 Construct 的额外参考，归在本项目固定 14 榜之外。

判定依据是任务要求改变已有页面/代码的实现，而非仅仅出现“交互前后截图”或算法内部反复改代码。原生 Edit、版本更新实验、多轮开发和生成方法的自我修订分别记录；输出完整代码也可以属于 Edit，patch 是输出格式的另一层选择。DesignBench 另设 image-only 等上下文变体，因此输入是否带源码也需要结合原生任务目标判断。

| Benchmark | 原文任务输入与目标 | 本次归类与原文定位 |
|---|---|---|
| WebCompass | 既有项目＋修改要求，按要求增加或调整功能 | 原生 Edit；16 种任务，11 类为 Repair。[§2.2.4、§2.5.1](https://arxiv.org/html/2604.18224v1) |
| DesignBench | 既有页面代码/图像上下文＋编辑指令，改变设计实现 | 原生 Design Edit；新增/修改/删除 × 文本/颜色/位置/尺寸/形状/组件两个轴。[§IV-C、§VI-D](https://arxiv.org/html/2506.06251v1) |
| WebUIBench | 既有 HTML 元素代码＋自然语言修改要求，输出修改后的片段 | 原生 Code Function Editing；元素级静态编辑。[§2.2 Task 6、附录 A.4 Task 6](https://arxiv.org/html/2506.07818v1) |
| FullFront | HTML-v1＋HTML-v2 的目标截图，完善旧 HTML | Code Refinement，50 个样本，属于视觉驱动修改。另一个 Interaction Authoring 的测试输入是交互前后截图，属于交互还原。[§2.3、附录 B.2](https://arxiv.org/html/2505.17399v1) |
| Flame-VLM-Code | 旧设计图＋旧代码＋新设计图，输出更新代码 | 论文 multi-image 版本更新任务；§6.6 明确改造 benchmark 做了评测，单独按扩展实验记录。[§6.6、附录 A.5](https://arxiv.org/html/2503.01619v1) |
| FronTalk | 新一轮文字/视觉指令＋历史对话及代码输出，继续更新网站 | 连续开发任务；后续轮次具有 Edit 性质，首轮与后续轮次分开。每段对话十轮，评价需求完成与旧功能遗忘。[§2.1–2.4、算法 1](https://arxiv.org/html/2601.04203v1) |
| Interaction2Code | 交互前后原型截图，生成能复现操作效果的网页 | 交互网页生成；截图描述用户操作状态变化。[§II-B、§IV-B](https://arxiv.org/html/2411.03292v3) |
| Vision2Web | 原型图及相应需求，交付静态页、多页前端或全栈网站 | 分层生成任务。[§2.1、附录 A.3.1](https://arxiv.org/html/2603.26648v1) |
| ArtifactsBench | 任务需求，生成网页、工具、游戏等 artifact | 生成任务；Multimedia Editing 指所生成工具的用途。[§2.2、表 2](https://arxiv.org/html/2507.04952v1) |
| Design2Code | 目标截图，生成匹配的 HTML/CSS | 截图还原；self-revision 是同一生成目标下的推理策略。[NAACL 正式论文 §2–4](https://aclanthology.org/2025.naacl-long.199.pdf) |
| WebGen-Bench | 网站需求，构建多文件代码库 | 从零生成。[§3](https://arxiv.org/html/2505.03733v1) |
| InteractWeb-Bench | 含缺失/歧义/冲突的初始需求，与模拟用户澄清后交付网站 | 交互式生成；执行过程允许反复修改，任务目标仍是完成初始网站需求。[§3.1–3.3](https://arxiv.org/html/2604.27419v1) |
| ComUIBench | 同一网站的多页设计截图，生成可复用组件与页面 | 多页生成与组件复用评测；ComUICoder 的元素增删、位置/尺寸/内容修订是方法内部反馈步骤。[§2.1、§3、§4.5](https://arxiv.org/html/2602.19276v1) |
| Web2Code | 网页截图，生成 HTML 或回答网页理解问题 | WCGB 生成与 WUB 理解；训练数据精炼是数据处理流程。[§3–4](https://arxiv.org/html/2406.20098v1) |

**WebUIBench 是此前速查表遗漏的直接 Edit 来源。** 附录明确列出四组构造方式：修改元素属性、修改文本、增加或修改样式、增加或删除子节点。其 §4.1 按生成 HTML 与标准答案的字符串相似度评分；这类任务适合补充精确局部修改，粒度与 WebCompass 的完整业务功能扩展分别记录。

通俗例子（自拟，说明粒度）：已有按钮 `<button>查看</button>` → 指令“将按钮文字改为查看详情” → 修改后的元素代码 → 检查该按钮的 DOM 文本。相比之下，WebCompass 式任务可能要求给整页增加包含选择、数量、总价与状态保存的购物流程。

本轮按论文阅读流程核对任务定义、构造过程、输入输出、相关评测与附录，产物为任务边界核对表。版本：Interaction2Code v3，Design2Code NAACL 2025 正式版，其余为表中 arXiv v1。研究优先级按用户要求确定为 WebCompass、DesignBench；其他四个具有修改任务或开发轮次的来源按各自粒度补充。

### Edit 类型与在线灵感库核对（2026-09-05）

本次按 Construct 当前源码、官方论文任务定义及 9-URL 小试的卡片/浏览器记录核对；范围是类型和证据对应关系。

**Construct 当前目录。** `construct/construct_common.py:1850` 的基础目录为 40 项，其中前 16 项对应 WebCompass 官方 Edit，后 24 项为沿用的组件/功能目录；`:1940` 再补 16 项参考 benchmark 能力整理的细粒度行为。实际导入 `load_edit_catalog()` 得到 `all=56`、`webcompass=56`，`interaction2code/artifactsbench/frontendbench` 各 12 项。`construct_text_editing.py` 默认 balanced 轮换这些本地 profile。`task_specs.py::INTERACTION_TYPES` 的 22 项则是另一层交互标签。完整简表已写入[项目 AGENTS.md](../../AGENTS.md)。

**分类来源补充。** [0805 扩展方案 §3.2](0805_edit_repair_interaction_expansion_plan_20260820.md) 和 `task_specs.py::BENCHMARK_SOURCES_BY_INTERACTION` 明确记录：交互扩展参考 Interaction2Code、ArtifactsBench、FrontendBench 与 WebCompass 的能力和评测要求，再转成 Construct 的 Edit 任务。例如悬停对应 Interaction2Code/FrontendBench/WebCompass，筛选对应 ArtifactsBench/FrontendBench/WebCompass。“本地”只表示目录在本项目实现，不能据此判断能力由项目凭空提出，也不能把参考任务的交互能力统称为原 benchmark 的官方 Edit 分类。当前记录能确认交互扩展的来源映射；沿用 24 项目录的逐项原始出处仍需按原始记录补充。

**原论文与历史记录追溯补充（2026-09-05）。** 用户确认构造设计参考多个 benchmark；现存扩展方案与代码映射支持这一总体来源。证据分成三层记录：官方分类、原论文中的具体能力、当时把能力纳入 Construct 的记录。

- **目录历史**：提交 `4bf60cd76fd93b12085cffafa68e3ebe44540c80`（北京时间 2026-06-03）明确记载 Edit 从 16 扩为 40，差异中一次加入下表所涉 24 项。提交说明与新增目录保留了扩展内容，逐项论文出处待追溯。当时的《四个 Benchmark 调研》讨论 WebCompass、Design2Code、Vision2Web、FLAME 的输入输出与数据要求；2026-08-20 的交互扩展方案则明确列出 Interaction2Code、ArtifactsBench、FrontendBench、WebCompass。两份“四个 benchmark”记录对应不同阶段。
- **已有交互扩展依据**：`task_specs.py` 保存 22 个交互标签的 benchmark 参考映射；当前目录另外增加 16 个细粒度行为。这是项目的来源记录，其每个映射对应的论文任务或示例仍按原文核对。例如筛选在 FrontendBench 附录 A 的金融产品页中有完整需求和测试，在 WebCompass 数据表要求中也直接出现。
- **能力改写为 Edit 的例子**：FrontendBench 原任务是生成带类别筛选的产品页；用于扩增时可写成“给已有产品列表增加类别筛选，选择后更新商品范围，切回全部恢复列表”。前者提供能力依据，后者是我们组织的增量任务形式。

**历史宽口径核查的适用范围。** 此前找到的深色切换、日期选择、弹窗实例位于 Interaction2Code 的生成任务；FullFront 的弹窗/提示来自 Interaction Authoring；FrontendBench 的颜色选择与撤销/重做出现在生成任务测试输出中，且该输出与附录金融产品页段落错配。以上记录作为一般能力参考保留。本次用户要求的 **Edit-only 对应以以下逐项表为准**。

#### 56 类目录与 22 个标签：只对应 benchmark 的 Edit 任务

口径：只有原生 Edit、明确更新旧实现的评测任务，或 FronTalk 首轮之后的开发需求，才可填写对应关系；方法内部修订与生成任务中的能力分别记录。**“没有”指在本次核对的原文任务定义及附录中没有找到明确 Edit 依据，并非断言所有公开样本都不含该能力。** 对应表示任务内容上的关系，历史采用来源另查提交记录。

证据索引（完整题名、版本和阅读位置）：

- **W**：[WebCompass: Towards Multimodal Web Coding Evaluation for Code Language Models](https://arxiv.org/html/2604.18224v1#S2.SS5)，v1，表 2 与 §2.5.1 的四组 Edit 定义。
- **F**：[FronTalk: Benchmarking Front-End Development as Conversational Code Generation with Multi-Modal Feedback](https://arxiv.org/html/2601.04203v1#A2)，v1，§2.1 的历史代码更新协议与附录 B 第 2–10 轮需求/测试；对应表明确标为连续 Edit，而非官方独立类别。
- **D**：[DesignBench: A Comprehensive Benchmark for MLLM-based Front-end Code Generation](https://arxiv.org/html/2506.06251v1#S4.SS3)，v1，§IV-C 的 Design Edit 两轴分类。
- **U**：[WebUIBench: A Comprehensive Benchmark for Evaluating Multimodal Large Language Models in WebUI-to-Code](https://arxiv.org/html/2506.07818v1)，v1，§2.2 与附录 A.4 Task 6 的元素级编辑定义。
- **FullFront / Flame**：沿用上一节的 v1 原文与任务边界，分别核对 Code Refinement（附录 B.2）和版本更新实验（§6.6）；按明确任务实例建立细类对应。

**A. 官方 16 类。** 每项都是 WebCompass 的官方 Edit 类别。

| 中文类型 | 代码标签 | 对应 benchmark Edit |
|---|---|---|
| 数据表 | Data Table | WebCompass Edit：Data Table（W） |
| 富文本编辑器 | Rich Text Editor | WebCompass Edit：Rich Text Editor（W） |
| 拖放界面 | Drag & Drop Interface | WebCompass Edit：Drag & Drop Interface（W） |
| 树形视图 | Tree View | WebCompass Edit：Tree View（W） |
| 实时看板 | Real-time Dashboard | WebCompass Edit：Real-time Dashboard（W） |
| 无限滚动 | Infinite Scroll | WebCompass Edit：Infinite Scroll（W） |
| 异步表单验证 | Async Form Validation | WebCompass Edit：Async Form Validation（W） |
| 带进度的文件上传 | File Upload with Progress | WebCompass Edit：File Upload with Progress（W） |
| 视差滚动 | Parallax Scrolling | WebCompass Edit：Parallax Scrolling（W） |
| 页面转场 | Page Transitions | WebCompass Edit：Page Transitions（W） |
| 粒子效果 | Particle Effects | WebCompass Edit：Particle Effects（W） |
| 骨架屏 | Skeleton Loading | WebCompass Edit：Skeleton Loading（W） |
| 购物车 | Shopping Cart | WebCompass Edit：Shopping Cart（W） |
| 用户认证 | User Authentication | WebCompass Edit：User Authentication（W） |
| 多步向导 | Multi-step Wizard | WebCompass Edit：Multi-step Wizard（W） |
| 通知中心 | Notification Center | WebCompass Edit：Notification Center（W） |

**B. 沿用的 24 类组件/功能。**

| 中文类型 | 代码标签 | 对应 benchmark Edit |
|---|---|---|
| 深浅主题切换 | Dark Mode Toggle | 没有；静态改颜色与可切换主题分别计 |
| 折叠面板 | Accordion | 没有；树节点展开/折叠与 Accordion 分别计 |
| 模态对话框 | Modal Dialog | 没有 |
| 提示浮层 | Tooltip | 没有 |
| 面包屑导航 | Breadcrumb Navigation | 没有 |
| 选项卡 | Tabs | 没有 |
| Toast 通知 | Toast Notifications | 没有；通知中心与 Toast 分别计 |
| 星级评分 | Star Rating | 没有 |
| 复制到剪贴板 | Copy to Clipboard | 没有 |
| 回到顶部 | Back to Top | 没有 |
| Cookie 偏好 | Cookie Consent | 没有 |
| 响应式导航 | Responsive Navigation | 没有 |
| 吸顶页头 | Sticky Header | 没有 |
| 搜索自动补全 | Search Autocomplete | 没有；F 第 7 轮是提交关键词后搜索，属于另一种能力 |
| 图片灯箱 | Image Lightbox | 没有 |
| 倒计时 | Countdown Timer | 没有；自动轮播的计时与倒计时组件分别计 |
| 颜色选择器 | Color Picker | 没有；编辑颜色样式与颜色选择器分别计 |
| 日期选择器 | Date Picker | 没有 |
| 轮播 | Carousel | FronTalk 连续 Edit：F 第 3 轮新增三篇文章自动轮换及前后箭头，第 6 轮新增轮换动画 |
| 键盘快捷键 | Keyboard Shortcuts | 没有 |
| 右键菜单 | Context Menu | 没有 |
| 图片懒加载 | Lazy Loading Images | 没有；W 无限滚动明确的是内容延迟加载，图片专项要求另计 |
| 打印样式 | Print Stylesheet | 没有 |
| 撤销/重做 | Undo Redo | 没有 |

**C. 细粒度 16 类行为。** 这里注明父 Edit 任务中的对应要求；它们是从任务要求整理的行为标签，区别于官方独立类别。对应到某项行为也只支持表内列出的范围，Construct prompt 附加的键盘替代、持久化、空状态等要求逐项另核。

| 中文类型 | 代码标签 | 对应 benchmark Edit 与具体范围 |
|---|---|---|
| 点击状态 | Click State | FronTalk 连续 Edit：F 第 2 轮点击点赞后计数增加 |
| 悬停状态 | Hover State | FronTalk 连续 Edit：F 第 4/5/6/9/10 轮悬停改变颜色、缩放、抬升或动画 |
| 焦点状态 | Focus State | 没有 |
| 输入驱动更新 | Input-driven Update | WebCompass Edit：W Async Form Validation 输入触发校验状态反馈；仅对应此分支 |
| 选择控件 | Select Control | WebCompass Edit：W Data Table 行选择、Tree View 级联选择；部分对应选择行为，select/listbox 的具体控件要求待证 |
| 开关控件 | Toggle Control | 没有；点赞累加与可开关的二态控件分别计 |
| 选项卡切换 | Tab Switch | 没有 |
| 下拉菜单 | Dropdown | WebCompass Edit：W Notification Center 通知下拉；键盘与关闭方式等细节另核 |
| 排序 | Sort Control | WebCompass Edit：W Data Table 排序 |
| 筛选 | Filter Control | WebCompass Edit：W Data Table 筛选、Tree View 搜索筛选 |
| 分页 | Pagination | WebCompass Edit：W Data Table 分页 |
| 导航流程 | Navigation Flow | FronTalk 连续 Edit：F 第 3/7/8 轮文章详情及搜索结果导航；返回时状态保留另核 |
| 表单验证 | Form Validation | WebCompass Edit：W Async Form Validation、User Authentication、Multi-step Wizard |
| 条件显示 | Conditional Rendering | WebCompass Edit：W Tree View 按展开状态显示子节点；仅对应该显示分支 |
| 加载状态 | Loading State | WebCompass Edit：W Infinite Scroll 加载占位与结束状态、Skeleton Loading 占位到内容显示 |
| 动画状态 | Animation State | WebCompass Edit：W Parallax Scrolling、Page Transitions、Particle Effects、Skeleton Loading；F 第 6/9/10 轮也有明确动画变更 |

**D. `task_specs.py` 的 22 个动作/行为标签。** 与上面 56 项分层使用；旧 `BENCHMARK_SOURCES_BY_INTERACTION` 保留的是一般能力参考映射，本表是本次核对的 Edit-only 对应。

| 标签 | 对应 benchmark Edit |
|---|---|
| click | FronTalk 连续 Edit：F 第 2 轮点赞 |
| hover | FronTalk 连续 Edit：F 第 4/5/6/9/10 轮悬停效果 |
| focus | 没有 |
| input | WebCompass Edit：W 异步表单验证；F 第 7 轮搜索输入 |
| select | WebCompass Edit：W 数据表行选择、树级联选择 |
| toggle | 没有 |
| tab_switch | 没有 |
| accordion | 没有 |
| dropdown | WebCompass Edit：W 通知中心下拉 |
| modal | 没有 |
| tooltip | 没有 |
| carousel | FronTalk 连续 Edit：F 第 3/6 轮轮播 |
| drag_drop | WebCompass Edit：W 拖放界面、拖放上传 |
| sort | WebCompass Edit：W 数据表排序、拖放重排 |
| filter | WebCompass Edit：W 数据表与树筛选 |
| pagination | WebCompass Edit：W 数据表分页 |
| navigation | FronTalk 连续 Edit：F 第 3/7/8 轮详情与结果页导航 |
| form_validation | WebCompass Edit：W 异步验证、认证、多步向导 |
| conditional_rendering | WebCompass Edit：W 树展开/折叠对应的子节点显示 |
| loading_state | WebCompass Edit：W 无限滚动、骨架屏 |
| toast | 没有 |
| animation | WebCompass Edit：W 转场、视差、粒子、骨架屏；F 第 6/9/10 轮动画 |

**DesignBench、WebUIBench 的对应粒度。** D 的官方分类是新增/修改/删除与文本/颜色/位置/尺寸/形状/组件两轴；U 是元素属性、文本、样式、子节点增删。两者提供直接 Edit 分类，但当前 56 个名称并未单列这些静态编辑轴；具体组件的行为需要相应任务证据。例如“把按钮背景改为深色”可以对应 D 的颜色修改或 U 的样式修改，“增加深浅主题开关并保存选择”则还需动态切换依据。FullFront 与 Flame 的更新输入输出同理，逐个组件按实例核对。

本轮阅读范围为上述论文的 Edit 定义、相关附录需求与已有源码标签；这是一份内容对应表，全部 benchmark 样本的逐条检索属于另一层覆盖核查。对应关系用于设计独立训练任务，样本内容与评测数据保持隔离。

**官方分类与任务边界。**

| 来源 | 原文定义 | 对本项目的用途 |
|---|---|---|
| [WebCompass](https://arxiv.org/html/2604.18224v1#S2.SS5) §2.4–2.5 | 16 类 Edit；11 类 Repair 缺陷 | 高级组件、动态效果与应用流程的主要参照；本地 56 项 profile 需保留本地来源标识 |
| [DesignBench](https://arxiv.org/html/2506.06251v1#S4.SS3) §IV-B/IV-C，图 5 | Edit 的两个标注轴：Add/Change/Delete；Text/Color/Position/Size/Shape/Component。摘要的“9 edit types”按 3+6 两轴理解 | 补充文本内容、排版、颜色、位置、尺寸、形状和整组件修改；保存修改前后的设计与代码 |
| [FronTalk](https://arxiv.org/html/2601.04203v1#S2) §2.1–2.3 | 100 个十轮对话；Functionality/Design 两类意图；每轮结合历史更新实现 | 组合功能开发与设计变更，保留历史需求和前序状态 |
| [Flame](https://arxiv.org/html/2503.01619v1#S6.SS6) §6.6 | multi-image update 输入旧设计、旧实现、新设计，输出新实现 | 布局、内容、样式变化的视觉驱动增量更新 |
| [FullFront](https://arxiv.org/html/2505.17399v1#A2.SS2) 附录 B.2 | Code Refinement 输入 HTML-v1 与 HTML-v2 的目标截图；Interaction Authoring 输入交互前后截图并生成完整网页 | 前者属于已有代码完善；后者提供交互类型参考，按截图还原任务记录 |
| [Interaction2Code: Benchmarking MLLM-based Interactive Webpage Code Generation from Interactive Prototyping](https://arxiv.org/html/2411.03292v3) §III-A/B、表 II、§V-B | 23 种元素标签与 8 种视觉变化，共 31 个分类标签；同一交互可多标签。原文有深色切换、弹窗和日期选择实例 | 为点击、输入、选择、显示变化及前后状态提供依据；31 个标签与 Construct 的组件目录分层记录 |
| [FrontendBench: A Benchmark for Evaluating LLMs on Front-End Development via Automatic Evaluation](https://arxiv.org/html/2506.13832v1) §3–4、附录 A | 五类应用、五档难度；每项包含需求与浏览器测试。附录产品页包含类别筛选、卡片与响应式网格 | 支持将应用中的交互和布局要求整理为 Edit；原文示例与测试输出的归属分别核对 |
| [ArtifactsBench: Bridging the Visual-Interactive Gap in LLM Code Generation Evaluation](https://arxiv.org/html/2507.04952v1) §2.2–2.3、表 2 | 游戏、网页应用、数据科学、管理系统、多媒体编辑工具等九大主题，按任务生成细粒度 checklist | 提供完整产品功能和视觉要求；“多媒体编辑”指生成的工具用途，与修改已有源码的 Edit 协议区分 |
| [WebGen-Bench: Evaluating LLMs on Generating Interactive and Functional Websites from Scratch](https://arxiv.org/html/2505.03733v1) §3、表 2、附录 L | 三大技术类、13 子类；测试覆盖搜索、筛选、文件操作、动态展示、响应式和组件样式 | 提供功能及视觉能力参考；原任务形式是从零建站 |

FullFront 的 10 种交互为：点击展开下拉、点击切换勾选、点击变背景色、点击弹窗、点击提示、点击显示输入框；悬停下拉、悬停加粗、悬停下划线、悬停提示。Interaction2Code 同样提供交互状态还原参考。其余榜单的生成、感知、组件复用或需求澄清任务按本报告各节记录，参考能力与原生 Edit 任务分别统计。

**9-URL 候选的对应情况。** 以 `runs/live_url_capability_mining_20260905/pilot_9_full_v2/` 的 60 张原始卡为边界；这是语义对应审阅，完整能力验收与全库覆盖率另行统计。

| 卡片中的内容 | 对应 Construct | 当前证据边界 |
|---|---|---|
| 数据表的排序、筛选、分页、行选择、列显隐 | Data Table；Sort/Filter/Pagination/Select Control | 有相关分项；完整数据表要求中的行内编辑等仍需逐项核对 |
| 树展开、层级搜索、父子勾选 | Tree View | 有层级选择结构；键盘、深度、虚拟化等分项另外核对 |
| 步骤导航、子步骤、按条件显示步骤 | Multi-step Wizard；Conditional Rendering | 有流程变体；跨步表单值保留及逐步校验另行核对 |
| 日期范围、预设日期、轮播、对话框、评分 | Date Picker；Carousel；Modal Dialog；Star Rating | 主要扩充本地组件目录与这些组件的变体 |
| 评分必填、半星键盘控制、悬停 | Form Validation；Focus/Hover/Select Control | 已有证据对应同步校验，异步校验需要等待/结果状态 |
| 上传入口、上传区方向调整与悬停 | File Upload with Progress 的入口；布局与 Hover State | 抽取结果未证明文件队列、进度、取消与完成状态，不能计为完整带进度上传覆盖 |
| 横竖布局、RTL、尺寸、间距、自定义符号 | 组件视觉变体；DesignBench 的位置/尺寸/形状/颜色等轴 | 按截图/布局证据保留具体效果，静态变体与实际修改过程分别记录 |

这批候选与 Construct 有明确重合，主要集中在少数组件及其变体。富文本、实时看板、无限滚动、异步校验、完整上传进度、视差、页面级转场、粒子、骨架屏、购物车、认证、通知中心等仍缺本批完整卡证据。轮播切换不等于页面级转场，普通校验不等于异步校验；60 张卡也不等于 60 种完整 Edit。

**此前“三张越界卡”的修正。** 当时线上抽卡 prompt 限定“只提取目标组件示例”，而浏览器材料仍包含整页 DOM/AX、文档控件和布局。`in_main` 只是位置标记；复制按钮和安装选项卡本来就在主内容中。模型因此把真实的文档站行为归到了 URL 指向的组件名下。对于用户要求的广义灵感库，处理方式应是校正对象、粒度与证据，而不是按文档站来源删除。

| 原始卡 | 实际发生的行为 | 当前判断 |
|---|---|---|
| `patternfly_multiple_file_upload__copy_example_code` | `b1_browser_2__step_1` 点击示例复制按钮，出现 Code copied 提示 | 可作为 Copy to Clipboard 候选，归到示例代码区域；提示证明反馈出现，剪贴板内容仍需对应证据 |
| `webawesome_carousel__carousel_import_tab_selection` | 安装区域切换 CDN/npm/Self-Hosted；保存的路径前三步成功，第四步失败 | 可作为 Tabs/Tab Switch 候选，归到安装说明区域；采用成功步骤支持的描述 |
| `webawesome_rating__rating_mobile_responsiveness` | 文档正文在移动视口变窄，宽表格产生横向溢出；原卡还把 `mobile_viewport` 写成了 `mobile` | 归到文档布局待复核；明确局部滚动容器、完整页面溢出和评分组件布局各自的范围 |

另发现 `webawesome_dialog__dialog_responsive_layout` 同时描述弹窗宽度和文档表格滚动，也有作用域混写。由此修正上一轮口径：这三张是先发现的归属问题，不能据此把剩余 57 张宣布为已验收有效卡；“53 张交互卡引用发生变化的路径”仅证明路径关联，不能代替逐项行为证明。本轮保留原始卡与证据，文档更新为上述判断。

完整例子：已有订单列表 → 借鉴真实树形选择，生成“增加地区层级筛选，选中省份联动城市，部分城市选中时省份显示半选，并同步订单范围与数量” → 目标为增加该行为的项目版本 → 浏览器勾选省/市、检查半选和订单变化。这里完整用户目标是按地区筛订单，勾选、半选、计数是同一功能内部要求。

### 1.1 “是否多页”不是简单的二元属性

- **WebCompass**：benchmark 级别支持项目级、多页任务，但七个子任务的具体实例范围并不完全相同。
- **Interaction2Code**：`new page` 是一种可观察的交互状态；它不等价于一个具有多路由、共享状态和跨页一致性的多页网站。
- **Vision2Web**：论文实际有三级：L1 静态响应式网页、L2 交互式多页前端、L3 长程全栈网站。当前表格只纳入 L1/L2，属于有意截断，而不是完整 Vision2Web。
- **WebGen-Bench / InteractWeb-Bench**：评价单位是项目级网站，部分要求天然产生多页或多视图，但不能把每条样本都机械标为“显式多页”。
- **FronTalk**：100 个十轮对话包含增量页面/功能开发；多页性取决于具体对话，不是所有轮次都天然多页。
- **FullFront / Design2Code / Web2Code / WebUIBench**：主要评价单位是单页、单视图或页面切片，不应从长截图推断多页。

### 1.2 “纯前端”也需要按 evaluator 边界定义

这里更有用的区分不是代码中有没有 API 字样，而是 benchmark 是否要求真实后端语义：

- **严格纯前端**：Design2Code、Interaction2Code、Flame-React-Eval、ComUIBench、WebUIBench、Web2Code，以及 DesignBench 的大部分任务。
- **前端为主，可用本地 mock/state 完成**：WebCompass、ArtifactsBench、FullFront、FronTalk。
- **项目级功能，可能跨出纯前端边界**：WebGen-Bench、InteractWeb-Bench；Vision2Web L3 明确是 full-stack。若当前训练边界不超过 WebCompass，应保留浏览器可观察语义，但把数据库、真实登录、支付、外部 API 改为本地持久化或明确的 mock contract。

### 1.3 公开数据集规模不能直接当作训练配额

样本规模反映的是作者的构造方式，不等于能力重要性。例如 WebUIBench 有约 21K QA，但它们主要测感知与 HTML 理解；ArtifactsBench 的 1,825 条是开放式 artifact query；FronTalk 只有 100 个对话，却提供 1,000 个有历史依赖的开发轮次。若按原始行数比例采样，QA 会淹没项目开发，长程状态保持又会严重欠采样。

## 2. 逐项调研

### 2.1 WebCompass

论文：[WebCompass: Towards Multimodal Web Coding Evaluation for Code Language Models](https://arxiv.org/abs/2604.18224)；数据：[NJU-LINK/WebCompass](https://huggingface.co/datasets/NJU-LINK/WebCompass)。

- **原生结构**：三种输入模态（文本、截图组、视频）× 三种生命周期任务（Generate、Edit、Repair），实际形成七类任务：Text/Vision/Video Generation、Text/Vision Editing、Diagnostic/Visual-Diagnostic Repair。
- **规模**：论文报告 1,526 个任务：123 / 109 / 94 个三类 Generate，300 / 300 个两类 Edit，300 / 300 个两类 Repair。
- **Generate 分类**：15 个领域，包括电商金融、企业生产力、社交通信、数据分析、多媒体、流媒体、游戏、教育、仿真、系统管理、DevTools、逻辑/工作流、交通位置、信息展示和生活工具。
- **Edit 分类**：16 种操作，包括数据表、富文本、拖放、树、实时看板、无限滚动、异步验证、上传进度、视差、页面转场、粒子、骨架屏、购物车、认证、多步向导和通知中心。
- **Repair 分类**：11 类缺陷：遮挡、拥挤、文字重叠、对齐、色彩/对比度、溢出、尺寸比例、交互丢失、语义错误、嵌套错误、属性缺失。
- **评测重点**：Generate 使用真实浏览器中的 Agent-as-a-Judge 探索并生成验收测试；Edit/Repair 使用细粒度 checklist 引导的多模态 judge。视觉美观、功能可执行和修改范围保护都是一等公民。

**Query 覆盖要求**：不要只按 15 个领域分桶。Generate query 还应显式组合页面数量、交互数量、状态持久化、视觉复杂度和测试路径。Edit 数据必须同时写清目标修改、允许修改范围和非目标保持项；Repair 必须保留缺陷证据与根因类型。

### 2.2 DesignBench

论文：[DesignBench: A Comprehensive Benchmark for MLLM-based Front-end Code Generation](https://arxiv.org/abs/2506.06251)；代码与数据：[WebPAI/DesignBench](https://github.com/WebPAI/DesignBench)。

- **原生结构**：Vanilla HTML/CSS、React、Vue、Angular 四种框架；Generation、Edit、Repair、Compile Error Repair 四种任务接口。
- **规模**：900 个网页样本，覆盖 11 个以上主题、9 种编辑类型、6 类 UI 缺陷。
- **输入变化是核心变量**：Generate 是截图；Edit 可用 image/code/both；Repair 额外有带高亮目标区域的 mark 模式；Compile Repair 可只给代码，也可给代码加编译错误。
- **评测重点**：视觉相似度、编译成功、错误类别，以及不同框架和上下文模式造成的性能差异。

**Query 覆盖要求**：同一个语义任务应有跨框架对照；Edit/Repair 应有 screenshot-only、code-only、both、mark 四类上下文，而不是只改变题材。Compile Repair 要覆盖语法、import/export、组件 API、模板语法、类型/构建配置等真实编译错误，同时避免把运行时行为错误混入编译修复。

### 2.3 Interaction2Code

论文：[Interaction2Code: Benchmarking MLLM-based Interactive Webpage Code Generation from Interactive Prototyping](https://arxiv.org/abs/2411.03292)；数据与代码：[WebPAI/Interaction2Code](https://github.com/WebPAI/Interaction2Code)。

- **原生结构**：输入不是普通单张截图，而是交互前后的原型状态序列。数据目录另有 action metadata，用于描述动作及索引对应状态；不要因此推断官方模型同时接收原始网页代码或本地资源。
- **论文明确的推理输入**：模型只接收交互前后的截图。论文将交互原型形式化为 `IP = {S_o, S_I}`，其中 `S_o` 是原始页面状态截图，`S_I` 是执行交互后的状态截图；Prompt Design 也明确第一张截图表示初始状态、后续截图表示交互后状态。论文没有把原始 HTML、CSS、JS、字体、图片文件或 `resources/` 定义为模型输入。
- **仓库实现但论文未披露的图片策略**：发布仓库的采集代码会在截图前把 `<img>`、`<picture>/<source>`、CSS `background-image`、SVG `<image>`、`input[type=image]` 和视频 poster 等图片类资源统一替换为 placeholder；实际样本中反复出现的纯色蓝色、黄色或橄榄色图片区块即受该策略影响。推理 prompt 再要求生成代码统一引用 `placeholder.jpg`。论文正文没有说明这一替换步骤，因此报告时必须标为仓库代码与实际样本证据，不能写成论文披露的协议。
- **当前公开版本**：官方仓库/新版摘要报告 127 个网页、374 个交互、15 类网页、31 类交互。arXiv 搜索中仍可能看到旧版本的 97/213/30，使用时要锁定数据版本。
- **考察内容**：点击、悬停、展开、弹窗、表单、切换、颜色/位置变化、视频、导航到新状态等；论文特别强调细微视觉变化和复杂变换是薄弱点。
- **评测重点**：交互元素是否正确、动作后效果是否正确，以及自动视觉指标与人工评价。

**Query 覆盖要求**：数据单位应是 `pre-state + action + post-state + state invariant`。需要覆盖瞬时/持续状态、可逆/不可逆动作、键鼠/触摸/键盘替代、成功/失败/空状态和多步组合。`new page` 只能作为状态转移类型，不能替代真正的多页架构训练。

### 2.4 Vision2Web L1 / L2

论文：[Vision2Web: A Hierarchical Benchmark for Visual Website Development with Agent Verification](https://arxiv.org/abs/2603.26648)；代码：[zai-org/Vision2Web](https://github.com/zai-org/Vision2Web)；数据：[zai-org/Vision2Web](https://huggingface.co/datasets/zai-org/Vision2Web)。

- **完整规模**：193 个任务、918 张 prototype、1,255 个 test case；100 个 L1 静态网页、66 个 L2 交互前端、27 个 L3 全栈网站。
- **L1**：同一页面的桌面/平板/手机三种原型，重点是响应式视觉还原。论文统计每题平均 3 张 prototype。
- **L2**：平均约 5.9 张 prototype、7.5 个测试点，加入多页导航、交互状态和共享前端状态。
- **L3**：平均约 8.5 张 prototype、28.2 个测试点并包含全栈语义；若超出当前边界，应明确排除，而不是混入 L2。
- **评测重点**：GUI agent 执行依赖图式 workflow，VLM judge 做视觉判断，分别报告 Functional Score 和 Visual Score。

**Query 覆盖要求**：L1 必须成组保留 viewport 和对应截图，覆盖 reflow、collapse、hide/show、文字换行、媒体裁剪和触控尺寸。L2 必须提供确切页面清单、页面关系、跨页流程和共享状态；不能从几张截图任意发明额外页面。

### 2.5 ArtifactsBench

论文：[ArtifactsBench: Bridging the Visual-Interactive Gap in LLM Code Generation Evaluation](https://arxiv.org/abs/2507.04952)；项目：[ArtifactsBenchmark](https://github.com/Tencent-Hunyuan/ArtifactsBenchmark)。

- **规模**：1,825 条开放式任务；九大主题为 Game 413、SVG 123、Web Application 441、Simulation 75、Data Science 122、Management System 314、Multimedia Editing 118、Quick Tools 179、Others 40。
- **原生结构**：公开 question 给生成器，细粒度 checklist 给 judge；不能把私有 checklist 泄漏进生成 prompt。
- **评测重点**：运行 artifact 后抓取时间序列截图，将文本需求、源码和动态视觉证据一起交给 MLLM judge；难度同时考虑静态、动态和高强度交互。
- **特性**：题材覆盖比传统网页 benchmark 更广，包括游戏、SVG、可视化、模拟器、媒体工具。

**Query 覆盖要求**：按“用户目标—直接操作—可观察反馈—失败恢复—视觉风格”构造；游戏/模拟器还要覆盖时间、物理、回合、评分、重置等状态机。不要用大量普通 dashboard 冒充 artifact 多样性。

### 2.6 Design2Code

论文：[Design2Code: Benchmarking Multimodal Code Generation for Automated Front-End Engineering](https://arxiv.org/abs/2403.03163)；数据：[SALT-NLP/Design2Code-hf](https://huggingface.co/datasets/SALT-NLP/Design2Code-hf)。

- **规模与来源**：484 个真实网页测试样本，主要从 C4 清洗而来；另有 80 个更困难的 Design2Code-HARD 样本。
- **原生任务**：单张网页截图到 HTML/CSS，重点是静态视觉还原，不是文本到网站功能设计。
- **评测重点**：CLIP、Block-Match，以及匹配块的文本、位置和颜色相似度，并用人工偏好验证指标排序。
- **主要困难**：元素召回不足和布局错误；真实网页的 DOM 深度、标签数和长页面复杂度明显高于早期合成数据。

**Query 覆盖要求**：真正的覆盖来自截图形态，不来自虚构文字描述。应按长宽比、页面长度、DOM/块密度、图片占比、文本层级、定位方式、重叠/背景和页面类型分层采样。

### 2.7 Flame-VLM-Code / Flame-React-Eval

论文：[Advancing Vision-Language Models in Front-End Development via Data Synthesis](https://arxiv.org/abs/2503.01619)；代码：[Flame-Code-VLM](https://github.com/Flame-Code-VLM/Flame-Code-VLM)；评测数据：[Flame-Eval-React](https://huggingface.co/datasets/Flame-Code-VLM/Flame-Eval-React)。

- **原生范围**：React；80 个手工构造测试题，包含截图、布局描述和可执行 React 代码。
- **正确条件**：能编译、能正常渲染、DINOv2 视觉相似度超过论文阈值 0.9；以 pass@1/3/5 报告。
- **multi-image update**：输入旧截图、旧代码和新截图，输出更新后代码；它是增量版本更新，不等于多页网站。
- **训练数据启示**：Waterfall、Additive、Evolution 三类合成方法本质是在覆盖开发轨迹和增量变化方式。

**Query 覆盖要求**：要覆盖 React 组件层次、数据驱动列表、事件处理、条件渲染、样式和布局；update 任务必须有“变化项 + 保持项”。不要把 multi-image 样本扁平化成只有目标截图的从零生成。

### 2.8 WebGen-Bench

论文：[WebGen-Bench: Evaluating LLMs on Generating Interactive and Functional Websites from Scratch](https://arxiv.org/abs/2505.03733)；代码与数据：[mnluzimu/WebGen-Bench](https://github.com/mnluzimu/WebGen-Bench)。

- **评测集**：101 个项目级网站 instruction、647 个经人工检查的 test case，每题约 4–11 个。
- **训练集**：WebGen-Instruct 有 6,667 条网站生成 instruction。
- **能力分类**：三大类 Content Presentation、User Interaction、Data Management；13 个子类覆盖静态/动态内容、可视化、媒体、表单、认证、实时功能、电商、AI、CRUD、API、大数据和文件处理。
- **评测结构**：每个测试点是 `operation/task + expected observable result`，由浏览器导航 agent 执行并判断 YES/PARTIAL/NO。

**Query 覆盖要求**：不要只扩写“完整网站”描述，而要保证每一条需求都能拆成原子浏览器操作和可观察结果。若限制纯前端，可保留 CRUD、认证、文件和 API 的用户流程，但把数据实现边界明确为本地 mock/localStorage，并避免宣称真实服务能力。

### 2.9 InteractWeb-Bench

论文：[InteractWeb-Bench: Can Multimodal Agent Escape Blind Execution in Interactive Website Generation?](https://arxiv.org/abs/2604.27419)；代码与数据：[AIforIP/InteractWeb-Bench](https://github.com/AIforIP/InteractWeb-Bench)。

- **本地官方数据核验**：101 个基础任务，各生成 P-MIN、P-RAM、P-INT、P-CON 四种 persona，共 404 条。
- **四类输入缺陷**：信息过少、冗长但含上下文、意图模糊、要求冲突。
- **动作空间**：Clarify、Implement、Verify、Submit；重点不是一次生成，而是能否在盲目执行前发现缺口、提出高价值问题、根据回答修改实现并做 GUI 验证。
- **评测重点**：需求完成、意图对齐、澄清命中、幻觉功能和验证行为，oracle 由可测试 requirement slots 组成。

**Query 覆盖要求**：必须保留 ground-truth instruction、persona 扰动 instruction、可逐步揭示的隐藏槽位和澄清对话。将四种 persona 改写成四条“完整最终需求”会删除 benchmark 最重要的监督信号。

### 2.10 FullFront

论文：[FullFront: Benchmarking MLLMs Across the Full Front-End Engineering Workflow](https://arxiv.org/abs/2505.17399)；代码：[Mikivishy/FullFront](https://github.com/Mikivishy/FullFront)；数据：[Mikivis/FullFront](https://huggingface.co/datasets/Mikivis/FullFront)。

- **三阶段**：概念化 Webpage Design、理解 Webpage Perception QA、实现 Webpage Code Generation。
- **八个子任务**：Webpage Design；Real-world/Synthetic/Multi-window QA；Image-to-Code、Text-to-Code、Interaction Authoring、Code Refinement。
- **公开规模**：50 个 design 问题、1,800 个 QA、400 个 code generation 问题，共 2,250 行。
- **输入变化**：文本、单/多窗口截图、选择题、before/after interaction、已有 HTML、目标截图。

**Query 覆盖要求**：若只拿 Text-to-Code/Design，会漏掉 FullFront 的主体。Interaction Authoring 应按动作和前后状态组织；Code Refinement 应保留原 HTML 和目标视觉。QA 可作为辅助感知训练，不宜与网站生成样本等权混合。

### 2.11 FronTalk

论文：[FronTalk: Benchmarking Front-End Development as Conversational Code Generation with Multi-Modal Feedback](https://arxiv.org/abs/2601.04203)；代码与数据：[shirley-wu/frontalk](https://github.com/shirley-wu/frontalk)。

- **规模**：100 个对话 × 10 轮 = 1,000 个开发轮次，配有 3,676 个 test case。
- **输入形式**：每轮意图既有文本表达，也有等价视觉表达；当前网站状态和历史对话决定本轮含义。
- **评测重点**：最终 pass rate、各中间版本对过去要求的保持、forgetting rate 和最终 usability。
- **核心难点**：后续修改覆盖早期功能；视觉反馈理解不足。

**Query 覆盖要求**：训练单位应是轨迹，不是 10 个独立 query，也不是一个合并后的最终需求。应包含增量添加、局部改版、跨页扩展、样式统一、撤销/纠错，以及显式的历史回归检查。

### 2.12 ComUIBench

论文：[ComUICoder: Component-based Reusable UI Code Generation for Complex Websites via Semantic Segmentation and Element-wise Feedback](https://arxiv.org/abs/2602.19276)；代码：[WebPAI/ComUICoder](https://github.com/WebPAI/ComUICoder)；数据：[whale99/ComUIBench](https://huggingface.co/datasets/whale99/ComUIBench)。

- **规模**：40 个真实网站、150 个子页面、2,055 个语义块、1,134 个组件组；约 63.3% 组件属于可复用组。
- **原生任务**：复杂多页截图到实现，同时评价页面内和跨页的组件抽取、合并、复用与一致性。
- **复杂度**：论文报告其平均页面长度、标签数和 DOM 深度明显高于 Design2Code 等单页集合。
- **评测重点**：视觉相似度、组件分割/聚类质量、代码复用和人工评价。

ComUIBench 的组件评测可以概括为三个连续层次：

1. **能不能把页面切对**：模型需要从每张页面截图中识别语义完整的 UI block，并预测其边界；人工组件框作为 Ground Truth，通过 IoU、Precision、Recall、F1 和 mean IoU 评价组件分割是否准确，是否出现漏检或过度切碎。
2. **能不能发现跨页面的重复设计**：在同一网站的多张页面中，模型需要判断哪些组件实例在结构、视觉和功能上等价，可以归入同一个组件组；预测分组与人工 component groups 通过 ARI 和 V-measure 等聚类指标比较。组件组只关心成员关系，不要求模型预测固定的组名。
3. **能不能把这种重复关系真正落实为可复用代码**：即使模型识别出相似组件，如果仍为每个页面复制一份实现，也没有完成 benchmark 的核心目标。因此还需结合 Reuse Rate、Repetitive Ratio 和代码结构指标，检查共享 Header、Footer、卡片组等是否被抽象成一次定义、多处调用的组件，而不是重复代码。

因此，它不是单纯测试“截图还原得像不像”，而是依次测试页面语义切分、跨页设计模式发现，以及复用关系能否落实到最终代码结构。

**Query 覆盖要求**：必须保留“同一网站的页面组”和 component group 标注。简单地给每张截图各生成一个页面，会在视觉上可能过关，却完全错过 benchmark 的复用目标。应覆盖共享 shell、重复卡片、表单原语、表格、导航、设计 token 和同组件不同数据/状态。

### 2.13 WebUIBench

论文：[WebUIBench: A Comprehensive Benchmark for Evaluating Multimodal Large Language Models in WebUI-to-Code](https://arxiv.org/abs/2506.07818)；代码：[MAIL-Tele-AI/WebUIBench](https://github.com/MAIL-Tele-AI/WebUIBench)；数据：[Tele-AI-MAIL/WebUIBench](https://huggingface.co/datasets/Tele-AI-MAIL/WebUIBench)。

- **规模**：约 21K QA，来自 0.7K 以上真实网站。
- **四大能力**：WebUI Perception、HTML Programming、WebUI–HTML Understanding、WebUI-to-Code。
- **九个公开任务标识**：EC、OCR、AP、VG、CEC、CFE、WHM、WHR、W2C，分别覆盖元素分类、OCR、属性感知、视觉定位、代码纠错/功能编辑、网页与 HTML 匹配/检索及截图到代码等能力。
- **CFE 的 Edit 边界**：输入元素级 HTML 片段与修改要求，输出改后代码；四组变化为属性、文本、样式、子节点增删。它是直接的代码编辑子任务，按 §4.1 的代码字符串相似度评分，与整站功能扩展的粒度分开。
- **评测重点**：识别/OCR/定位等多为结构化准确率；W2C 才是生成任务。

**Query 覆盖要求**：WebUIBench 更适合建立“感知先修能力”小池和诊断集，而不是把 21K 问答都改写为网站需求。应重点训练元素、属性、空间关系、截图—DOM 对齐和最小代码修改。

### 2.14 Web2Code

论文：[Web2Code: A Large-scale Webpage-to-Code Dataset and Evaluation Framework for Multimodal LLMs](https://arxiv.org/abs/2406.20098)；代码与数据：[MBZUAI-LLM/web2code](https://github.com/MBZUAI-LLM/web2code)。

- **训练数据**：约 1.18M instruction-response pairs，混合网页代码生成、已有数据增强、网页理解和推理扩写；它是训练语料，不应和评测集规模混淆。
- **WUB**：1,198 张网页截图上的 5,990 个 yes/no QA，用准确率评估网页理解。
- **WCGB**：使用同一批图像做截图到 HTML，并从布局结构、颜色审美、文本内容和 UI 一致性等维度评价渲染结果。
- **数据特性**：大量样本带固定风格词（例如 material design），这些词可能形成 prompt 模板偏置。

**Query 覆盖要求**：截图到代码应优先保留真实视觉分布，避免只扩写固定模板句；QA 可帮助模型理解文本、位置、颜色和组件，但不等价于代码执行能力。

## 3. 横向能力覆盖矩阵

| 能力轴 | 最直接 benchmark | 训练数据应保留的最小结构 |
|---|---|---|
| 文本到可交互 artifact | ArtifactsBench、WebGen-Bench、WebCompass | query + 原子验收点 |
| 单图静态还原 | Design2Code、Web2Code、DesignBench | screenshot + viewport + code |
| 多分辨率响应式 | Vision2Web L1 | 同页三分辨率图组 + breakpoint 行为 |
| 交互状态恢复 | Interaction2Code、FullFront | before + action + after + invariant |
| 多页导航与共享状态 | Vision2Web L2、WebGen-Bench | page graph + workflow + shared state |
| 组件复用与设计系统 | ComUIBench | page group + component groups + shared tokens |
| 框架迁移/差异 | DesignBench、Flame | 同任务跨 Vanilla/React/Vue/Angular |
| 局部编辑与回归保护 | WebCompass Edit、DesignBench Edit、FronTalk | current project + delta + preservation tests |
| 视觉/交互根因修复 | WebCompass Repair、DesignBench Repair | faulty project + evidence + expected oracle |
| 编译修复 | DesignBench Compile | broken code + compiler output + framework |
| 多轮遗忘 | FronTalk | ordered history + snapshots + cumulative tests |
| 主动澄清与冲突处理 | InteractWeb-Bench | noisy instruction + hidden slots + dialogue policy |
| 感知/OCR/定位/HTML 理解 | WebUIBench、FullFront QA、Web2Code WUB | screenshot/code + structured question + answer |
| 时间/物理/游戏状态 | ArtifactsBench | state machine + observable feedback + reset |

这个矩阵比“每个 benchmark 生成多少条”更适合做总控。单条样本可以命中多个能力轴，但每条必须有一个 primary capability，否则统计会重复膨胀。

## 4. Query 设计的统一坐标系

每条生成或编辑任务至少标注以下字段。没有这些字段，就无法判断覆盖是“题材多”还是“能力多”。

### 4.1 任务与输入

- `lifecycle`: generate / edit / repair / refine / compile_repair / dialogue / perception
- `modality`: text / single_image / multi_viewport / multi_page_images / video / before_after / code / code_and_evidence
- `scope`: component / page / SPA-state / multi-page / project / full-stack
- `framework`: vanilla / React / Vue / Angular / unrestricted
- `turn_structure`: single / incremental multi-turn / clarification dialogue

### 4.2 功能与状态

- `interaction_primitives`: click、hover、keyboard、drag、scroll、input、upload、media control、canvas/SVG manipulation
- `state_scope`: ephemeral、component、page、cross-page、persistent local、remote
- `workflow_length`: 0、1、2–3、4–6、7+
- `failure_states`: validation error、empty、loading、permission、conflict、undo/reset、retry
- `observable_oracle`: 操作、目标元素、预期状态变化、视觉约束

### 4.3 视觉与结构

- `viewport_set`: desktop/tablet/mobile
- `page_length`: above-fold / medium / long
- `density`: sparse / normal / dense
- `visual_challenges`: typography、grid/flex、overlap、layer、sticky/fixed、image crop、chart/SVG/canvas、animation
- `consistency_scope`: within component / within page / cross-page / design system
- `reuse_requirements`: none / repeated instance / cross-page shared component / shared design tokens

### 4.4 需求质量与修改关系

- `requirement_quality`: complete / minimal / rambling / ambiguous / conflicting
- `edit_footprint`: target roots/elements and allowed file set
- `preservation_invariants`: 文本、ARIA、导航、状态、视觉区块和既有测试中必须保持的内容
- `defect_type`: WebCompass 11 类 + compile/runtime/dependency
- `relation`: add / replace / remove / reorder / restyle / behavior-change / inverse / conflict / dependency

### 4.5 难度不要只用 Easy/Medium/Hard

建议由可计算维度组合：页面数、交互原语数、最长 workflow、共享状态数、视觉块密度、资源数、修改足迹大小、保持约束数和需求缺陷数。这样才能解释模型究竟在哪一类复杂度上退化。

## 5. 推荐的 15K 覆盖方案

以下是按 **primary capability** 分配的建议，而不是把 benchmark 名当类别。它遵守“前端为主、不超过 WebCompass 后端复杂度”的边界。

| Primary capability | 数量 | 比例 | 主要来源 |
|---|---:|---:|---|
| Text-to-functional site/artifact | 4,050 | 27% | WebCompass Generate、ArtifactsBench、WebGen-Bench |
| 单图与多分辨率视觉还原 | 2,400 | 16% | Design2Code、Web2Code、DesignBench、Vision2Web L1 |
| Before/after 交互实现 | 1,200 | 8% | Interaction2Code、FullFront、Flame update |
| 多页前端、导航与共享状态 | 1,800 | 12% | Vision2Web L2、WebGen-Bench |
| 组件复用与跨页设计系统 | 900 | 6% | ComUIBench |
| 局部 Edit / Refinement | 1,800 | 12% | WebCompass、DesignBench、FullFront、FronTalk |
| Visual / Functional Repair | 1,200 | 8% | WebCompass、DesignBench |
| Compile Repair | 300 | 2% | DesignBench |
| 多轮遗忘、模糊与主动澄清 | 900 | 6% | FronTalk、InteractWeb-Bench |
| Perception / OCR / grounding / HTML understanding | 450 | 3% | WebUIBench、FullFront QA、Web2Code WUB |
| **总计** | **15,000** | **100%** | |

这 15K 不能存进一种统一的 `query-only.jsonl` 后就宣称等价覆盖。建议物理上拆为：

- `generate_text.jsonl`
- `generate_visual.jsonl`
- `interaction_authoring.jsonl`
- `multipage_generation.jsonl`
- `edit.jsonl`
- `repair.jsonl`
- `compile_repair.jsonl`
- `dialogue.jsonl`
- `perception.jsonl`

如果当前阶段只能生成文本 query，应先完成表中 Text-to-functional 的 4,050 条；可以额外生成 Visual/Multipage 任务的 **query wrapper**，但必须标记 `asset_required=true` 和 `prompt_is_complete=false`，在真实 screenshot/page group 绑定前不得算作可训练样本。

## 6. 各池内部的配额原则

### 6.1 Generate 不要被普通管理后台统治

建议在 4,050 条 Text-to-functional 中控制上限：普通 dashboard/CRUD 合计不超过 30%；游戏/模拟/SVG/可视化不少于 25%；内容/电商/教育/社交/工具覆盖剩余 45%。每条至少有 2 个可观察交互，但并非越多越好，应覆盖 1、2–3、4–6、7+ 四档 workflow。

### 6.2 Visual pool 按视觉难点而非行业分层

至少覆盖：短/中/长页，稀疏/密集，纯文本/图片主导/混合，正常流/绝对定位/叠层，表格/卡片/文章/营销页，桌面/响应式，以及不同字体和语言长度。截图 benchmark 的 domain label 只能作为次级轴。

### 6.3 Edit/Repair 必须有回归负担

每条 Edit 至少 1 个修改目标和 2 个保持项；Hard 任务应有 2–3 个相关修改以及跨页/共享组件影响。Repair 应平衡视觉缺陷、DOM 语义错误、交互丢失和编译/运行错误，不能只做 CSS 对齐。

### 6.4 Multi-page 与组件复用要区分

有五个页面并不自动意味着组件复用。Multi-page pool 评价页面图、导航和状态；ComUI pool 另外要求共享组件、token、相同组件不同实例/状态和避免复制粘贴。两者可重叠，但标签和评测必须分开。

### 6.5 对话任务需要“选择不立即写代码”的正例

InteractWeb-Bench 型数据应包含应该 Clarify 的状态，以及问题得到回答后再 Implement 的轨迹。若所有训练样本第一步都是写代码，会直接强化论文所批评的 blind execution。

## 7. 数据构造与验收流程

1. **锁定 benchmark 版本**：保存论文版本、仓库 commit、HF revision、split/config 和许可信息。
2. **先抽原生 schema**：每个 benchmark 至少人工检查 20 条，并保留真实输入字段和 evaluator 所需证据。
3. **建立能力标签**：按第 4 节字段标注，benchmark 只作为 provenance，不作为唯一类别。
4. **去重与防污染**：对公开 test query、页面截图、代码和 checklist 做哈希；训练扩写不得近似复述 test，也不得把 judge-only checklist 放入输入。
5. **先做最小闭环**：每个任务包先跑 1 条真实样本、真实模型、真实浏览器；验证生成、部署、交互、截图和评分链路。
6. **逐条 append**：结果包含 `status`、模型、prompt 版本、资源清单、渲染证据、测试轨迹和失败原因，并支持断点续跑。
7. **分层抽样质检**：按 primary capability × modality × difficulty × framework 抽样，不能只随机抽总池。
8. **正式评测隔离**：预检查、简单视觉评分、完整浏览器评测和人工复核分别统计，不能合并成一个分数。

## 8. 一个合格样本的最低验收合同

### Generate

- 每个需求都能映射到至少一个 `operation → expected observable result`。
- 页面/路由数量、资源边界和数据持久化边界明确。
- 不要求无法验证的抽象词；“现代、好看”必须配合具体视觉约束。

### Edit

- 明确 current state、target delta、allowed footprint、preservation invariants。
- 至少有一个正向目标测试和两个回归测试。
- 共享组件修改要验证所有消费者页面。

### Repair

- 缺陷能在当前项目复现；证据与 defect type 对齐。
- 修复后验证根因消失，而不是仅遮挡症状。
- 非目标行为与布局保持。

### Multi-turn / Clarification

- 历史状态可重放；每轮测试分为新增要求和累计要求。
- 隐藏需求只在有效澄清后揭示。
- 冲突任务允许协商优先级，不把不可能同时满足的要求强行作为全部通过标准。

## 9. 对当前 14-benchmark Generation-only 方案的直接判断

当前仓库已有 `fourteen_benchmark_generation_15k_20260820` 方案，它把 14 个来源都映射为 Generate profile。这个方案可用来扩充**题材与最终状态需求**，但不等于 14 个 benchmark 的完整能力覆盖，具体损失如下：

- DesignBench：丢失 image/code/both/mark 和 compile error 上下文。
- Interaction2Code：若没有真实 before/after prototype，只剩文字描述，不再是视觉状态恢复。
- Vision2Web：若未绑定完整 viewport/page screenshot group，只是文本仿写。
- Design2Code / Web2Code：从 screenshot-to-code 变成 text-to-code，改变了任务本体。
- Flame：丢失 React 代码版本与 multi-image update 关系。
- InteractWeb-Bench：完整化 persona 指令会消除缺失、模糊与冲突。
- FullFront：只保留 Code Generation 会漏掉设计、感知、interaction authoring 和 refinement。
- FronTalk：合并 final-state 会消除遗忘率和历史约束。
- ComUIBench：若截图组和 component annotations 未进入任务，无法监督复用。
- WebUIBench：把 QA 改写成 Generate 会失去诊断意义。

所以更准确的定位是：**14-source-inspired Generate query expansion**，而不是 **14-benchmark-complete training coverage**。建议保留现有 Generate 产物的 provenance，但新增上述八到九个原生任务包，逐步补齐真正缺失的监督结构。

## 10. 下一步优先级

1. **P0：先修任务表示**。在继续扩写大批 query 前，确定九种任务包 schema 和统一 capability tags。
2. **P0：绑定视觉资产**。Design2Code、Vision2Web、Interaction2Code、ComUIBench 和 DesignBench 的视觉种子必须保留真实 asset refs。
3. **P1：构造 100 条闭环 pilot**。建议 Generate 25、Visual 15、Interaction 10、Multipage 10、ComUI 5、Edit 15、Repair 10、Dialogue 5、Perception 5；全部真实浏览器验证。
4. **P1：用 test oracle 反推 coverage**。将 WebGen 的 `task/expected_result`、WebCompass checklist、FronTalk cumulative tests 和 InteractWeb requirement slots 统一成内部 observable contract。
5. **P2：再决定 15K 最终配额**。依据 100 条 pilot 的失败分布、构造成本和 train0814 的真实分项结果调整，不要仅按论文样本量或直觉分配。

## 11. 证据范围与未确认项

- 本报告查阅了论文正文/官方仓库，并核验了当前工作区中的官方数据快照与样本 schema；不是只依据摘要。
- 当前粘贴表格中的 `base`、`train0814` 主要以图片占位出现，没有可读的逐项分数，因此本报告没有虚构“train0814 已覆盖/未覆盖比例”。配额是能力导向的初始设计，下一轮应结合真实分项成绩调整。
- 公开仓库和论文版本可能不一致，Interaction2Code 的旧版 97/213 与新版 127/374 是明确例子；正式运行前应冻结 revision。
- 本报告没有运行任何模型 benchmark，也没有产生新的实测分数；“重点考察”和“建议配额”分别来自官方 evaluator 结构与覆盖设计判断。

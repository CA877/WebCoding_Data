# WebCompass 官方 16 类 Edit 操作参考

## 1. 来源、版本与使用边界

- 论文：[*WebCompass: Towards Multimodal Web Coding Evaluation for Code Language Models*](https://arxiv.org/abs/2604.18224)
- 数据集：[zai-org/WebCompass](https://huggingface.co/datasets/zai-org/WebCompass)
- 下列官方实例核对自 2026-09-08 的公开 Edit JSONL，数据集 commit 为 `bde80d4f4cc09f9cfa763fd3bb047d3cdb302eb0`。
- 这里的实例是公开指令的忠实中文转述。该快照中 Edit 的 `dst_code`、`label_modified_files` 为空，所以它们是“真实指令实例”，不是公开 target 或唯一标准实现。
- SP/MP 共用相同的 16 类。MP 表示 source 项目有多个独立页面，不等于每项操作都必须跨页修改。

论文将 16 类组织为四组：

| 大组 | 官方类型 |
| --- | --- |
| Complex Components | Data Table、Rich Text Editor、Drag & Drop Interface、Tree View |
| Frontend–Backend Integration | Real-time Dashboard、Infinite Scroll、Async Form Validation、File Upload with Progress |
| Advanced Animations | Parallax Scrolling、Page Transitions、Particle Effects、Skeleton Loading |
| Business Scenarios | Shopping Cart、User Authentication、Multi-step Wizard、Notification Center |

这些组表示功能性质，不是严格的难度排序。

## 2. 通用判定原则

### 2.1 用状态变化定义能力

优先把需求还原成：

```text
修改前状态
→ 用户动作、滚动、时间或异步事件
→ 中间状态
→ 修改后可观察状态
→ 刷新、返回或失败时的保持/恢复状态
```

类别名称只能辅助理解，不能替代上述状态链。

### 2.2 四级证据

| 证据层 | 适用情况 | 能证明什么 |
| --- | --- | --- |
| DOM/ARIA | 表格、树、向导、通知等 | 当前结构、可访问状态和部分业务状态 |
| 真实动作 | 拖放、编辑、购物车、表单等 | 用户操作确实触发预期状态变化 |
| 时间采样 | 异步验证、上传、无限滚动、实时看板 | pending、进度、追加和持续更新不是静态伪装 |
| 几何/图像/连续帧 | 视差、转场、粒子、Canvas | 运动轨迹、相对速度和像素级动态效果 |

DOM 中出现 `authenticated=true`、`upload complete` 或不断变化的数字，只能证明前端状态，不证明真实服务器能力。

## 3. Complex Components

### 3.1 Data Table（数据表）

**核心语义**

以行列结构呈现一组同构数据，并让排序、筛选、分页、选择或响应式展示真正作用于同一数据集合。

**达到完整任务通常需要**

- 明确列、行与数据来源；
- 至少一种真实数据操作，如排序、筛选或分页；
- 多种操作共存时状态一致，例如筛选后重新计算分页；
- 指令要求移动端适配时，窄屏仍保留等价信息。

只有静态 `<table>`、表头箭头或纯 CSS 表格外观不够。

**官方实例**

- SP `1061447_www.sicapital.net_L12_0`
- 在投资组合页面加入 `Portfolio Performance` 表格，包含 Company Name、Sector、Investment Year、Status；支持点击表头排序、超过十条后的客户端分页、公司名筛选，并在移动端转成卡片布局。

**状态链**

```text
全量行 + 默认顺序
→ 输入公司名/点击表头
→ 过滤后的数据集 + 新排序
→ 重新计算页数并显示当前页
```

**验收证据**

- 比较操作前后的实际行顺序和行集合；
- 检查筛选后总数、页数和当前页；
- 切换窄屏后核对每张卡是否保留同样字段；
- 检查空结果和清除筛选后的恢复。

**常见假通过**：箭头变向但数据不动；只隐藏文本却不更新分页；移动端直接横向溢出。

### 3.2 Rich Text Editor（富文本编辑器）

**核心语义**

让用户对选区或当前块施加语义格式，插入结构化内容，并产生可保存、可清理的 HTML 或等价文档状态。

**达到完整任务通常需要**

- 编辑区域和格式工具栏；
- 格式作用于真实选区或块；
- 标题、列表、引用、链接、图片等指令要求的结构；
- 编辑状态与提交字段或序列化输出同步；
- 指令要求时执行 sanitization。

只有 `contenteditable=true` 或一个带按钮的普通 textarea 不够。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L4_1`
- 为内部 CMS 制作 `Content Composer`：使用 Libre Franklin 和 sticky 工具栏，支持粗体、斜体、下划线、删除线、H1–H3、列表、引用、链接弹窗和图片 URL 预览；清理 HTML，并实时同步到隐藏输入字段。

**状态链**

```text
选中文本
→ 点击格式/插入链接或图片
→ 编辑区 DOM 产生对应语义结构
→ 序列化并同步到提交字段
```

**验收证据**

- 实际选择文本并点击工具栏，检查生成的 DOM；
- 插入链接和图片后核对 URL、预览与保存内容；
- 修改正文后检查隐藏字段同步；
- 输入危险 HTML，检查 sanitization 是否生效。

**常见假通过**：按钮切换 active 样式但正文没变；视觉加粗却无法保存；工具栏操作破坏选区。

### 3.3 Drag & Drop Interface（拖放界面）

**核心语义**

用户通过连续的按下、移动和释放手势，把项目移动到合法目标，从而改变顺序、分组或父级关系。

**达到完整任务通常需要**

- 可拖动源和合法放置目标；
- 拖动中的 ghost、占位或高亮反馈；
- drop 后真实数据或 DOM 顺序变化；
- 指令要求时持久化或跨列表移动。

点击上下按钮重新排序或只播放移动动画，不自动算拖放。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L4_1`
- 制作 `Brand Portfolio Manager`：品牌卡可拖动重排；拖动时卡片半透明，目标区域用企业蓝高亮；放下后计算新索引并存入 `localStorage`，刷新后保持顺序。

**状态链**

```text
顺序 A,B,C
→ pointerdown B → move → drop 到 C 后
→ 顺序 A,C,B
→ 刷新后仍为 A,C,B
```

**验收证据**

- 使用真实 Pointer Events 或浏览器拖放动作；
- 手势过程中检查 ghost 和 drop zone；
- drop 后检查父节点、索引或 DOM 顺序；
- 刷新后检查持久化结果。

**常见假通过**：只触发最终回调，没有真实拖动过程；视觉移动但数据顺序未变；刷新后丢失。

### 3.4 Tree View（树形视图）

**核心语义**

用父子节点表示层级数据，并提供展开、折叠、选择、搜索或父子选择联动。

**达到完整任务通常需要**

- 明确的层级关系；
- 父节点展开/折叠；
- 选择状态与子树联动；
- 指令要求时支持 indeterminate 和搜索展开路径。

用缩进字符画出目录但没有层级状态，不够。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L7_0`
- 增加 `Brand Directory`：例如 Gaming > Console > PlayStationLifestyle；父分类可展开，选中父节点会选择全部子品牌，取消单个子节点后父节点变为半选；搜索会过滤并展开匹配路径。

**状态链**

```text
父节点折叠/未选
→ 展开并选择父节点
→ 全部子节点选中
→ 取消一个子节点
→ 父节点进入 indeterminate
```

**验收证据**

- 检查层级 DOM/ARIA，如 `tree`、`treeitem`、`aria-expanded`、`aria-checked=mixed`；
- 操作父子复选框并核对联动；
- 搜索深层节点，检查祖先路径是否自动展开；
- 清除搜索后核对原状态。

**常见假通过**：只有嵌套列表；父节点图标变化但子节点不变；搜索命中深层节点却仍被折叠隐藏。

## 4. Frontend–Backend Integration

### 4.1 Real-time Dashboard（实时看板）

**核心语义**

指标、图表或状态随时间或数据事件持续变化，并向用户显示刷新状态、时间或连接状态。

**达到完整任务通常需要**

- 至少一组动态指标；
- 时间或事件驱动的更新；
- 数字和图表等相关视图保持一致；
- 指令要求的时间戳、状态或异常反馈。

页面上写 `Live` 或只播放一次计数动画不等于实时看板。

**官方实例**

- SP `1061447_www.sicapital.net_L11_1`
- 在 Strategy 区域加入 `Live Impact Metrics`：CO2 Saved 和 Renewable Energy Generated 每隔几秒更新；数字带动画；Canvas/SVG 青绿色 sparkline 同步变化；显示最近刷新时间并适配 `.contenedor2`。

**状态链**

```text
t0 指标/图表/时间戳
→ 等待更新周期
→ t1 新指标/新图表/新时间戳
```

**验收证据**

- 在至少两个时间点采样指标、图表数据和时间戳；
- 检查相关值是否共同变化；
- 检查定时器清理、页面离开后的行为和布局溢出；
- 若声称真实实时服务，另查网络连接和服务端证据。

**常见假通过**：固定数字旁放闪烁绿点；图表和数字各自随机且不一致；模拟数据被误称为真实实时后端。

### 4.2 Infinite Scroll（无限滚动）

**核心语义**

用户接近列表末端时自动获取并追加下一批数据，直到数据耗尽，同时正确管理 pending、去重、顺序和结束状态。

**达到完整任务通常需要**

- 有限的初始批次；
- 滚动阈值或观察器触发下一批；
- 加载中和结束状态；
- 追加而不是覆盖，且防止重复触发；
- 指令要求时恢复已加载内容和滚动位置。

一次性把所有数据放入 DOM 再逐步显示，不等价于真实的追加流程。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L5_2`
- 在页脚上方加入 `Company News`：初始 5 条，接近列表底部时模拟获取后 5 条；加载时显示品牌 spinner；达到 30 条后显示 `End of Content`；离开再返回时恢复滚动位置。

**状态链**

```text
5 条
→ 滚动接近末端 → loading
→ 追加为 10 条
→ 重复直到 30 条
→ End of Content，停止加载
```

**验收证据**

- 记录每次触发前后的条目数、ID 和顺序；
- 在 pending 时检查 loading；
- 快速滚动检查是否产生重复批次；
- 达到上限后检查不再请求；
- 返回页面后检查内容和滚动位置。

**常见假通过**：滚动一次重复追加多批；旧列表被覆盖；结束后仍不断触发；恢复的只是 scrollY 而不是已加载内容。

### 4.3 Async Form Validation（异步表单验证）

**核心语义**

表单字段除本地格式检查外，还要等待异步结果，并让 pending、成功、失败和提交资格保持一致。

**达到完整任务通常需要**

- 明确异步触发时机，如 blur 或 debounce；
- pending 反馈；
- 成功与失败结果；
- 新输入不会被旧请求结果覆盖；
- 提交按钮受同步和异步状态共同控制。

仅用正则检查邮箱格式属于同步验证，不是该类。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L5_2`
- `Advertising Partnership Inquiry` 中，Company URL 停止输入 500ms 后模拟检查域名是否已是合作方；检查时输入框内显示 spinner，已存在时显示警告，不存在时显示成功标记；全部同步和异步检查通过前禁用提交。

**状态链**

```text
输入新域名
→ debounce 500ms
→ checking/pending
→ available 或 already exists
→ 更新错误、成功标记与 submit disabled
```

**验收证据**

- 在 500ms 前后和响应后分别采样；
- 检查 pending、错误/成功和提交状态；
- 快速连续输入两个值，验证旧结果不会覆盖新值；
- 同时制造其他字段错误，确认异步成功不会错误启用提交。

**常见假通过**：固定延迟后永远成功；没有 pending；旧异步结果覆盖新输入；验证未完成即可提交。

### 4.4 File Upload with Progress（带进度的文件上传）

**核心语义**

文件从选择或拖入开始，经过类型校验、排队、上传进度、完成/失败/取消，界面始终反映每个文件的独立状态。

**达到完整任务通常需要**

- 文件选择器或 drop zone；
- 类型/大小等指令要求的校验；
- 每个文件的 pending 与进度；
- 完成、失败、取消或删除中的必要状态；
- 多文件要求下的独立队列。

只有文件名展示、循环进度动画或瞬间 100% 不够。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L7_0`
- Careers 中加入 `Quick Apply`：支持拖入或选择 PDF/DOCX；显示文件图标、名称和进度条；在 2–3 秒内模拟百分比增长；可排队多个简历/求职信；可取消或移除。

**状态链**

```text
空队列
→ 选择文件并通过校验
→ queued → uploading 25% → 70% → complete
或 uploading → cancel/remove
```

**验收证据**

- 用真实文件选择器或 drop 操作；
- 采样中间进度而非只看最终状态；
- 检查多个文件各自进度；
- 取消后确认进度停止且资源清理；
- 若声称真实上传，另核对网络请求和服务器结果。

**常见假通过**：取消只隐藏行但计时器继续；多个文件共用一个进度；前端完成被误称为服务器已收到文件。

## 5. Advanced Animations

### 5.1 Parallax Scrolling（视差滚动）

**核心语义**

滚动时至少两个视觉层以不同速率或方向移动，从而产生相对深度；它不是任意 scroll-triggered 动画。

**达到完整任务通常需要**

- 明确的背景、中层或前景；
- 同一滚动区间内存在可测的相对位移差；
- 指令要求的进入视口动画或性能处理。

整个容器统一平移，或元素进入视口时单次淡入，不构成视差。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L7_0`
- `Our History` 分为慢速抽象背景、中速时间线标记和快速文字图片三层；垂直滚动时各层以不同速率移动，时间线图片进入视口时淡入并上滑。

**状态链**

```text
scrollY=s0：记录三层位置
→ 滚动到 s1
→ 三层位移量不同，且进入视口元素开始过渡
```

**验收证据**

- 在多个 scrollY 位置连续采样每层几何坐标；
- 比较位移斜率，而不是只看最终截图；
- 用截图确认遮挡、抖动和视觉深度；
- 检查移动端和性能，但只有指令明确要求时才把特定降级策略列为硬门禁。

**常见假通过**：三层位移完全相同；只有 CSS 背景固定；一次淡入被误判为视差。

### 5.2 Page Transitions（页面转场）

**核心语义**

当前页面或视图退出、新页面或视图进入时形成有方向、有中间态、可完成并可反向的连续过渡。

**达到完整任务通常需要**

- 明确旧视图退出和新视图进入；
- 动画期间的层级、可点击性和最终状态正确；
- 指令要求时浏览器历史与反向转场一致。

换页完成后给新页面播放一个无关动画，不等价于页面转场。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L5_2`
- 把 `Our Brands` 网格改为 SPA 式详情：点击品牌后主页淡出并略微缩小，详情从右侧滑入；Back 反向播放，浏览器后退也触发正确反向序列。

**状态链**

```text
Home 可见
→ 点击品牌
→ Home exiting + Detail entering
→ Detail 稳定可交互
→ Back/history
→ 反向过渡并恢复 Home
```

**验收证据**

- 在点击前、动画中、动画后采样 opacity、transform、层级和命中目标；
- 检查最终 URL/history 与视图一致；
- 执行网页 Back 和浏览器 back 两条路径；
- 观察白屏、闪烁和双层内容同时可交互问题。

**常见假通过**：`display:none` 瞬间切换后再淡入；浏览器后退直接跳转；隐藏视图仍拦截点击。

### 5.3 Particle Effects（粒子效果）

**核心语义**

一组粒子随时间演化，并根据邻域、鼠标、点击或物理规则产生可观察的群体动态。

**达到完整任务通常需要**

- 持续变化的粒子系统；
- 指令要求的颜色、连接或运动规则；
- 鼠标/点击等交互响应；
- 指令要求时的视口暂停或性能控制。

静态点阵背景、GIF 或一个 Canvas 空元素不够。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L7_0`
- Hero 上叠加蓝白 Canvas 粒子网络：节点缓慢漂浮，靠近鼠标时逃离，点击时向外爆发，邻近节点连线，Hero 离开视口后暂停动画。

**状态链**

```text
空闲漂浮
→ 移动鼠标到粒子附近
→ 局部粒子逃离
→ 点击
→ 短时爆发
→ 滚出视口后动画暂停
```

**验收证据**

- 采集连续帧或 Canvas 图像哈希，证明空闲时也在变化；
- 鼠标移动和点击前后比较局部分布；
- 检查邻近连线变化；
- 滚出视口后检查 animation frame 或像素是否停止更新。

**常见假通过**：DOM 有 Canvas 但没有绘制；粒子播放固定动画却不响应输入；仅凭 DOM 无法验证 Canvas 内部效果。

### 5.4 Skeleton Loading（骨架屏）

**核心语义**

真实内容未就绪时，用与最终结构和尺寸相近的占位元素保持布局，再平滑替换为内容。

**达到完整任务通常需要**

- 占位块映射最终标题、图片、正文等结构；
- loading 阶段可观察；
- 数据完成后替换或淡入；
- 布局尺寸尽量稳定。

中央 spinner、文字 `Loading...` 或不对应内容结构的灰色矩形不自动等于骨架屏。

**官方实例**

- SP `1061447_www.sicapital.net_L12_0`
- News slider 加入匹配标题、日期和图片块的灰色 skeleton，带 pulse/shimmer；模拟加载完成后骨架淡出，真实内容淡入。

**状态链**

```text
初始 skeleton 结构
→ loading/pulse
→ 数据完成
→ skeleton fade out + content fade in
```

**验收证据**

- 页面刚加载时立即捕获占位结构；
- 检查占位几何是否接近最终内容；
- 延迟后确认骨架移除、正文出现；
- 比较替换前后布局偏移。

**常见假通过**：spinner 冒充骨架；骨架与最终布局完全不匹配；真实内容出现后占位仍留在 DOM 并占空间。

## 6. Business Scenarios

### 6.1 Shopping Cart（购物车）

**核心语义**

维护用户选择的项目集合，并让添加、删除、数量/汇总、展示和持久化共同作用于同一购物车状态。

对象可以是商品，也可以是文档、服务或预约项目。

**达到完整任务通常需要**

- 从列表加入项目；
- 查看购物车集合；
- 删除或调整项目；
- 数量、价格或其他汇总随状态更新；
- 指令要求时跨刷新或跨页保持。

点击后只弹出 `Added` 消息不够。

**官方实例**

- SP `1061447_www.sicapital.net_L11_1`
- 为 News 和 Legal Notices 制作 `Document Request Basket`：PDF 旁可加入；侧边栏显示选中文档与缩略图；支持移除；`Request Zip` 计算模拟总大小；使用 `localStorage`，导航到 Contact 后仍保留选择。

**状态链**

```text
空篮子
→ 加入文档 A、B
→ badge=2，侧栏=A+B，总大小=A+B
→ 删除 A
→ badge=1，总大小只含 B
→ 刷新/导航后仍保留 B
```

**验收证据**

- 添加、重复添加、删除并检查集合和汇总；
- 核对徽标、侧栏和底层状态同步；
- 刷新与跨页导航后检查持久化；
- 检查空购物车和重复项目策略。

**常见假通过**：徽标与侧栏数据不同步；总额写死；只存徽标数字不存项目；刷新后状态丢失。

### 6.2 User Authentication（用户认证）

**核心语义**

根据登录/注册/退出结果维护会话状态，并让导航、受限入口或用户信息即时反映该状态。

**达到完整前端任务通常需要**

- 登录或注册输入及验证；
- 未认证、认证中/失败、已认证、退出状态；
- 成功后相关 UI 立即更新；
- 指令要求时持久化与恢复。

仅有登录表单外观或把按钮文字改成用户名不够。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L5_2`
- Header 中未登录显示 Login；弹窗含 Login/Register；注册需要邮箱、密码、Company Name，登录需要邮箱和密码；模拟成功后关闭弹窗，显示用户名和 Logout，以 `localStorage` 保存并无需刷新。

**状态链**

```text
unauthenticated
→ 打开 modal → 验证输入
→ simulated authenticated
→ header 显示用户和 Logout
→ 刷新恢复 / Logout 清除
```

**验收证据**

- 测试无效输入、失败和成功路径；
- 登录后检查弹窗、导航和用户菜单同步；
- 刷新检查持久化，退出检查清除；
- 若声称真实认证，另查 token、cookie、服务端授权和受限资源访问。

**常见假通过**：只修改 DOM 文本；退出不清理存储；`localStorage` 模拟状态被误称为安全认证。

### 6.3 Multi-step Wizard（多步向导）

**核心语义**

把一个完整流程拆成有顺序的步骤，以验证控制前进，并在前后导航中维护已输入数据，通常在最后汇总确认。

**达到完整任务通常需要**

- 当前步骤和进度指示；
- 每步进入/离开条件；
- 前进前验证；
- 返回后数据保留；
- 指令要求的最终摘要或提交。

简单隐藏三个 `<div>` 而不维护状态和验证不够。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L4_1`
- `Freelance Talent Application` 分 Personal Information、Experience & Portfolio、Legal Disclosures 三步；渐变蓝进度；每步验证通过后 Next 才可用；返回修改时不丢后续数据；最后显示完整摘要再提交。

**状态链**

```text
Step 1 空表单，Next 禁用
→ 填写有效数据 → Step 2
→ 填写 Step 2/3
→ Back 到 Step 1，数据仍在
→ Final Summary 与全部输入一致
```

**验收证据**

- 空值和非法值是否阻止前进；
- 前后导航后检查各步数据；
- 修改旧步骤后检查后续状态和摘要更新；
- 检查进度指示与真实步骤一致。

**常见假通过**：Next 不验证；Back 重建表单导致数据丢失；摘要使用旧副本；视觉进度与实际步骤错位。

### 6.4 Notification Center（通知中心）

**核心语义**

维护一组通知的未读、已读、分组、严重程度、删除和新增状态，并让徽标与列表同步。

**达到完整任务通常需要**

- 入口和未读计数；
- 通知列表；
- 单条/批量已读或删除；
- 指令要求的分组、严重程度和新通知到达；
- 所有视图基于同一通知状态。

一个铃铛图标、固定数字或普通 toast 不等于通知中心。

**官方实例**

- SP `1047829_www.evolvemediallc.com_L4_1`
- Header 中加入 Executive Dashboard 通知系统：铃铛显示动态未读数；按 Advertising、Corporate Dev、Content、Legal 分类；区分 Success/Error/Info；按 Today/Earlier 分组；每隔几秒模拟新通知；可关闭单条或 Mark All as Read。

**状态链**

```text
未读 n
→ 打开通知列表
→ 标记一条已读，未读 n-1
→ Mark All Read，未读 0
→ 时间事件到达新通知，未读 1
```

**验收证据**

- 比较徽标和实际未读项目数量；
- 执行单条已读、全部已读和删除；
- 等待新通知到达并检查分组、严重程度和计数；
- 检查关闭再打开后状态是否符合指令。

**常见假通过**：徽标写死；列表变化但计数不变；toast 消失后没有可管理记录；定时器重复创建造成通知倍增。

## 7. 容易混淆的类型边界

| 容易混淆 | 关键区别 |
| --- | --- |
| Real-time Dashboard vs Notification Center | 前者核心是持续变化的指标/图表；后者核心是可管理的消息集合与已读状态。一个任务可同时包含两者。 |
| Infinite Scroll vs Skeleton Loading | 前者核心是滚动触发分批追加；后者核心是加载阶段用结构化占位替代最终内容。Infinite Scroll 可以使用 skeleton 作为子反馈。 |
| Async Form Validation vs User Authentication | 前者核心是字段异步校验生命周期；后者核心是会话状态及认证前后 UI/权限变化。登录表单可能包含异步校验，但两类不能互相替代。 |
| Drag & Drop vs Data Table sorting | 拖放依赖连续空间手势和 drop；表格排序通常由表头点击改变数据顺序。 |
| Parallax Scrolling vs Page Transitions | 视差由滚动驱动多层相对位移；页面转场由视图/路由切换驱动退出和进入动画。 |
| Particle Effects vs普通 CSS 动画 | 粒子是多个个体随时间和交互演化的系统；一个背景元素循环移动不够。 |
| Rich Text Editor vs普通表单 | 富文本核心是选区/块级语义编辑及可保存结构；普通 textarea 的输入验证不是富文本能力。 |
| Shopping Cart vs普通收藏按钮 | 购物车要求集合、汇总和管理状态协同；孤立收藏切换通常只是父业务中的一个小能力。 |

## 8. 批量分类时的输出建议

对每条指令记录：

```text
primary_type
secondary_types
business_object
trigger
pre_state
intermediate_states
post_state
persistence_or_time_requirement
required_evidence
missing_for_full_type
confidence
```

不要用正则或关键词替代语义判断。若指令只说“添加上传按钮”，应写：

```text
接近 File Upload with Progress，但未达到完整任务；
缺少文件校验、上传中间状态、进度、完成/失败/取消中的必要状态。
```

若指令同时要求“滚动加载下一批卡片，并在等待时显示匹配卡片布局的骨架”，可以标为：

```text
主类型：Infinite Scroll
次类型：Skeleton Loading
```

因为分批追加决定主状态机，骨架是完整且可独立验收的加载阶段表现。

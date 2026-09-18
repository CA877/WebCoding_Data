# reversed 与 WebCompass 六类任务输入差异

> 本报告保留 v3/v4 的输入差异原始审计；0905 当前输入检查口径统一见 [0905 数据检查策略与实施记录](reports/0905_data_check_strategy_implementation_20260912.md)。

日期：2026-09-04

## 更新
目前这些问题都已经被注意到。
基本都在解决中。

## 结论

WebCompass 实际有 7 类任务；本文只比较 reversed 已覆盖的 6 类，暂不包含 Video-Guided Generation。

当前最需要修正的不是六类任务名称，而是以下输入细节：

1. **Image Generate 的图片证据明显更弱。** WebCompass 116 条样本每条 2—41 张图，共 996 张，中位数 4.5；reversed 10,094 条中 7,094 条只有 1 张图，中位数 1。reversed 的 3,000 条多图样本也没有模型可见的页面/状态/动作映射。
2. **多页图片缺少稳定角色说明。** WebCompass 网页型多页样本使用带编号入口的主页图和对应子页图；当前正式 reversed 没有 `page_entry_mapping`，物理多页 Image Generate 仍有 14 条只给一张图。2026-09-03 pilot 已证明入口标注可行，但尚未合入 v4。
3. **交互关键帧缺少时序语义。** reversed 有多图记录，但正式 release 中没有 `interaction_mapping`；仅凭 `clean_00.jpg` 等文件名无法区分 before、action、after。pilot 中新增的 4 条清晰交互样本也尚未合入。
4. **SPA 多页尚未完成图片覆盖审计。** v4 已补全 203 条物理多 HTML Image Edit 的全部页面截图，但当前多页定义已允许 pathname/hash SPA；这部分尚未按“主页两个真实入口及两个不同页面级视图”重新分类并补齐视图截图。
5. **Edit/Repair 的任务密度偏低。** WebCompass Edit 和 Repair 每条均为 4—12 个任务/缺陷；reversed Edit 有 2,185/5,974（36.6%）只有 1—3 个任务，Text Repair 有 4,931/9,250（53.3%）只有 1—3 个问题，Image Repair 有 3,659/7,373（49.6%）只有 1—3 个问题。
6. **Repair prompt 没有被可靠送进最终 chat。** release record 的 `repair_instruction` 隐藏具体 defect label，只写问题数 N；WebCompass 还会给 11 种缺陷的公共定义。更严重的是，当前工作树中的训练转换器已被删除，而 Git 上一版 Text Repair 转换器会忽略 `repair_instruction`，连 N 也不会送给模型。
7. **资源可用方式不同。** WebCompass 会把 `resources` 指向的图片、字体等复制进工作区；reversed release 只实体化任务截图，不实体化源项目资源。若代码仍引用这些路径，`resources` 字段本身不能替代文件可用性。
8. **六类最终 chat 的构造入口不完整。** `train/convert_to_llamafactory.py` 当前在工作树中处于已删除状态；Git 上一版只支持三类 text 任务，不支持三类 image 任务，并且 Text Repair 忽略 `repair_instruction`。因此当前仓库不能复现六类 record 到最终模型消息的统一序列化过程。

## 比较口径

- WebCompass：2026-09-04 读取 Hugging Face `NJU-LINK/WebCompass` 当前公开数据及本地官方推理代码。
- reversed：下载已公开验收的 `reversed_20260829_v3` 六个完整 gzip 分片做全量字段统计；v4 只改 Image Edit，因此其余五类沿用 v3 统计，Image Edit 使用 v4 已验收的 203 条补图结果。
- 物理机 `/data2/.../reversed_20260903_v4` 本轮 SSH 仍被 reset，未重新读取；本文不把 2026-09-03 pilot 当作已经合入正式 release。
- 只比较模型可见输入。`problem_statement`、`dst_code`、`label_modified_files`、`task_type` 隐藏标签等 evaluator/oracle 字段不算输入。

## WebCompass 六类实际输入

| 任务 | 模型实际收到 | 不会收到 |
| --- | --- | --- |
| Text Generate | 长文本网站规格 | 截图、源码、隐藏 checklist |
| Image Generate | 通用截图复现指令、按文件名标识的全部参考截图 | 内容型 text query、隐藏 checklist |
| Text Edit | 完整 Edit 描述列表、完整 source code；资源文件在工作区可用 | source screenshot、target screenshot、GT patch |
| Image Edit | Text Edit 的全部输入 + current/source screenshots | target screenshot、GT patch |
| Text Repair | 11 类公共缺陷定义、问题数 N、faulty source code | 每条样本的 defect label/description、任何截图、GT patch |
| Image Repair | Text Repair 的全部输入 + current/faulty screenshots + target/clean screenshots | 每条样本的 defect label/description、GT patch |

需要纠正旧结论：WebCompass Repair **不向模型提供每条样本的自然语言故障描述**。官方 `description` 与 `task_type` 存在于数据记录中，但 prompt constructor 将它们隐藏，只使用 `len(description)` 生成 N。

## 六类逐项对比

### 1. Text Generate

| 项目 | WebCompass | reversed | 判断 |
| --- | --- | --- | --- |
| 内容输入 | 123 条结构化网站规格 | 24,094 条，来自多个 benchmark | 类型一致，但风格更异构 |
| query 字符数 | 4,589—8,926 | 2,922—18,802；中位数 5,840 | 4,886 条短于 WebCompass 最短值；2,241 条长于其最长值 |
| 多页表达 | 在需求中自然描述页面角色和跨页功能，不要求输出固定数量 HTML | 部分 query 描述多视图；旧 `page_type=mp` 不能证明有两个真实入口 | 需要按浏览器行为重新标记，不应把 HTML 数写进 query |
| 隐藏 checklist | 每条 10—14 项，只用于评测 | 正式训练 record 没有同级 hidden oracle | 不影响训练输入，但影响后续独立验证能力 |

Text Generate 不需要为了字面一致强制统一模板；需要处理的是明显过短、只列视觉名词、没有交互结果或页面角色不清的 query。

#### 具体例子

**WebCompass `694`：AI 对话与项目管理应用。** 原始英文 query 很长，中文概括如下：

- 页面结构：桌面端常驻但可折叠的左侧栏，移动端改为汉堡菜单；主区域包含模型选择、对话流、输入框和设置弹窗。
- 页面状态：空对话、新建对话、流式回答、停止生成、历史搜索、重命名/删除/归档、明暗主题与动画开关。
- 完整流程：用户新建对话，选择模型，输入“制定营销策略”，页面立即加入用户消息、显示思考态、逐字输出回答，并在侧栏创建新会话。
- 持久化：主题和动画偏好写入本地存储；关闭动画后，渐变边框、模糊和入场动画都必须出现可观察变化。
- 视觉：深色 SaaS 风格、青紫渐变发光边框、玻璃效果、按钮按压反馈和统一圆角。

这个例子体现了官方 query 的特点：它不是只描述“做一个聊天页”，而是同时指定页面区域、状态变化、动作顺序、持久化和视觉反馈。隐藏 checklist 再从这些要求中抽出 10—14 个评测点。

**reversed `complex-00074`：CNC 机床监控。** 中文概括如下：

- 使用 Vue 3、TypeScript、Vite、Pinia 和 Vue Router；包含“实时仪表盘”和“作业队列”两个视图。
- 用 SVG 仪表显示主轴转速、冷却液温度和轴负载，并由模拟 WebSocket 更新。
- 在队列暂停作业后，仪表盘必须立即进入“停机”状态；操作员确认前不能恢复。
- 提供 3 个作业及历史遥测的本地数据，项目可安装、构建和运行，不依赖外部后端。

这条只有 2,922 个字符，语义其实完整；它比 WebCompass 更短主要是因为附加的是工程交付约束，而不是把每个界面状态逐层展开。它应保留，不能用“低于官方最短字符数”直接判低质。

**reversed `gen14-interactweb-bench-iwb-g5-00014`：社区资源田野调查应用。** 中文概括如下：

- 需要介绍交换概念的首页、可按类别筛选物品/技能的发现页、并排比较多个条目的比较页，以及解释定性研究方法的方法页。
- 用户路径是“浏览 → 筛选 → 并排比较 → 明确选择”，全部使用本地静态数组，不使用数据库或登录。
- 视觉使用低饱和大地色和暖琥珀色；导航必须让不熟悉技术的研究者不迷路。

这条约 5,840 字符，已经很接近 WebCompass 的信息密度，而且页面角色是自然写进用户需求的；真正需要验证的是生成结果是否有两个可点击的页面级入口，而不是 query 是否写了“至少两个 HTML”。

**reversed `gen14-webcompass-wc-5-00697`：生态修复追踪器。** 中文概括如下：

- 包含项目总览、现场数据录入、分析工作区和报告生成器四个区域。
- 明确规定“调查提交后跳到带预设筛选条件的分析页”和“从异常图表跳到已预填配置的报告页”两条跨页流程。
- 还规定草稿恢复、分类检索、图表与表格联动、异常侧栏、报告生成进度、取消与失败恢复等状态。

这条达到 18,802 字符，明显长于官方范围。内容本身不是错，但混入了大量统一的 benchmark contract 和输出协议，训练时可能让模型更多学习“如何吐文件”而不是“如何理解产品需求”。因此 Text Generate 的优化应是分离用户需求与生产约束，不是机械截断 query。

### 2. Image Generate

| 项目 | WebCompass | reversed | 判断 |
| --- | --- | --- | --- |
| 图片数 | 116 条、996 张；每条 2—41 张，中位数 4.5 | 10,094 条、17,987 张；7,094 条单图，总体中位数 1 | 最大差距 |
| 网页型多页 | 55 条恰好 3 张；样本 `114` 为“带编号主页 + 2 个子页” | 3,014 条标称 MP；其中 14 条物理多 HTML 只有一张图 | 正式 release 尚未补齐这 14 条 |
| 页面映射 | 入口编号直接画在主页；子页由页面文件名和内容识别 | 正式 v3/v4 无 `page_entry_mapping` | 无法稳定知道哪张子页对应哪个入口 |
| 交互/状态 | 多个样本包含点击前后、下拉展开、hover、动画阶段和流程状态，最多 41 帧 | 有 3,000 条多图，但无 action/时序字段；正式数据无 `interaction_mapping` | 多图不等于关键帧序列 |
| 图片命名 | 常用页面名或自然语言状态描述 | 多为 `clean.png`、`clean_00.jpg` 等 | 模型可见语义较弱 |
| 文本 query | 没有内容型 query，只有通用任务说明 | 统一 351 字符通用说明 | 基本对齐 |

2026-09-03 pilot 的视觉效果已经可接受，但仍有两个落地条件：

- `page_entry_mapping` / `interaction_mapping` 必须进入模型可见 prompt，不能只留在 metadata；
- 不改变 GT 时，新增图片必须覆盖 GT 中实际要求的页面/状态，不能只任取两个子页后丢弃其他已有覆盖。

#### 具体例子

**WebCompass `114`：主页入口标注 + 两个子页。** 模型收到 3 张图：`home.png`、`index.php.png`、`involvement.php.png`。主页截图上直接叠加两个编号：红色 `1` 标在“Getting Involved”入口，蓝色 `2` 标在“HOMEPAGE”入口；另外两张图展示相应目标页。模型不需要从相似页面中猜测“哪张图是从哪个入口打开的”。

这类样本的关键信息不是“恰好三张图”，而是形成了完整对应关系：

`标注后的主页 → 编号 1 的目标页 → 编号 2 的目标页`

**WebCompass `1`：同一页面的交互前后帧。** 两张截图分别展示点击 Fortune Cookie 前后的界面。它不是多页导航，而是同一页面的状态转换。正确的模型输入语义应为：

`点击前 → 点击 Fortune Cookie 按钮 → 点击后`

因此不能只把两张图按 `image_0`、`image_1` 排列；否则模型只能凭视觉差异猜动作。

**reversed `WebGen-Bench.prompt_1660`：五个 HTML，只给一张首页图。** GT 包含 `index.html`、`about.html`、`contact.html`、`portfolio.html`、`services.html`，但输入只有 `clean.png`。这里至少存在三个问题：

1. 模型看不到四个子页的视觉目标；
2. 首页图中没有编号说明入口与子页的对应关系；
3. 如果 GT 的子页有独特布局，单张首页图不可能提供这些信息。

这正是应该无 LLM 补图的 14 条物理多页单图样本之一：保留原 GT，逐页渲染，再在主页临时叠加入口编号。

**reversed `gen14-interactweb-bench-iwb-g5-00216-db157c1738`：四页四图，但角色不透明。** GT 包含 `index.html`、`catalog.html`、`dashboard.html`、`planning.html`，输入也有 4 张图，但文件名只是 `clean-000.jpg` 到 `clean-003.jpg`。数量覆盖是够的，语义覆盖仍不完整：模型不知道 `clean-001` 是目录页、仪表盘还是规划页，也不知道主页上的哪个入口通向它。最低成本修复不是重做 GT，而是在 prompt 中增加例如：

- `clean-000.jpg`：带编号入口的主页；
- `编号 1 → clean-001.jpg：资源目录页`；
- `编号 2 → clean-002.jpg：研究仪表盘`；
- `编号 3 → clean-003.jpg：规划页`。

**reversed `gen14-artifactsbench-ab-2-00796-148136ea96`：单 HTML 四帧。** 这条有 `clean-000` 至 `clean-003` 四张图，但 GT 只有 `index.html`。它可能是 SPA 的不同视图，也可能是交互状态帧；仅靠现有字段无法判断。必须通过 URL 变化和实际动作把它归为“页面级导航”或“交互关键帧”，不能仅因有四张图就算多页已对齐。

### 3. Text Edit

| 项目 | WebCompass | reversed | 判断 |
| --- | --- | --- | --- |
| source code | 完整 source code，以路径分隔 | 完整 `instruction.src_code` | 对齐 |
| Edit 指令 | 每条 4—12 项，格式为 task type + 详细 description | 每条 1—12 项；36.6% 只有 1—3 项 | reversed 更偏原子 Edit |
| 图片 | 无 | 无 | 对齐 |
| 资源 | 资源文件复制到 agent workspace | record 可有 `resources`，但 release 不含对应源项目二进制 | 有意偏离；必须保证代码不依赖缺失资源 |
| 输出要求 | search/replace XML | record 中存结构化 patch list | 语义一致，最终 chat serializer 需统一 |

原子 Edit 本身不是低质量，但若目标是分布对齐，应单独标注 `atomic_edit`，再保留一部分 4—12 项的组合 Edit，不应把两者混为同一难度分布。

#### 具体例子

**WebCompass SP `1047829_www.evolvemediallc.com_L4_1`：一条记录内有四个完整 Edit。** 中文概括如下：

1. 富文本编辑器：为内部 CMS 增加固定工具栏、粗体/斜体/下划线/删除线、H1—H3、列表、引用块、链接弹窗、URL 图片预览、HTML 清洗和隐藏字段实时同步。
2. 拖拽管理：把品牌做成可排序卡片，拖动时显示半透明幽灵和蓝色落点，放下后计算新序号并写入 `localStorage`。
3. 三步申请向导：个人信息、经历与作品、法律声明；每步校验后才能继续，可返回修改且不丢后续数据，提交前显示汇总。
4. 通知中心：全局铃铛、未读计数、按部门和时间分组、三种严重级别、模拟实时消息、单条关闭和全部已读。

它说明官方所谓“一条 Edit”并不等于一个按钮变化，而可能同时要求多个独立组件与状态机。

**WebCompass MP `1047829_www.evolvemediallc.com_L10_2`：四页源码上的十项组合修改。** 其中三个代表任务是：

- 在首页增加“实时网络覆盖”仪表盘，显示活跃读者、参与速度、最近十分钟折线和每 5 秒更新的时间戳；超过阈值时品牌状态变为绿色脉冲。
- 为品牌 Logo 与领导头像增加与最终布局一致的骨架屏，资源加载完成后淡入，并设置 `aria-busy`。
- 把品牌列表改成支持多列排序、搜索、类别筛选、多选对比、内部备注行内编辑以及移动端卡片化的数据表。

模型还同时收到 `about.html`、`contact.html`、`index.html`、`services.html` 的完整源码。任务数和跨页影响范围都明显高于 reversed 的大量原子 Edit。

**reversed `gen14-frontalk-ft-g5-00006-ceb44b7ea5`：一个跨页原子 Edit。** 中文要求是：增加全局 Toast，页面跳转后仍能工作；Toast 有进入/退出动画、进度条、悬停暂停和关闭逻辑，并分别在 Home 演示动作和 Deck 保存成功时触发。它虽只有 1 项，但包含跨页状态和两个触发点，不能因任务数为 1 就判低质。

**reversed `gen14-interactweb-bench-iwb-g5-00178-6d70a62dd2`：一个全局加载态 Edit。** 中文要求是：路由切换时固定显示 600ms 骨架屏，再渲染目标视图，并对所有已连接页面保持一致。它同样是 1 项，但修改会影响整个路由系统。

**reversed `webdev_4143`：三项常规组合 Edit。** 要求分别是平滑回到顶部按钮、带帮助弹窗和全局监听的快捷键系统、带格式工具栏并同步隐藏 textarea 的所见即所得编辑器。它比单项样本更接近官方组合形式，但每项描述仍比官方短，缺少更细的状态、数据和可访问性条件。

### 4. Image Edit

| 项目 | WebCompass | reversed v4 | 判断 |
| --- | --- | --- | --- |
| 文字与源码 | 与 Text Edit 相同 | 与本地 Text Edit 5,974 条逐 ID 配对 | 对齐 |
| SP source 图 | 150/150 每条一张 | 单页面记录每条一张 | 对齐 |
| MP source 图 | 144 条 4 张、6 条 3 张；不按 affected page 过滤 | 203 条物理多 HTML 已补为每 HTML 一张，共 746 张 | 物理多页已基本对齐且更完整 |
| SPA 页面级视图 | 官方 MP 集没有 SPA，均为 4 HTML | reversed 旧 MP 中有大量单 HTML route/view 项目 | 尚未按新定义验证两个入口并补全视图图像 |
| target 图 | 不给模型 | `dst_screenshot=[]` | 对齐 |

v4 的 203 条补图只解决物理多 HTML。它没有自动解决“单 HTML 但确实是页面级 SPA”的 source-view 覆盖。

#### 具体例子

**WebCompass MP `1047829_www.evolvemediallc.com_L10_2`。** Text Edit 中的十项要求、四页源码，在 Image Edit 中保持不变，只额外给 `about`、`contact`、`index`、`services` 四张当前页面截图。模型由此同时知道：现有页面长什么样、各页面源码是什么、需要新增哪些能力。它不会看到编辑后的目标截图。

**reversed v4 的同类物理多页记录。** 203 条物理多 HTML 已改为每个 HTML 都提供当前截图。例如四个 HTML 的项目现在对应四张 source 图；这部分在“图片数量覆盖”上已经接近官方。仍需保留文件/页面映射，避免仅靠 `clean-000` 的序号猜页面。

**reversed `gen14-frontalk-ft-g5-00006-ceb44b7ea5`。** 它被标为 MP，Toast 要在 Home 和 Deck 两个视图触发，但 v3 模型输入只有一张 `clean.jpg`。由于项目只有 `index.html + app.js + styles.css`，它很可能是 SPA。当前输入只展示一个状态，模型看不到另一个页面级视图的原貌，也看不到两个入口在哪里。

**reversed `gen14-interactweb-bench-iwb-g5-00178-6d70a62dd2`。** 它要求骨架屏覆盖所有路由，源码中包含 `router.js`，但输入同样只有一张 `clean.jpg`。若评测只截首页，模型可能完成一个首页骨架屏就获得部分分数；若按任务语义验收，则应至少覆盖“主页入口、另一个路由、切换时骨架、切换后内容”这些证据。这里应补 source-view 截图和页面映射，不需要改 GT。

### 5. Text Repair

| 项目 | WebCompass | reversed | 判断 |
| --- | --- | --- | --- |
| faulty code | 完整 source code | `instruction=[{path,code},...]` | 对齐 |
| 每条故障描述 | 隐藏 | 隐藏 | 对齐；旧报告对此判断有误 |
| 问题数 | 明确告诉 N；N=4—12 | release 的 `repair_instruction` 存有 N；N=1—12，但 Git 上一版转换器忽略该字段 | 53.3% 为 1—3 个问题，且最终 chat 可能连 N 都没有 |
| 公共 defect 定义 | prompt 中给出 11 类定义 | release 与 Git 上一版转换器均未加入 | 不对齐 |
| 图片 | 无 | 无 | 对齐 |

#### 具体例子

**WebCompass SP `1047829_www.evolvemediallc.com_L12_1`。** 数据内部记录了 12 个具体缺陷，例如“About Us 文本溢出”“页脚链接错位”“Reach out 被错误实现成不可交互的 `span`”。但这些逐项描述不会给模型。模型真正看到的是：

- 11 类公共缺陷及其定义；
- “一共有 12 个问题，只修复这 12 个”；
- 完整故障源码。

因此官方任务要求模型自行从代码和公共缺陷空间中定位问题，而不是照着 12 条答案逐项修改。

**reversed `webdev_4143`。** 记录内部标签是“尺寸比例、语义错误、遮挡”，并存有“只有 3 个问题，不得多修”的指令。但 Git 上一版转换器只把故障代码送入 Text Repair chat，既没送这句 N=3，也没送 11 类公共定义。最终训练输入会退化为“看到一份坏代码，但不知道要找几个问题、问题边界是什么”。

**reversed `gen14-artifactsbench-ab-1-00007-d9d6e8667a`。** Text Repair 内部故障是“状态同步失败”，N=1，源码只有 `index.html`。合理的模型输入应表达“只修 1 个问题”并附故障代码，但不暴露“状态同步失败”这个隐藏答案。当前 record 层做到了前半部分，旧 converter 没有做到。

**任务密度差异的实际含义。** WebCompass 的 N 总在 4—12；reversed 有 1,574 条 N=1、1,722 条 N=2、1,635 条 N=3。N=1 并非坏数据，适合训练精确的小范围修复；但如果直接与官方混合统计，会显著降低组合定位和避免过修复的训练强度。应增加 `atomic_repair` / `compound_repair` 分层，而不是删除 N=1—3。

### 6. Image Repair

| 项目 | WebCompass | reversed | 判断 |
| --- | --- | --- | --- |
| faulty code 与 N | 与 Text Repair 相同 | record 中有 `input_files` + `repair_instruction`，但当前仓库没有 Image Repair chat converter | 存储字段接近，模型输入未闭合 |
| current/target 图 | SP 为 1+1；MP 按 4 页给 4+4 | 每条 src/dst 数量相等；中位数 1，P90 为 4，最大 12 | 数量字段完整，但页面角色仍主要靠序号 |
| 可见变化 | 允许部分页静态图相同，但样本至少应有可观察修复证据 | 历史审计发现 995 对 src/dst 完全相同，分布在 497 条记录中 | 需区分合理的语义/交互修复与错误截图 |
| 与 Text Repair 配对 | 同一 Repair 样本切换 text/image mode | Image Repair 7,373 条均能在 Text Repair 找到；另有 1,877 条 Text-only；115 个同 ID 的 `task_type` 不同 | 不是严格的同实例双模态视图 |
| prompt 公共定义 | 含 11 类定义 | 缺少 | 不完全对齐 |

同一 `instance_id` 在 Text/Image Repair 中代表不同故障是高风险问题。例如 `gen14-artifactsbench-ab-1-00007-d9d6e8667a` 在 Text Repair 是 `state_sync_failure`，在 Image Repair 是 `overflow`，patch hash 也不同。它们应使用不同 ID，或明确 `parent_instance_id + repair_variant_id`。

#### 具体例子

**WebCompass MP `1047829_www.evolvemediallc.com_L11_2`。** 内部有 11 个缺陷，例如 About 页非法嵌套、Contact 页 LinkedIn 图标比例错误、首页 ComingSoon Logo 变形。模型看不到这些逐项文字，但会收到：

- N=11 与 11 类公共缺陷定义；
- 四页故障源码；
- `about/contact/index/services` 四张 current 图；
- 同四页的四张 target 图。

即使某个缺陷是语义或交互问题、单页前后静态截图没有明显差异，模型仍可结合代码、N 和其他页面截图定位；官方不是用“每一对截图必须像素不同”作为样本定义。

**reversed `gen14-webcompass-wc-c05-00049-338898992d`。** 这是一个多视图 Image Repair，N=1，内部故障为“覆盖层行为失效”，提供 4 张 `repair_defective_00..03` 和 4 张 `clean_00..03`。数量上不错，但文件名不说明：哪张是 Overview、Inspector、Repair Log 或 Validation，也不说明要执行什么动作才能看到覆盖层故障。应增加页面与动作映射，例如“在 Inspector 点击详情按钮后，覆盖层应打开并阻止背景点击”。

**reversed `gen14-webgen-bench-wg-2-00081-cffed948c4`。** N=1，内部故障为“错误状态转换”，提供 5 张 current 和 5 张 target。若错误只在点击后的状态发生，十张静态图仍需要明确排序和动作；否则模型无法知道哪一对是初始态、哪一对是操作后状态。

**同 ID 冲突 `gen14-artifactsbench-ab-1-00007-d9d6e8667a`。** Text Repair 将其定义为“状态同步失败”，Image Repair 却定义为“溢出”，两者 N 都是 1，但 patch hash 不同。这不是“同一个故障的文字版和图片版”，而是两个独立修复任务误用了同一 ID。训练时若按 ID 去重、配对或划分 split，会造成错误关联。

**497 条含相同截图对的样本如何判断。** 假设四页中 About 页修复了非法 DOM 嵌套，而另外三页没有变化，那么三对截图完全相同是合理的；如果所有页面都相同，但问题是点击后弹窗失效，也可能需要交互回放才能证明；只有既无任何可见差异、又没有动作后差异或可验证语义修复证据时，才应判输入证据不足。不能用“任意一对相同就删整条”的规则。

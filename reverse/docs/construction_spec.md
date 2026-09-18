# 六类 WebCoding 任务构造规范

## 1. 先区分四个容易混淆的概念

- **六类任务**：Text/Image × Generate/Edit/Repair；Video Generate 不在本项目这六类中。
- **单页/多页**：项目是否有不同的页面级视图，不按截图张数或 HTML 文件数直接判断。
- **一条记录的子任务数 N**：例如一条 Edit 同时要求数据表、上传、向导和通知中心，N=4。
- **连续 Edit 链的轮数**：Q1→Q2→…→Q10 是十轮修改，不等于一条官方 Edit 记录的十个子任务。某轮也可以包含多个子任务。

### 1.1 Source、Target 和 GT 的方向

| 阶段 | Source | Target / GT | 模型答案 |
| --- | --- | --- | --- |
| Generate | 没有待修改源项目 | 满足文字/截图要求的完整正确项目 | 完整文件及路径 |
| Edit | 修改前的正确项目 | 完成增量需求后的正确项目 | source→target 的 patch |
| Repair | 注入缺陷后的错误项目 | 注入前的正确项目 | defective→clean 的 patch |

Edit/Repair 母本统一从 **Generate 数据中经过验证的正确 GT** 选取；母本数量与派生任务数量分别统计。Repair 的缺陷注入方向是 clean→defective，训练答案方向相反。

### 1.2 单页与多页

- 本项目已确认的多页资格：主页至少有两个真实入口，点击后分别到达内容明显不同的页面级视图。
- 多个 HTML、pathname 路由、hash 路由和其他 SPA 页面切换都可以实现多页。四个业务页面不等于四个 HTML。
- 普通 Tab、弹窗、下拉、accordion、局部筛选是页内状态；不能仅凭出现 Tab 或 URL 变化就判成多页，要看是否切换页面级内容。
- Query 明确要求首页、商品、购物车、结账四个页面角色时，GT 必须实现四个角色及其真实到达路径；文件数量只是辅助信息。
- 当前用于对齐官方 Edit/Repair 源码形式的专项补充批次，另行要求“物理多 HTML、优先四 HTML”。这是该批次采样条件，不改写通用多页定义。
- 仅两个真实页面、但不满足上述“两条主页入口”的项目，是现有资格规则的边界；保留实际页面记录并确认批次口径，不擅自改标签或直接筛除。

**页数一致性规则（2026-09-12 用户确认）：** 多页记录必须保留可核对的页面清单（页面角色、入口或 route，及相应截图映射）。“页数正确”指该清单与需求/图片映射一致，且每个列出的页面在相应项目版本中存在；不以截图张数、Tab 数或 HTML 文件数单独替代页面数。Generate 可以采用单 HTML 的 SPA，但必须由不同、可到达的页面级 route/角色构成完整清单。新构造的 Edit/Repair 多页数据优先选用物理多 HTML 母本；此时递归 HTML 清单与页面清单逐页对应。若有意保留 SPA 变体，必须显式记录其 route→页面映射，不能计入“物理多 HTML 多页”母本或该专项产量。Edit 若明确新增/删除页面，分别核对 source 与 target 的页面清单；Repair 的 defective 与 clean 页面清单应保持对应。

### 1.3 六类任务的统一定义

- **Text Generate**：输入完整、具体的网页需求，输出从零实现该需求的完整项目文件；模型不接收已有项目代码。
- **Image Generate**：输入网页目标截图及必要的图片角色/动作关系说明，输出对应的完整项目文件；目标代码和隐藏验收信息不进入模型输入。
- **Text Edit**：输入正确的完整 source 项目和增量编辑要求，输出将 source 修改为 target 的精确 patch；编辑必须是正向新增或调整，不把恢复原功能伪装成编辑。
- **Image Edit**：与 Text Edit 使用同一 source、编辑要求、target 和 patch。常规对齐记录额外输入 source 状态截图；已明确标记的历史变体可输入 source、target 或 source+target 截图，实际模型图片以有序 `input_images` 为准。
- **Text Repair**：输入带缺陷的完整 source 项目、公共缺陷定义和本例问题数量 N，输出恢复到 clean target 的精确 patch；逐实例缺陷位置和答案保持隐藏。
- **Image Repair**：与 Text Repair 使用同一 defective source、问题集合和 patch，额外输入 defective/current 与 clean/target 截图；clean 代码和逐实例缺陷答案不进入模型输入。

### 1.4 六类任务的共用数据关系

每条数据以完整网页项目为基本单位，不以单个HTML文件代替项目。渲染环境保留完整文件集合；默认Edit/Repair输入完整代码，2026-09-08 image-based只读渲染依赖例外见9.3节。代码上下文限制和最终消息协议以第9节及对应实现为准。

六类任务围绕同一项目形成配对关系：Text/Image Generate 共享正确 GT，Image Generate 将截图作为输入；Text/Image Edit 共享 source、编辑要求和 patch，Image Edit 额外提供按变体声明的 source/target 图；Text/Image Repair 共享 defective source、问题集合和修复 patch，Image Repair 额外提供 defective/clean 截图。Generate 的正确 GT 是 Edit/Repair 的合法母本，patch 方向始终是 source→target，Repair 的 source→target 则是 defective→clean。

旧版六类说明中的部分数字是当时批次口径，不作为当前统一规则：Edit/Repair 的 4–12 项要求、Image Repair 的可见差异要求和多页页面覆盖，以本文后续章节及 2026-09-06 当前记录为准。

### 1.5 物理机在线多页母本池（2026-09-09）

已完成一批可供 Edit/Repair 继续筛选的在线资源母本候选：

- 运行根：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/online_mothers_3000_20260908/batch/`
- 入口证据：`manifest.jsonl`、`progress.json`、`run_config.json`；来源 URL 队列为同级 `../url_queue_v4/urls.txt`。
- 运行配置：`target=1000`、`workers=8`、`max_child_pages=3`、`min_pages=2`、`max_code_tokens=40000`、`context_policy=image_render_assisted`、`total_timeout=0`。主页加最多三个同站子页，资源策略为保存业务代码并绝对化在线媒体/已核验公共库。
- 当前现场统计：`progress.json` 为 `complete`、`passed=1000`、`attempted=7997`、`in_flight=0`；`manifest.jsonl` 中有 1001 个唯一 `status=pass` 项目，项目目录均存在并可递归读取 HTML。页面分布为恰好 4 页 723、3 页 140、2 页 138。
- 这 1001 条的 `quality_status` 仍为 `online_mother_candidate`。723 个四页项目是本轮 Edit/Repair 母本优先筛选池，但“恰好四个 HTML”只证明文件结构；正式使用前仍要确认主页入口、页面角色差异、导航/刷新行为和需求–GT 对齐。当前造数批次不追加本地浏览器语义验收。
- 选择路径：从 manifest 过滤 `status=pass`、项目目录存在、递归 HTML 数为 4 的记录，再读取每个项目的页面清单、截图和资源/依赖 manifest。`image_render_assisted` 项目中的排除依赖只能作为只读渲染依赖，不能成为 Edit patch 目标或 Repair 注错目标；Text Edit/Repair 只有在完整模型输入和 Generate GT 资格均满足时才可派生。
- 不把这批候选直接称为 accepted Seed、Generate GT 或正式训练母本；候选数量、资源回放通过和正式语义准入必须分开记录。数据母本数量与派生 Edit/Repair 数量也分别统计。

## 2. 2026-09-06 用户新增要求 Checklist

以下勾选只表示对应工作已完成并经过文档中所列检查；候选、已写入、基础检查和正式验收仍分开记录。按 2026-09-12 用户口径，当前造数批次不执行浏览器验收；下列历史 checklist 中的浏览器验收项不作为本批次门槛。

### 2.1 最新版 0805 数据集核对（2026-09-07）

- **数据集名称**：`0805_webcompass_aligned_20260906_v2`
- **远端路径**：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`
- **当前六类数量**：Text Generate 10,596；Image Generate 11,192；Text Edit 3,005；Image Edit 3,005；Text Repair 3,349；Image Repair 3,017，共 34,164 条。
- **Image Generate 来源补充**：已追加 Vision2Web L1/L2 141 条、Flame-VLM-Code 143 条、Interaction2Code 143 条，共 427 条和 427 张实体图；导入记录显示 GT response 哈希未变化、重复 ID 为 0、缺图为 0。
- **Text Generate 来源补充**：已确认追加 1,502 条 WebCompass 多页数据；WebGen-Bench、InteractWeb-Bench 的 Text Generate 尚未找到对应的本版导入记录，因此“全部来源都拿过来”仍未完成。
- **Image Generate 状态类型**：索引记录含 multipage 1,988、interaction 1,723、transient 609、sequence 864；这证明对应记录已进入最新版，但主页真实入口和状态回放仍需按本文件要求继续验收。
- **Edit/Repair 子任务数**：最新版 Text/Image Edit 的 `task_count` 均为 1–7；Text Repair 为 1–7；Image Repair 为 1–7，尚未达到本文件要求的 4–12 项。
- **核对依据**：[数据资产台账](data_assets_registry.md)、[0906 逐项处理报告](../../../reverse/docs/reversed_edit_repair_training_regression_20260906.md)和该 release 的 `dataset_index.json`、`image_generate_source_import_20260906.json`。

- [ ] Text Generate：从 `0805_supplement` 纳入 WebCompass、WebGen-Bench、InteractWeb-Bench 来源，并完成来源去重、需求–GT 对齐、浏览器与资源检查。
- [x] Text Generate 多页母本：已完成 supplement 多 HTML GT 盘点；来源分布、页面文件数和待验收边界见 [0906 待办](../../../reverse/docs/reversed_edit_repair_training_regression_20260906.md)。
- [x] Image Generate 运行路径：supplement 的图像生成已在物理机上采用受限并发、硬上限和可观测运行方式；具体候选仍按状态类别分别统计。
- [x] Image Generate 来源补充：已从 supplement 纳入 Vision2Web L1/L2、Flame-VLM-Code、Interaction2Code，共427条记录和427张实体图；GT哈希保持不变。
- [ ] Image Generate 多页/状态输入：完成主页真实入口点击核验、主页入口标注与子页映射核验，并对单页渲染、交互/临时状态、连续步骤分别完成回放验收。
- [x] 0805 Edit/Repair 缺口统计：已统计子任务数量、8–12项分布和多 HTML 母本规模；统计证据见 [0906 全量统计](../../../reverse/docs/reversed_edit_repair_training_regression_20260906.md)。
- [ ] Text Edit：针对 0805 低频类型定向补充，覆盖单页与多 HTML 多页，新增任务覆盖4–12个子任务，并完成 query–GT、patch、功能与非目标回归检查。
- [ ] Image Edit：与 Text Edit 使用同一 source、编辑要求、target 和 patch；常规记录单页提供 source 图、多页提供全部可用页面 source 图；历史变体可显式提供 target 或 source+target 图，并以 `input_images` 及角色映射为准。
- [ ] Text Repair：针对 0805 低频类型和任务密度定向补充，覆盖单页与多 HTML 多页，新增任务覆盖4–12个问题，并完成缺陷数量、公共11类定义、patch 和 clean target 检查。
- [ ] Image Repair：与 Text Repair 使用同一故障 source、问题集合和 patch；单页提供 defective/clean 配对，多页提供全部可用页面的逐页配对，并完成最终消息序列化检查。
- [ ] 六类统一收尾：完成真实 Generate 母本准入、Edit/Repair 浏览器功能验收、资源闭包、图文配对、最终 chat 协议和 release 级索引/哈希检查。

## 3. Text Generate：文字 → 完整项目

### 单页要求

重点来源：WebCompass 、WebGen-Bench、InteractWeb-Bench。
目前状态：最新版已确认追加 1,502 条 WebCompass 多页 Text Generate；WebGen-Bench、InteractWeb-Bench 的 Text Generate 尚未找到对应导入记录，不能记为全部完成。

### 多页要求

重点来源：WebCompass 、WebGen-Bench、InteractWeb-Bench。
允许单 HTML 的 SPA：多页 GT 不要求多个 HTML，只要主页和子页角色/route 完整可核对。页面清单必须与需求、路由映射及 Image Generate 的逐页截图映射一致；不得因只有一个 HTML 而降成单页，也不得把多个状态截图误计为多个页面。
当前状态：最新版已追加 1,502 条 WebCompass 多页 Text Generate；其中多 HTML 和 SPA 的页面口径仍需按真实页面和来源继续核对，WebGen-Bench、InteractWeb-Bench 尚未完成同批追加。

### 3.1 输入与 Query

模型看到用户需求和必要的通用输出协议，不把已有 GT 代码或隐藏评测 checklist 当输入。

需求应说明实际需要的内容，而不是机械填满统一模板：

- 产品用途、业务对象和具体内容；
- 页面区域、布局、颜色、字体、间距等视觉要求；
- 用户操作、操作后的状态变化和组件之间的相互作用；
- 需求确实涉及的表单反馈、响应式、持久化等细节。

单页写清页内结构和交互；多页另外写清各页面角色、入口关系、跳转结果及必要的共享状态。用户要求的页面数、数据对象和功能范围必须与 GT 对应。

**长度是分布参考，不是合格阈值。** 2026-09-04审计中，官方123条 Text Generate 的 instruction 为4,589–8,926字符；这是字符数而非token数，也不是给其他benchmark统一设限。历史 reversed 为2,922–18,802字符，部分长度来自工程协议。比较时应分开用户正文、系统协议和代码上下文。[统计与例子](../../../reverse/docs/reversed_vs_webcompass_six_task_input_gap_audit_20260904.md)

### 3.2 输出与例子

输出完整项目文件 `{path, code}`，包括所需组件、样式、脚本及构建配置；React/Vue项目不能只留下HTML入口。

以下为解释性缩写，不是正式完整训练query：

- 单页：任务看板需求 → 三列任务板、拖拽及筛选交互 → 完整项目 → build、打开页面、移动任务后检查所属列变化。
- 多页：资源发现、比较、方法介绍等页面需求 → 具有真实导航的多个页面角色 → 完整项目 → 从主页进入各页面并检查角色是否齐全。

同一需求可以有不同正确实现；训练中的GT是其中一个具体项目，不代表唯一代码答案。

## 4. Image Generate：目标截图 → 完整项目

### 单页要求

分为：
（1）单页渲染截图——单图
（2）交互、临时状态、一系列状态——多图，目前已经追加到0805数据中。

最新版核对：Image Generate 共 11,192 条，其中索引记录 multipage 1,988、interaction 1,723、transient 609、sequence 864；Vision2Web L1/L2、Flame-VLM-Code、Interaction2Code 的 427 条来源补充已写入该版本。

### 多页要求

多页渲染截图
在 supplement 里改过了，在主页上会标出子页的入口。

最新版核对：multipage 记录已进入 `0805_webcompass_aligned_20260906_v2`，但主页真实入口点击、编号标注和子页映射仍需逐条完成验收，暂不把数量视为验收完成。

### 4.1 输入给模型的文字

使用通用截图复现说明，表达：复现截图中的布局、颜色、字体、间距、组件及明确暗示的交互；多视口有证据时复现相应响应式行为；输出完整项目。

再提供**图片角色和必要的动作对应说明**，而不是把原 Text Generate 的长产品需求完整复制过来：

- 哪张是主页，哪张是子页；
- 编号入口对应哪张子页图；
- 哪张是操作前/后，执行了什么动作；
- 连续帧的顺序及各帧展示的状态。

目标代码、隐藏 checklist、完整内部capture plan不进入模型输入。动作说明用于消除截图关系歧义，不能夹带未展示功能的答案。官方runner主要用通用说明和截图文件名；本项目把必要角色映射显式写进instruction，是本项目的输入补充。

### 4.2 四种截图组织方式

| 记录类型 | 图片如何组成 | 典型数量 | 当前边界 |
| --- | --- | --- | --- |
| 多页 `multi_page` | 标注主页＋各真实子页图 | P张；例如主页＋4子页=5张 | 覆盖实际GT页面，不截成固定三张 |
| 普通交互 `same_page_interaction_states` | 操作前→一次操作→操作后 | 通常2张 | 筛选、选择、排序等已有交互 |
| 同页状态 `transient_ui_state` | 基准状态→一次状态转换→结果状态 | 当前独立产物通常2张 | 接受所有稳定可观察的同页变化，不限弹层 |
| 连续操作 `multi_step_interaction_sequence` | 初始状态＋依次执行后的关键状态 | 至少3张 | 至少两步真实操作；现有较长有效流程保留 |

`transient_ui_state` 是保留的字段名。2026-09-06已放宽定义：hover/focus、Tab/accordion、搜索/筛选/排序、选中状态、主题/视图切换、表单反馈、轮播/分页，以及弹窗、菜单、下拉和toast都可以；不强制元素初始隐藏。

因此“普通交互”与“临时状态”有语义交集，不是四种天然互斥能力。`image_generate_visual_types` 可多选，独立派生记录用 `metadata.image_generate_primary_mode` 区分类别；类别覆盖数不能直接相加当独立样本数。

连续操作需要保留真实先后关系。例如“选场地→分配物资→安排志愿者→汇总→完成”，不能从不同基准状态各截一张后拼成流程。为降低成本，近期planner优先两步可靠操作，即初始帧＋两张结果帧；不是把连续操作改成只有两张图。

旧单图样本可以保留，但不能算多状态覆盖。官方2026-09-04图像生成审计为116条、每条2–41张，55条网页型多页样本恰好3张；这些是观察到的分布，不是给每条数据规定的固定图片数。

### 4.3 多页主页上的标注

已确认的制作顺序：

1. 从GT页面信息和浏览器事实确定目标页面清单。
2. 找到主页通向这些子页的真实入口，记录入口文字、位置及目标页面。
3. 仅在主页截图上临时叠加**彩色边框＋编号圆点**；编号与子页图一一对应。
4. 通过实际导航核实页面，再保存子页正常截图。
5. 将编号、入口、目标route和图片关系写入数据；标注不写回GT源码。

标注只说明“从哪里进入哪张图”，不是需要生成的新UI。未入选的其他链接、页内锚点和局部控件保持原状。颜色本身不承担业务含义，不能要求所有样本必须使用同一红蓝顺序。官方样例114用红色1、蓝色2；本地覆盖层使用多色编号框。

有五个真实页面就保留五页覆盖，不因为官方某类常见“主页＋两个子页”而裁掉剩余页面。子页缺少主页直接入口时，记录实际到达路径并复核，不凭空添加入口。

模型可见映射示意：

```text
annotated_home.png：主页；彩框编号是导航提示，不属于网页本身。
编号1 / About → about.png
编号2 / Services → services.png
编号3 / Portfolio → portfolio.png
编号4 / Contact → contact.png
```

内部 `page_manifest`、DOM定位器、坐标用于制作和复核；模型只接收必要的截图与关系说明，不接收完整目标项目。

### 4.4 多状态截图上的标注与顺序

- 当前明确确认的图片内彩框编号用于多页主页入口；没有要求给所有交互帧统一画箭头、圈出变化区或叠加步骤水印。
- 操作前后和步骤关系主要通过文件名、图片顺序及instruction的 `Reference image roles` 段说明。
- 普通交互示例：`before.png`显示All列表 → 选择Leadership → `after.png`显示对应结果。
- 连续步骤示例：`frame_00`初始 → 点击入口后的`frame_01` → 完成下一操作后的`frame_02`。
- 同一状态序列使用一致的viewport、滚动位置或明确记录的滚动动作，避免把滚屏、随机内容或渲染抖动当作功能变化。
- 图片必须由原GT中的真实动作产生；截图补充不能修改GT、增加原本不存在的功能，或伪造交互结果。

### 4.5 已有案例与实现边界

[四类本地示例预览](WebCoding_Data/logs/reversed_four_cases_local_20260905_v3/preview.html) 中，已有多页5张、普通交互2张、灯箱2张、连续步骤5张的案例；具体ID和验证范围见[交接记录](WebCoding_Data/docs/handoffs/reversed_image_generate_refresh.md)。灯箱案例记录了原图外链失败，不能把截图产出等同于资源质量已通过。

当前独立派生记录保留 `parent_instance_id`、独立ID、该类别自己的图片和instruction，复用母本GT。原始记录保留，后续新增图像样本主要从supplement母本生产。此前“只合并图片、总行数绝不增加”的规则是早期方案，已由用户允许独立追加所取代；六目录、每类单个gzip分片的外部布局继续保留。

**实现缺口：** 通用 `pilot_refresh_reversed_image_generate.py` 的多页分支仍包含枚举链接后直接 `page.goto()` 的路径；它不等于已验证真实入口可点击。定向示例做过点击核实，但不能外推所有历史多页记录都已完成相同验证。

## 5. Text Edit：正确项目＋增量要求 → Patch

### 单页要求

（1）在 0805 的基础上最好再补充一点，不直接使用0805supplement中的同任务数据（包含了非webcompass的类型）
（2）在之前0805数据中，每个任务的子任务数量有点少，需要补充4–12个子任务的任务，重点补充缺少的数量的。

最新版核对：Text Edit 当前为 3,005 条，但 `task_count` 仍为 1–7，4–12 项任务尚未补齐。

### 多页要求
**Important：edit和repair任务全部依托于generate母本**

当前状态：欠缺，几乎没什么这类的样本。
新构造优先选择包含多个独立 HTML 文件的母本；逐页列出 HTML、页面角色、入口/route 和图片映射，并保证清单页数正确。SPA 多页历史记录可保留为明确变体，但不计入物理多 HTML 母本。构造时注意每个任务需要包含4–12个子任务。

最新版核对：Text Edit 多页母本和新增记录已部分进入 v2，但当前 `task_count` 仍为 1–7，4–12 项要求未完成。

### 5.1 输入与 Query

输入完整source项目代码，以及逐项编辑要求。官方消息组织为 `Task编号 - task_type: description`，Edit类型和具体需求都是公开输入。

一个功能要写清**业务对象、完整操作、状态变化、组件相互作用和必要的视觉/产品细节**。不靠重复“保持原功能”“符合无障碍”“提供空状态”“持久化”来凑长度；这些条件仅在该功能真正需要时出现。

- 单页：说明修改所在区域、与现有控件/数据的关系。
- 多页：说明首页、具体子页或全局共享模块的作用范围；一条多页Edit可以只改一个子页，也可以改多页，不能强制每页都改。
- 子任务可以是独立功能，也可以存在状态依赖；不要强迫全部串成一条因果链。
- WebCompass每条实例有4–12个子任务；当前专项新增只使用官方16类，重点补单页8–12项和多页4–12项。历史1–3项记录不因项数少就自动成为错误数据。
- 每个子任务可以需要多个patch；子任务数不等于patch块数。将一个简单按钮拆成十条句子，也不会变成十个完整子任务。

官方16类：数据表、富文本编辑器、拖放界面、树形视图、实时看板、无限滚动、异步表单验证、带进度的文件上传、视差滚动、页面转场、粒子效果、骨架屏、购物车、用户认证、多步向导、通知中心。其他历史目录类型保留来源信息，不能称为官方Edit类型。

### 5.2 一个子任务应有的完整度

例如数据表子任务：在现有课程列表加入标题搜索、讲师/类别筛选、价格排序和分页；搜索与筛选共同作用，改变条件后回到第一页，结果数量同步更新；桌面显示表格，窄屏采用同信息的卡片布局；行内收藏操作与已有收藏列表同步。

这是一项包含相互作用的完整功能，不是“新增搜索按钮”后再附几段套话。正式组合实例可同时包含其他适合该产品的功能，但不应虚构source中不存在的数据字段。

链式扩增时，Q2可以使用Q1预计新增的状态，但必须在Q1明确创建；既不能引用不存在的逐帖字段，也不能要求再次添加source已具备的行为。

### 5.3 输出与静态验收方向

`正确source＋编辑要求 → patch → 新target`。patch应精确应用，新增功能按 query 和 task schema 可检查，非目标区域及旧功能按任务范围保留。完整target和目标截图可以作为内部产物或图片素材，但本批次不通过浏览器功能验收。

## 6. Image Edit：在Text Edit上增加当前截图

### 2026-09-08 用户指定的历史图片变体补充

用户明确要求将历史 source_image 65、target_image 61、source_target_images 55、source_target_images_no_query 59 共240条加入0805。本批保留原 instruction（包括59条空列表）、input_images顺序和GT patch，不用4–12项要求裁掉历史记录。上述 target 图和 source+target 图均是允许的训练变体，不得审计成泄漏；`source_target_images_no_query` 的空 instruction 也是该变体的既定输入，不得按空 instruction 判坏。新增ID采用 `原ID__historic_变体名`，metadata标记 `image_variant_extension=true`、`model_image_field=input_images`；消费这些扩展记录时必须读取input_images，保留各自source/target角色。常规WebCompass Image Edit仍按下面的source图协议。本批导入检查为文件保真和patch回放，不等于重新完成浏览器功能验收。

### 单页要求

和 Text Edit 对齐，在Text Edit上增加当前截图

最新版核对：Image Edit 当前为 3,005 条，图片补全记录已进入 v2；但由于对应 Text Edit 尚未达到 4–12 项，Image Edit 的该项要求也未完成。

### 多页要求

和 Text Edit 对齐，在Text Edit上增加当前截图

最新版核对：多页 Image Edit 的存量缺图补全已完成，但“与 4–12 项 Text Edit 对齐”仍未完成。

文字、source代码、编辑目标和GT patch与对应Text Edit一致，只增加修改前截图。

- 单页：典型输入一张source图。
- 多页：输入全部可用页面的source图，保存页面/route→图片的对应；不只截受影响页。
- 常规WebCompass对齐记录的模型看到的是“现在是什么样”，不发送 target 截图；这不覆盖明确声明的历史 Image Edit 变体。
- 历史变体的 target 截图只能按其原始 `input_images` 顺序与 source/target 角色映射发送；不能由训练器隐式追加，也不能把它误报成泄漏。
- 图片旁的角色说明是Current Screenshot＋文件名/页面身份；没有统一要求对Edit图片画新增组件位置、修改区域或答案框。

例：四页source代码＋十项编辑要求＋首页/About/Contact/Services四张当前图 → patch → 修改后四页项目。任务只要求更新Contact时，仍提供四页当前图，但不要求四页都发生视觉变化。

当前 `construct/v2_records.py::edit_records` 保留全部canonical source图，导出 `dst_screenshot=[]`，并在 `metadata.src_screenshot_pages` 保存页面映射。这是构造器行为，不代表所有旧分片均已补齐。[实现](../../../reverse/v2_records.py)

## 7. Text Repair：故障项目＋N → 保守修复

### 单页要求
（1）在 0805 的基础上最好再补充一点，不直接使用0805supplement中的同任务数据（包含了非webcompass的类型）
（2）在之前0805数据中，每个任务的子任务数量有点少，需要补充4–12个子任务的任务，重点补充缺少的数量的。

最新版核对：Text Repair 当前为 3,349 条，但 `task_count` 仍为 1–7，4–12 项问题尚未补齐。

### 多页要求
当前状态：欠缺，几乎没什么这类的样本。
新构造优先选择包含多个独立 HTML 文件的母本；逐页列出 HTML、页面角色、入口/route 和图片映射，并保证 defective/clean 的页面清单对应。SPA 多页历史记录可保留为明确变体，但不计入物理多 HTML 母本。构造时注意每个任务需要包含4–12个子任务。

最新版核对：Text Repair 多页母本和新增记录已部分进入 v2，但当前 `task_count` 仍为 1–7，4–12 项要求未完成。

### 7.1 模型公开看到什么

**长期要求（2026-09-08）：Text/Image Repair 的训练 prompt 与 WebCompass Repair 对齐。** 直接读取固定官方副本 `third_party/WebCompass_official/editing_repair/llm/mllm/prompt.py` 的完整 `Repair_Instruction_Prompt`，保留11类公共定义以及全部XML `search_replace`输出要求，按官方`construct_messages_for_repair`追加换行和本例问题数量N；禁止截掉`Output Format Requirements`，也不能退回仅通用修复句＋N。N按问题项数计算，重复类型不去重；具体问题标签、位置、描述和clean代码保持隐藏。Text Repair使用`repair_instruction`＋`instruction`中的故障代码；Image Repair使用相同prompt＋`input_files`＋全部current图和target图，先current后target。内部`response`仍保留原JSON patch数组，最终模型答案按官方XML序列化。检查prompt时按同N与官方完整文本比对；公共定义中出现类型名不属于逐实例答案泄漏。当前0805增强导出实现为`reverse/utils/build_0805_aligned_enhanced.py`，历史包的升级入口为`scripts/update_0805_generate_repair_20260908.py`。

1. 通用修复与patch输出协议。
2. **11类公共缺陷及其定义**，不表示本例包含全部类型。
3. 本例恰好有N个问题、不要超出该问题范围的说明。
4. 完整故障source代码。

11类：遮挡Occlusion、拥挤Crowding、文字重叠Text Overlap、对齐Alignment、颜色对比Color Contrast、溢出Overflow、尺寸比例Sizing Proportion、交互丢失Loss of Interactivity、语义错误Semantic Error、嵌套错误Nesting Error、属性缺失Missing Attributes。准确英文定义由官方prompt提供。

### 7.2 哪些是隐藏答案

本例具体有哪些缺陷、分别在哪里、逐条description、注入计划、clean代码和修复patch，都不能提前出现在用户输入中。N由真实问题数量得到，不按类别去重；12个问题可以包含重复类别，但必须是不同问题。

官方构造器只读取 `len(description)` 生成N，不把description正文发送给模型。旧文档中的“缺陷说明”应理解为公共类型解释，不能理解为逐条故障答案。[官方代码](../../../evaluate/WebCompass/editing_repair/llm/mllm/mllm_chat.py)

### 7.3 单页、多页与输出

- 单页：所有问题位于一个页面项目中，模型看到其故障代码。
- 多页：提供完整多页故障代码；N是整条记录总问题数，不是每页N个。缺陷不必覆盖每一页。
- 输出defective→clean的精确patch，不把注入缺陷的patch当训练答案。
- 本轮官方类型补充范围为4–12个问题；旧样本可以只有1–3个。具体标签数量、description数量和实际注入问题数应一致，不能为达到N而重复计同一缺陷。

例：某四页项目共4个问题，内部记录分别涉及遮挡、溢出、缺属性及交互失效。模型只得到公共11类定义、N=4和故障代码；修复后恢复原正确页面，而不是照着隐藏的四条定位答案修改。

## 8. Image Repair：再增加错误与正确截图

### 2026-09-08 输入清单与0905变体（优先于旧包隐式拼图规则）

`input_images`必须是模型实际收到的完整、有序图片清单，不允许训练器隐式补入未列出的`dst_screenshot`。标准前后对照为`src_screenshot + dst_screenshot`；用户指定的current-only变体仅为`src_screenshot`，其dst仍保存作内部参考但不得送入模型。前后角色根据src/dst成员关系标注，代码、公共Repair prompt和GT patch保持。0905现有3,017条中2,517条前后对照，500条仅修复前，不增加记录；500条按固定ID哈希选取，记录`metadata.repair_image_input_mode`和`model_image_field=input_images`。以上变体覆盖第1、7、9、10节中默认两组输入的概述；不宣称current-only与官方两组图协议完全相同。

### 单页要求

和 Text Repair 对齐，再增加错误与正确截图

最新版核对：Image Repair 当前为 3,017 条，已有多页 defective/clean 图片补全记录；但对应 Text Repair 尚未达到 4–12 项，因此该项仍未完成。

### 多页要求

和 Text Repair 对齐，再增加错误与正确截图

最新版核对：多页 Image Repair 的存量逐页图片补全已完成，但“与 4–12 项 Text Repair 对齐”仍未完成。

与对应Text Repair使用同一个故障source、问题集合和修复patch，并额外给出：

- Current/defective截图：错误版本。
- Target/clean截图：正确版本。

### 8.1 数量、顺序、配对

- 单页典型1张defective＋1张clean，共2张。
- 多页完整覆盖P页时为P＋P；例如四页共8张。
- 官方消息顺序是**先所有current图，再所有target图**，每张图前写角色与文件名；不是依靠列表位置默默猜配对。
- 配对键应包含页面/route和状态；同一对使用相同viewport、相同操作起点及对应交互状态。
- 存储保留src/dst两组列表，实际序列化严格以`input_images`为准。前后对照发送两组；current-only只发送src。历史包的input_images可能只有defective，升级时明确选定变体，不能靠训练器隐式追加dst。

### 8.2 是否每页都必须有差异

**不是。** 未受影响页可以完全相同，不能因为某一对图相同而删除整条多页样本。

2026-08-24官方固定版本抽查：单页10/10有差异；多页10/10至少一页有差异，但40页中6页完全一致。该结果仅证明这20条的情况，不代表全量比例。[抽查证据](../../../reverse/docs/webcompass_official_repair_screenshot_difference_audit_20260824.md)

当前本项目视觉Repair补图要求：至少一个真实受影响页面/状态提供超过渲染噪声的可见修复证据。故障只在打开弹窗或筛选后出现时，应取该操作状态的图；纯语义、属性类问题可能没有静态视觉差异，可用于Text Repair，Image Repair资格需另行确认，而非硬造像素变化。

具体故障位置仍是隐藏答案；输入图片不统一增加“这里是bug”的红框或修复定位标注。Current/Target角色标识与泄漏缺陷位置是两回事。

## 9. 存储字段与真正送入模型的内容

下表依据本次读取的本地reversed v3六分片首条记录及当前打包代码。它解释现有字段，不要求重建一套schema；最新版本须核对其实际record和最终messages。

| 任务 | 用户需求/协议来源 | 输入代码 | 模型图片 | 答案 |
| --- | --- | --- | --- | --- |
| Text Generate | `instruction`字符串 | 无已有项目 | 无 | `response=[{path,code}]` |
| Image Generate | `instruction`通用说明＋角色映射 | 不输入GT | `input_images`的参考图 | 完整项目`response` |
| Text Edit | `instruction.description` | `instruction.src_code` | 无 | `response` patch列表 |
| Image Edit | `instruction`描述列表；历史 no-query 变体可为空列表 | `input_files` | 常规为 source 图；历史变体以 `input_images` 的 source/target 角色和顺序为准 | `response`/`patches` |
| Text Repair | `repair_instruction` | `instruction`文件列表 | 无 | `response` patch列表 |
| Image Repair | `repair_instruction`，新包同步到`instruction` | `input_files` | `input_images`：前后对照或current-only，见第8节 | `response`/`patches` |

特别注意：

- Image Generate中历史字段名 `src_screenshot` 也可以装目标参考图；“src”字段名不代表它是修改前网页。角色由任务语义决定。
- Text Repair的 `instruction` 不是自然语言query，而是代码列表；不能只读该字段而漏掉N和公共定义。
- `task_type` 在Edit中可以公开；Repair的具体标签只能留作隐藏元数据。patch中的附加 `task_type` 也不应拼入用户问题。
- `problem_statement`/隐藏checklist、验收断言、GT代码和GT patch属于内部材料。Repair的clean截图是明确允许的模型输入，clean代码不是。
- 只保存 `page_entry_mapping` 等metadata不等于模型看到了它；应核验最终消息包含必要图片关系和真实图片内容，而不只是本地路径文字。
- 资源文件与参考截图不同。字体/图片/CSS/JS等运行依赖按各来源资产规则处理；截图文件齐全不代表网页依赖齐全。历史包的外链问题不能因本次整理规范而宣称已解决。

### 9.1 图片映射与分辨率

现有映射字段包括：`page_entry_mapping`、`additional_page_mapping`、`interaction_mapping`、`interaction_sequence_mapping`，以及历史多组映射字段。至少应能还原“图片→页面→版本→状态/动作顺序”。

已有构造数据常用 `desktop_1920_full_page`；新Image Generate派生记录标为 `desktop_1440x900`，部分截图采用full-page因此实际高度可超过900。它们不是全项目统一分辨率标准，读图时以实际像素尺寸和capture配置为准。不要仅为统一尺寸重拍所有历史图片；同一对比/序列的一致性更重要。

### 9.2 答案序列化

Generate最终输出完整文件；Edit/Repair最终输出官方风格XML：

```xml
<search_replace path="src/App.vue">
<search>源文件中的精确原文</search>
<replace>替换后的代码</replace>
</search_replace>
```

search包含精确空白和缩进，一个块对应一组search/replace，多处或多文件修改使用多个块。官方Edit允许新增文件，此时search为空、replace为完整新文件。路径须与实际项目一致。

内部JSON patch可以继续保存 `{path,search,replace}` 等字段，但必须验证转成最终训练答案后仍能回放到正确target；字段存在不等于最终chat协议已经对齐。

### 9.3 Image-based Edit/Repair的只读渲染依赖（2026-09-08）

- 用户允许bundle、大型独立CSS/JS仅作为渲染依赖，保留文件或明确公共库绝对链接，正文不计模型代码40K，也不进入后续Image Edit/Repair输入。这是本项目显式变体，不改写官方全代码任务定义，也不自动派生对应Text记录。
- Mothers默认独立文件达到100,000 bytes或命中bundle文件名/打包特征时排除；仅minified文件名不代表bundle。它们可能含业务实现，不能声称是纯公共库。HTML和内联CSS/JS仍计入40K，不通过删代码、截断或重建绕过预算。
- 母本的 `project/render_dependencies.json` 列出每个排除文件的路径、来源、大小、SHA256、排除原因、`model_input=false`、`editable=false`。项目上一级的 `input_files.json` 和 `training_context.txt` 是模型输入，`training_context_manifest.json` 同时记录模型文件、排除文件、模型token与全部保存代码token。
- 后续构造、输入打包和Harness渲染必须分开：运行目录完整保留依赖；模型输入只取可编辑文件集合。排除文件不能成为patch、注错或修复目标，不能设计必须阅读/修改隐藏依赖才能完成的任务。改HTML或可见样式/脚本仍须参与实际回放，冻结依赖在source/target之间保持一致。
- 共享文件枚举/serializer尊重排除manifest；`construct_common.build_generation_data(..., image_based=True)`显式接收该变体并核验依赖哈希，默认全代码调用拒绝含此类依赖的项目。其他消费入口接入前也必须遵循manifest，不能将完整渲染目录递归拼回输入。
- 示例：两页HTML和小型业务代码8K，加一份大型样式表和bundle后全部代码90K → 输入仅8K代码、当前/目标截图按任务角色提供，渲染时加载完整90K代码 → 只修改可见HTML/CSS → 自动核对依赖SHA256不变、输入不含被排除正文，并回放编辑/修复效果。

## 10. 图文复用与当前校验范围

当前造数批次只执行数据格式/打包层和必要的文件级静态检查；不执行浏览器功能/语义验收层。不要把 `basic_pass`、截图生成、patch 回放或字段齐全表述成完整功能通过。

### 10.1 配对与同步

- Text/Image Generate共享正确GT；Image版本改成截图驱动输入，不简单复制Text长query。同一GT可以派生多种图片状态记录，不能假定永远一对一。
- Text/Image Edit共享source、编辑要求、target与patch；Image常规提供 source 图，历史已标记变体可提供 target 或 source+target 图。
- Text/Image Repair共享故障source、clean target及问题集合；Image额外提供两组图。Text-only问题不强行凑Image记录。
- 先修Text对应的代码/答案，再同步Image；未变版本复用已核验截图，变化版本和对应受影响状态需更新截图及映射。
- 配对不能只凭同ID：历史reversed审计发现过同ID不同缺陷/patch。应检查母本、source、target、patch和变体关系。

### 10.2 三种检查不能混为一谈

| 层级 | 做什么 | 能得出什么结论 |
| --- | --- | --- |
| 数据格式/打包 | 字段、图片路径、配对、patch回放、GT哈希 | 输入答案和文件组织是否一致 |
| 当前存量低成本validate | 代码可build、能基本正常渲染 | `basic_pass`，不代表完整需求都满足 |
| 任务语义/正式评测 | query–GT、实际功能、视觉与回归、隐藏checklist | 指定任务范围内的功能/质量证据 |

当前六类存量试跑以第二层为主：Generate检查target；Edit检查source和应用patch后的target；Repair主要检查clean target与patch关系，不能要求故障source先无错误，也不能把训练题本身的故障修掉后当作数据清洗成功。正常样本由脚本处理，LLM按代码修复需要调用，并非每条都送截图评分。

原先提出的query–GT对应、风格对齐仍是数据目标，但不是这轮build/basic-render试跑已经全面验证的内容。若以后执行query修复，用户已允许成本优先、将query改成符合正确GT；需要记录改动，不能把改query说成补齐了原要求的功能。

## 11. 已纠正的旧表述与待核实项

| 旧表述/风险 | 当前采用的口径 |
| --- | --- |
| 多页Image Generate固定“主页＋两个随机子页” | 这是官方部分样本形态；本项目覆盖GT全部真实页面，不裁GT |
| Image Edit可任选是否提供target图 | 常规对齐记录只给source；明确标记的历史 source_image、target_image、source_target_images 与 no-query 变体按原始 `input_images` 保留 |
| Repair提供逐条自然语言故障描述 | 给公共11类定义＋N，具体标签、位置和description隐藏 |
| 临时状态必须初始隐藏、只能弹层 | 已放宽为所有稳定可观察的同页状态转换 |
| 普通交互、临时状态天然互斥 | 范围重叠；区分主类别和独立记录计数 |
| 多页每张Repair前后图都要变化 | 未受影响页可相同，按真实affected页面/状态判断 |
| 4页等于4HTML | 按页面角色和真实导航；物理HTML是专项采样维度 |
| 生成了图片等于已合入且质量合格 | 分开记录候选、已写入、基础检查和完整任务验收 |

截至本次整理可确认的实施边界：

1. 2026-09-06增强v1已补6,366条Repair的公共定义＋N；本地v3首条仍为仅含N的旧prompt。不能从旧转换器推断新包缺prompt，也不能从新包字段推断训练器一定使用了它。
2. 2026-09-06增强v2已完成原有9条多HTML Image Edit和8条多HTML Image Repair的逐页补图；该项的字段、图片引用、分片哈希和非目标字段检查见[0906待办](../../../reverse/docs/reversed_edit_repair_training_regression_20260906.md)。新构造样本仍需单独通过页面语义与浏览器验收。
3. 普通多页截图分支的真实点击验证、部分SPA页面发现、最终六类训练messages序列化仍需结合所用版本核验。
4. Query没有统一强制字数，也没有为每类任务统一规定PNG/JPEG、所有截图尺寸或交互帧水印。未明确的实施细则先查WebCompass具体实现或问用户，不自行补规则。

## 12. 追溯来源

### 本次直接读取的其他任务

| 任务原名 | ID | 本文采用的内容 |
| --- | --- | --- |
| 检查reversed数据质量 | `019fe108-025a-7e92-a7a1-3ae6e42bc352` | 2026-09-06多页图片全覆盖确认、同页状态放宽、连续步骤、独立派生与历史结果保留 |
| WebCompass 六类任务解读 | `01a06aef-9f5f-7f00-93d8-18401f79152f` | 官方真实输入、隐藏字段、截图角色、patch协议 |
| 审查 validate 页面校验逻辑 | `01a06c6b-7b9d-7a13-89cf-5161b39215de` | 页面角色与HTML区别、Generate母本来源、官方类型与任务数补充批次 |
| 指令扩增方案&灵感整理（本任务） | `01a02fff-1b32-72e2-81c8-eff5b593ee60` | 完整Edit要求、减少套话、4–12条链与单记录任务数区分、六类基础validate与图文复用 |

早期聊天汇总已清理；本文只以以下源码、官方材料和仍保留的验证记录追溯，不把不可见历史补写成结论。

### 数据、代码与报告

- 官方：[WebCompass代码](https://github.com/NJU-LINK/WebCompass)、[数据集](https://huggingface.co/datasets/NJU-LINK/WebCompass)。本次直接核对本地官方副本：[消息构造](../../../evaluate/WebCompass/editing_repair/llm/mllm/mllm_chat.py)、[Edit/Repair协议](../../../evaluate/WebCompass/editing_repair/llm/mllm/prompt.py)、[Image Generate输入](../../../evaluate/WebCompass/generation/inference/image_to_web.py)。
- [六类输入差异审计](../../../reverse/docs/reversed_vs_webcompass_six_task_input_gap_audit_20260904.md)：官方2026-09-04图片数、query长度和真实样例；其中旧版现状以新报告为准。
- [官方Repair单页10条＋多页10条抽查](../../../reverse/docs/webcompass_official_repair_screenshot_difference_audit_20260824.md)：截图相同与不同的证据。
- [2026-09-06对齐与补充报告](../../../reverse/docs/reversed_edit_repair_training_regression_20260906.md)：最新MP图片审计、公共定义＋N更新及尚待完成项。
- [Image Generate输入计划](../../../reverse/docs/reversed_image_generate_input_refresh_plan_20260903.md)、[模块交接](WebCoding_Data/docs/handoffs/reversed_image_generate_refresh.md)：入口标注、状态帧、实例与历史版本变化。
- [v2记录构造](../../../reverse/v2_records.py)、[旧reversed输入重打包](../../../reverse/utils/repackage_reversed_webcompass_inputs.py)、[0805对齐包构造](../../../reverse/utils/build_0805_aligned_enhanced.py)、[Image Generate独立追加](../../../reverse/utils/apply_image_generate_overlays_in_place.py)：存储与模型输入边界。
- 本地原始schema抽查：`/tmp/reversed_v3_shards/`六个gzip各读取首条；只用于确认字段形态，不作为最新release全量结论。
- [六类低成本校验试跑](../../../reverse/docs/reversed_six_task_validation_pilot_20260905.md)：当前build/basic-render范围与图文配对策略。

Product Session不要求每条原子Edit独立创新：产品方向负责组合后的新用途。当前桥接设edit_originality_required=False，保留原创性原始分数作描述，不因常规功能/沿用原有风格而追加美化Repair；功能、设计质量、工艺、浏览器风险/回归、范围要求保留。

## 2026-09-13 Product Session出口

当前连续Edit主线保留全部原子Edit及自然Repair，另导出4–12个连续Edit的组合；4–12数量分布用官方频数采样索引对齐，不截断或丢弃补充样本。六类模型输入及页面/状态映射沿用本文1.3和7.1定义。实现、目录与数量策略见[当前构造流程](WebCoding_Data/docs/synthesis/pipeline.md#六类自动导出与子任务数量2026-09-13)。

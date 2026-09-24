# 六类 WebCoding 数据构造规范

本文是 reverse 路线的长期规则。当前 release 的数量、路径和验收状态以 release manifest 和实际运行证据为准；实现与本文冲突时，以构造代码、manifest 和实际运行证据为准。

## 1. 统一定义

数据以完整网页项目为单位，不以单个 HTML 文件代替项目。`source` 是模型输入的起点，`target` 是正确结果，`GT/response` 是从 source 到 target 的完整答案或项目文件。

六类任务：

| 任务 | 模型输入 | 答案 |
| --- | --- | --- |
| Text Generate | 文字需求 | 完整项目 |
| Image Generate | 目标截图及页面/状态说明 | 完整项目 |
| Text Edit | 完整 source 项目 + 增量需求 | source→target patch |
| Image Edit | Text Edit 输入 + 按角色排列的 source 图 | 同一 patch |
| Text Repair | 故障 source + 问题数 N + 官方公共定义 | 修复 patch |
| Image Repair | Text Repair 输入 + current/target 图 | 同一修复 patch |

Edit/Repair 的答案必须精确回放到 target。内部可保存 JSON patch，但最终训练消息使用官方 XML `search_replace` 协议；新增文件使用空 `search` 和完整文件内容。Generate 答案必须包含完整文件集合，不只保存单个页面。

## 2. 页面与项目口径

- 单页是一个页面级入口；Tab、弹窗、下拉、accordion 和局部筛选属于页内状态。
- 多页按页面角色、真实入口/route 和版本中的页面清单判定。截图张数、Tab 数或 HTML 文件数不能单独证明页数。
- Generate 可使用 SPA，但必须给出可到达且可核对的页面级 route/角色映射；物理多 HTML 是 Edit/Repair 专项母本的优先形态。
- 多页 Edit/Repair 同时保存 source/target 或 defective/clean 的页面清单及图片映射；新增/删除页面要分别核对两侧清单。
- 每条记录保留源码、资源、图片、页面清单、版本哈希和 lineage；不要只保留截图或单个 HTML。

## 3. 各任务构造要求

### Text Generate

需求应描述用户目标、页面角色、主要内容、对象、交互、状态变化和必要的页面间关系。多页需求必须明确入口、跳转结果及共享状态，并与完整 GT 对齐。不要用 benchmark 名称、工程协议或重复套话填充长度；没有统一字数阈值。

### Image Generate

截图必须对应目标项目的真实页面或可观察状态，并保存 `图片→页面→版本→状态/动作` 映射。可使用：

- 多页页面集合；
- 同页状态转换（如筛选、排序、菜单、表单反馈、主题/视图切换）；
- 连续操作序列，保留真实先后关系。

截图不要求每条固定数量或固定分辨率；同一序列应保持 viewport、滚动位置和动作起点一致。截图存在不代表网页资源闭包、行为或需求已验收。

### Text Edit / Image Edit

Edit 是从正确 source 到正确 target 的增量变化。每个 case 使用 4–12 个任务时，任务应是独立有价值的功能；允许前序状态依赖，但不能要求 source 已具备本次新增行为，也不能把多个独立能力压成一个无边界任务。Image Edit 与 Text Edit 共用 source、需求、target 和 patch；常规输入提供 source 图，明确标记的历史 source/target 变体按原 `input_images` 顺序保留。

### Text Repair / Image Repair

Repair source 必须真实包含待修复问题，target 必须恢复该问题并保留其他功能。训练输入只公开官方 11 类公共定义和问题数 N；具体类型、位置、描述、注入计划、clean 代码和 patch 细节是隐藏信息。N 按独立问题数计算，同一类别可重复，但不能重复计同一问题。

官方 11 类：Occlusion、Crowding、Text Overlap、Alignment、Color Contrast、Overflow、Sizing Proportion、Loss of Interactivity、Semantic Error、Nesting Error、Missing Attributes。

Image Repair 的 `input_images` 明确记录角色和顺序：标准模式为全部 current/defective 图后全部 target/clean 图；current-only 仅在已标记的历史变体中使用。未受影响页面可以相同；没有真实可见修复证据时不强造 Image Repair，应保留 Text Repair。

## 4. WebCompass 对齐口径

Edit 的官方 synthetic 类型为：Data Table、Rich Text Editor、Drag & Drop Interface、Tree View、Real-time Dashboard、Infinite Scroll、Async Form Validation、File Upload with Progress、Parallax Scrolling、Page Transitions、Particle Effects、Skeleton Loading、Shopping Cart、User Authentication、Multi-step Wizard、Notification Center。

每个 Edit/Repair case 的任务数按官方 4–12 范围构造：Edit 类型不重复抽样，Repair 类型允许同类重复。历史 1–3 项记录可以保留并明确标记，不为凑数量伪造任务。

Repair prompt 必须包含完整官方公共定义、N 和完整输出格式要求；不可把具体缺陷答案写进用户输入。Image Repair 在此基础上增加 `input_files` 和按角色排列的图片。

## 5. 字段与模型可见性

模型真正收到的内容以最终消息为准，不能因为路径或 metadata 在本地存在就声称模型看到了它。至少核对：

- Text Generate：需求；
- Image Generate：截图和页面/状态说明，不输入 GT 代码；
- Text Edit：需求和 `src_code`；
- Image Edit：需求、`input_files` 和实际 `input_images`；
- Text Repair：`repair_instruction`、N、公共定义和故障代码；
- Image Repair：以上内容及 current/target 图片。

具体问题标签、位置、隐藏 checklist、验收断言、GT 代码和 GT patch 不得泄漏。字体、图片、CSS、JS 等网页运行依赖与训练截图分开管理；如果使用 image-based 只读渲染依赖，必须保存排除文件的路径、大小、哈希和 `model_input=false` / `editable=false` 标记，且依赖不得成为 patch、注错或修复目标。

## 6. 图文复用与验收层级

- Text/Image Generate 共享正确 GT，但 Image Generate 可从同一 GT 派生不同页面/状态记录。
- Text/Image Edit 共享 source、需求、target、patch；只有受影响版本或状态才更新对应图片。
- Text/Image Repair 共享 defective source、clean target、问题集合和 patch；Text-only 问题不强行派生 Image Repair。
- 配对不能只凭 ID；必须核对 source、target、patch、母本版本和图片角色。

验收分三层，不能混称：

1. **格式/打包**：字段、图片路径、配对、patch 回放、GT 哈希；
2. **基础运行**：build、启动和主要页面渲染，可标记 `basic_pass`；
3. **任务语义/正式评测**：需求覆盖、真实功能、视觉、回归和隐藏检查。

基础通过不等于完整任务验收；候选、已写入、accepted、canonical 和正式发布必须分开记录。当前批次若只做格式或基础运行检查，不得写成“质量已通过”。

## 7. 发布前不变量

- 保留原记录语义、schema、ID、图片角色/顺序、GT 和 lineage；目录迁移不等于字段重写。
- 所有图片引用必须指向真实文件，禁止依赖软链接、外部绝对路径或临时目录。
- 每个 release 都有 manifest/index，记录分片、数量、哈希、图片根和版本；消费前现场核对，不能相信目录名或历史数量。
- 失败样本保留失败证据并与可训练样本分离；不因数量目标删除、注错或伪造 Repair。
- 发布、上传和覆盖操作遵循 `publish-dataset` skill，未获明确授权不得改变远端状态。

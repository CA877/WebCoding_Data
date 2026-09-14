---
name: synthesize-data
description: 构造、扩增、补充或审计 WebCoding 的 Generate、Edit、Repair 训练数据时使用；不用于仅规划连续 Edit 指令或单独发布数据集。
---

# Synthesize WebCoding Data

先确定用户请求涉及构造、扩增、审计还是问题定位；只读取该阶段需要的项目知识和实现。

造数批处理遇连接错误、网关超时或临时限流，只在原请求内有界退避重试；不因连续几个失败暂停供应商或整批，不重跑已完成阶段。耗尽后记录该样本失败，继续其他样本。鉴权/额度、明确实现故障、资源危险及用户取消单独处理；保留成功产物、请求尝试数、用量可见性、硬超时及指定并发。0905受控构造当前每请求最多5次尝试，具体阈值见当前运行说明。

## Canonical docs

灵感库先形成完整功能卡再批量生产：每张卡须具备与 WebCompass 16 类 Edit 相当的组件级或流程级任务粒度。同一组件和同一业务对象上的多个操作合成一张卡，例如表格的增删、选择、排序、筛选和分页不能按动作拆卡；只有不同组件系统或不同端到端流程才分卡。不得用静态说明或孤立属性补卡数；无完整功能时允许空结果并继续下一来源。来源输入（URL/本地项目）及输出 schema 保持不变。具体流程由下列灵感库构造文档维护；改动须真实浏览器＋LLM 小样本验证后再恢复批量。

- 当前流程与执行约束：[pipeline.md](../../../web-coding-agent/docs/synthesis/pipeline.md)
- 流程总览：[README.md](../../../web-coding-agent/docs/synthesis/README.md)
- 灵感库构造：[inspiration_library.md](../../../web-coding-agent/docs/inspiration_library.md)
- 正向构造设计：[forward_producer.md](../../../web-coding-agent/docs/forward_producer.md)
- 数据构造语义：[construction_spec.md](../../../validation/docs/data/construction_spec.md)

需要 WebCompass 类别或字段细节时，再读取本 skill 的 `references/`。先核验相关源码、manifest 和运行记录；文档只定义口径，不替代现场证据。遵循项目 `AGENTS.md` 的权限、验证和批处理边界。

只规划连续 Edit 指令时使用 `generate-edit-instructions`；只运行或调试独立 Harness 时使用 `run-webcoding-harness`；整理或发布已存在的数据集时使用 `publish-dataset`。

## 连续 Edit 的检查范围（2026-09-13）

检查流程从目标页面开始，只有本条Edit明确要求导航时才测试导航。每个不同的状态变化保留一个有区分力的结果断言；刷新或联动只在指令要求时执行。操作成功已证明控件可用，不再预先断言可见；不逐项检查复制的日期、地点、标签或占位文字，不对同一结果重复检查文字、可见性、数量和存储。

每条 Edit 仅一个连续 browser_check，在生成指令的同一次调用中产生。以实际用户操作验证本条指令明确要求的状态变化、相关功能联动和持久化；只在要求保存时检查刷新/重新打开，只在要求联动时操作相关消费界面。可初始化前置数据，但不能预先写入本次行为的期望结果。删除不证明状态变化的标题、标签、容器和种子文本断言，避免重复检查同一结果；不追加全站检查、历史回归或独立审核模型。Harness 在这条操作流程涉及的实际网页和相关交互状态，检查适用的 WebCompass 11 类缺陷：Occlusion（遮挡）、Crowding（拥挤）、Text Overlap（文字重叠）、Alignment（对齐）、Color Contrast（颜色对比度）、Overflow（溢出）、Sizing Proportion（尺寸比例）、Loss of Interactivity（交互失效）、Semantic Error（HTML语义错误）、Nesting Error（嵌套错误）、Missing Attributes（属性缺失）。复用既有确定性浏览器检测，按目标区域和状态去重；不可到达的状态不编造缺陷。一次检测收集全部可观察的真实问题，保存类别、节点/测量值、截图和失败证据；剔除源码中同样存在的旧问题。多个类别或同类多个问题合并为一次 Repair 调用，随后复跑原功能流程和同一组缺陷检查；仍失败则记录失败，不追加第二次 Repair。自然 Repair 数量由真实失败及修复成功决定。

表单值优先使用 assert_value；assert_text 对 textarea/文本输入读取当前 value，对 select 读取选中项显示标签，对普通文字节点读取 textContent。等待与结果记录使用同一读法，不用HTML默认文字替代空值或错误当前值，避免因合理的控件实现差异制造 Repair。

## 逐步 Generate（2026-09-12）

自主 Session 对每个已验收状态 S1–SN 各合成一次独立完整建站需求，绑定对应完整源码、状态编号、源码哈希和已完成 Edit 前缀。下一步前由数据出口保存 Edit、Generate 和符合证据的自然 Repair；恢复时补缺并去重，终态不额外重复 Generate。训练用 Generate 输入仅为独立需求，不含 Seed 代码或未来计划。连续 Edit 指令仍一次调用生成，Generate 需求合成单独计量。

自然 Repair 的Harness修复调用使用同一次检测的具体失败证据；最终WebCompass训练输入仅使用公共11类定义、问题数N和故障源码，具体故障说明保存在隐藏元数据。

代码响应已完整保存、尚未应用时，格式适配后的恢复复用该响应；精确替换字段的等价结构可程序归一化，不改变补丁文本或猜测未知操作。每条 Edit 的代码生成仍只有一次，回放失败不追加生成调用；网页检查发现的问题仍最多一次 Repair。

assert_text 的 contains 模式按互不包含的最外层匹配区域读值，避免卡片与内部按钮共用属性时对同一内容重复断言；独立匹配区域仍逐个要求满足，exact及计数语义保持原规则。浏览器证据记录策略版本；修正检测器后，恢复仅复测原失败轮现有源码，保留旧grade/证据/状态，不追加生成或Repair。

桥接到Harness时，把本条Edit的全部completion_criteria完整合并为一个exit_criteria条目；原列表保留在链元数据中。一个功能Edit仍只绑定一个验收条目和一个连续browser_check，不因旧Planner的10条列表限制中断，也不截断用户要求。

## Edit 生成输入约束（2026-09-12）

Edit指令生成输入包含Seed简短介绍、主任务转变方向、召回的top-k灵感、当前浏览器信息和简短Edit记录。动态字段为seed_introduction/task_transformation/retrieved_inspirations/browser/edit_records，禁止传入整库、当前网页源码、完整执行日志或校验器源码。先按产品方向和实际状态做语义Top-K召回，默认k=3（可配置）；当前使用TokenWave gpt-5.5语义排名，召回与单次Edit生成分别计量。仅传所选卡的行为信息和相关性理由；多页信息来自各HTML页的真实观察，历史每步仅保留edit_id与一句功能摘要summary，直接复用已有capability，不传完整指令、代码或依赖展开，不追加摘要模型调用。代码修改与逐步Generate仍按各自接口消费源码。请求身份绑定输入策略和k，恢复复用同一状态的已有响应。

默认返回Top-3灵感；召回和Edit生成仅使用行为信息。待本条Edit确定inspiration_refs后，在交给Harness时按这些实际引用读取库内source_slices，不把全部召回卡的代码前置输入。相同代码按内容哈希去重；没有代码的引用记录为unavailable，不补造代码。参考片段只供Harness实现模型按需借鉴，不作为目标源码或额外要求，训练Edit指令仍不含参考代码。

## Seed背景与主任务转变（2026-09-12）

每条Edit Prompt显式包含seed_introduction（原Seed的简短产品介绍）和task_transformation（original_primary_task、target_product、target_primary_task、task_reversal）。主任务转变以原Seed的用户任务为起点，说明如何转向已确定的目标用户任务，不能把灵感来源产品当作Seed。自然语言保持简短，不传Seed源码或冗长执行元数据。

新Session在原有方向选择调用中同时生成这些介绍，不新增规划调用；旧Session缺失时只根据原Seed浏览器观察与已选方向补齐一次并保存product_context，保持既定目标不变。每一步直接复用，Edit历史仍是编号与一句功能摘要。Generate与Harness的源码输入沿用各自接口。

## 步数约束与批次失败隔离（2026-09-12）

方向选择接收已均匀抽取并保存的edit_count，要求目标在N个单能力Edit内形成有用的新产品；按步数调整目标范围，能力继续逐步产生。

产品Session批量入口隔离单Seed的内容、格式、局部超时及验收失败，保留成功前缀和失败证据后继续下一Seed；全部派发结束记completed或completed_with_failures并记录成功/失败数。鉴权/额度、API有界重试耗尽、明确运行时或数据完整性故障和用户中断暂停整批。session_failure.json记录当前失败范围与证据，batch_state.json保存各Seed结果；恢复忽略旧尝试的失败标记。

target_routes和browser_check若只放错到顶层，可等价移回edit；内外字段冲突或未知字段仍按原规则拒绝，保存规范化证据并复用模型响应。Harness解释器保留虚拟环境入口的绝对路径，不解析Python符号链接到基础解释器。

## 六类自动导出与子任务数量（2026-09-13）

每个已验收状态导出 Text/Image Generate；每次成功 Edit 导出 Text/Image 原子 Edit；同一轨迹额外导出所有长度为4–12的连续 Edit 窗口。N步链的组合数为 sum(N-k+1, k=4..N)，8步为15条组合，12步为45条组合；原子记录全部保留，组合输入按时间顺序列出原指令，源码取窗口起点，答案为起点到终点的可回放净patch。窗口内允许前序能力依赖，新增文件使用官方空search格式。

自然Repair保持同一故障版本→一次Repair→复测通过。问题数按独立问题计，不按类别去重，不把同一问题的多状态检测重复计数；不同控件的属性缺失分别计项，共享根因的布局症状由同一次Repair响应分组，绑定具体失败位置。同一故障修好的全部问题完整导出，1–3项或超过12项保留在补充池；不跨版本拼故障、不为配额注错。训练Repair公开输入为官方11类公共定义＋N＋故障源码，具体故障说明、位置和标签仅保留在内部元数据及Harness修复输入。

Image Generate仅输入目标图和页面/状态说明；Image Edit仅增加source图；Image Repair顺序为全部current图→全部target图。图片必须来自相应Git版本，使用整页截图覆盖项目所有HTML页及本条已有流程涉及的状态。属性/语义修复没有可见变化时保留Text Repair，并在image_skips记录原因；不制造视觉差异。图与源码通过哈希、页面清单和交互映射绑定，原始资源随版本保存。图片路径相对六类出口根目录解析。

出口是dataset/six_tasks/dataset_index.json；仅消费该索引指向的六类不可变JSONL分片，不glob目录中的历史分片。每行含messages、images/input_images、response及隐藏metadata，Edit/Repair答案为官方XML search_replace，Generate答案为完整项目Markdown。图片/资源按内容版本缓存，恢复校验哈希后复用，最后原子更新索引。

按官方600条Edit/Repair的实际4–12项频数保存sampling索引；单页/多页各占官方任务的50%。保留全量样本，并为数量对齐部分计算权重；批入口汇总所有Session后重新计算全局权重和缺档。数量对齐与16/11类标签对齐分别标记，扩展Edit类别保持原标签。原子补充池与对齐部分的训练混合比例由消费侧配置，当前不丢数据、不强制抽样。由同一原始源码派生的样本共用lineage_group，训练/验证按组划分。官方频数和源文件SHA在Harness的src/orchestration/webcompass_subtask_distribution.json。

# reversed 训练后的 Edit / Repair 退化与调整方案

> 0905 的数据检查策略、已实施证据与未覆盖范围统一见 [0905 数据检查策略与实施记录](reports/0905_data_check_strategy_implementation_20260912.md)。本报告保留生产缺口、版本演进和回归方案。

## 今日逐项处理清单与新版本交付（2026-09-06）

本次 Image Generate 来源补充已完成：从 `0805_supplement` 纳入 Vision2Web L1/L2、Flame-VLM-Code、Interaction2Code，共427条记录和427张实体图。导入前 API 批次已完成并释放共享锁，目标 release 未覆盖已有 ID，GT 哈希保持不变。

21:10 从 0805_supplement 直接补入 1,502 条 WebCompass 语义多页 Text Generate 及其 487 条对应 Image Generate，GT 保持不变。合并时两类数量为 10,596/10,551，新增 2,012 张图；新增/旧行、ID、图片引用和索引哈希验证全部通过。该批 Generate GT 可作为后续 Edit/Repair 母本，是否进入 accepted 母本池仍按网页验证结果决定。

18:50 用户调整 Image Generate supplement 新增池最低目标为：多页 1,988、普通交互 1,500、临时状态 500、连续操作 500。多页 1,988 完成；普通交互全量得到的 1,723 条全部纳入，超过最低量 223。API 按 500/500 续跑同一个 manifest，当前 supplement 实时计数 transient 200、sequence 114；4 并发、最多 5,000 次、零重交，达标自动结束并完成最后合并。当前正式 release 分片 9,571 条 Image Generate、六类合计 31,041 条；API 运行中尚未分批写入的通过项另计。

18:20 扩批口径更新：原 0805 的 5,094 条 Image Generate 及已合入的 1,500 条普通交互继续保留；后续新增母本全部来自 `0805_supplement`。四类最低量按 supplement 新增池单独核算：多页 2,000、普通交互 1,500、临时状态 2,000、连续操作 2,000。已迁回 supplement 存量 2,195 条（1,988/0/174/33）和 API pilot sequence 1 条。16 API 并发命中 TokenWave `gateway_concurrency_limit`，19 个提交中浏览器通过 5 条并已合并，随后不重交这些母本；续跑改为服务允许的 4 并发。当前包 29,238 条、Image Generate 7,768 条。普通交互继续 16 并发全量扫描；API 单条无能力、计划格式或截图失败只记录并继续，不再触发整批质量门禁，仍保留人工 STOP、22 小时和 5,000 母本硬上限。

目标：以 ckpt-622 对应的 0805 为基础，在已完成的 `0805_webcompass_aligned_20260906_v1` 上逐项补齐，最后统一交付一个新的六任务数据集。沿用六目录、每类单 gzip JSONL 和实体图片布局；每完成一项更新本表的数量、验证证据和状态。

| 顺序 | 优先级 | 待解决问题 | 当前基础/缺口 | 完成条件 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | 高 | 迁回已有 Image Generate 改善 | 原 0805 同 GT 的 237 条图片更新、472 条独立派生记录（109 临时状态＋363 连续操作）可复用 | 核对图片角色、顺序、引用与 GT，处理重复说明；合入通过记录并登记实际数量 | 存量已合入 v2，普通交互 1,500 条覆盖；新批次 1 次调用、1 条回放通过并追加，总 27,037 条；余 19 次暂停 |
| 2 | 高 | 多页 Image Edit/Repair 图片覆盖 | 原有 9 条 Image Edit 和 8 条 Image Repair 已补齐 | 全部多页记录覆盖所有物理页面；Edit 只给 source，Repair 给逐页 defective/clean | 已完成 |
| 3 | 高 | 官方类型的 SP/MP 复杂组合任务 | 8–12 项整条白名单合格候选为 0；多页数量不足 | 补充仅含官方 16 类 Edit/11 类 Repair 的单页、多 HTML 多页组合；覆盖 4–12 项，重点 8–12 项；记录生产数量与真实验证 | 用户确定四组各 1,000；0805 分布已核对，待多页母本扩充/复用策略与真实 pilot |
|   |
|  |
| 4 | 高 | Text Generate 来源与多页母本覆盖 | supplement 已完成多 HTML 盘点；当前已合入 1,502 条 WebCompass 语义多页 Text Generate，WebGen-Bench/InteractWeb-Bench 的全量纳入与验收仍未完成 | 从 supplement 纳入三类来源；完成去重、需求–GT 对齐、页面/导航、资源和浏览器验收；合格后才能作为 Edit/Repair 母本 | 多 HTML 盘点已完成；来源分布为 ArtifactsBench 541、InteractWeb-Bench 57、DesignBench 10、WebCompass 9、WebGen-Bench 8；三类来源的定向纳入与 accepted 判定待完成 |
| 5 | 高 | Image Generate 物理机运行、来源补充与多页入口映射 | 已有物理机受限运行和 1,988 条多页候选；新增来源已从 supplement 筛出 | 物理机生成真实截图；主页彩框编号对应真实可点击入口和子页图；各状态序列按原 GT 动作回放并登记结果；目标来源 query/图片/GT 进入 0805 release | 427 条已合入：Vision2Web L1/L2 141、Flame-VLM-Code 143、Interaction2Code 143；Image Generate 10,765→11,192，427张图闭包通过；完整回放验收仍待完成 |
| 6 | 中 | 0805 Edit 低频类型与 4–12 项补充 | 已完成 0805 子任务数量、多 HTML 母本和低密度分布统计；0805 Edit 仍全部为 1–7 项 | 按低频类型定向补充单页与多 HTML 多页，新增任务覆盖 4–12 项；Text/Image Edit 共享 source、query、target、patch，并完成浏览器与非目标回归 | 统计已完成；候选构造和真实 pilot 待完成 |
| 7 | 中 | 0805 Repair 低频类型与 4–12 项补充 | 已完成 0805 Repair 子任务数量、多 HTML 母本和低密度分布统计；0805 Repair 仍全部为 1–7 项 | 按低频类型定向补充单页与多 HTML 多页，新增任务覆盖 4–12 个问题；Text/Image Repair 共享故障 source、问题集合、patch 和 clean target，并完成缺陷范围与浏览器检查 | 统计已完成；候选构造和真实 pilot 待完成 |
| 8 | 中 | Generate 需求与领域覆盖收尾 | 页面角色、交互状态、响应式要求及领域分布已有来源统计，但完整语义与资源审计未完成 | 先统计与抽查，再对实际缺口定向补充；核对运行资源可用性，并把合格 Generate GT 纳入 accepted 母本池 | 来源与多 HTML 初盘已完成；语义、资源和 accepted 判定待审计 |
|   |

执行口径：保留已经带来收益的 0805 基础；新增 Edit/Repair 按整条官方类型筛选。任务数、物理多页数、图片类型分别统计。已有候选优先复用，新增生产先做真实小样本并明确数量与费用。各项验收采用与修改风险匹配的现有检查。

新版本命名与最终数量在收尾时登记；未完成项保留状态，不计入已交付能力。

### 用户新增要求的当前进度（2026-09-06）

- 已完成：统计 0805 的 Edit/Repair 子任务分布、8–12 项缺口和多 HTML 母本规模；结果显示 0805 的 Edit/Repair 均为 1–7 项，后续补充不能只依赖原 0805。
- 已完成：盘点 supplement 的 Generate 多 HTML 母本，Text Generate 632 条、Image Generate 297 条；这些记录仍需逐条核对页面语义、真实入口、资源和浏览器行为后，才能作为 accepted 母本。
- 已进行：物理机上的 Image Generate 受限运行、主页入口映射和状态类候选生产；已有合入记录不等于所有状态类别和所有页面入口均已完成正式验收。
- 已完成：从 supplement Image Generate 导入 Vision2Web L1/L2、Flame-VLM-Code、Interaction2Code；合计427条、427张图，目标 release 为 `/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`，导入前后为10,765/11,192。
- 待完成：从上述统计和母本盘点出发，分别构造 Text/Image Edit 与 Text/Image Repair 的单页、多 HTML 多页 4–12 项任务，并按同一 source/query/target/patch 或 defective/clean 关系完成配对验证。
- 待完成：将 WebCompass、WebGen-Bench、InteractWeb-Bench 的 supplement Generate 来源完成定向纳入、去重、query–GT 对齐和 accepted 判定；当前已合入的 1,502 条是 WebCompass 语义多页补充，不代表三类来源全部完成。

### 第 2 项：多页 Image Edit/Repair 图片覆盖现状（2026-09-06 20:00）

2026-09-06 20:37 已完成。使用 `scripts/complete_0805_mp_edit_repair_images.py`，不调用 LLM，直接从正式记录的 `input_files` 重建页面并截图：9 条 Image Edit 共得到 21 张 source 图，8 条 Image Repair 共得到 18 组 defective/clean。正式 release 仍为 `/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`；缓存和修改前备份位于 `runs/0805_mp_edit_repair_image_completion_20260906/`。

最小验证：Image Edit 3,005 行、Image Repair 3,017 行；仅 9/8 条的截图字段和相关 metadata 变化；所有多页记录截图数与物理 HTML 页数一致，图片引用缺失 0，两个分片哈希与 `dataset_index.json` 一致，其他训练字段保持不变。

严格按 `input_files` 中至少两个 HTML/HTM 统计，增强 v2 有 14 条 Image Edit 和 25 条 Image Repair。此次从 supplement 新增的 5 条 Edit、17 条 Repair 已按每个 HTML 配齐图片；缺口只在原 0805 的 9 条 Edit 和 8 条 Repair。

WebCompass 当前官方 `mp` 原始数据全量核对：Edit/Repair 各 150 条，每条均为四个 HTML。两类各有 144 条提供四页图片；另外 6 条只提供 about/index/services 三页，统一缺 contact。即官方主流口径是全页面覆盖（96%），但不是绝对 150/150。Image Edit 的 `dst_screenshot` 全部为空；Image Repair 的 source/target 数量逐条相等，144 条为 4+4、6 条为 3+3。官方消息构造器会遍历并发送记录中列出的全部 source 图，Repair 再发送全部 target 图。

- Image Edit 缺口 ID：`webcode2m-natural-prompts_4576`、`webdev_1958`、`webdev_582`、`artifacts_1376`、`WebGen-Bench.prompt_3660`、`webdev_1037`、`webdev_4875`、`WebGen-Bench.prompt_2875`、`webcode2m-improved-prompts_3681`。这些项目有 2–4 个 HTML，但模型输入只有首页 source 图。v4 已为九条生成逐页 source 图；其中五条 render-ok，可核验后迁回，另外四条标记 render error，需重新渲染或确认错误页，不能只按文件存在接收。
- Image Repair 缺口 ID：`webcode2m-natural-prompts_4576`、`webdev_4875`、`WebGen-Bench.prompt_2875`、`webcode2m-improved-prompts_3681`、`webcode2m-improved-prompts_1810`、`artifacts_292`、`artifacts_1538`、`webdev_2781`。这些项目有 2–4 个 HTML，但只有首页 defective 图和首页 clean 图；v4 没有补 Repair。

补齐口径按 WebCompass：Image Edit 的模型输入提供全部可用页面的修改前 source 截图并保存 `page → path` 映射，target 图仍是生产验收材料，不作为模型输入；Image Repair 提供全部可用页面在同 viewport、同状态下的 defective/clean 配对。页面确实无法获得有效截图时允许像官方少量样本一样显式缺失，但不能把“多页项目仅给首页图”作为正常完成状态，也不刻意复刻官方 4% 的缺页异常。未受缺陷影响的页面允许前后相同，但至少一个真实 affected page 必须有高于渲染噪声的可见差异。若缺陷只在弹窗、筛选或其他交互后出现，则该交互状态而非静态首页才是对应截图。

### 第 3 项：候选与代码准备（2026-09-06）

- 母本来源修正：按用户要求统一从 Generate 的正确 GT 选择。下面早期从 Image Edit/Repair 分片取母本的 v1 清单仅供追溯；新生产以本节后的 Generate 盘点为准，计划构造器的旧来源读取逻辑待调整。
- 0805 生产 Edit/Repair 代码已定位并用本地 Git tag `webcoding-sft-v2-20260805-edit-repair-producer` 固定到提交 `60a243542f63031d9020455fd86e7b89f897a248`；当前实现从该基线继续支持 8–12 项、物理多页和新 ID 前缀，不覆盖历史快照。
- 当前 `webcompass` Edit profile 已收紧为官方 16 类；Repair 新增官方 11 类 profile，并按官方数据允许 12 项任务中重复缺陷类别。重复类别必须描述不同问题，且每个问题至少对应一个 patch。
- 用户更新成功目标：多页 Edit/Repair、单页 Edit/Repair 四组各 1,000，共 4,000 个任务实例；全部配对通过时对应 8,000 条 Text/Image 记录。子任务数量按固定官方版本的各组实际频数，用最大余数法缩放；单页先限制为 8–12 项再归一化。
- 多页候选只收至少两个物理 HTML/HTM，优先四 HTML；SPA 不进入本批多页清单。单页只收一个 HTML 且原记录标记为 SP。当前缓存全池母本为 Edit MP/SP 194/1,200、Repair MP/SP 292/1,721，全部来自 `0805_supplement`。多页达标需要扩大母本池或同母本派生不同组合，策略待确认；母本数与成功任务数分别统计。
- `datasets/0805_webcompass_edit_repair_plan_20260906_v1/` 保留为历史各 150 的候选计划，共 1,086 个尝试位；新版 v2 工作清单待母本策略确定后生成。
- 物理机只读核验 1,086/1,086 个源码目录及 canonical 截图清单存在。当前第 1 项 Image Generate 服务仍运行，因此尚未同步代码、调用 API 或生成 Edit/Repair 训练记录；批量入口会先拒绝与 Image Generate 并跑，并要求四支线 pilot 通过。

| 每实例子任务数 | 多页 Edit | 多页 Repair | 单页 Edit | 单页 Repair |
| --- | ---: | ---: | ---: | ---: |
| 4 | 120 | 107 | — | — |
| 5 | 147 | 113 | — | — |
| 6 | 93 | 113 | — | — |
| 7 | 140 | 80 | — | — |
| 8 | 93 | 87 | 173 | 185 |
| 9 | 73 | 127 | 160 | 210 |
| 10 | 134 | 120 | 222 | 222 |
| 11 | 93 | 140 | 235 | 173 |
| 12 | 107 | 113 | 210 | 210 |
| 合计 | 1,000 | 1,000 | 1,000 | 1,000 |

### Generate 多 HTML 母本盘点与重新生成建议（2026-09-06）

真实试产：用户批准先试 10 条、API 并发 1，并明确使用 TokenWave。首条 Harbor Fix 四页需求使用 `gpt-5.5`、零自动重试、最多 24,000 输出 tokens、600 秒请求超时，服务硬限 900 秒/2 GiB/1 CPU。首次非流式请求在 60.24 秒返回 nginx HTTP 504，代码产出 0、usage 未返回，服务已停止。已提前固定 9 组浏览器验收要求；本地改为流式 Responses 并要求完整终止事件，41 项生成解析与提交保护测试通过，真实重试待授权。独立运行根为 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/generate_multi_html_tokenwave_trial_20260906_v1`，生产入口 `scripts/run_generate_multi_html_trial.py`；本地回执见 [`tokenwave_trial_receipt.json`](../logs/generate_multi_html_inventory_20260906/tokenwave_trial_receipt.json)。首条验收后再决定其余 9 条。

API 选择纠正：此前误用旧 Doc API 提交 1 次 Qwen 请求，已停止本地服务，尚无返回结果，远端计费未知；保留在 `runs/generate_multi_html_trial_20260906_v1` 追溯。当前入口仅使用 TokenWave Responses，凭据由既有受保护配置注入。

来源：物理机 `releases/0805_supplement` 的 Text/Image Generate 两个完整分片。候选清单见 [`candidates.jsonl`](../logs/generate_multi_html_inventory_20260906/candidates.jsonl)，统计见 [`summary.json`](../logs/generate_multi_html_inventory_20260906/summary.json)。Text Generate 项目的绝对路径由 summary 的 `project_roots[project_root]` 与 `project_name` 拼接；Image-only 项直接记录 `source_project`。

- Text Generate 有 632 个多 HTML GT：2/3/4/5 HTML 分别为 44/139/409/40。
- Image Generate 有 297 个多 HTML GT；与 Text Generate 按完整代码内容去重后，共 635 个 GT 版本、633 个源码项目路径。额外 3 个 Image GT 版本需核对与 Text GT 的差异，不能直接当作 3 个全新母本。
- 本次清单限定多 HTML 结构；各页面的语义差异、导航、功能和资源仍需验证后才能作为 accepted 母本。此前六分片并集 638 个版本混入了 Edit/Repair，已退出母本统计口径。

代表样本（页面文件已确认，功能待复核）：

| Generate ID | 主题 | HTML 文件 |
| --- | --- | --- |
| `gen14-webcompass-wc-1-00281` | 天文台观测、历史档案、社区报告与参观 | `index.html`, `archive.html`, `community.html`, `visit.html` |
| `gen14-webcompass-wc-5-00182` | 野外厨房物资录入、布局、分析与报告 | `index.html`, `layout.html`, `analysis.html`, `report.html` |
| `gen14-artifactsbench-ab-2-00230` | 移动服务车辆地图、预约与服务进度 | `index.html`, `booking.html`, `session.html` |

需求分布：632 条中 ArtifactsBench 541、InteractWeb-Bench 57、DesignBench 10、WebCompass 9、WebGen-Bench 8、FronTalk 7。从导出 instruction 中仅提取 `<user_request>` 内的需求正文，其中位数为 1,485.5 字符；本地固定官方 Text Generate 123 条 instruction 的中位数为 6,700 字符。当前 9 条 WebCompass 风格正文中位数为 8,510，说明主要差距是来源构成与明确需求覆盖，并非每一条都太短。原始需求例子见 [`query_examples.json`](../logs/generate_multi_html_inventory_20260906/query_examples.json)。

对齐依据：官方 [数据集](https://huggingface.co/datasets/NJU-LINK/WebCompass) Text Generate 样例 `100` 明确描述页面职责、筛选排序、库存限制、购物车刷新保留、结账状态和视觉细节；隐藏评测逐项检查操作与结果。当前 `generate_webcompass_style_queries.py` 同时要求三段式需求，又禁止 WebCompass 的具体尺寸、时长、百分比和字体，和官方样例存在可核实差异。新生产应参考实际样例，取消无依据的描述限制；后端能力以本项目的本地模拟范围实现。

额外候选：现场核对 `physical_mp_calibration_50_20260829_v1` 保存 47 个生成项目、28 个旧 v6 浏览器通过项；`physical_mp_production_calibration_300_20260830_v1` 实际已运行 22 条日志、保存 19 个项目、8 个旧 v6 通过项。旧“300 条尚未执行”文档已过时。这些项目属于独立实验目录，与正式 Generate GT 的去重、源码版本与语义验收待核对，暂不加入 635。

建议按以下顺序推进：

1. 从 Generate GT 复核现有多 HTML 母本，优先四 HTML；保留正确且需求充分的项目。
2. 对 GT 已有充分功能但 query 描述不足的样本，基于源码和浏览器事实补写 query，并保留独立版本；新增要求超出现有 GT 时，重新生成 GT。
3. 新造样本以 WebCompass 的内容、交互、视觉三部分为参考，明确页面职责、跨页数据传递、异常与恢复、移动端和视觉层级；四 HTML 是本批母本的工程选择，不作为 WebCompass 的通用页面定义。
4. 建议先做 10 条真实新生成试产，再决定新增 Generate 配额与费用。通过 query–GT、直接页、跨页操作和资源验证后，才派生 Edit/Repair；四组各 1,000 目标保持。

完整设计例（待生产）：原移动服务预约需求 → 扩成地图首页、车辆详情、预约、服务记录四页，具体说明车辆/时段传递、冲突后保留表单、预约刷新保留、服务完成后才能评价及移动布局 → 重新生成四 HTML 与共享资源 → 自动检查首页选车进入正确详情、预约正确车辆/时段、冲突阻止提交但保留输入、刷新后记录一致、完成前后评价按钮状态及四页直接访问；再由浏览器和语义检查验收。新功能不能仅写入旧 query 而沿用未经修改的 GT。

### 第 1 项：TokenWave 调试结果（2026-09-06）

批次结果（18:07）：首个母本 `WebGen-Bench.prompt_4555` 的请求 HTTP 200/completed，21,005 tokens；模型把 `visible` 与文字值写进同一断言，触发严格校验停止。将该组合无损拆成“可见＋文字匹配”两项，18 项测试通过；使用保存回答零 API 回放，sequence 1/1 通过，四图（主页→登录面板→服务列表→VPS 详情）及原 GT 已独立追加。Image Generate 5,567 条、全包 27,037 条；独立 transient 109、sequence 364。`runs/0805_image_generate_replay_20260906/heartbeat.json` 为 finished、in_flight=0、unmerged=0。付费批次余 19 次暂停，恢复需确认；未重试已付费母本。恢复时使用原 batch 的 submitted 记录避免重复提交。

本轮合并：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2` 继承 v1 六任务结构。迁回 237 条原记录输入更新和 472 条独立衍生记录；历史普通交互 1,500 条中 182 条已有、1,318 条本次补入原记录，引用缺失 0。调试的两个 `(mode,parent)` 已有独立行，因此其六张新图补入母本输入，不增加独立样本计数。新 API 结果仍按独立行追加；上限 20 次、并发 1、零重试，低于既有 80% 截图门槛时停止。批次根：`runs/0805_image_generate_batch20_20260906`。合并保留所有 GT；17 项相关测试通过，迁移先通过真实双记录 pilot。

- 用户授权先调试 API。使用 TokenWave `gpt-5.5`、并发 1、零自动重试：1 次最小探针＋2 次有记录的源码规划请求，共 65,296 tokens（服务端回执）。正式数据包仍为既有版本。
- 传输改为 curl `--data-binary @request.json`，授权头通过 stdin 注入。12 项测试通过，含大段 Unicode/换行/引号请求的真实本地 HTTP 正文完整性测试。真实探针 HTTP 200/API_OK，随后约 102 KB 的源码请求两次均 HTTP 200，旧 400 根因仍未获因果确认。
- 第一轮模型把临时状态前后条件混进 start，steps 为空，被验证器拒绝。增加 steps 最少 1 项和明确的 before/after 阶段约束后，第二轮同母本 `webdev_814` 的 transient 与 sequence 均通过真实 Chromium 回放。
- 临时状态：编辑器初始页 → 命令面板打开，2 图；连续步骤：编辑器 → AI Chat → 显示单元测试建议 → Apply 后编辑器内容更新，4 图。Codex 已查看前后及中间截图；代码内容变化发生在网页模拟编辑器中，训练 GT 源码保持一致。
- 两条候选已复用独立记录导出器导出：通用截图生成指令＋图像角色说明、独立 ID 与图片路径、原 GT。调试运行根 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/image_generate_debug_20260906_v2`，候选位于 `candidates/image-generate/candidate_records.jsonl`。服务已结束。
- 本地证据：`logs/image_generate_debug_20260906/`；[命令面板打开前](../logs/image_generate_debug_20260906/transient/webdev_814/frame_00.png)、[打开后](../logs/image_generate_debug_20260906/transient/webdev_814/frame_01.png)、[连续操作完成](../logs/image_generate_debug_20260906/sequence/webdev_814/frame_03.png)。1 个母本的成功不能作为批量通过率；下一步先处理已有迁回候选，再逐步校准新增 API 规划。

## 0805 后续缺口与 Image Generate 现场状态（2026-09-06）

### 重要修正：0805 Edit 原本就是扩展类型

现场全量统计原始 0805：Edit 覆盖 40 类（含官方 16 类），每模态 3,000 条中 2,717 条至少含一项官方清单外类型，仅 283 条整条属于官方类型。原始 Text/Image Repair 则分别 3,332/3,000 条全部属于官方 11 类。新增数据的严格白名单规则只应用于 supplement，基础 0805 按用户决定完整保留。

因此，已有效的 0805 Edit 本身也是混合类型；“类型增加导致退化”是待验证原因，不能仅凭清单差异归因。后续优先补官方类型的高密度和物理多页组合，保留已有有效基础。

### Image Generate 扩充进展

现场 v4 正式分片共 10,773 条：原记录 10,094，独立 transient 283，独立 sequence 396。文件最近修改时间为 2026-09-05 16:59；API 心跳为 stopped、in_flight=0、unmerged=0，当前相关 user services 无运行项。

| 类型 | 正式 v4 情况 | 进度解释 |
| --- | --- | --- |
| 多页 | 2,000 条有 `page_entry_mapping`，2,022 条带 multi_page 标签 | 2,000 条入口映射已写入；标签数和入口标注数采用不同口径 |
| 普通交互前后状态 | 335 条带 same_page_interaction_states 标签 | 历史 manifest 有 1,500 条 status=ok 结果，不能将候选数当作正式写入数 |
| 临时状态 | 独立 283 条；含历史重叠标签共 386 条 | 按独立样本目标 2,000，尚差 1,717 |
| 连续操作 | 独立 396 条；含历史重叠标签共 498 条 | 按独立样本目标 2,000，尚差 1,604 |

多标签可重叠，表中四类总数不可直接相加。API 正式批次共提交 8 个母本，截图成功 3/8；因 HTTP 400 `Request body is empty` 保护停止，错误原因仍需诊断。恢复前应先核对普通交互候选到正式记录的对应关系。

这些更新保存在 `reversed_20260903_v4`，本次 0805 增强包 Generate 继承原始 0805，尚未带入这些更新。现场按原 0805 Image Generate ID 匹配：

- 原 5,094 条的 GT 在 v4 中全部一致；其中 237 条 `input_images` 与原始不同，12 条有主页入口映射。
- 独立派生样本中有 109 条 transient、363 条 sequence 的母本属于原 0805，共 472 条；472 条 GT 全部与原母本一致。
- 这 237 条输入更新和 472 条派生记录是优先迁回候选。迁回前检查图像角色、动作顺序和文件引用；已观察到个别历史记录重复拼接 Reference image roles，v4 还有一条 125 图记录，应控制冗余而非仅按图片数接收。

### 按优先级补齐

1. **官方类型＋4–12 项＋物理多页的组合样本。** 0805 及本次新增均未补上 8–12 项。增强包物理多页 Edit 每模态 14 条，Text Repair 27 条、Image Repair 25 条；官方 Edit/Repair 各 300 实例中 150 为四 HTML 多页。上述 14/27/25 是文件形式计数，Edit 不等于全部通过官方类型筛选。
2. **单页的 8–12 项也要补。** 官方 SP/MP 均覆盖 4–12 项；不能只补多页长任务。按官方类型和子任务数分层，避免只增加简单单项任务。
3. **迁回已有 Image Generate 改善。** 优先使用上面的原 0805 同 GT 更新与派生样本，再处理 supplement 母本。原始 0805 5,094 条 Image Generate 全为单图，距官方多图/状态输入仍有差距。
4. **已有物理多页的 Image Edit/Repair 补全图片。** 原始 0805 的 9 条多 HTML Image Edit 均只给一张 source 图，8 条多 HTML Image Repair 均为一张 source＋一张 target。v4 的 Image Edit 补图可按 ID 复用，Repair 需补齐对应页面及前后关系。
5. **最终 chat 协议验证。** 新包已补 glossary＋N；训练导出时核对这段确实可见、隐藏字段不进入 prompt、图片角色清楚、source code 完整，结构化答案按官方 search/replace XML 序列化。当前实际训练用 converter/chat 待核验。
6. **要求与 GT 的完整性。** 用已有检查覆盖多项任务是否全部完成、patch 是否精确回放、非目标内容是否保留；图像修复并非要求每一页都变化，应对应真实受影响页面/状态。
7. **Generate 内容分布与资源条件。** 后续核查文字需求是否明确页面角色、交互状态和响应式要求，以及领域分布；源码所需资源须在实际训练/运行环境中可用。此项属于待审计方向，本轮未进行全量语义判断。

当前应区分“对齐输入协议”“对齐任务分布”“GT 质量”和“训练收益”。前两项可据数据统计与导出检查改进，收益以相同预算的 benchmark 对照确认。

## 0805 增强包实施记录（2026-09-06）

### 筛选结果

选择规则：`(8–12 个子任务 OR 输入源码至少两个 HTML) AND 每个子任务都属于官方类型`。按任务内 `instance_id` 去重，整条保留或排除。官方白名单为 16 类 Edit、11 类 Repair；大小写、空格、下划线作同名规范化，例如 `text_overlap` 对应 Text Overlap。`semantic_structure`、`missing_handler` 等更宽的概念独立记录为越界类型。

| 任务 | 两组并集候选 | 因类型越界排除 | 新增 | 0805 基础 | 合并后 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Text Edit | 753 | 748 | 5 | 3,000 | 3,005 |
| Image Edit | 753 | 748 | 5 | 3,000 | 3,005 |
| Text Repair | 1,546 | 1,529 | 17 | 3,332 | 3,349 |
| Image Repair | 1,323 | 1,306 | 17 | 3,000 | 3,017 |

新增共 44 条训练记录，全部属于多 HTML 组。8–12 项组符合完整白名单的数量为 0，因此长任务缺口仍保留。新增 Edit 均为 1 项任务，Repair 为 1–3 项。Text/Image Repair 各 17 条的 ID 集不完全相同，按各自原始记录筛选。

典型排除实例：`gen14-webcompass-wc-1-00689-44d2fa1341` 有 10 项 Edit，包含 Select Control、Filter Control、Modal Dialog 等官方 16 类以外的类型；`gen14-artifactsbench-ab-2-00493-0bfb1d8455` 有 10 项 Repair、3 个 HTML，包含 missing_handler、framework_component_api、state_sync_failure 等类型，整条排除。

### 输入更新与来源

- 原始 0805 六类共 26,520 条全部作为基础；Generate 分别保留 9,094 / 5,094 条。增强包六类总数为 26,564。
- 新增样本选自正式 `0805_supplement`；新增 Image Edit 使用 v4 对应的补图记录，逐条比较源码、指令、答案和类型一致性。
- 全部 6,366 条 Repair 统一在 `repair_instruction` 写入官方 11 类公共定义和本例 N。Image Repair 同时更新 `instruction`；Text Repair 的 `instruction` 继续保存缺陷代码。
- `task_type` 与 `metadata` 属于隐藏元数据；训练按 `dataset_index.json.model_input_contract` 读取文本、源码和截图，答案继续使用原有 patch schema。
- 产物保持六目录、每类一个 gzip JSONL、任务目录内实体截图。原始 0805 和 supplement 保留，可继续追溯。

已完成路径：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v1`，约 8.4 GiB；26,564 条、14,241 张实体截图。全量保真检查六类均为 `exact_record_pass`。新增清单：[44 条入选记录](../logs/0805_aligned_enhanced_20260906/added_samples.jsonl)；[逐类验证结果](../logs/0805_aligned_enhanced_20260906/preservation_validation.json)。

### 版本盘点

| 版本/目录 | 当前用途与差异 |
| --- | --- |
| `/data1/.../releases/webcoding_sft_v2_20260805_compatible` | ckpt-622 对应基础包；26,520 条，作为此次原始基础 |
| `/data1/.../releases/0805_supplement` | 正式增补包；36,239 条，作为此次候选来源 |
| `/data2/.../releases/reversed_20260829_v3` | 完整合并包；62,759 条，约 13 GiB；统一了 Image Generate 指令及 Repair N 字段 |
| `/data2/.../releases/reversed_20260903_v4` | 63,438 条，约 16 GiB；Image Edit 203 条补多页图，Image Generate 增至 10,773 条；Text Generate、Text Edit、两类 Repair 索引哈希与 v3 相同 |
| `/data2/.../releases/modelscope-reversed-stage-qyikrsaw` | 约 146 MiB 的上传暂存；只有 Image Edit 分片与根元数据，属于局部暂存 |
| `/data1/.../releases/0805_supplement.edit_repair_staging_v1/v2` | supplement 发布前的 Edit/Repair 中间打包目录，正式候选使用 `0805_supplement` |
| `/data2/.../runs/reversed_paired_basic_physical_20260905_v1` | 30 对基础校验试跑；Text 25 basic_pass、Image 24 basic_pass；唯一 API 代码修复候选为 repair_candidate_rejected，正式 release 两类 Repair 仍为原版本 |
| `/data2/.../backups/reversed_*` | Image Generate 原地更新前的备份及追加记录，用于回溯，不合并为额外训练数据 |

两类 Repair 已现场计算 v3/v4 分片 SHA-256，分别完全一致。其他 v3/v4 差异依据现场索引及文件布局。`runs/` 中的截图探索、API probe、worker 分区和试跑目录保存候选/证据，并非独立完整 release。较早的 `fourteen_benchmark_gt_*` 是 Generate 构造中间包，`sharegpt_0805_provenance_fixed_*` 是不同训练格式导出；本次沿用兼容六任务基础包。

### 实现与验证

- 实现：`scripts/build_0805_aligned_enhanced.py`；逐条筛选结果在 `selection.jsonl`，来源在 `lineage.jsonl`，汇总在 `selection_summary.json`。
- 验证：7 项单元测试通过；真实 pilot 完成六类共 10 条记录及截图的打包、重新读取与字段检查。
- 正式打包单 worker、nice 10、扫描上限 20,000、输出上限 27,000、进程超时 880 秒、外层超时 900 秒、15 秒心跳，日志 `runs/0805_aligned_enhanced_pilot_20260906/build.log`。
- 发布完成状态以根目录 `validation.json` 为准；全量原始记录与答案保持检查由 `scripts/verify_0805_aligned_enhanced.py` 写入 `preservation_validation.json`。本轮验证范围为选择规则、记录保真、prompt 和截图文件完整性；网页功能质量继承来源记录。

## 当前决定与全量统计（2026-09-06）

以 `ckpt-622` 对应的 **0805 为训练基础**。用户报告该版本已在 WebCompass Edit/Repair、ArtifactsBench、WebGen-Bench 上获得提升。0805_supplement 用于定向补充类型对齐、任务密度合适的样本及物理多页母本。下文此前的双轨加权方案保留为备选实验。

### 统计口径与来源

- 0805、0805_supplement、reversed v4：2026-09-06 直接读取物理机三个 release 的四类 Edit/Repair 完整 gzip 分片。
- 0805 路径：`/data1/xieqianqian/webcoding/WebCoding_Data/releases/webcoding_sft_v2_20260805_compatible`。
- supplement 路径：同级 `0805_supplement`；reversed 路径：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/reversed_20260903_v4`。
- 训练数据子任务数按 `len(task_type)` 计，与 `metadata.task_count` 全量一致；这是构造时声明的任务数，实际功能完成度需另行验证。一个子任务可对应多个 patch，patch 数不作为任务数。
- WebCompass 按官方数据的 `len(description)` 计，与 `len(task_type)` 一致；使用 2026-09-04 获取的官方公开缓存，Edit/Repair 各 300 条，分别包含 150 SP＋150 MP。Text/Image 共享实例，分别评测。
- 证据：[release 全量结果](../logs/edit_repair_task_counts_20260906/release_counts.json)、[WebCompass 结果](../logs/edit_repair_task_counts_20260906/webcompass_counts.json)；复核脚本：`scripts/audit_edit_repair_task_counts.py`。

### 子任务数量对比

Edit Text 与 Image 数量和分布完全相同，下表按每种模态列一行，不重复相加。

| 数据 | 任务 | 总量 | 1–3 项 | 4–12 项 | 4–12 项占比 | 平均项数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| WebCompass | Edit（Text/Image 各） | 300 | 0 | 300 | 100% | 7.88 |
| WebCompass | Repair（Text/Image 各） | 300 | 0 | 300 | 100% | 8.03 |
| 0805 | Edit（Text/Image 各） | 3,000 | 1,286 | 1,714 | 57.13% | 4.00 |
| 0805 | Text Repair | 3,332 | 1,428 | 1,904 | 57.14% | 4.00 |
| 0805 | Image Repair | 3,000 | 1,286 | 1,714 | 57.13% | 4.00 |
| 0805_supplement | Edit（Text/Image 各） | 2,974 | 899 | 2,075 | 69.77% | 5.30 |
| 0805_supplement | Text Repair | 5,918 | 3,503 | 2,415 | 40.81% | 4.40 |
| 0805_supplement | Image Repair | 4,373 | 2,373 | 2,000 | 45.74% | 4.80 |
| reversed | Edit（Text/Image 各） | 5,974 | 2,185 | 3,789 | 63.42% | 4.65 |
| reversed | Text Repair | 9,250 | 4,931 | 4,319 | 46.69% | 4.26 |
| reversed | Image Repair | 7,373 | 3,659 | 3,714 | 50.37% | 4.48 |

| 子任务数 | WebCompass Edit | WebCompass Repair | 0805 Edit / Image Repair | 0805 Text Repair | supplement Edit | supplement Text Repair | supplement Image Repair |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 0 | 429 | 476 | 328 | 1,098 | 677 |
| 2 | 0 | 0 | 429 | 476 | 302 | 1,246 | 823 |
| 3 | 0 | 0 | 428 | 476 | 269 | 1,159 | 873 |
| 4 | 40 | 38 | 428 | 476 | 401 | 347 | 253 |
| 5 | 37 | 31 | 428 | 476 | 383 | 267 | 207 |
| 6 | 29 | 33 | 429 | 476 | 345 | 287 | 220 |
| 7 | 38 | 29 | 429 | 476 | 366 | 225 | 193 |
| 8 | 28 | 28 | 0 | 0 | 104 | 218 | 187 |
| 9 | 24 | 36 | 0 | 0 | 89 | 278 | 240 |
| 10 | 38 | 36 | 0 | 0 | 141 | 269 | 240 |
| 11 | 33 | 35 | 0 | 0 | 123 | 261 | 233 |
| 12 | 33 | 34 | 0 | 0 | 123 | 263 | 227 |

0805 的全部 Edit/Repair 均为 1–7 项。supplement 引入了 8–12 项：Edit 每模态 580 条、Text Repair 1,289 条、Image Repair 1,127 条。Edit 的任务密度由 supplement 拉近官方分布；Repair 的 1–3 项占比则升高。因此，任务密度与类型偏移应分别分析。

### 多 HTML 母本数量

按模型输入源码中 `.html` 文件数量统计，反映文件组织形式。页面可达性和任务类型适配作为后续选样条件。

| 数据 | 任务 | 标记 mp | 至少 2 个 HTML | 恰好 4 个 HTML |
| --- | --- | ---: | ---: | ---: |
| WebCompass | Edit | 150 | 150 | 150 |
| WebCompass | Repair | 150 | 150 | 150 |
| 0805 | Edit（Text/Image 各） | 9 | 9 | 1 |
| 0805 | Text Repair | 10 | 10 | 1 |
| 0805 | Image Repair | 8 | 8 | 1 |
| supplement | Edit（Text/Image 各） | 1,774 | 194 | 126 |
| supplement | Text Repair | 3,280 | 359 | 236 |
| supplement | Image Repair | 2,652 | 292 | 191 |

优先从 supplement 中检查已有四 HTML 母本，并结合 4–12 项任务及类别适配选择补充样本。上述数量是候选规模，Text/Image 存在配对关系；四 HTML 与 4–12 项的交集另计。SPA 仍可用于通用多页训练；这次补充四 HTML 项目是对齐官方 Edit/Repair 的源码组织形式。

### 输入与类型判断的修正

1. reversed Repair record 已保存含 N 的 `repair_instruction`，全量字段核验中 N 与缺陷数一致。待补的是 11 类公共定义。最终训练是否加入该定义，应检查实际使用的 chat 与 system prompt。
2. WebCompass 向模型提供 11 类公共定义和本例问题数 N，具体 defect label 保留为隐藏元数据。例如 N=6 表示修复六个问题，不表示从十一类中公开指定六类答案。
3. Edit 的交互功能本身也存在于 WebCompass，例如官方实例包含 Data Table、Async Form Validation、Shopping Cart 等。类型筛选需要看具体任务定义和要求，不能仅凭 Modal、Filter 等名称判断偏离。
4. Repair 的新旧类别存在语义重叠，例如部分交互错误可能落在 Loss of Interactivity 范围。新增类别需按定义判断适配程度。
5. 当前分数是用户提供的实测结果；类型偏移、prompt 差异和任务密度属于原因假设，应结合固定训练预算的对照实验确认。

### 下一步

以 0805 为固定基础，先形成 supplement 定向候选清单：优先检查四 HTML 母本和 8–12 项任务，按 WebCompass 类型定义核实 query/缺陷含义，再做已有基础验证。Repair 统一补充公共 glossary，同时保留 N 和隐藏标签边界。实际选入数量、采样比例及训练版本在候选清单确认后确定。

## 1. 数据与 checkpoint 关系

- `ckpt-622`：使用 `0805` 数据训练得到的旧版本。
- `ckpt-1300`：从 `ckpt-622` 继续使用 reversed 数据训练得到的新版本。
- reversed 数据由 `0805` 与 `0805_supplement` 合并形成。

因此，下表反映的是模型从 `0805` 训练阶段继续进入 reversed 训练阶段后的能力变化。

## 2. 当前现象

Generate 能力继续提升，但 Edit 和 Repair 明显下降：

| 任务 | ckpt-622 | ckpt-1300 | 变化 |
| --- | ---: | ---: | ---: |
| Edit / Text | 3.88 | 2.96 | -0.92 |
| Edit / Image | 3.75 | 3.16 | -0.59 |
| Repair / Text | 5.15 | 2.94 | -2.21 |
| Repair / Image | 4.98 | 2.88 | -2.10 |

这说明 reversed 中的新增训练数据提升了通用网页生成能力，但对 WebCompass 所要求的精确 Edit / Repair 能力产生了负迁移，其中 Repair 退化最明显。

## 3. Edit 问题

Edit 的主要问题是任务分布发生偏移。

新增 Edit 数据加入了较多复杂、开放的交互功能，例如 Modal、Filter、Carousel、Click State 和表单控制。这些任务有助于扩展通用网页能力，但与 WebCompass Edit 的任务分布并不完全一致。

模型逐渐更擅长增加新功能和进行较大范围修改，同时在 WebCompass 所要求的能力上退化：

- 修改不够精准；
- 多项要求容易漏做；
- patch 可能没有真正应用成功；
- 容易修改无关内容；
- 功能完成度下降。

后续 Edit 数据扩增应在提高任务多样性的同时，保留足够比例的 benchmark-aligned Edit 数据回放，避免训练分布持续远离 WebCompass。

## 4. Repair 问题

Repair 的核心问题是训练任务定义混合。

WebCompass Repair 的评测范围固定为 11 类缺陷，包括 Occlusion、Crowding、Color Contrast、Missing Attributes 等类型。新增 Repair 数据还包含更广泛的软件 Bug：

- `wrong_state_transition`
- `missing_handler`
- `event_runtime_exception`
- `route_resource_failure`
- `compile_syntax`
- `module_dependency`

这些样本具有通用训练价值，但不属于 WebCompass 的 11 类 Repair。当训练 prompt 仍声明缺陷属于 WebCompass 11 类，而 supervision 中出现大量范围外问题时，输入定义与训练答案不一致。

这会让模型逐渐把 Repair 学成泛化 debugging 和代码重写，而不是在指定缺陷范围内定位 root cause 并进行最小化、精确修复。

## 5. Repair 数据拆分

### 5.1 WebCompass-aligned Repair

用于保持和提升 WebCompass Repair 能力：

- 缺陷严格属于 WebCompass 原始 11 类；
- prompt 保留 WebCompass defect glossary；
- 强调 root cause 定位；
- 强调最小化修改；
- 避免修改无关功能；
- 训练时给予较高 sampling weight。

### 5.2 General Web Repair

用于提升通用网页 Debug / Repair 能力，覆盖：

- 状态切换错误；
- handler 缺失；
- JavaScript runtime exception；
- 路由和资源加载失败；
- 编译和语法错误；
- 模块依赖错误；
- 其他真实网页 Bug。

这部分不使用“缺陷只能属于 WebCompass 11 类”的 prompt，改用开放式 Repair 指令：

> Diagnose the root cause of the webpage malfunction and minimally repair the implementation.

训练时给予较低 sampling weight，作为通用能力补充。

## 6. 训练配比

第一轮采用以下加权方案：

| Repair 类型 | 建议权重 |
| --- | ---: |
| WebCompass-aligned Repair | 2–3× |
| General Web Repair | 1× |

后续进行 `1:1`、`2:1`、`3:1` ablation，对比 WebCompass、ArtifactsBench 等 benchmark 的变化。

## 7. 总体调整原则

- Edit：扩展任务多样性的同时，持续回放 benchmark-aligned 数据。
- Repair：显式拆分 WebCompass 11 类 Repair 与 General Web Repair，并提高前者的训练权重。
- Prompt 与 supervision 使用同一任务定义：WebCompass-aligned Repair 使用 11 类 glossary；General Repair 使用开放式诊断指令。

目标是同时获得更强的通用 WebCoding 能力和稳定的精准 Edit / Repair 能力。

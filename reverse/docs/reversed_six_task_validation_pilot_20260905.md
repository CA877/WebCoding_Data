# reversed 六类数据：基础校验与配对修复试跑

日期：2026-09-05。本文件是 v3 的冻结试跑记录，不维护当前检查策略。

> 本报告保存 v3 的 60 条历史浏览器试跑和原始证据；0905 当前检查策略与适用边界统一见 [0905 数据检查策略与实施记录](reports/0905_data_check_strategy_implementation_20260912.md)。

执行口径更新：两个已有修复由 Codex 手工定位，作为调试参照；自动修复统计单独从“脚本调用 LLM → 结构化修改 → 代码应用 → 复测”的真实记录计算，当前自动成功数为 0。

- [60 条图片预览与逐条证据](../logs/reversed_six_task_validation_20260905_v1/preview_v2.html)
- [固定样本及原始分片哈希](../logs/reversed_six_task_validation_20260905_v1/manifest.json)
- [逐条初查汇总](../logs/reversed_six_task_validation_20260905_v1/summary_v2.json)

## 试跑结果

30 对共 60 条的浏览器观察已完成；新规则直接复用原日志和截图汇总，新增渲染 0、API 调用 0。结果：[物理机汇总副本](../logs/reversed_paired_basic_physical_20260905_v1/basic_summary_0_30.json)。

| 视图 | 基础通过 | 资源/环境待处理 | 代码待修 | 同步待处理 |
|---|---:|---:|---:|---:|
| Text（30 条） | 25 | 4 | 1 | 0 |
| Image（30 条） | 24 | 4 | 1 | 1 |

四对资源问题表现为可见图片不可用；唯一代码修复入口为 `repair_01`，对应原 target 的无效初始化调用。其 `repair_request.json` 已在物理机生成，状态为 `waiting_for_repair_api`。基础通过表示 build/加载/主体内容/运行错误及截图可读取检查通过，完整视觉与功能语义另行评估。正式保留至少 50k 的数量要求在全量版本上统计。

实现入口：`scripts/pilot_validate_reversed_six_tasks.py` + `scripts/reversed_pair_validation.py`；启动脚本 `scripts/run_reversed_pair_validation.sh`。`pair-offline` 运行浏览器后汇总，`pair-screen` 仅复用已有证据汇总，`pair-live` 只处理代码失败对，`pair-finalize` 在修后基础复测和图片映射满足时导出增量候选。物理机使用 `PYTHON_BIN` 指向项目 `web-coding-agent/.conda/lora/bin/python`。

本地及物理机相关测试最新均为 **46 passed**，覆盖正常对跳过 API、并发锁、故障 source 边界、文件复用、patch 同步和候选导出协议。远程框架 build 待补 npm 环境验证，当前物理机批次为静态/SPA 项目。

### 物理机真实 API 与首次修复

- TokenWave 凭据已使用。物理机直连 `gpt-5.6-luna` 返回 HTTP 200，探针 4.851 秒，输入 4,413 / 输出 34 tokens；见 [探针结果](../logs/reversed_paired_basic_physical_20260905_v1/physical_api_probe_result.json)。此前超时为本地观测，后续 API 执行以物理机成功结果为准。
- `repair_01` 已实际调用一次代码修复，输入 16,294 / 输出 185 tokens（含 reasoning 61），截图输入 0、并发 1、自动重试 0。模型把故障 source 的 `initializeApp` 改成 `init`，相当于回答原训练题，遗漏 clean target 的 `setupDragAndDrop` 报错。source/target 检查拦截该候选，状态为 `repair_candidate_rejected`，成功修复数 0；[返回内容](../logs/reversed_paired_basic_physical_20260905_v1/cases/repair_01/llm_review.json)、[用量](../logs/reversed_paired_basic_physical_20260905_v1/cases/repair_01/llm_receipt.json)、[拦截结果](../logs/reversed_paired_basic_physical_20260905_v1/cases/repair_01/decision.json)。
- 提示词已明确“修数据集 clean target 的运行错误，保留原 source 故障”。新版 Repair 输入先给 target，再给原训练 patch 表达 source 差异，减少双份代码并突出任务边界。复用第一次返回重放了拦截流程，新增 API 调用 0；后续重试使用独立尝试记录。
- 公共 `/api/pricing` 返回 404。此轮配置的输入 $50/M、输出 $100/M 为高位预算估算参数，修复请求预留 $3.34865，并为探针留出预算；这些数值是预留假设，供应商实际费用待账单核对。当前模型调用为探针 1 次、修复 1 次。

## 1. 首轮确认的要求与历史范围

- 使用本地 `/tmp/reversed_v3_shards` 中 reversed v3 的六个分片。逐行统计为 62,759 条；正式处理前与最新版本重新对齐。
- 每类 10 条，共 60 条。随机种子 20260905，按旧 `page_type` 标签各取 5 条 SP/MP，流式 reservoir 抽样；实际页面性质由后续浏览器证据判断。这是定额调试集，其通过率用于定位问题，整体比例需按全量分层权重另行估计。
- 成本优先，允许将 query 调整为符合正确 GT；每次调整记录具体增删要求。GT 的坏功能单独修复或隔离。
- TokenWave / `gpt-5.6-luna`，本轮付费上限 5 美元，付费失败自动重试为 0。
- 正式保留数量至少 50,000。按当前 v3 算术上最多剔除 12,759 条；数量统计以通过校验的正式记录为准，问题样本与待验样本单列。若质量与数量发生冲突，先报告缺口再决定处理方式。

## 2. 上一版轻量计划：含 Query 与截图审核

以同一个任务的 Text/Image 配对为处理单位：先修 Text 的 query、source、GT/patch，再更新对应 Image。结果标记为 `basic_pass`（基础质量通过）。适用范围为本轮 reversed 存量修复；Harness 的新数据准入规则保持独立。

### 共同检查

1. **代码与运行环境**：文件和资源可读取；框架项目按自身配置安装依赖、执行已有 build 并启动；纯静态 HTML/CSS/JS 直接通过本地 HTTP 服务运行，build 记为“不适用”。依赖下载和环境故障单列待处理。
2. **渲染**：浏览器打开主页和已记录的主要页面级路由，每页保留一张桌面截图及启动错误。检查主要内容出现，画面没有明显空白、错误页、大面积错位或关键资源缺失；移动端与额外交互按异常需要追加。截图正常由支持图片的模型结合运行证据判断。
3. **Query 粗对齐**：保留页面数量/角色、主要功能及明显矛盾检查。优先按正确 GT 调整 query，保留有意义的任务内容；如四页要求实际只有三个正常页面，可改为三页并记录删改项。基本风格参考 WebCompass，Generate 按来源兼顾 WebGen-Bench / ArtifactsBench；用自然描述去掉明显生产套话，具体评测题目保持隔离。

交互检查限于打开必要页面/截图状态，以及已发现异常的定位；逐控件测试、全部状态穷举和完整旧功能回归改为后续可选抽查。

### 三种 Text 任务与对应 Image

| 配对任务 | Text 的最低检查 | Image 同步与补充检查 |
|---|---|---|
| Generate | 完整 GT 能构建或静态启动，主要页面渲染正常，query 与页面/主要内容大体对应 | 共用修正后的 GT；保持截图驱动指令，按原页面/状态更新受影响的参考图及图片映射 |
| Edit | 正常 source 可打开；patch 精确应用且产生实际改动；target 能构建、渲染，编辑描述与主要改动对应 | 同步 source、编辑描述和 patch；source 改动时刷新 source 图，只有 target 改动时复用已有 source 图 |
| Repair | 故障 source 的 patch 可精确应用且有实际修复内容；target 能构建、渲染；沿用缺陷记录粗核问题数 N | 同步故障 source、修复 patch、N 和诊断说明；按实际变化刷新 faulty/clean 图，保持页面与状态对应 |

Repair 的正常运行要求针对修复后的 target。source 保留任务故障；故障造成的运行或画面异常作为输入的一部分。静态前后图相同按原缺陷范围处理。发现公共底座错误时同步修 source/target，保持原任务故障及 patch 方向。

### 已核对的构造与字段对应

- `construct/v2_records.py::edit_records`：同一记录同时导出图文 Edit，共享 source、description 和 patches；Image Edit 使用编辑前截图。
- `construct/v2_records.py::repair_records`：图文 Repair 共享故障 source 和修复 patches；满足图片派生条件才输出 Image Repair，因此两类数量可以不同。
- `construct/construct_image_generation.py`：从同一来源项目保存 GT 与参考截图；`scripts/repackage_reversed_webcompass_inputs.py` 将 Image Generate 改为通用截图指令，并统一 Repair 的 N 描述。
- 本地 v3 的 30 条已有 image case 均找到 text 对应项：Edit/Repair 各 10 对的 source、patch 后 target 和 query 一致；Generate 3 对同 ID，另 7 对通过 `metadata.source_instance_id` / `source_project` 找到。Generate 9 对 GT 文件一致，`gen14-interactweb-bench-iwb-g5-00218` 对应 image 版少一个含静态服务配置的 `package.json`。这是文件差异，运行影响待实测。

| 字段 | Text → Image 更新规则 |
|---|---|
| Generate GT | `response` → `response`，并同步现有 `output_files`、文件清单和资源引用 |
| Edit source/query | `instruction.src_code` → `input_files`；`instruction.description` → `instruction` |
| Repair source/query | `instruction`（文件列表）→ `input_files`；`repair_instruction` → 同名字段及 Image 的 `instruction` |
| Edit/Repair patch | `response` → `response` 和现有 `patches`，重新精确回放得到 target |
| 图片及元数据 | 按任务更新 `input_images`、`src_screenshot`、`dst_screenshot` 及已有引用/页面状态映射；同步 N、任务标签、文件和版本信息 |

配对先查显式来源，再核对 ID、来源项目与代码版本；同一 Generate 若派生多个图片样本则同步所有已确认子项。只有相同 ID 而版本不同的条目先对齐版本。Generate/Edit/Repair 之间以各自 source/target 版本处理，避免仅凭同项目名连带覆盖。只有图片损坏时单独更新图片；text 结果可复用。

旧 60 条独立抽样结果保留。下一轮配对试跑复用现有每类 10 条 image case，加载其对应的 text：共 30 个配对任务、60 条记录，修复和运行结果在对内复用。

## 3. 初查结果

| 任务 | 抽样 | GT 有确定 JS 错误 | 出现资源请求失败或坏图 | 运行环境待补 |
|---|---:|---:|---:|---:|
| Text Generate | 10 | 0 | 2 | 1 |
| Image Generate | 10 | 0 | 2 | 0 |
| Text Edit | 10 | 2 | 1 | 0 |
| Image Edit | 10 | 0 | 2 | 0 |
| Text Repair | 10 | 1 | 0 | 0 |
| Image Repair | 10 | 1 | 2 | 0 |

- 60 条结构检查均通过；40 条 Edit/Repair 的 patch 都能精确回放。
- 60 个初查 worker 全部结束，59 条完成静态浏览器观察，1 条为 framework runtime 待补；共保存 215 张 source/target 桌面或移动端截图。
- 30 条图片任务的 90 张原始参考图下载并解码成功。原始参考图与本次渲染图分别保存。
- 4 条 GT JS 错误是确定问题；9 条资源异常需区分环境、外链和缺失资源后处理。数字以原始数据初查为准，修复结果单独保存。
- 初查通过与最终接收分别记录；完整语义接收计数当前为 0。

### 已确认的问题

| Case | 发现 | 当前状态 |
|---|---|---|
| `text-edit_04` / `webcode2m-improved-prompts_2786` | target 重复声明 `dateInput`，脚本语法失败 | 待修 |
| `text-edit_09` / `gen14-artifactsbench-ab-2-00245-d4c546a034` | target 重复声明 `artisans` | 待修 |
| `text-repair_06` / `gen14-artifactsbench-ab-2-00356-9ead3d0568` | 修复后的 Dashboard 初始化读取不存在的 `event.target` | 待修 |
| `image-repair_01` / `gen14-webcompass-wc-3-00163-23d78be511` | 原 patch 修好启动函数名称，但 target 又调用不存在的 `setupDragAndDrop` | 共有底座修复候选通过定向回测 |
| `text-generate_09` / `gen14-artifactsbench-ab-2-00364` | 四页文件齐全，但 Catalog 初始化检查了不存在的 `catalog-content`，页面没有图书和筛选内容 | 单处 DOM ID 修复后六项回测通过 |
| `text-edit_01` / `artifacts_207` | 帮助弹窗设置 `hidden` 后仍可见；面板列出的导航、搜索、刷新等快捷键没有对应处理器 | 待修；打开成功不足以判断新增功能完整 |

### 功能验证示例

1. **Generate 四页图书网站**：原 query → Home/Catalog/Compare/Selections → 点击主页入口、组合年龄与主题筛选、详情页收藏、跨页显示收藏、最多三本比较。原始 6 项中 2 项通过、4 项失败；修正初始化 DOM ID 后 6/6 通过。原 query 保留，GT 只改一处 ID。详见 [修复与候选记录](../logs/reversed_six_task_validation_20260905_v1/cases/text-generate_09/simple_fix/repair.json)、[六项回测](../logs/reversed_six_task_validation_20260905_v1/cases/text-generate_09/simple_fix/replay/evidence.json)。完整页面审美与所有要求覆盖仍待补齐。
2. **Image Repair 生态修复画布**：同时移除 faulty/clean 中原有的无效初始化调用，保留 source 的 `initializeApp` 故障与原来的单问题 patch。浏览器证明 source 的故障保留、target 无初始化报错、鼠标拖入物种成功、重置成功；重新生成双方图片。详见 [证据](../logs/reversed_six_task_validation_20260905_v1/cases/image-repair_01/shared_fix_v2/evidence.json)、[候选 record](../logs/reversed_six_task_validation_20260905_v1/cases/image-repair_01/shared_fix_v2/candidate_record.json)。候选图片路径以本次 run 为根，正式打包时更新资源清单。
3. **Text Repair 行程面板**：source 的按钮被 `pointer-events:none` 阻止，键盘触发又改错 footer；target 点击能展开面板，键盘能展开/收起。四项针对性检查通过，分别保存在 `text-repair_02/targeted_checks/source|target/evidence.json`。

## 4. Query 风格观察

- 本次 Text Generate 字符数为 3,964—8,193，中位数 6,502；长度适中仍可能混入 benchmark 名称、重复交付协议或存在页面内容缺失。按实际内容审查。
- Image Generate 全部 351 字符，属于统一截图驱动说明；重点转向图片页面/状态映射和证据充分性。
- Edit 存在“7 项功能，每项一句泛化要求”的样本，如 `image-edit_01`。下一步依据 source、patch、target 中真实实现补齐具体产品要求，保留原任务单位并避免虚构功能。
- 两种 Repair 的当前文字多为 103—105 字符，只含修复说明与 N。部分样本属于官方 11 类，部分包含状态同步、路由、构建等扩展故障；公共诊断范围需与真实缺陷空间匹配，具体缺陷标签继续留作内部信息。
- Query 的自动语义改写候选尚待 Luna 产出。本轮两个修复均为代码层的明确小改动。

## 5. 成本、限制与下一步

TokenWave 公共价格接口连接超时。随后对指定 `gpt-5.6-luna` 发起一次无重试的最小 Responses 请求，15.282 秒后 `ConnectTimeout`，成功响应数 0，usage 未返回。原始记录见 [API 探针](../logs/reversed_six_task_validation_20260905_v1/provider/probe_result.json)。本轮两个代码修复由本地人工定位并作确定性修改，API 计费回执待服务端核验。

轻量后续流程：关联 Text/Image → 脚本构建/启动、回放 patch 和截图 → 按每个 Text 配对任务合并一次 LLM 粗审（query、必要代码、日志、页面清单及截图）→ 返回通过或 query/代码最小修改 → 脚本应用并复跑基础检查 → 同步 Image 与受影响截图。优先一次请求合并审查与修改；修后画面复核按需补一次调用，默认每对最多一轮代码修复。图片能力先做单样本确认；模型只有文本能力时另选获授权的图像审核渠道，并计入相同预算。

分别保存 `basic_pass`、`basic_pass_after_fix`、`reject_candidate`、`pending`；实际丢弃数量按 Text/Image 训练行分别汇总，保证正式保留至少 50k。只有图片异常的条目单独处理。旧原始分片与候选修复分开保存。先核实供应商价格及计费口径，在 5 美元总预算内预留费用，批次依单样本结果决定。

下一步最值得做的一件事：实现一个配对 case 的 Text 修复 → 基础复测 → Image 字段与截图同步。优先复用已有 Image Repair 公共底座失败例对应的 Text；真实修改由脚本调用 LLM 产生，API 连通后再试跑。

## 6. 入口与验证

- 实现：`scripts/pilot_validate_reversed_six_tasks.py`，复用已有静态服务器、Chromium 启动与浏览器断言工具。两个顺序 worker，各处理 30 条，最多同时两个浏览器；单 case 90 秒硬超时、心跳、已有结果跳过和子进程清理。
- 测试：`uv run python -m pytest -q tests/test_pilot_validate_reversed_six_tasks.py`，19 passed。直接调用 `uv run pytest` 曾因解释器路径找不到 `scripts` 而收集失败，改用项目 Python 的 `-m pytest` 后通过。
- 修复 demo 首次将已有 `index.html` 的服务地址再次追加路径，导致 404 并触发断言；修正调用后结果保存在 `shared_fix_v2`，首次证据保留在 `shared_fix`。
- `prepare` 写出不可变原始样本、代码项目、review packet 与分片哈希；`browser` 写逐样本运行日志与证据；`images` 保存原始参考图；`checks` 回放给定 JSON 检查计划；`repair-demo` / `repair-generate-demo` 复现两条本地修复。`summary --report-tag <新标签>` 写新版本汇总。
- 原始 release 与分片保持原样；两个候选写在各 case 子目录中，正式训练发布按后续完整验收结果处理。

## 7. 历史记录：API 复测与此前较细的验收方案（2026-09-05）

下列逐要求、F2P/P2P 与完整回归设计保留为可选深入检查；当前 reversed 试跑采用第 2、5 节的轻量计划。

直连设置更新：probe 清除大小写 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY，设置大小写 NO_PROXY=*，HTTP 客户端保持 trust_env=False。命令启动层同步清除代理后，单次最小请求于 15.318 秒返回 ConnectTimeout；连接设置与结果见 [直连复测](../logs/reversed_six_task_validation_20260905_api_direct_v1/probe_result.json)。该设置仅作用于测试进程，系统代理保持原配置。

### API 定位

用户授权后重新发起一次最小 `gpt-5.6-luna` Responses 请求，自动重试 0，15.193 秒后 `ConnectTimeout`。独立直连诊断：域名解析至 `38.55.103.162`，TCP 443 连通，TLS 握手在 8 秒超时；curl 限定 TLS 1.2 也返回 SSL connection timeout，HTTP 状态 000。证据：[网络分层诊断](../logs/reversed_six_task_validation_20260905_api_retry_v1/network_diagnostic.json)、[请求结果](../logs/reversed_six_task_validation_20260905_api_retry_v1/probe_result.json)。

当前确定阻塞位于 HTTPS 握手。key 鉴权与模型路由需要 HTTP 通信恢复后验证；具体是服务端、网络路径还是本机环境造成，继续按连接证据定位。该次请求没有返回 usage。

### 训练数据验收的参考依据

- [SWE-smith: Scaling Data for Software Engineering Agents](https://arxiv.org/html/2504.21798v1)：§2.1 先建立测试基线，再保留能破坏原本通过测试的 bug；附录 A.3 记录 Fail-to-Pass 和 Pass-to-Pass。可借鉴 Repair 的“故障确实出现、修复后恢复、其他能力保留”。这是 Python 仓库训练数据方法，浏览器与视觉部分需要我们另外实现。
- [OpenCodeInstruct: A Large-scale Instruction Tuning Dataset for Code LLMs](https://arxiv.org/html/2504.04030v1)：§2.4–2.5 同时提供模型生成测试、执行反馈和语义评分；§4.1 的筛选消融中，LLM 评分筛选优于仅按生成测试筛选。作者指出测试错误与同模型自洽偏差。对应到本项目：区分产品缺陷与测试失误，结合执行证据和语义复核。

本次为验收机制定向核对，检查了上述方法、实验、消融与限制相关正文，后续八段论文笔记另按论文目录管理。以下是项目方案调整，属于待真实模型验证的实现要求。

### 六类需要补齐的具体证据

| 类型 | 重点补齐 | 具体例子 |
|---|---|---|
| Text Generate | 从 query 先列页面角色与必要结果，再与 GT 核对；每页需有真实入口和相应内容 | 四个 HTML 齐全但 Catalog 空白仍为缺陷；查询 DOM 中实际图书与筛选结果 |
| Image Generate | 建立参考图→页面/状态→动作映射，检查参考图是否足以支持要求的 GT 内容；区分视觉相似与行为正确 | 一个菜单展开截图应对应真正能打开的菜单；初始截图无法确定的隐藏业务规则另列证据需求 |
| Text Edit | 同一行为在 source 是否已具备、target 是否按要求改变；按受影响范围回放原有功能 | 新增筛选应实际改变结果集；改默认排序可从已有排序开始，不能一律要求 source 完全没有该能力 |
| Image Edit | Text Edit 全部要求，加 source 图片与真实 source 的版本、路由、状态对应及非目标视觉区域保护 | 当前截图不能错用编辑后的图；新增侧栏后原内容和移动端布局仍应正确 |
| Text Repair | 原故障的可观察证据、target 恢复、原有功能保留；额外检查问题能否仅凭模型可见材料诊断，独立缺陷数 N 与测试数分开 | 一个缺陷可以让多个测试失败；只有 clean 图才知道的任意配色差异不直接当成可诊断文字故障 |
| Image Repair | Text Repair 的功能保证加 faulty/clean 图的页面与状态配对；图像中未变的页面按具体修复范围判断 | 只修第二页时其他页面图可相同；交互缺陷通过对应操作后的状态证明 |

### 轻量调用顺序与校准

1. 脚本整理原始模型输入、GT、资源与浏览器事实，保存版本哈希。模型可见输入与内部 GT/缺陷信息分开。
2. 由 LLM 从任务可见要求推导待检查结果，再结合 GT 与浏览器证据定位差异；选择器可以参考代码，预期结果以任务要求为依据。禁止按“GT 现在做了什么”倒推所有正确答案。
3. 脚本执行检查。LLM 结合失败证据区分产品问题、错误测试、环境异常；返回 query 改写或精确 patch 候选，由脚本应用。LLM 自评通过仍需相应运行证据。
4. 修复前后的对应检查固定保存；改 query 时列出改变的要求，并复核新 query 与 GT 的一致性。修 Repair 的公共底座时，要同步维护故障版本、GT、问题数、patch 和图片。
5. 用已固定的失败版、回测正确版、原本正确但截图无变化的 Repair、错误测试/环境失败四种情形校准。分别统计漏检和误拒；经手工修复的调试参照从自动修复成功率中排除。

预算优先安排确定性检查、复用同一项目的运行结果；语义调用与视觉调用按任务需要分配。复杂样本可减少本轮尝试，证据覆盖不足时标记待补。每项核心要求都要有对应证据，测试预算不能被误用为“只测六项其余默认通过”。query 长度、细节密度和任务难度分别统计；全量剔除与 50k 底线一起核算，保留语义与来源多样性。

当前实现边界：分任务结构适配和浏览器取证已验证；上述自动语义流程、任务专用准入判断与实际收费上限控制仍待 API 恢复后的单样本验证。

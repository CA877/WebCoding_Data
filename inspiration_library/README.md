# 灵感库生成与连续 Edit 链生成

本模块包含两条相接的流程：从网页积累可迁移的功能灵感，再针对一个目标网页生成连续的完整 Edit 任务。

## 1. 灵感库生成

```text
公开 URL / 本地网页项目
→ 桌面与移动端浏览器观察
→ 自动操作 + LLM 多步探索
→ LLM 抽取功能灵感
→ 定位局部参考代码
→ capability_pool.jsonl
```

统一入口：[mine_live_url_capability_pool.py](../scripts/mine_live_url_capability_pool.py)，单来源监管入口：[run_live_url_audit_case.py](../scripts/run_live_url_audit_case.py)。

输入使用 sources JSONL，每行一个来源：

```json
{"seed_id":"demo_url","entry_url":"https://example.com/demo"}
```

或在 `--mode local_project` 下：

```json
{"seed_id":"demo_project","project_path":"/absolute/path/to/project"}
```

本地项目当前要求可通过 index.html 直接运行。两种来源共用探索和抽卡方法；本地从项目文件定位源码，在线从页面获取局部 DOM/CSS/JS 和公开示例。实际挖掘在项目运行服务器执行，开发机用于编辑、单元测试和查看结果。

- `scan`：只采集浏览器事实，无 LLM 调用。
- `full`：自带基线采集、探索、抽卡和参考代码获取。
- 在线 `--source-mode reference/examples/none` 分别获取局部参考、仅公开示例、仅灵感。
- 探索结合事件监听、委托 selector、Shadow DOM 和可见 iframe；最多四轮自动探索共享原两轮总路径预算，继续尝试状态变化的控件。reference 按证据动作重放后在当前页面取码，输出可用 HTML/CSS/JS 参考与模块文件；大 bundle 保留在 closure 目录，具体依赖问题单独记录。
- 旧功能卡保留可读性；新版产品Session通过`--product-patterns`增加产品流程记录及卡片关联/分类。
- 参考代码先按卡各尝试一个观察区域，再轮转分配额外区域。默认四区域预算不足以覆盖所有卡时，提升到首轮覆盖所需数量；例如七张卡各有不同区域时先尝试七个区域。定位或加载失败保留实际已取得的片段，输入输出格式保持不变。

卡片主要保存 `capability_id/change_type/summary/requires/user_actions/produces/visible_result/future_uses/source_slices`，并附现有来源和观察关联。原始观察、截图及参考文件单独保存。卡片数量由实际观察决定。

## 2. 产品方向与连续 Edit Session（当前主线）

```text
目标网页 + 真实观察 + 产品流程/功能灵感库
→ 均匀随机抽取N∈[4,12]并保存
→ 选择一个产品演化方向
→ 按产品方向与实际状态召回Top-K灵感
→ 输入Seed简介、主任务转变方向、Top-K灵感、当前浏览器信息及简短Edit记录，生成下一项Capability、Edit、分类及唯一browser_check
→ 现有Harness执行和验证
→ 检查目标网页及相关状态中的适用11类缺陷，汇总分类和失败证据
→ 有真实失败时一次Repair修复全部问题，复测原流程及同一组缺陷检查
→ 更新实际网页，合成该状态的独立Generate需求
→ 导出本步Edit、Generate及有效自然Repair
→ 重复至N步完成
```

单Session入口为`run_product_edit_session.py`，批量入口为`run_product_edit_batch.py --manifest <jobs.jsonl> --max-sessions N`。批量清单逐行指定seed文件和独立run_dir，串行调用同一Session实现，状态保存到batch_state.json；Harness使用顶层独立仓库的`run_product_session_step.py`。初始化仅保存产品方向和总N，不预先生成完整能力计划；每步依据已完成的真实状态决定下一项能力，允许多个真实前序依赖。16类完整定义集中在`edit_taxonomy.py`。先确定产品方向及所需能力，再优先采用符合16类行为的功能设计，最后生成Edit并分类。该顺序在规划Prompt内引导，最终指令隐藏benchmark元数据；扩展类需解释实际必要性，多标签不增加任务数。

建库增加`--product-patterns`，输出`product_patterns.jsonl`及关联功能卡；旧库缺少产品层时需按真实来源更新。小库用LLM语义选择产品方向；每步另做语义Top-K召回（默认--top-k 3），再单次生成Edit。Edit请求不传整库或网页源码，历史每步仅保留edit_id和一句功能摘要summary；召回与生成分别计量。仅在本条Edit确定引用后，按inspiration_refs取库内参考代码交给Harness；不提前给召回/指令生成模型，重复代码去重，缺失代码如实记录。当前试点限制32产品/128卡，具有本地入口的单页/多页静态项目；真实小样本通过后再扩量。

每个已验收状态S1–SN各导出一条Generate，独立需求与对应完整源码绑定；恢复补缺去重，终态不额外重复导出。

输入输出、运行参数、完整16类和本次验证记录见[产品Edit Session](../docs/product_edit_session.md)。`run_linear_edit_query_augmentation.py`保留为历史一次性生成链入口，不能代替新的实际状态反馈流程。

## 3. 代码阅读顺序

| 文件 | 职责 |
|---|---|
| [production_browser.py](production_browser.py) | 启动页面、执行动作、采集页面事实 |
| [deep_browser_exploration.py](deep_browser_exploration.py) | 自动与 LLM 路径探索、状态合并和压缩 |
| [dynamic_capability_retrieval.py](dynamic_capability_retrieval.py) | 抽卡、卡池合并及共用工具；也保留部分旧逐轮检索逻辑 |
| [live_component_sources.py](live_component_sources.py) | 在线局部参考代码获取 |
| [component_closure.py](component_closure.py) | 单个组件的 HTML/CSS/JS 依赖闭包提取，含事件记录器注入；也可独立作 CLI 运行 |
| [one_shot_capability_retrieval.py](one_shot_capability_retrieval.py) | 本地代码片段、检索 query、Top-K 和功能计划 |
| [linear_edit_queries.py](linear_edit_queries.py) | 指令生成、结构约束与数据格式 |
| [doc_api.py](doc_api.py) | 模型接口与请求/用量记录 |

先看两个主入口，再沿调用关系阅读上述模块即可。

## 4. 配置与运行

项目聊天默认使用 TokenWave gpt-5.5；各入口的历史客户端默认值可能不同，运行前显式配置供应商与模型。Edit 监管入口使用 TOKENWAVE_API_KEY / TOKENWAVE_OPENAI_API_KEY 等受保护凭据。embedding 服务独立配置，复用向量时使用原模型和维度。密钥通过环境或监管器 stdin 注入。

先从仓库根目录查看单样本入口参数：

```bash
uv run python scripts/run_live_url_audit_case.py --help
uv run python scripts/run_edit_instruction_case.py --help
```

使用实际来源清单、项目路径、卡池路径和新运行目录；避免直接沿用代码中的机器专用默认路径。单样本监管器提供尝试量限制、心跳、进程超时与子进程清理；批次参数按实际计算资源配置。

在线批量先通过单来源实跑，逐条保存灵感卡和产品流程。当前运行使用 TokenWave `gpt-5.5`、并发 1、`--source-mode none`：跳过组件参考代码提取，保留原有输出结构与浏览器观察证据。已有代码片段保留，新卡不保证带参考代码。每次尝试默认 600 秒，整批无累计时限。

2026-09-13 精简版真实单样本通过：CookieConsent Playground，6 张卡，80.63 秒；关闭模型补充探索及探索轮次中的重复移动端观察，保留一轮自动交互、卡片提取和产品流程整理。2 次 TokenWave `gpt-5.5` 调用共 22,218 tokens，未产生组件取码目录。物理机运行目录为 `/data2/adminweihunj/webcoding/inspiration_library/runs/kimi28_online_1000_20260913/batch_tokenwave_streamlined_v2`；生产服务 `inspiration-tokenwave-streamlined-v4-production-20260913.service`，并发 1。实时进度以该目录 `batch_status.json` 为准。

2026-09-14 将当时尚未派发的 897 个来源按 1:3:1 分为互斥分片：TokenWave `gpt-5.5` 180 个、GLM `glm-5.2` 538 个、Kimi `kimi-for-coding` 179 个，对应来源并发 1、3、1。分片及独立运行目录位于物理机 `provider_shards_20260914/`，各自维护 `results.jsonl`，不共享写入。GLM Coding 接口使用文本 DOM、布局和交互证据，不发送截图；Kimi 单样本完成，GLM 实际调用完成但首个语义结果按样本失败记录，均不阻断生产派发。

自动探索按目标任务给控件排序：优先示例组件、表单、弹窗、标签组和菜单内部的按钮、输入框及菜单项；Header、导航、Support、代码工具栏和文档 API 表格降权。目标组件没有足够相关的新控件时结束探索，不用外围控件补足路径数。Radix Tabs 真实单样本只执行 `Account`、`Password` 两个标签，随后停止探索并成功生成 3 张卡，耗时 152.08 秒。

网页先直连，连接失败、超时或 HTTP 错误时改走配置的代理；两路均失败只跳过当前来源，继续派发。取消 robots 前置请求。后续观察沿用本次成功的浏览器线路；模型 API 线路独立配置。仅下述明确全局故障停止整批；成功来源不重跑，诊断后的旧失败/中断通过 `--retry-seed-id <id>` 显式恢复，累计最多 3 次。`results.jsonl` 保留历史，`run_dir` 指向该次监管目录，卡池位于其 `miner/` 下。生产部署使用 systemd 控制组清理和 watchdog。凭据仅通过环境或 stdin 注入。

## 5. 相关测试

完整功能建库口径：单张卡应能支撑一个与 WebCompass 16 类 Edit 同等粒度的独立任务，相关控件、状态、反馈和展示合并为功能。抽取使用 `edit_taxonomy.py` 的既有定义作为范围参照，也允许同等粒度的扩展；只观察到静态说明、属性或组件外壳时保存空结果并继续下一来源。输入 URL/本地项目及输出 schema 不变。具体规则见 [灵感构造流程](../docs/inspiration_library.md)。此前 Tabs 的三张展示类卡只说明旧流程跑通，不满足本次完整功能口径。

2026-09-14 真实 Element Plus Table 验证：浏览器分别操作多选行和展开行，TokenWave `gpt-5.5` 将两条动作、选择状态、展开状态和结果区域合成一张 `data_table_selection_and_expansion` 卡，完整运行 `status=ok`，耗时 233.02 秒。另一个排序目标因没有观察到排序后的行顺序与方向而返回空卡；空卡路径跳过产品流程生成并继续批次。相关本地测试 6 项通过。

耗时优化优先控制重复输出：能力卡和产品流程使用紧凑 JSON、简短事实描述，保留全部必要字段、完整动作、触发/结果引用及限制说明；不硬降输出上限，不按数量裁掉能力卡，不降低模型或推理等级。以真实调用的耗时、输出量及覆盖情况判断收益，而不是仅依据输入 token 数。

能力卡提取后，产品流程生成与参考代码提取并行执行，两者独立落盘，再汇合输出原有卡池与产品流程文件。产品生成仅使用已有行为字段，不依赖参考代码；来源并发数和每来源 LLM 并发数不增加。某一分支失败时保留另一分支已保存的结果，单来源超时仍由监管器统一限制。

模型输入优化由 `prompt_evidence.py` 维护：沿用现有 DOM/AX 语义视图与基线/交互差量，把重复控件字段编码为列与行，把相似记录编码为基线及独立 set/remove 差量，并将重复长证据保存一次、使用引用。编码可还原原模型视图，短输入或包含保留标记时回退普通 JSON。探索保留操作选择器，能力卡提取沿用行为证据视图，产品阶段只读行为字段并排除来源调度权重和登记日期；原始观察、来源记录、参考代码及输出 schema 不变。截图仅按内容精确去重，共用图片保留全部状态 ID，不降低分辨率。编码还原测试及真实 LLM 小样本用于改动验证，不增加生产审核门禁。

探索阶段的选择器及控件记录保持直读；能力提取的动作/状态记录保持直读，并提供精简 action_steps 链，避免省略尚未产生 DOM 变化的触发动作。交互卡须同时引用触发动作和后续结果状态。截图去重后的空位可补充其他不同状态，仍受原八张/12 MiB 上限限制，因此去重不等于减少最终图片数量。前后实测可运行 `tests/run_inspiration_prompt_ab.py`，通过 `--stages`、`--modes` 只复测受影响阶段；真实测试需使用受保护凭据及单工作单元监管器。

并发默认 2，显式 `--concurrency 1..8` 可调整；续跑允许只改变并发，模型/来源等身份仍必须一致。实际并发记录在 batch_status.json，batch_identity.json 中的并发是首次启动值。`--max-new-sources N` 限制本轮派发来源数，用于有界试跑；完成后去掉此参数可继续原队列，已完成来源不重复。

批量错误以 worker 的 `worker_failure.json` 结构化类别为准，旧日志识别仅用于兼容。默认隔离单来源异常：校验失败记为 `sample_check_failed`，未知异常为 `sample_error`，单次硬超时为 `timeout`；保留产物和错误，不计成功、不杀其他 worker。只有显式全局错误（API 鉴权/额度、运行时依赖缺失、磁盘/内存等资源故障）或用户取消才停止整批。

空响应、流意外结束、API 408/409/429/5xx 和传输错误仅重试失败请求，最多 3 次尝试，退避 5、10 秒；保留此前浏览器和 LLM 阶段，不重跑整个来源、不暂停其他派发。耗尽只记录当前来源失败。输出长度截断、内容过滤和样本校验失败不以相同参数重试。所有尝试及用量独立保留；批次独占锁防止重复启动调度器。SDK 自身重试仍关闭。

从仓库根目录运行：

```bash
uv run pytest -q \
  tests/test_inspiration_modes_and_library.py \
  tests/test_live_mining_evidence_fixes.py \
  tests/test_live_component_sources.py \
  tests/test_edit_chain_integration.py \
  tests/test_one_shot_capability_retrieval.py \
  tests/test_linear_edit_query_augmentation.py
```

测试覆盖输入输出、代码引用、检索及生成接线与结构约束。模型生成效果使用真实小样本另行调试。

# WebCoding 项目规则与路由

## 项目目标

面向 WebCompass 等 Web Coding benchmark 构造可用于 SFT 的 Generate、Edit、Repair 网页数据，覆盖文本/图像与单页/多页输入，并与目标任务语义、输入协议、patch 和浏览器评测对齐。

数据来自互补但不可混淆的两条路线：

- **Reverse / controlled producer**：`reverse/` 从清洁网页项目受控构造数据，侧重覆盖和配额。
- **Forward / agentic producer**：`harness/` 集成 Harness、灵感库和连续 Edit 指令规划；它通过 planner → generator → evaluator 产生实现轨迹，Edit 基于 accepted baseline，Repair 对应实际复现的缺陷。

## 五个工作板块

项目按职责分为五个板块。处理某个板块的任务时，先阅读该板块目录内最近的
`AGENTS.md`。

| 板块 | 主要目录 | 职责边界 |
| --- | --- | --- |
| 逆向数据构造 | `reverse/`、`crawl/`、`validate/` | 从清洁网页、母本和 benchmark 约束出发，受控构造 Generate/Edit/Repair 数据，处理查询、网页快照、资源闭包、任务变换、验证和 release admission。这里的产物是否可训练必须遵循数据 schema、证据链和验收状态，不能把 candidate 或 pilot 自动称为 canonical。 |
| 正向数据构造（灵感库） | `inspiration_library/` | 从真实网页和能力证据中挖掘可复用的交互、视觉和功能灵感，规划连续 Edit 能力与目标状态，形成供 Harness 或后续构造消费的结构化灵感资产。灵感、候选和已接收训练数据必须保持状态区分。 |
| 训练 | `Webcoding-Model-Project/` 的训练配置、数据导出和 `LLaMA-Factory/` | 管理 ShareGPT/多模态训练协议、数据注册、token 长度和过滤、Qwen3-VL SFT 配置、训练启动、checkpoint、训练日志及训练侧 smoke 验证。训练参数和数据快照以该独立仓的 run 目录及其训练文档为准。 |
| 评测 | `evaluate/` 以及 `Webcoding-Model-Project/benchmark/`、各 run 的 `eval/` | 管理 WebCompass、ArtifactsBench、WebGen-Bench、Vision2Web 等推理、渲染、判分和结果归档。评测采样参数、模型版本、基线对照、失败分类和分数口径必须与训练配置和正式评测文档分开记录，不能用局部 smoke 或历史分数代替正式结果。 |
| Harness | `harness/` | 管理 planner → generator → evaluator 的 agentic 生产链、浏览器执行、连续 Edit 规划、accepted baseline、Repair 缺陷复现和运行轨迹。它是独立 Git 仓，任务状态和运行产物遵循 `harness/` 内部文档，不直接改写逆向路线或训练 release。 |


## 全局不变量

- 复用现有实现和 schema，保持最小必要改动；实现细则不明确时先核对官方 WebCompass 样本/代码或询问用户，不能猜测。
- 未经明确要求，不新增独立审核模型、judge、reviewer 或基于其结果的筛选门禁。
- 修改代码、配置、脚本、提示词或数据流程后，运行覆盖改动路径的真实小样本；涉及 LLM 的行为必须有真实 LLM 调用。纯文档改动只做文档核验。
- 默认直接交付可用结果；正式发布所需门禁仍按用户要求执行。不要把候选、局部门禁或历史报告混称为 accepted/canonical。
- 批处理不能因单个 case 失败停止整批；单 case 失败须真实记录，整批停止条件见 [batch_jobs.md](docs/operations/batch_jobs.md)。
- 凭据只从受保护来源注入，不写入代码、文档、日志、manifest 或提交记录。
- 默认 LLM 为 TokenWave `gpt-5.5`；API 使用、重试和真实验证见 [api_usage.md](docs/operations/api_usage.md)。

## 任务路由

| 请求 | 先使用 |
| --- | --- |
| 构造、扩增、审计 Generate/Edit/Repair 数据 | `synthesize-data` |
| 规划连续 Edit 指令 | `generate-edit-instructions` |
| 抓取母本、网页快照或资源闭包 | `crawl-web-pages` |
| 运行或调试 Harness | `run-webcoding-harness` |
| 查 URL 候选池 / 历史抓取 | `webcoding-url-pools` / `webcoding-crawl-results` |
| 挖掘网页功能灵感 | `mine-webcoding-inspiration` |
| 解释 WebCompass Edit 类型 | `webcompass-edit-types` |
| 整理、交付或发布数据集 | `publish-dataset` |
| 阅读论文 / 写 WebCoding 论文 | `read-papers` / `write-paper` |
| 长期规则、路由或 owner 变化 | `maintain-webcoding-rules` |

## Source of Truth

- 架构：[project_architecture.md](docs/architecture/project_architecture.md)
- 数据构造语义与输入协议：[construction_spec.md](validate/docs/data/construction_spec.md)
- 数据资产、版本与允许用途：[data_assets_registry.md](validate/docs/data/data_assets_registry.md)
- 当前数据构造流程：`harness/docs/synthesis/pipeline.md`（在独立仓 `harness/` 内，本仓不追踪）
- 浏览器与正式评测口径：[evaluation_protocol.md](evaluate/docs/evaluation/evaluation_protocol.md)
- 环境、批处理、API 和发布：[operations/](docs/operations/)
- 当前状态：[current_state.md](docs/current_state.md)
- 完整文档地图：[docs/README.md](docs/README.md)

术语、数据事实、运行命令、实验数量和历史结论均由上述唯一 owner 维护；其他文件只引用，不复制。

## 知识维护

新要求先判断归属：全项目行为约束 → 本文件；某类任务工作流 → 对应 skill；项目事实/设计 → 对应模块 `docs/`；运行细节 → `docs/operations/`；当前进度 → `docs/current_state.md`；保留的实验结论 → 对应模块 `docs/` 或运行目录。没有跨任务价值的临时要求不持久化。

全项目不变量在 `AGENTS.md`；任务工作流在 skill；项目事实/设计在 `docs/`；运行细节在 `docs/operations/`；状态在 `docs/current_state.md`；历史结论在报告或 archive。

迁移或修改规则时，保留原信息、更新引用并删除完整重复副本；不要把临时参数、进度或单次例外升级为长期规则。规则改变数据语义、运行行为或接口时，同步更新实现和权威文档；用户仅要求文档时不扩大为实现任务。

## 发布数据的要求

先读取 [发布运行手册](../../../docs/operations/publishing.md)、[数据资产登记](../../../validation/docs/data/data_assets_registry.md)和目标 release 的 manifest。确认用户授权的源版本、目标仓库、目标路径和覆盖范围后，再执行任何上传。

保留记录语义、schema、图片角色和现有数据；需要字段或 prompt 对齐时转用 `synthesize-data`。发布后核验文件清单、索引、哈希与远端结果，并报告版本、目标和兼容边界。


## 远程机器
### 代码同步原则
代码修改必须要在本地完成，然后同步到远程机器上，两者代码需要保持一致，除了部分内容不需要同步到物理机上。


### 物理机
- SSH：`ssh -p 65022 adminweihunj@36.213.175.38`；凭据使用受保护来源。
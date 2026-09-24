# WebCoding 项目规则与路由

## 项目目标

面向 WebCompass 等 Web Coding benchmark 构造可用于 SFT 的 Generate、Edit、Repair 网页数据，覆盖文本/图像与单页/多页输入，并与目标任务语义、输入协议、patch 和浏览器评测对齐。

要刷的benchmark榜单：Artifactsbench、Webcompass、Vision2Web、WebGen-Bench、Interaction2Code、Flame-VLM-Code

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

- 多页按实际页面视图与导航行为判定：单 HTML 配合 hash 路由实现多个页面视图，也可以认作多页；构造、检查和验收不得仅因只有一个 HTML 文件或使用 hash 路由而判定不符合多页要求。
- 用户要求“造一些 case 和 benchmark 对齐”时，Generate case 的 query 应与对应 benchmark query 在长度、风格、内容和技术栈等方面对齐；Edit、Repair case 的 query 应与对应 benchmark query 在难度、任务数量等方面对齐。
- 复用现有实现和 schema，保持最小必要改动；实现细则不明确时先核对官方 WebCompass 样本/代码或询问用户，不能猜测。
- 原则是尽可能复用原始结果（前提是在各种运行条件都没有改变的前提下），从而节省成本。
- 数据补充、修复和优化阶段，新产物须先确认质量符合当前任务要求，再加入当前指定的正式发布版本，或替换其中原本有问题的数据；同步更新索引与清单，不得将新数据长期零散留在运行目录或另作一套最终交付。未通过质量确认的产物应明确标注状态，不得混入正式可用数据。
- 合入正式版本目录后，确认记录、代码和依赖资源完整、可读取且替换正确，再清理本轮临时文件、重复导出、暂存副本、被替代的数据及临时备份，只保留必要的来源和清理记录；仍被未迁移数据或在运行任务引用的共享资源须保留，直至依赖一并迁移。
- 构造 Generate、Edit、Repair case 时采用逐 case 可恢复的 agent 增量循环：保存每轮产物、校验反馈和调用用量；先确定性修复可无歧义处理的格式问题，仍有缺口时向 LLM 提供当前产物与具体错误，只生成受影响的文件或 patch，并在已有状态上继续校验。仅当现有产物无法可靠修补时重新生成整条 case。
- 修改代码、配置、脚本、提示词或数据流程后，运行覆盖改动路径的真实小样本；涉及 LLM 的行为必须有真实 LLM 调用。纯文档改动只做文档核验。
- 默认直接交付可用结果；正式发布所需门禁仍按用户要求执行。
- 批处理不能因单个 case 失败停止整批；单 case 失败须真实记录，批处理细则见 `docs/batch-running.md`（如适用）。
- 默认 LLM 为 Nju-Link的base url的模型 `gpt-5.6-luna`，默认使用流式调用；
- 远程批处理、浏览器渲染、数据生成和上传启动前，先完成一个真实小样本；明确尝试量、样本量、并发、单工作单元超时、存活保护、中断和子进程清理。
- 真实小样本通过且已授权批量运行时，直接在物理机启动批处理；默认不启用周期心跳或自动监控，保留逐 case 进度日志、超时和资源保护。
- 整批不设置累计运行时限：主进程、监控、外层 shell/systemd 和代理隧道不得因累计时长退出。保留单请求/单 case 超时、资源保护。
- 单个样本的内容、格式、证据或质量检查失败时，记录失败并继续其他样本；只有系统性故障、数据损坏风险、资源危险、鉴权或额度阻塞或用户取消才暂停整批。网页访问必须走代理，仍不可达则跳过该来源，不视为全局网络故障。网关限流及 API 临时错误只对失败请求有界重试（最多 3 次，退避 5、10 秒），不重跑整来源、不暂停派发 5 分钟；重试耗尽记录该来源失败并继续。共享物理机运行前后检查 CPU、内存和 I/O，并按负载降并发或停止。

## 生成类任务首次尝试必须人工检查

对于生成类任务（例如生成 query、网页结果、数据 case 或其他需要验收的产物），**第一次尝试完成后必须立即停止继续扩展或批量执行**。

必须先用中文向我汇报本次尝试的：

* 实际执行结果
* 关键输出或样例
* 是否达到预期
* 暴露的问题与风险

然后**明确提醒我进行检查**，等待我确认后才能继续下一步。

禁止在第一次生成结果尚未经过我检查时，自动继续批量运行、扩大规模、修改方案或进入下一阶段。

代码整理、代码同步、文档修改和其他不产生待验收生成结果的任务不受本节暂停要求限制，可在授权范围内直接完成并验证。

“效仿实现”必须做实质对齐

如果我要求效仿某份代码、某个项目或某个已有实现，含义不是只参考整体思路，而是应尽可能从具体实现层面对齐，包括但不限于：

参数与默认配置
Prompt / System Prompt / 模板
输入输出格式
调用方式与执行流程
模型与工具配置
采样、重试、过滤、验证等策略
关键代码结构与实现细节

必须先检查参考实现中的具体做法，再决定如何迁移。禁止只根据项目描述、论文摘要或自己的理解进行“近似复现”。

## 任务路由

| 请求 | 先使用 |
| --- | --- |
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

- 架构：本文件的项目目标、五个工作板块和 Source of Truth 章节
- 数据构造语义与输入协议：[construction_spec.md](validate/docs/data/construction_spec.md)
- 数据资产、版本与允许用途：`validate/docs/` 及当前 release manifest。
- 当前数据构造流程：`harness/docs/synthesis/pipeline.md`（在独立仓 `harness/` 内，本仓不追踪）
- 浏览器与正式评测口径：[evaluation_protocol.md](evaluate/docs/evaluation/evaluation_protocol.md)
- 环境、批处理、API 和发布：[operations/](docs/operations/)
- 当前状态：以当前 release manifest、运行记录和模块 owner 文档为准。
- 完整文档地图：[docs/README.md](docs/README.md)

术语、数据事实、运行命令、实验数量和历史结论均由上述唯一 owner 维护；其他文件只引用，不复制。

## 知识维护与文档规则

**核心原则：严格控制文档数量，严格控制技术细节。文档首先服务于人类快速理解项目，而不是记录 AI 的工作过程。**

### 文档数量

* **默认禁止新建文档。** 已有文档能够承载的信息，必须追加到已有文档中。
* 新建文档前必须确认：现有文档均无法合理承载该信息，且该内容具有长期、独立的维护价值。
* 禁止为了单次任务、一次排查、一次实验、一个技术问题单独建立文档。
* 禁止把同一事实复制到多个文档；每项信息只能有一个 Source of Truth，其他位置只引用。
* 文档必须持续压缩。过时过程、重复描述和失去价值的中间信息应删除，而不是无限累积。

### 文档内容

文档只保留对后续工作真正有价值的信息：

* 当前问题
* 已确认原因
* 最终解决方案
* 实验结论
* 关键数据
* 当前进度
* 尚未解决的问题
* 长期有效的设计决策

**禁止记录 AI 的工作流水账。**

以下内容默认不得写入长期文档：

* 排查过程
* 尝试过但无长期价值的方法
* 命令执行过程
* 运行耗时
* API 调用细节
* 模型调用过程
* 临时字段名
* 临时脚本
* 中间日志
* 调试输出
* 环境安装过程
* 无长期价值的参数
* “先做了什么，再做了什么”式过程描述

需要保留的技术细节只能进入对应的实现文档、运行目录、日志或代码注释，不得污染项目状态文档和人类阅读文档。

### 人类阅读文档

用于我查看项目状态、问题和解决方案的文档，**必须保持极简、结论优先、人类可读。**

这类文档只回答四个问题：

> **发生了什么问题？**
> **问题为什么重要？**
> **现在是否解决？**
> **最终结论是什么？**

**严禁写入技术实现和排查细节。**

包括但不限于：

* 用了什么模型
* 跑了多少次
* 花了多久
* 调用了什么 API
* 使用了哪些具体字段
* 执行了什么命令
* 中间出现了什么报错
* 如何一步步排查
* 临时 workaround
* 具体脚本实现
* 无助于理解最终结论的实验过程

判断一条信息是否应该进入此类文档，只使用一个标准：

> **如果删除这条信息后，我仍然能够判断“现在有什么问题、解决到哪一步、结论是什么”，就不要写。**

### 表达要求

* 用最短的句子表达最高信息密度的事实。
* 用户要求简洁时，只写最短结论；证据仅保留必要的路径或数字，不展开证据链。
* 优先写结论，不写过程。
* 优先写数字和明确状态，不写模糊描述。
* 禁止防御性表达、解释性废话和无信息量限定语。
* 禁止“我们没有……”“这并不意味着……”“需要注意的是……”等无实际结论的铺垫。
* 不记录数据链接、运行口径、技术背景等我明确不关心的信息。
* 一个问题原则上控制在：**问题 → 结论/原因 → 解决状态** 三部分内。

### 信息归属

* 全项目长期行为约束 → `AGENTS.md`
* 某类任务工作流 → 对应 skill
* 项目设计和稳定事实 → 对应模块 `docs/`
* 运行、部署、批处理细节 → `docs/operations/` 或运行目录
* 当前整体进度 → 当前 release manifest、运行记录和模块 owner 文档
* 单次运行日志和调试信息 → run/log 目录
* 人类查看的问题追踪 → 对应问题文档，只保留问题、结论和状态

**技术细节有地方保存，但不得进入面向我阅读的项目主文档。**


## 发布数据的要求

使用 `publish-dataset` skill；先读取 `validate/docs/` 中的数据资产登记和目标 release 的 manifest。确认用户授权的源版本、目标仓库、目标路径和覆盖范围后，再执行任何上传。

保留记录语义、schema、图片角色和现有数据；需要字段或 prompt 对齐时转用 `synthesize-data`。发布后核验文件清单、索引、哈希与远端结果，并报告版本、目标和兼容边界。


## 远程机器
### 代码同步原则
代码修改必须先在本地完成，再同步到物理机；本地与物理机上的对应代码应保持一致，明确不需要同步的内容除外。同步前后应核对目标路径和文件内容，避免只在物理机上直接修改代码。


### 物理机

- SSH：`ssh -p 65022 adminweihunj@36.213.175.38`
- WebCoding 数据根目录：`/data2/adminweihunj/webcoding/WebCoding_Data`
- 正式 release 根目录：`/data2/adminweihunj/webcoding/WebCoding_Data/releases`
- “0921”默认指本轮优化数据，唯一正式读写目录为 `/data2/adminweihunj/webcoding/WebCoding_Data/releases/0921/`；本轮后续优化产物直接更新这里，`runs/` 仅承载运行日志、断点和回滚材料。
- 当前数据版本、数量和具体 release 路径以 [`docs/数据发布版本.md`](docs/数据发布版本.md) 中的 manifest 记录为准。
- 0905版本在物理机上的路径：/data2/adminweihunj/webcoding/WebCoding_Data/runs/delivery_0905_incremental_20260913/

### 服务器（GPU）


参考/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/Webcoding-Model-Project/AGENTS.md文档。

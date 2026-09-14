# WebCoding 项目规则与路由

## 项目目标

面向 WebCompass 等 Web Coding benchmark 构造可用于 SFT 的 Generate、Edit、Repair 网页数据，覆盖文本/图像与单页/多页输入，并与目标任务语义、输入协议、patch 和浏览器评测对齐。

数据来自互补但不可混淆的两条路线：

- **Reverse / controlled producer**：`reverse/` 从清洁网页项目受控构造数据，侧重覆盖和配额。
- **Forward / agentic producer**：`harness/` 集成 Harness、灵感库和连续 Edit 指令规划；它通过 planner → generator → evaluator 产生实现轨迹，Edit 基于 accepted baseline，Repair 对应实际复现的缺陷。

当前根目录是主仓；顶层 `harness/` 及第三方评测仓库是独立 Git 仓，分别修改、测试与推送。主仓不追踪它们的内容。

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

## 已知悬空引用

以下引用在本次目录重构前后都不指向仓库内文件，属历史遗留，保留原样待补。排查路径问题时不要把它们误判为重构遗漏，也不要在没有实现的情况下补空文件：

- `crawl/pipeline_a/main.py` 的 `from reverse.add_js import ...`：`add_js.py` 在 HEAD 和物理机上均不存在。
- `scripts/run_product_edit_session.py` 与 `scripts/run_product_edit_batch.py`：被 `configs/product_session_*` 和 `harness/docs/product_edit_session.md` 引用，从未入库，物理机上同样没有。
- `validate/docs/data/construction_spec.md` 中 3 条 `WebCoding_Data/...` 链接：指向已删除或从未入库的历史产物（`docs/handoffs/`、`docs/synthesis/`、`logs/`）。

## 已知过期测试

`tests/` 为重构前的版本，而本地 `crawl/`、`inspiration_library/` 的实现已领先该版本数百行（`crawl/pipeline_c/main.py` +815 行、`inspiration_library/production_browser.py` +306 行、`live_component_sources.py` +290 行、`deep_browser_exploration.py` +240 行、`dynamic_capability_retrieval.py` +197 行），因此部分测试断言的是已被取代的旧行为。

实测（`uv run pytest tests/ -q`）：175 通过、13 失败、2 跳过。其中：

- `test_complex_query_routing.py::test_current_1k_routes_to_expected_stable_counts` —— 缺 `runs/` 数据，**重构前后同样失败**，属环境问题。
- `test_construct_text_editing.py::test_forward_strategy_extends_original_project` —— 该文件重构前依赖已消失的 `WebCoding_Data` 包，**根本无法收集**；修好导入后才暴露为失败。
- 其余 11 个是测试落后于实现：`test_pipeline_c_absolute_resources.py`(2)、`test_pipeline_c_preflight.py`(1)、`test_pipeline_c_remote_fonts.py`(2)、`test_dynamic_capability_retrieval.py`(2)、`test_live_component_sources.py`(1)、`test_live_mining_evidence_fixes.py`(3)。

**这些失败与目录重构无关**：同一份测试在重构前的目录名下跑重构前的源码可通过，跑当前源码同样失败。物理机上同名测试文件与仓库内版本逐字节相同（仅 `test_construct_text_editing.py` 例外），故不存在"更新的测试"可补。在决定补测试还是回退实现之前，不要改动这些断言，也不要删测试来让结果变绿。

## 知识维护

新要求先判断归属：全项目行为约束 → 本文件；某类任务工作流 → 对应 skill；项目事实/设计 → 对应模块 `docs/`；运行细节 → `docs/operations/`；当前进度 → `PROJECT_STATUS.md`；保留的实验结论 → 对应模块 `docs/` 或运行目录。没有跨任务价值的临时要求不持久化。

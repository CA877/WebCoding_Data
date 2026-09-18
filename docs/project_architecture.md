

## 项目定位

- 项目面向 WebCompass、DesignBench、Interaction2Code、Vision2Web、ArtifactsBench、Design2Code、Flame-VLM-Code、WebGen-Bench、InteractWeb-Bench、FullFront、FronTalk、ComUIBench、WebUIBench 和 Web2Code。
- 重点目标是构造与 WebCompass 的领域、任务分布、输入模态和评测方式基本对齐的训练集，并通过 SFT 提升 WebCompass、WebGen-Bench 和 ArtifactsBench 等榜单表现。
- 六类任务的模型输入、输出和页面口径统一记录在 [数据集构造目标细节](../../数据集构造目标细节.md)。

## 仓库与模块分工

- `reverse/` 从已验证母本构造受控 Generate/Edit/Repair 数据。
- `Novelty_construct/` 集成 Harness 与 `inspiration_library/`，负责灵感驱动的连续 Edit、浏览器验收、自然 Repair 和数据导出。
- `crawl/` 负责网页抓取、预处理、资源本地化和资源闭包检查。
- `Benchmark_evaluation/` 保存第三方 benchmark、官方实现和评测资产。
- 顶层 `web-coding-agent/` 仍是独立仓库；它不与本仓库的 `Novelty_construct/` 自动同步。

## 数据生产主线

```text
Seed candidate
  → validate
  → accepted Seed S_k
  → novelty 生成增量指令 Δq_k
  → Harness 执行 S_k + Δq_k
  → 浏览器和保护性检查
  → accepted S_(k+1)
  → canonical Edit
  → checkpoint/complete Generate 与 natural Repair
```

- 所有蒸馏结果、benchmark GT、爬取网页和 source material 先登记为 Seed candidate。
- 通过统一 validate 的候选才获得 `accepted_seed` 身份，并成为连续 Edit 的合法起点。
- Construct 和 Harness 是互补 Producer，合并数据时保留 `producer_pipeline` 和具体 construction route。
- 相邻 accepted checkpoint 形成 canonical Edit；中间累计需求形成候选 `checkpoint_generate`；终态累计需求形成 `complete_generate`。
- 真实有效测试发现的失败并在同一 Sprint 恢复后形成 `natural_repair`，受控缺陷单独标为 `controlled_repair`。
- 每条谱系至少保留 `parent_seed_id`、`source_checkpoint_id`、`target_checkpoint_id`、`parent_trajectory_id` 和 `checkpoint_index`，同一谱系进入同一数据 split。

## 统一准入

- canonical 数据需要完整 source/target、精确可回放 patch、query–GT 对齐、target render、功能和交互证据、非目标回归、资源闭包、页面集合一致性和独立审计。
- 仅有 HTTP 200、代码可解析、patch replay、`status=ok` 或单张截图时，样本仍保持 candidate 状态。
- 更强浏览器检查推翻旧 accepted 时，旧版本失去 canonical 资格，新版本通过 supersession 成为唯一正式版本。
- 模型可见输入、hidden oracle、评测器数据、截图和运行资源分开保存，不能把隐藏答案混入生成输入。

## 能力分类与来源

- Edit 类型以 `reverse/construct_common.py::load_edit_catalog()` 和 `task_specs.py` 为代码准绳。
- WebCompass 官方 Edit 类型、Repair 缺陷类型、其他 benchmark 的能力映射和覆盖缺口见 [benchmark/query 研究](../reverse/docs/benchmark_query_coverage_research_20260820.md) 与 [Reverse construct README](../../reverse/README.md)。
- Seed 灵感库记录组件、视觉风格、布局、内容组织、交互和状态变化，并保留来源、区域、动作、前后状态和证据。

## 低上下文与安全边界

- 低上下文只压缩重复信息，provider、枚举、状态 schema、共享 handler 和 import 依赖等决定正确实现的事实必须以最小源码切片或可追溯摘要提供。
- 读取范围和写入范围分开控制，模型可以读取必要依赖，但 patch 只能修改被允许的文件、路由、DOM 区域和 selector。
- canonical 训练代码上下文遵守 40K Qwen code token 上限，灵感网页单独记录精确 token 后再按训练口径筛选。
- 资源闭包要求本地 HTTP 回放无公网请求、无本地 404、无占位资源和未声明 CDN 回退。

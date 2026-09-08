# WebCoding_Data — Web Coding 数据构造与评测

用于网页预处理、Generate/Edit/Repair 数据构造、灵感挖掘、连续 Edit 指令生成和浏览器评测。

## 模块入口

| 目录 | 用途 |
|---|---|
| [preprocess/](preprocess/README.md) | 网页抓取、清洗与资源处理 |
| [construct/](construct/README.md) | 受控 Generate/Edit/Repair 构造 |
| [instruction_augmentation/](instruction_augmentation/README.md) | 本地项目与 URL 灵感挖掘、连续 Edit 指令生成 |
| [web-coding-agent/](web-coding-agent/README.md) | 正向 Agent 与 Harness |
| web_evograph/ | 网页轨迹演化实验 |
| scripts/ | 数据处理、运行与导出工具 |
| tests/ | 行为与回归测试 |

两种数据生产路线的分工见 [DATA_PRODUCERS.md](DATA_PRODUCERS.md)。

## 合作者阅读入口

主流程：`URL / 本地网页 → 灵感库 → Top-K 灵感召回 → Edit 指令链 → Harness 实现与测试 → 数据导出`。

- **灵感库构建**：[构建入口](scripts/mine_live_url_capability_pool.py)，输出 `capability_pool.jsonl`。
- **灵感召回**：[召回与规划](instruction_augmentation/one_shot_capability_retrieval.py)，根据目标网页生成 query、召回 Top-K 并规划任务。
- **Edit 链生成**：[运行入口](scripts/run_linear_edit_query_augmentation.py)，详细流程见 [模块说明](instruction_augmentation/README.md)。
- **Harness**：[模块说明](web-coding-agent/README.md)、[链调度](web-coding-agent/scripts/run_batch.py)、[数据导出](web-coding-agent/scripts/export_trajectory_dataset.py)。源码直接包含在本仓库，普通 clone 即可获取。

Harness 使用自己的依赖环境，在 `web-coding-agent/` 内运行 `uv sync --frozen` 和 `uv run pytest -q`。向 Harness 提供已验收的 Seed 与完整 `sequences/*.json`，以保留顺序、依赖和验收信息。

## 开发环境

Python 3.11+，使用 uv 安装项目依赖：

```bash
uv sync --frozen
uv run playwright install chromium
```

相关模块的运行参数见各自 README。浏览器、模型和外部数据依赖按实际任务配置。

## 测试

```bash
uv run pytest -q
```

部分测试依赖本地数据或浏览器环境，可按模块选择测试文件。独立 Harness 的依赖和测试命令见其 README。

## 凭据与本地产物

API 密钥通过环境变量注入，变量模板见 [.env.example](.env.example)。具体模型与 endpoint 配置以对应入口为准。

内部文档、研究草稿、机器配置、数据集、运行日志、发布产物与临时文件保留在本地，由 .gitignore 排除。模块 README 中引用的内部报告按本地研究资料管理。

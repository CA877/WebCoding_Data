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

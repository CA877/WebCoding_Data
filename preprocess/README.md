# preprocess 数据预处理

本目录把网页来源处理成可供 `construct/` 使用的本地项目。当前生产入口是 Pipeline A、B；Pipeline C 用于真实网页资源闭包和质量门禁。历史实验 Pipeline D 仅作失败对照。

## 当前入口

### Pipeline A：WebRenderBench

- 实现：`pipeline_a/main.py`
- 兼容 CLI：`pipeline_a_sample_level.py`
- 启动：`run_pipeline_a.sh`
- 输入：`datasets/pipeline_a/useful`
- 处理：单页清理、可选多页扩展、按比例生成 JS、样本级超时与断点续跑

### Pipeline B：WebCode2M URL

- 实现：`pipeline_b/main.py`、`pipeline_b/postprocess.py`
- 兼容 CLI：`pipeline_b_sample_level.py`
- 启动：`run_pipeline_b.sh`
- 前置：`filter_webcode2m_urls.py`、`preflight_webcode2m_urls.py`
- 处理：Playwright 爬取、资源清理、挑战页隔离、样本级超时与断点续跑

`run_server.sh` 可并行启动 Pipeline A/B。物理机运行时使用项目 `AGENTS.md` 规定的目录、`lora` 环境和 HTTP 代理；100 条小规模预检查建议先使用 `--site-timeout 600`。

### Pipeline C：真实网页资源闭包

- 主实现：`pipeline_c/main.py`
- 页面策略：`pipeline_c/policy.py`
- token 门禁：`pipeline_c/qwen_token_gate.py`
- 最终截图：`final_screenshot.py`
- 历史数据抢救：`pipeline_c/offline_rescue.py`

Pipeline C 只保留有训练价值且能稳定渲染的页面资源。不要把旧 picsum 替换、fake URL 分区或“只保留 HTML”的历史口径重新接回当前流程。

## 辅助工具

- `playwright_crawl.py`：A/B 共用的抓取、扩展和资源处理底层实现。
- `clean_resources.py`：A/B 共用的资源清理逻辑。
- `extract_all_webcode2m_urls.py`：生成 WebCode2M 全量 URL 清单。
- `extract_commoncrawl_urls.py`、`collect_cssda_candidates.py`：候选 URL 来源工具。
- `filter_low_quality.py`、`purge_css.py`：质量过滤与 CSS 清理。
- `postprocess_webcode2m_crawl.py`：Pipeline B 后处理兼容 CLI。

## 历史对照

`pipeline_d/` 是直接抓取最终 DOM 的失败实验：其 pass 只代表 token 门禁通过，不代表完成资源闭包、截图或质量验收。不得将其输出直接作为训练数据。保留代码是为了复现实验结论和运行现有回归测试。

## 已移除的旧流程

以下流程已经被当前实现替代，不应再引用：独立 `expand_only`、小批量 HF rows URL 提取、picsum 重截图/背景尺寸修补、`fake_url` 五任务分区，以及旧 fast/test shell 入口。

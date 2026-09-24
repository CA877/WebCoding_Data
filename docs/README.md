# WebCoding Documentation Index

本文档中心只负责导航。当前事实以源码、配置、manifest、追加式运行记录和相应 canonical 文档为准；带日期的报告只代表其记录时的状态。

## Architecture

- 仓库关系、producer 分工和主数据流：见根目录 `AGENTS.md`。

## Four module boards

- [reverse/docs/](../reverse/docs/)：受控构造、reversed 数据、任务语义与母本准入。
- [harness/docs/](../harness/docs/)：Harness、灵感库、产品 Session 与连续 Edit。
- [evaluate/docs/](../evaluate/docs/)：第三方 benchmark、query 研究与正式评测协议。
- [crawl/docs/](../crawl/docs/)：网页来源、抓取、URL 候选池与资源闭包资产。
- [validate/docs/](../validate/docs/)：数据资产台账、质量检查策略与 release 校验。

## Operations

- `docs/batch-running.md`：批处理生命周期、失败处理和共享机器保护（如存在对应模块文档）。
- `docs/environment.md`：环境、代理和凭据边界（如存在对应模块文档）。
- API 调用与验证规则以当前模块运行文档和项目规则为准。
- `publish-dataset` skill：打包、兼容布局、ModelScope 上传和发布后核验。
- [crawl/assets.md](crawl/assets.md)：URL 候选池与爬取资产口径；具体爬取过程见 `crawl-web-pages` skill 的 `references/pipelines.md`。

## Current status and retained evidence

- [docs/数据发布版本.md](数据发布版本.md)：当前数据版本与发布路径。
- 模块目录中的交接文档：仅保留仍可继续执行的模块交接。

已被现行规范覆盖的旧计划、状态快照、聊天汇总与中间试验说明不再保留在 `docs/`；需要复核时以 Git、运行目录、manifest 和正式数据索引为准。

新增内容应先确定唯一 owner：项目级不变量在根 `AGENTS.md`，任务流程在 `.agents/skills/`，事实/设计在本目录，运行细节在 `operations/`，状态在状态文件，实验结论在报告。

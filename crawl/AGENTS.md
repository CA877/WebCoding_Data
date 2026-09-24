# crawl 目录规则与文档索引

## 职责

`crawl/` 将网页来源处理成可供 `reverse/` 消费的本地项目，也维护 URL 候选池、资源闭包和回放证据。抓取候选、灵感候选、accepted Seed 与 canonical 训练数据必须保持状态区分。

## 唯一入口

- `README.md`：Pipeline A/B/C/D、Pipeline Mothers、运行保护和已废弃流程的总览。
- `docs/assets.md`：URL 池的来源、路径、筛选程度和适用范围；查询 URL 池不启动抓取。
- `.agents/skills/crawl-web-pages/`：实际抓取工作流；`.agents/skills/webcoding-crawl-results/`：历史结果查询。

## Pipeline 口径

- Pipeline A/B：WebRenderBench 与 WebCode2M 的常规预处理。
- Pipeline C：严格离线资源闭包；HTML/CSS/JS 全部进入模型输入并计入 Qwen 40K，二进制进入 `resources/`；超限、资源失败或离线回放失败即拒绝。
- Pipeline D：保留外链并验证联网回放；只保存 HTML/metadata，外链失败按 admission warning 或拒绝规则记录，不能冒充 Pipeline C。
- Pipeline Mothers：多页在线母本候选，优先真实首页入口和同站子页；结果默认是 `online_mother_candidate`，不是 accepted Generate GT。

## 不变量

- 网页访问走代理；单站失败只影响当前站点，有界重试并继续其他样本。
- 长任务必须有单站硬超时、心跳、资源保护、进程组清理、可观察 manifest 和断点续跑；除用户明确授权外不启动无限批量。
- 模型代码最多 40,000 Qwen tokens 的规则由具体 pipeline 说明决定；`render_dependencies.json` 标记的只读依赖不能成为 patch 或注错目标。
- 旧的 `expand_only`、picsum/fake_url 分区和 HTML-only 快路径已废弃，不得重新接入。

## 证据与状态

候选 URL 行数不等于成功样本数；URL 池可能重叠，不能相加。运行结果以对应 run 的 `manifest`、`progress`、`attempt` 和资源哈希为准。修改抓取流程后，先跑单 URL，再跑小矩阵，最后才放量。

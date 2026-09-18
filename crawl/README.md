# preprocess 数据预处理

本目录把网页来源处理成可供 `reverse/` 使用的本地项目。当前生产入口是 Pipeline A、B；Pipeline C 用于严格离线资源闭包，Pipeline D 用于保留外链的联网回放样本。

## 当前入口

### Pipeline Mothers：多页在线资源母本候选

2026-09-08 本批最新累计目标为1,000、固定8并发、无整批时长上限；运行脚本默认目标已同步。原 `runs/online_mothers_3000_20260908/` 保留用于断点续跑，目录名为历史命名；实时状态见 `batch/progress.json`。

入口：`python -m crawl.pipeline_mothers.main`。本次最新要求至少首页加一个不同的同站子页；优先抓四页，不足时接受两页或三页（`--min-pages 2`）。首页保留内容筛选，子页不做语义评分。Chromium 对保存页面执行 localhost 全页资源/画面对照，并实际点击首页链接确认加载保存子页。同站复用一个浏览器进程，页面 context 保持隔离；16 MB 的站内原字节下载缓存跨失败子页回滚复用，重新执行资源本地化和 token 检查。候选链接过滤 feed/媒体/download/未激活模板，页面不足或重复在本地回放前拒绝。

保存完整 DOM HTML、内联代码和原文件级CSS/JS；共享文件写入 `code/`，站点字体原样写入 `media/`，图片和明确公共库保持绝对外链。默认 `--context-policy image_render_assisted --render-only-min-bytes 100000`：独立CSS/JS达到100,000 bytes或命中bundle文件名/打包特征时，保留为只读渲染依赖，正文从模型输入和40K排除；不以此声称文件是纯公共库，仅 `.min` 名称不触发排除。`full_code`模式保留全部本地代码计数。CSS import、JS模块、字体和资源引用仍按原规则处理、真实回放；不重建代码或替换图片。

模型可见代码最多40,000 Qwen tokens，HTML/内联代码仍计入，共享文件只算一份；另记录 `all_saved_code_tokens`。`project/render_dependencies.json`列出排除文件的路径、来源、大小、源/落盘SHA256、原因和只读标记；项目上一级导出 `input_files.json`、`training_context.txt`、`training_context_manifest.json`。含排除文件的项目限image-based Edit/Repair，后续不能将这些文件作为输入或patch/注错目标；依赖保留在渲染目录。共享serializer/文件枚举默认尊重该manifest；`construct_common.build_generation_data(..., image_based=True)`显式接受此模式，默认拒绝含隐藏依赖的项目并核验只读文件哈希。其他消费者接入时必须遵循manifest，不能直接递归把渲染目录打包为模型输入。结果仍为 `online_mother_candidate`，不等同accepted Generate GT。滚动、lazy/background资源和保存页导航门禁保留，默认无付费视觉模型调用。

```bash
PYTHONPATH=. python -m crawl.pipeline_mothers.main \
  --urls crawl/pipeline_mothers/strict_pilot_urls.txt \
  --output runs/online_mothers_pilot \
  --qwen-tokenizer .cache/qwen3-tokenizer.json \
  --limit 1 --max-child-pages 3 --site-timeout 240 \
  --browser-proxy http://127.0.0.1:7890
```

`--workers` 为 1–8 的上限，调度器按共享主机负载余量自动降并发；`--target` 为累计合格多页项目数量，重定向到同一最终站点不重复计数。每站独立进程组，单站硬超时、20 秒心跳、中断清理、manifest 逐条 fsync、断点跳过已记录结果。按用户2026-09-08要求不设整批运行时长上限：爬虫与监控默认 `--total-timeout 0`，systemd `RuntimeMaxSec=infinity`；SSH代理隧道使用 `-N`，不附加定时退出命令。目标达到、队列或尝试预算耗尽、明确故障或用户中断时结束。`attempt.json` 保存启动/结束/中断，重试继续计入 `--limit` 总尝试上限。`--lease-file` 与 `--lease-max-age` 可在监控续期中断时停止，负载/内存/磁盘保护可主动停止批次。远程以 systemd 约束 CPU、内存和进程树。`build_queue.py` 将 4K 预筛、历史成功及 WebCode2M 池合并为 86,269 个唯一网站；`runs/online_mothers_3000_20260908/url_queue_v2/` 与 v1 集合一致，仅按历史多页/HTML/脚本成本调序。

Mothers 长任务的独立监控入口为 `crawl.pipeline_mothers.supervise`：以 `--` 传入原爬虫命令，设置同一输出和 lease。网络单次失败先重试（`--network-retry-interval 5`秒），连续3次失败（`--network-pause-after 3`）创建 `<lease-file>.pause`，爬虫只暂停新增派发，在途任务继续原超时和结果收集。持续失败300秒（`--network-outage-timeout 300`，从首次失败起）才停止并清理；成功清零失败计数、移除暂停标记并恢复派发。启动前网络异常也按同样有界策略重试，首次探测成功才启动爬虫。恢复期间监控仍核验本次实时心跳/资源并续租；旧或过期心跳不续，避免90秒lease覆盖300秒网络恢复窗口。监控与爬虫放在同一 systemd cgroup，保留内存/磁盘保护和进程树清理；已停止进程无自动重启。日志使用新路径独占创建，保留失败次数/持续时间和暂停/恢复/停止事件；不要依赖聊天调度持续 touch lease。

明确授权固定并发时，爬虫传 `--workers 8 --fixed-concurrency`，监控传 `--ignore-host-load`；两层同时跳过整机负载降并发/停批，内存、磁盘、心跳、网络及单站硬超时保护保持。2026-09-08 本批已获此授权；其他任务默认仍按共享机负载自适应。

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

`run_server.sh` 可并行启动 Pipeline A/B。物理机运行时使用工作区 `../../AGENTS.md` 规定的目录、`lora` 环境和 HTTP 代理；100 条小规模预检查建议先使用 `--site-timeout 600`。

### Pipeline C：真实网页资源闭包

- 主实现：`pipeline_c/main.py`
- 页面策略：`pipeline_c/policy.py`
- token 门禁：`pipeline_c/qwen_token_gate.py`
- 最终截图：`final_screenshot.py`
- 历史数据抢救：`pipeline_c/offline_rescue.py`

Pipeline C 只保留有训练价值且能稳定渲染的页面资源。不要把旧 picsum 替换、fake URL 分区或“只保留 HTML”的历史口径重新接回当前流程。

当前严格口径：

- HTML 保留在项目根目录，CSS 写入 `styles/`，JavaScript 写入 `scripts/`；三者全部进入模型输入和精确 Qwen 40K 统计。
- 图片、字体、音视频、favicon 等二进制写入 `resources/`，不进入 code token 统计。
- 40K 前执行保守瘦身：删除静态不可达孤儿、原 URL 明确属于 tracker/广告/同意弹窗的代码、cookie UI 和逐字节重复代码；动态 JS 图不确定时保留，规则级 CSS 删除禁用。
- 瘦身前回放用于诊断，瘦身后回放是强门禁；最终保留的 HTML/CSS/JS（含 bundle）仍全部计入训练上下文。
- 所有保留 bundle 同样计入 40K；超过 40K 拒绝整个项目，不做截断或 HTML-only 降级。
- 本地 HTTP 回放会阻断公网请求；存在公网资源请求、本地资源失败、破图或渲染失败时拒绝。
- 每个通过项目保存 `training_context.txt`、`training_context_manifest.json`、`resource_manifest.jsonl` 和离线截图。

真实小规模调试入口：

```bash
bash crawl/pipeline_c/run_strict_local_debug.sh \
  datasets/urls.txt runs/pipeline_c_strict_debug 1 1 0 180
```

写完或修改 Pipeline C 后必须先跑单元测试，再用上述入口跑 1 个真实 URL，最后跑多个普通 URL 的小规模矩阵；日志保存在 `logs/pipeline_c_strict/<run_id>/`。
该调试入口会设置 `PIPELINE_C_KEEP_REJECTED_DEBUG=1`，保留拒绝项目供定位；正式批量入口默认删除拒绝项目，二者不得混作同一数据集。

### 丰富页面候选流水线

`pipeline_c` 的严格抓取前增加三层候选门禁，避免只按代码体积最小值选择旧式文本页：

1. `scripts/build_pipeline_c_rich_url_queue.py` 从历史真实浏览器成功记录中提取不同主域名；历史成功只作为可访问性先验。
2. `crawl/utils/preflight_pipeline_c_rich_urls.py` 在当前网络环境中排除 HTTP 失败、challenge、停放页和低结构页面；这里的六类宽粒度页面结构只用于第一层召回。
3. `crawl/utils/probe_pipeline_c_url_complexity.py` 用独立 Chromium 测量真实请求体积，并按 WebCompass 的 16 类 Edit 能力记录候选证据：Data Table、Rich Text Editor、Drag & Drop、Tree View、Real-time Dashboard、Infinite Scroll、Async Form Validation、File Upload Progress、Parallax、Page Transitions、Particles、Skeleton Loading、Shopping Cart、Authentication、Multi-step Wizard、Notification Center。同时记录 tabs、dialog、search、pagination、toggle、loading/selected/disabled state 等原子特征。DOM 命中只是候选证据，动态能力仍需浏览器动作确认。
4. 按任务资源口径二选一：需要离线闭包时进入 Pipeline C；只保留外链时进入 Pipeline D。两类输出不得混合统计。

小规模端到端入口：

```bash
PIPELINE_C_PROXY_URL=http://127.0.0.1:7890 \
UV_BIN=/data1/xieqianqian/webcoding/.local/bin/uv \
bash crawl/pipeline_c/run_rich_url_pilot.sh \
  datasets/pipeline_c/rich_url_candidates_YYYYMMDD/candidate_manifest.jsonl \
  runs/pipeline_c_rich_url_pilot_YYYYMMDD \
  4000 200 30 4 180
```

其中 4,000 条是当前 HTTP 与静态结构预检通过的候选清单，不得直接记为 4,000 条严格训练样本；浏览器探测和严格抓取仍会继续淘汰反爬、超 40K、资源不闭包或离线渲染失败的页面。

调试入口默认 `PIPELINE_C_VISUAL_REVIEW=0`，避免无意触发付费视觉 API。正式训练准入必须显式设置 `PIPELINE_C_VISUAL_REVIEW=1` 并配置视觉模型凭据；截图 judge 会继续淘汰过时、广告/SEO、空壳、低价值或视觉不完整页面。视觉 API 不可用时不得把仅技术门禁通过的项目升级为 accepted 数据。

## 辅助工具

- `playwright_crawl.py`：A/B 共用的抓取、扩展和资源处理底层实现。
- `clean_resources.py`：A/B 共用的资源清理逻辑。
- `extract_all_webcode2m_urls.py`：生成 WebCode2M 全量 URL 清单。
- `extract_commoncrawl_urls.py`、`collect_cssda_candidates.py`：候选 URL 来源工具。
- `filter_low_quality.py`、`purge_css.py`：质量过滤与 CSS 清理。
- `postprocess_webcode2m_crawl.py`：Pipeline B 后处理兼容 CLI。

### Pipeline D：保留外链并验证联网回放

- 实现：`pipeline_d/main.py`
- 每个通过项目只保存 `index.html` 和 `metadata.json`；不把图片、字体、CSS、JS 或其他站点资源写入项目目录。
- 在 HTML 中加入指向原网页的绝对 `<base>`，原有 `src`/`href` 保持为外链或原相对值。
- 现代灵感 URL 优先由 `scripts/collect_pipeline_d_design_gallery_urls.py` 从允许访问的设计画廊 sitemap 解析到真实原站，并保存画廊详情页 provenance；支持直接外链，也支持 One Page Love 的 `Demo` 重定向解析。CrUX 只作为补充召回。画廊候选仍须经过实时正文安全/结构/robots 预筛和 Pipeline D 浏览器门禁，候选数不能记作成功样本数。
- The Component Gallery 当前只作为设计系统和组件类型的参考目录：其 `robots.txt` 声明 `ai-train=no,use=reference`，因此不得把该站页面直接收为训练 Seed。可沿目录定位外部官方设计系统文档，再分别检查目标站 robots 并抓取其组件文档页；不要优先抓动态 Storybook `iframe.html`，其版本化 bundle 在联网回放中容易失配。
- 回放时仍导航到原网页 origin，但拦截顶层 document 并返回保存的 `index.html`；CSS/JS/图片/字体继续从外链实时加载。这避免 `Cross-Origin-Resource-Policy: same-origin` 把 localhost 页面引用的正常资源误判为跨域。默认 `inspiration` 准入允许不影响主体的小面积破图、字体或第三方脚本失败，并把它们写入 `admission_warnings`；若源截图停在动画初态，但作为交付物的回放已经完整，则源首屏稀疏、回放内容更多和两者动态画面差异也只记 warning。主文档、样式表、同源核心脚本失败，大面积破图，回放正文缺失，源和回放均为空壳，完整状态之间的严重回放差异，或可见交互入口保留率低于 0.6 仍拒绝。长页面首屏外尚未触发的 lazy image 不算可见破图。截图稳定化把动画压缩到终态，不再用 `animation:none` 把 reveal 页面冻结在透明首帧。页面异常全部记录；仅当它是回放新增且同时伴随明显视觉退化时据此拒绝。
- Pipeline D 的可见交互入口检查只能发现按钮、链接、表单等结构是否明显丢失。灵感抽取阶段仍须按识别出的组件执行对应点击、输入和状态变化检查；未通过具体交互检查的候选不能升级为 accepted 灵感。`PIPELINE_D_ADMISSION_PROFILE=strict` 会恢复任何关键资源失败或视口破图都拒绝的严格回放策略，但它不替代 Pipeline C 的本地资源闭包和 canonical 训练准入。
- Pipeline D 仍精确统计保存 HTML（包括内联 CSS/JS）的 Qwen token，但灵感库抓取默认不设 token 硬上限；`metadata.json` 和 manifest 保留 `code_tokens`，后续训练导出时再按目标模型口径筛选。若某次对照需要恢复上限，显式设置 `PIPELINE_D_MAX_CODE_TOKENS`。外部 CSS/JS 正文没有下载，因此不属于模型输入；若训练输入必须包含外部 CSS/JS 正文，应改用 Pipeline C。
- `render_evidence/` 是抓取质量截图，不属于项目资源目录。

运行入口：

```bash
PIPELINE_D_LIMIT=20 PIPELINE_D_WORKERS=4 \
bash crawl/pipeline_d/run_full.sh
```

物理机默认使用 `http://127.0.0.1:7890`；无代理环境显式设 `PIPELINE_D_PROXY_URL=`。大批量前仍须先按 1 个真实 URL、多个普通 URL 矩阵的顺序调试。`run_full.sh` 通过独立进程组运行爬虫并记录 PID，收到中断时会终止该进程组，避免遗留 Playwright/Chromium 子进程。

4K 丰富网页队列先做 WebCompass/原子能力探测和细粒度平衡，再抓取：

```bash
bash crawl/pipeline_d/run_rich_external_full.sh
```

脚本的 probe JSONL、selection 和 crawl manifest 均可保留阶段证据；probe 与 crawl 支持逐条落盘，crawl 默认断点续跑。

历史 `pipeline_d` 输出没有上述联网回放门禁，不能因当前代码升级而追溯认定为通过。新 run 中，默认灵感候选认 `quality_status=inspiration_candidate` 并保留 warnings；显式严格回放认 `quality_status=render_verified`。二者都不能直接冒充 Pipeline C/canonical 训练准入。

## 已移除的旧流程

以下流程已经被当前实现替代，不应再引用：独立 `expand_only`、小批量 HF rows URL 提取、picsum 重截图/背景尺寸修补、`fake_url` 五任务分区，以及旧 fast/test shell 入口。

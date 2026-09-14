---
name: crawl-web-pages
description: 在 WebCoding 项目中抓取网页、爬取母本、离线全资源爬取、在线网页快照或保存多页 HTML 时使用。按用途区分在线资源母本、离线全资源爬取（原 Pipeline C）、在线网页快照（原 Pipeline D）；若用户要在线挖掘交互能力而非保存网页，转用 mine-webcoding-inspiration。
---

# WebCoding 网页爬取

## 先选择用途

若用户只查已有抓取结果、历史批次或清理决定，转用 `webcoding-crawl-results`；它维护现存产物清单，本 skill 负责新的抓取实现与执行。

| 用户目标 | 策略 | 主要入口 |
|---|---|---|
| 爬取母本，用于构造 Edit/Repair | 完整 HTML、外链绝对化、严格联网渲染；image-based 可分离只读渲染依赖，模型代码 40K | Pipeline Mothers |
| 完整爬取、所有资源本地化、离线网页 | 离线全资源爬取：资源递归本地化、断网回放、整项目 40K code token | `crawl/pipeline_c/main.py` |
| 保存网页供浏览或后续挖掘灵感 | 在线网页快照：HTML 快照、资源继续在线、宽松联网回放 | `crawl/pipeline_d/main.py` |
| 在线分析 URL 的交互灵感、构建能力卡池 | 浏览器探索与模型抽取，不是网页项目下载 | 转用 `mine-webcoding-inspiration` |

对用户统一使用“离线全资源爬取”和“在线网页快照”；旧代号 C/D 仅用于定位现有代码，不改模块路径。上下文能确定用途时直接选择；只说“爬取”且上下文不足时，问用途，不默认启动付费 API 或整批运行。

## 必读与代码位置

项目定位起点：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft`；可迁移，不把该路径当作永久不变。
先读项目 `AGENTS.md`、`crawl/README.md`、[数据资产登记](../../../../validate/docs/data/data_assets_registry.md)，再读本 skill 的 [pipeline 目录](references/pipelines.md) 和所选入口代码。只读取相关模块。
修改数据生产逻辑时同时使用 `synthesize-data`，读取其完整指令。当前代码与本 skill 不一致时，区分“要求”与“实现”，不能把描述当作运行证据。URL 候选池与资产口径见 [assets.md](../../../docs/assets.md)。

## 母本策略的硬要求

1. 保留完整 DOM HTML、内联代码和站点 CSS/JS，不删除、不重建或截断业务实现。2026-09-08 最新 image-based Edit/Repair 策略允许 bundle 和大型独立 CSS/JS 作为只读渲染依赖，保留下载文件供浏览器加载，正文不计40K且不进入后续模型输入；它们可能包含业务代码，不能冒称纯公共库。Mothers 默认 `--context-policy image_render_assisted --render-only-min-bytes 100000`：独立文件达到100,000 bytes，或文件名/源码命中bundle打包特征，记录具体排除原因；仅 `.min.js` 名称不自动排除。HTML及内联代码仍计入。明确公共库可继续用绝对外链，纯库身份仍按版本固定发行地址或整文件字节匹配确认。站点字体原样下载，明确字体服务可在线；保留原图。
2. 将需联网解析的相对资源引用转换为绝对 URL。按重定向后的文档 URL 和有效 base 解析；覆盖 `src`、资源 `href`、`srcset`、poster、内联 CSS 的 `url()`/`@import` 等，使用对应解析器，不做全局正则替换。外部 CSS 内相对引用由其原 CSS URL 解析。保留 data URL、片段语义，不把 blob URL 误当可持久资源。
3. 动态 JS 拼接 URL、CSS 背景、lazy image、跨域限制需真实回放验证；不能仅加 base 就宣称“引用已绝对化”。不要通过替换图片掩盖失败。
4. 本次 2026-09-08 最新要求为至少两个独立 HTML：主页加至少一个不同的同站子页；优先抓到四页，不足时接受两页或三页，单 HTML 的 SPA 路由不充数。该口径替代此前“恰好四页”。按捕获正文与图像资源指纹排除首页别名/重复内容；保存 URL→文件映射，确认导航加载保存子页而非线上原页。其他任务按各自明确页数。本批默认 `--min-pages 2`、最多四页；不把旧的页数拒绝直接改成成功，保留历史后按新版重新抓取。
5. 使用Qwen精确统计最终模型可见代码，含HTML/内联代码、未排除CSS/JS和文件分隔标记，共享文件只算一次，最多40,000 token；另报全部保存代码的token数，不混称“全项目40K”。`project/render_dependencies.json`逐文件保存路径、来源、大小、源/落盘SHA256、排除原因、`model_input=false`、`editable=false`；母本同时导出 `input_files.json`、`training_context.txt` 和 `training_context_manifest.json`，明确哪些未计入。后续Image Edit/Repair只读取模型文件集合，冻结依赖不能成为patch、注错或修复目标，不能把缺少隐藏源码才能完成的任务交给模型。运行目录始终保留依赖，模型可编辑文件也必须参与实际回放。Text-only/默认全代码任务不得直接复用含隐藏依赖的输入；`--context-policy full_code`保留旧全代码口径，既有成功结果不回写成新版。
6. 用 Playwright/Chromium 对保存项目进行 localhost 联网回放：对照原站画面、正文保留率和资源响应；全页滚动覆盖 lazy image、CSS background/image-set/mask/content 及伪元素图像。短页面不因不足固定 300 字符被视为正文缺失。当前任务不做子页语义评分、付费视觉打分或后续 Generate/Edit/Repair 验收；抓取中的资源完整性和保存页导航仍需成立。母本不采用 D 的“小面积破图可警告通过”；检查时可用不保证外链永久可用。
7. 原站 origin 的 document interception 可避免同源资源限制，但不等于 localhost/下游 Harness 可渲染；还要在实际消费方式下验证。保存原始捕获及变换记录，报告 origin 依赖。
8. 产物先标记 `online_mother_candidate`。爬取成功不等于正确 Generate GT；配对 Generate query 并完成 validate 后，才可作为 accepted Generate 母本派生 Edit/Repair。不要从已有 Edit/Repair 记录反向统计母本。

## 启动与交付

只写 skill 或只整理策略时不启动爬虫。实际执行时遵守 [批处理运行手册](../../../../docs/operations/batch_jobs.md) 和 [远程环境手册](../../../../docs/operations/remote_environment.md)：核验物理机资源、代理和环境；明确 URL 尝试数、目标数、并发、单站超时、中断和子进程清理。在线母本爬取按用户2026-09-08要求不设整批时长上限：爬虫和监控默认 `--total-timeout 0`，systemd `RuntimeMaxSec=infinity`，SSH代理隧道用 `-N` 保持转发，不附加 `sleep N` 或其他定时退出。达到目标、候选/尝试预算耗尽、明确故障或用户中断才结束；这不取消单站超时、失联/资源保护、300秒持续断网停止，也不授权自动无限重启。先一个真实样本，再按授权扩大；不沿用脚本较高默认并发。代码本地修改测试后同步远程。
不调用 LLM 的网页爬取，在确认物理机可用内存（`MemAvailable`）充足、真实单样本通过且 CPU/I/O 无明显压力后，可以直接使用 8 个站点并发，无需为了保守而长期停留在 1–2 并发。保留资源监控和降并发/停止保护；8 是允许的并发上限，含 LLM 的流程另按其 API 授权和配额执行。
本批 2026-09-08 用户明确要求固定8并发，不因其他任务拉高整机负载而降并发或停批：爬虫使用 `--workers 8 --fixed-concurrency`，独立监控同时使用 `--ignore-host-load`。仍保留内存/磁盘保护、CPU/内存配额、单站硬超时、心跳、代理探测及进程树清理；固定并发授权仅限当前批次，其他任务默认自适应负载保护。
网络探测采用分级恢复：单次超时先重试，连续失败再暂停新站点派发，持续探测失败达到时限才停止并清理。Mothers 默认失败后每5秒重试、连续3次失败暂停派发、从本轮首次失败起持续300秒才停批；探测成功清零失败计数并恢复派发。在途任务继续按原超时运行，暂停期间仍检查心跳/资源并续租，避免90秒lease抢先终止300秒恢复窗口；监控失效、心跳过期和资源不足仍停止，单站硬超时只淘汰该站。探测失败是联网路径异常证据，不等于所有网站均不可访问。具体参数和暂停文件见 [pipeline 目录](references/pipelines.md)。
明确实现/运行故障停批诊断，真实小样本验证后在原授权范围继续；重试有界且计数，已停止任务不自动无限重启。正常样本淘汰继续派发，不视为批次故障。检查 robots/访问和使用限制，不绕过登录、验证码或反爬，不提交表单或产生真实交易。
交付给出策略、输入/输出位置、尝试/候选/门禁通过/accepted 分别数量、token 口径、浏览器证据和未实现要求；不混报三类产物。

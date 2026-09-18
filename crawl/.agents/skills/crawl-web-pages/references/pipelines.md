# 现有 pipeline 目录

以下为代码检查快照，路径相对 `WebCoding_Data/`。Mothers 更新于 2026-09-08；其他模块沿用 2026-09-07 定位。运行前重读所选入口，不把快照当永久配置。

## Pipeline Mothers：在线资源多页母本候选

- 2026-09-08 16:48 最新累计目标下调至1,000（替代2,000），`mothers-batch-0908-v18` 从597条断点续跑，输出原 `batch/`；监控 `supervisor_v18.jsonl`、lease `monitor_v18.lease`。脚本默认target同步1,000，保留固定8并发、无整批时限、原资源策略与86,269尝试预算。只改运行配置，沿用已通过的真实单样本证据；以下旧目标均为历史记录。
- 2026-09-08 16:44 最新运行：用户禁止整批运行时长上限；`mothers-batch-0908-v17` 从592条恢复，实测8个在途、目标2,000、未暂停；监控 `supervisor_v17.jsonl`、lease `monitor_v17.lease`。爬虫和监控 `--total-timeout 0`，实测systemd `RuntimeMaxUSec=infinity`；代理17897改用无定时退出的SSH `-N`转发。20项运行控制测试及真实 `pilot_no_deadline_v1`（1/1，73.374秒达标退出）通过。单站360秒、总尝试86,269、样本目标、心跳/资源及持续断网保护保持；下列v16及更旧批次的总时限属于历史配置，不能照搬。
- 2026-09-08 16:00 最新运行：v16从523条继续到累计2,000，心跳实测8并发；监控 `supervisor_v16.jsonl`、lease `monitor_v16.lease`，原 `batch/` 输出。真实 `pilot_render_only_v1` 的echoalex两页通过：全部保存代码436,813 tokens、模型输入38,995 tokens，3份大型CSS/JS仅渲染，输入排除/依赖哈希/保存导航核验通过。旧结果不回写，试跑不重复计入生产。
- 2026-09-08 新模型输入口径：默认 `--context-policy image_render_assisted --render-only-min-bytes 100000`。独立CSS/JS达到100,000 bytes或命中bundle文件名/打包特征，整体保存为只读渲染依赖，不计模型代码40K、不进入后续输入；不声称是纯公共库，不改变HTML/内联代码。`code/`保留实际文件和原引用关系，`project/render_dependencies.json`逐文件列出来源/大小/SHA256/排除原因及只读标记；项目上一级导出 `input_files.json`、`training_context.txt`、`training_context_manifest.json`，另报全部保存代码token。共享serializer/枚举默认遵守manifest，构造读取须显式 `image_based=True` 并验证依赖哈希；不把隐藏文件作为patch/注错目标。旧 `full_code` 和历史全项目40K记录保留，含隐藏依赖的新母本仅用于image-based Edit/Repair。82项回归包含真实浏览器“全部代码>40K但输入<40K、隐藏依赖仍加载、输入不泄漏”验证。
- 2026-09-08 14:44 最新累计目标改为2,000（替代原3,000），v15实际心跳449/2,000、8个在途；监控 `supervisor_v15.jsonl`、lease `monitor_v15.lease`。仍固定8并发、至少2页优先4页、整项目40K。`run_remote.sh`默认target同步为2,000；原 `online_mothers_3000_20260908` 目录保留用于断点，目录名不代表当前目标。历史批次的3,000参数仅为旧记录。
- 2026-09-08 14:20：分级网络恢复通过14项针对性测试和真实 `pilot_network_v1`（1/1，56.946秒正常退出）；v14从419条继续，实测8个在途。当前日志 `supervisor_v14.jsonl`、lease `monitor_v14.lease`、输出原 `batch/`；下列旧v9–v13运行数量均为历史快照，网络策略以本页分级恢复说明为准。
- 入口 `crawl/pipeline_mothers/main.py`；`capture.py` 做原站/localhost 全页捕获，`resources.py` 用 HTML/CSS/JS 解析器绝对化，`code_assets.py` 按原文件边界保存业务代码。
- 流程：robots/同代理 TLS 预检 → 首页捕获 → 同站子页优先尝试到四页，不足时至少两页 → 共享资源去重、模型输入40K → 保存页导航。首页保留C内容筛选，子页不做语义评分；失败子页新增文件和排除manifest一起回滚，可尝试其他入口。
- `project/` 含二至四个 HTML、`code/` 中的 CSS/JS、`media/` 中原字体及 metadata。递归处理 CSS import、ESM 静态/字面量动态 import，保留 import 条件；在线媒体 URL 绝对化，CSS font-face/字体预加载引用原样保存的本地字体。公共库按精确发行地址或字节身份认定，不能仅看 CDN、文件名或大小。
- 同站捕获和导航共用一个 Chromium 进程，各页原站/回放仍用独立 context，避免页面状态串扰。下载缓存仅限当前站点、最多16 MB、只缓存成功响应原字节；失败子页回滚后复用下载，资源本地化和 token 门槛仍重新执行。过滤 feed/媒体/download/未激活模板链接，首页不足最少入口、重复子页在本地回放前拒绝；不按无 JS 的静态 HTML 猜测动态网站没有子页。
- 最新2026-09-08 09:51：50项回归含真实浏览器单次启动、2/3页接收、单页拒绝与缓存回滚；`pilot_fast_v1` 的 Cynthia 2页/3,953 tokens 和 Susam 4页/10,619 tokens、保存导航均通过。生产存量69；v11在爬虫启动前因共享机高负载停止，恢复须用新unit/log，保留 `--min-pages 2`、v4队列、3,000目标和8并发上限。旧2/3页拒绝仅通过 `requeue_page_count_candidates.py` 在停批时安排一次重抓，保留历史，不直接改为pass。后文v9/v10和四页试跑属于历史记录。
- 09:53 的 `mothers-batch-0908-v12` 曾以3并发启动，随后因共享机负载停止，存量69。10:13 按用户明确授权启动固定8并发的 `mothers-batch-0908-v13`，监控日志 `supervisor_v13.jsonl`、租约 `monitor_v13.lease`；爬虫 `--fixed-concurrency --workers 8`，监控 `--ignore-host-load`。8项针对性测试通过；新心跳已出现8个在途，10:13:48通过数71、有效槽位8（完成交替时在途7）。后续状态继续读实际心跳。
- 原始 DOM、滚动后 DOM、source/replay 全页截图和资源记录在 `captures/`；这些不是训练代码。动态 JS 重新拼接相对 URL、未保存远程脚本、无法处理的 importmap、blob、解析失败或跨域资源失败可导致拒绝，不假装通用拆包已经完成。
- 公共库身份核实同时考虑压缩/未压缩及官方 bundle 发行文件；jQuery 的旧版完整 banner 和 Bootstrap 的空白差异只用于找候选，最终仍要求整文件字节一致。某发行源的 robots/网络失败不证明文件含业务代码，可核对允许访问的另一公开发行源，记录成功来源；不绕过访问限制。真实 IRTF 四页曾因整包超预算被拒绝，补齐官方 Bootstrap 身份比对后以 13,213 tokens 通过；不能由此推断任意混合 bundle 可拆。已知修复可用 `requeue_library_candidates.py` 在停批状态下为受影响旧拒绝安排一次重试，保留原记录并计入总尝试；banner 仅决定重试资格，不决定合格。CSS component-token 解析通过后，stylesheet 语法仍可能失败，应明确拒绝并保留源文件，不能让已知 ParseError 变成整批程序崩溃。
- 当前拒绝活动 iframe/frame 嵌入文档，避免额外业务 HTML 和其内部资源藏在四页/40K 之外。当前 Chromium 启用 JavaScript，`noscript` 内的标记属于未激活文本：保留原内容，不把解析器构造的嵌套 iframe/link 当作活动文档或需下载的代码；不能将此例外扩展到普通 iframe 或假定任意动态模板安全。页面内容指纹排除首页别名；已发现的历史误计数用 `audit_page_duplicates.py` 保留文件、备份 metadata、追加 `needs_recrawl` 更正。读取 manifest 时以每个 source URL 的最后一条状态为准，不能简单累加所有历史 `pass`；该审计仅用于已定位的重复计数修复。
- CLI `--limit` 必填；`--target` 是累计成功数，`--workers` 范围 1–8，`--child-attempts` 控制子页尝试量，`--min-pages` 默认为2、可显式设3/4，`--max-child-pages` 当前只接受3（最多四页）。保留 `--site-timeout` 单站硬上限；按用户最新要求取消整批时长上限，爬虫及监控默认 `--total-timeout 0`，systemd `RuntimeMaxSec=infinity`，代理隧道用SSH `-N`且不附加 `sleep N` 或其他定时退出。达到目标、队列/尝试预算耗尽、明确故障或用户中断时结束。20秒心跳，独立站点进程组，中断清理，manifest逐条fsync。`--lease-file`/`--lease-max-age` 可在监控续期失效时停止。
- 长批次用 `crawl.pipeline_mothers.supervise` 在同一 systemd cgroup 中启动原爬虫命令：指定输出、独立 lease、独占新日志、代理和已确认可访问的 HEAD 探测 URL、`--total-timeout 0`，再以 `--` 接原命令。正常每20秒检查；网络失败改为 `--network-retry-interval 5` 秒重试，连续 `--network-pause-after 3` 次失败创建 `<lease-file>.pause`，爬虫暂停新派发、继续收集在途任务并发心跳。首次失败起持续 `--network-outage-timeout 300` 秒才停批；成功清零计数、移除暂停标记并恢复派发。启动阶段也有界重试，首次联网成功才启动爬虫。网络恢复窗口内仍核验本次新心跳/资源并续lease；stale 60秒、lease 90秒，暂停不会被旧90秒租约误杀。监控失效、过期心跳和资源异常仍停止并清理，已停止进程不自动无限重启；外层cgroup负责全树清理。日志记录失败次数、持续时间、暂停/恢复/停止，progress记录 `dispatch_paused`。2026-09-08 v13在11:39因旧版单次ReadTimeout停止于419条，该分级策略替代旧单次失败即停批规则；状态继续读实际unit/新日志/心跳。
- `run_remote.sh` 是本次 1,000 目标、8 并发上限的运行配置；代理转发地址是临时环境状态，启动前现场核验。生产外围用 systemd cgroup 约束CPU、内存、进程树；默认按整机负载减少槽位或停止，当前批次明确授权通过上述两层参数固定8并发，仅豁免整机负载判断，内存/磁盘/心跳/代理/单站超时保护保持。`attempt.json` 记录启动、结束和中断；中断后的重试继续计入 `--limit` 总尝试预算。
- `build_queue.py` 合并现有 URL 池并按 host 去重，保留来源和输入哈希；`runs/online_mothers_3000_20260908/url_queue_v2` 与 v1 的 86,269 URL 集合相同，v2 仅按历史多页/HTML/脚本成本调整优先顺序，不当作准入证据。重定向到同一最终站点的项目不重复计数。真实批次是否启动/完成以物理机 unit、manifest、progress 为准，不从入口或测试通过推断。
- 新 `url_queue_v4` 按轻量目录 6,672 候选 → Kagi Small Web 39,850 候选 → 旧 v2 合并为 130,154 个 host；原队列保留，来源、提取边界见 `webcoding-url-pools`。Susam 在同一抓取实现下真实四页试跑通过，10,619 tokens、保存页导航通过；单次通过不证明新池整体质量。生产 `mothers-batch-0908-v9` 使用 v4，累计尝试上限仍 86,269，不因扩池自动增加预算。`run_remote.sh` 默认仍指向 v1，续跑必须显式传 `--urls`。

## 离线全资源爬取（原 Pipeline C）

- 入口 `crawl/pipeline_c/main.py`；筛选 `policy.py`，token `qwen_token_gate.py`，历史抢救 `offline_rescue.py`。
- 抓取真实网页并本地化保留资源：HTML 根目录、CSS `styles/`、JS `scripts/`、二进制 `resources/`；递归资源引用也必须闭包。
- 40K 前保守瘦身：静态不可达孤儿、明确 tracker/广告/cookie UI、逐字节重复代码；动态 JS 图不明时保留，禁用规则级 CSS 删除。不是逐字节完整归档，如用户要无损镜像须明确区别。
- HTML/CSS/JS 包括 bundle 全部进入 Qwen 40K；二进制不计 code token；超限整项目拒绝。
- 本地 HTTP 回放阻断公网，公网请求、本地资源失败、破图、渲染失败均拒绝；瘦身后回放为强门禁。
- 输出 `training_context.txt`、`training_context_manifest.json`、`resource_manifest.jsonl`、离线截图。技术通过不替代 query/功能/视觉语义准入；正式视觉复核需明确 API 配置和授权。
- 单样本入口 `crawl/pipeline_c/run_strict_local_debug.sh`。debug 保留拒绝样本，正式入口可能删除拒绝目录，运行前核对保留策略，不把 debug 数据混作 accepted。

## 在线网页快照（原 Pipeline D）

- 入口 `crawl/pipeline_d/main.py`、`run_full.sh`、`run_rich_external_full.sh`。
- 默认保存 `index.html` 和 metadata，插入绝对 base，原相对属性不逐个改写；不下载外部 CSS/JS/图片/字体。原站 origin 拦截 document 回放，联网加载资源。
- 默认 `inspiration` profile 容许不影响主体的小面积破图、字体/第三方脚本失败并写 warnings；主体、核心资源或严重视觉退化仍拒绝。交互入口保留率检查不是交互功能验证。
- 默认不设 token 硬上限，但记录保存 HTML token；显式 `PIPELINE_D_MAX_CODE_TOKENS` 可设上限。`PIPELINE_D_ADMISSION_PROFILE=strict` 收紧资源/视口破图检查，仍不是离线闭包。
- 默认结果 `inspiration_candidate`，strict 结果 `render_verified`；二者不自动变成 accepted Seed 或 accepted 灵感。真正灵感抽取交给在线 mining skill。

## URL 召回与预筛：不是独立成品爬取

- `scripts/build_pipeline_c_rich_url_queue.py` → `preflight_pipeline_c_rich_urls.py` → `probe_pipeline_c_url_complexity.py`：历史可访问性召回、HTTP/结构预检、真实 Chromium 请求与能力候选探测；随后进入 C 或 D。
- `scripts/collect_pipeline_d_design_gallery_urls.py`：画廊 sitemap/详情页解析到原站并保留 provenance；来源站和目标站的许可分别检查。
- `datasets/url_lists/balanced_inspiration_v2_20260905/` 是已有灵感 URL 清单定位线索，运行前查 registry/目录确定最新版本。URL 数量不是可访问网页或已验收能力数量。
- 在线挖掘入口 `inspiration_library/utils/mine_live_url_capability_pool.py` 不要求先保存网页或下载资源；详见 `mine-webcoding-inspiration`。

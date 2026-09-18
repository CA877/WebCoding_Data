---
name: webcoding-url-pools
description: 查找、解释或选择 WebCoding 的 URL 列表与候选池，尤其是 WebCode2M 已过滤 URL、历史成功抓取召回池、HTTP 预筛 4K 清单和多来源灵感池；记录来源、路径、筛选程度和适用范围。实际抓取或灵感挖掘转交对应 skill。
---

# WebCoding URL 候选池

## 使用边界

- 用户问“URL 池从哪里来”“筛选过的 WebCode2M 在哪”“用哪份 URL 清单”时，先按下表定位，只核验相关池。
- 优先使用用户指定列表；推荐池时解释来源和筛选程度。查询或推荐本身不启动爬虫、不切换运行中队列、不调用付费 API。
- 数量和路径是 **2026-09-08 核验快照**。回答“当前”状态前，检查目标文件及非空行数；需要唯一数量时另做 URL/host 去重，不把行数当成功数。
- URL 清单均是 candidate，不是 accepted Seed、可用网页或训练样本。历史 HTTP 成功不代表当前可访问，也不代表能得到恰好四页。
- 各池可能重叠，不相加作为总规模。子集也不与父池相加。

## 路径基准

- 本地仓库：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft`
- 物理机仓库：`/data1/xieqianqian/webcoding/WebCoding_Data`
- SSH：`ssh -p 65022 adminweihunj@36.213.175.38`
- 下文相对路径均相对于仓库根；向用户给本地文件链接时展开成绝对路径。
- 资产登记入口：`validation/docs/data/data_assets_registry.md`。旧共享存储路径和临时目录仅作 provenance，不能假定仍然存在。

## 池选择

| 候选池 | 入口文件 | 核验数量 | 适用范围 |
| --- | --- | --- | --- |
| WebCode2M 静态过滤域名池 | `datasets/pipeline_c/webcode2m_filtered_urls_86740.txt` | 86,740 | 大规模网站根 URL 召回；用户所说“筛选过的 WebCode2M URL”优先指这份 |
| 历史成功抓取召回池 | `datasets/pipeline_c/rich_url_candidates_20260903_v1/candidate_urls.txt` | 12,000 | 参考历史抓取和多页信息选择网站 |
| HTTP/结构/robots 预筛池 | `datasets/pipeline_c/rich_url_preflight_20260903_v1/selected_urls.txt` | 4,000 | 优先复用已有预筛工作；不是实时可用性保证 |
| 多来源灵感池 | `datasets/url_lists/balanced_inspiration_v2_20260905/urls.txt` | 15,609 | 交互能力、组件、应用和设计灵感；含大量非首页 URL |

以上四份入口文件在核验日本地均存在；WebCode2M 86,740 清单当日从物理机同步到本地并核对 SHA256。

## WebCode2M：86,740 条

- 物理机原始池：`/data1/xieqianqian/webcoding/WebCoding_Data/webcode2m_all_urls.txt`，111,023 行；核验时未同步本地。
- 过滤池本地和物理机相对路径一致：`datasets/pipeline_c/webcode2m_filtered_urls_86740.txt`。
- 文件大小 2,488,457 字节；SHA256：`793b0a2b7bf510d893622ef83974fc199e3415bac1f86ae9e3c2dc82a06764d8`。
- 现场集合检查：86,740 个不同 URL、86,740 个不同 host，全为根路径；全部包含于原始池，且全部通过当前 `reject_reason` 静态规则。此结果不证明历史生成时的所有 CLI 参数。
- 提取实现：`preprocess/extract_all_webcode2m_urls.py` 从 Hugging Face `xcodemind/webcode2m` 的 parquet `text/lang` 列读取数据，默认 en/zh，从 HTML 中推断主要域名后去重。它不是直接读取可靠的原站 URL 元数据，可能有推断误差。
- 过滤实现：`preprocess/filter_webcode2m_urls.py` 去重 host，并依据噪声/CDN/资源域、托管域、TLD、子域及随机样式域名等静态规则过滤；默认 shuffle seed 为 20260531。
- **该文件是静态 URL 过滤结果，不能称为 HTTP 或浏览器验证通过池。** 网络预筛另有 `preprocess/preflight_webcode2m_urls.py`。
- `preprocess/run_pipeline_b.sh` 的旧默认文件名 `datasets/pipeline_b/inputs/webcode2m_preflight_passed_urls.txt` 仅是历史定位线索；核验时当前物理机未找到该文件，不能拿它替代已存在的 86,740 清单或编造数量。

## 历史成功召回与 4K 预筛

### 12,000 条召回池

- 同目录证据：`candidate_manifest.jsonl`、`summary.json`。
- 构建入口：`scripts/build_pipeline_c_rich_url_queue.py`。
- 来源是历史 Pipeline B 的 `status=ok` 记录，再做风险路径过滤、注册域去重，以及来源、Tranco 排名和历史多页信息整理。
- summary 记录：历史输入 96,020 行，其中 `ok` 35,656 行；合格唯一域名 34,757，选出 12,000；其中历史多页标记 9,293。
- 原来源路径记录为物理机 `/data1/xieqianqian/webcoding/output_full/multi_page/pipeline_b_results.jsonl`；该历史目录后来已删除。以保留的 manifest/summary 查 provenance，不依赖旧路径或 `/private/tmp` 副本重建。
- 不未经集合比对就声称此池严格包含于 WebCode2M 86,740 池；历史 `ok` 和多页标记都不是当前状态证明。

### 4,000 条预筛池

- 从上述 12,000 候选中检查 8,000 条；HTTP/结构初始 pass 4,592，策略过滤 96 后为 4,496；robots 筛后合格 4,310，最终选出 4,000。
- 最终 4,000 个 source domain、最终 URL 和最终 host 各自唯一；robots 状态为 allowed 或 missing。missing 仅是历史 robots 未取得/不存在状态，不等于显式许可。
- 同目录证据：`selected_manifest.jsonl`、`preflight_results.jsonl`、`robots_results.jsonl`、`summary.json`。
- 实现：`crawl/utils/preflight_pipeline_c_rich_urls.py`；策略说明：`docs/pipeline_c_rich_url_strategy_20260903.md`。
- 这是 2026-09-03 的网络/结构预筛，不是完整浏览器验收，也没有“恰好四页”的保证。

## 多来源灵感池：15,609 条

- 同目录 `manifest.jsonl` 保留来源，`summary.json` 和 `README.md` 记录构建口径；9,003 个 host、145 个来源组。
- 分类：component_docs 4,968，interactive_examples 1,669，domain_apps 4,374，design_gallery 4,598。
- 来源类型：设计画廊引用的原站、开源/免登录应用与产品目录、组件官方文档及组件目录外链、Three.js/Codrops/图表/编辑器等交互示例。主要经目录、索引、导航和 sitemap 提取，不是逐条浏览器通过列表。
- 构建入口：`scripts/build_diverse_inspiration_links.py`、`scripts/rebalance_inspiration_links.py`；配置：`inspiration_url_expansion_20260905.json`、`inspiration_rebalance_20260905.json`（定位时按文件名查找）。
- 同目录子集：`edit_priority_urls.txt` 1,869 条；`balanced_core_urls.txt` 144 条；来源分别见对应的 `*_sources.jsonl`。
- 较早版本在 `datasets/url_lists/diverse_inspiration_{4000,10000,15000}_20260905/urls.txt`（花括号表示三个版本）。其中 inspiration 4K 与 `rich_url_preflight` 4K 是不同清单。

## 下游衔接

### 2026-09-08 新增公开网站候选

- 本次母本批次的数据根为本地 `runs/online_mothers_3000_20260908/`，物理机对应 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/online_mothers_3000_20260908/`，不是上文旧 `/data1` 池根。
- `lightweight_pool_v1/urls.txt`：6,672 个唯一 host，来自 512kb.club、250kb.club、1mb.club、personalsit.es 和 nownownow.com 官方目录；优先轻量目录与 /now 重叠的站点。各目录的页面重量标准不等于 40K code token，也不证明有四页。
- `smallweb_pool_v1/urls.txt`：从 Kagi Small Web 官方 `smallweb.txt` 当次 40,634 个 feed 条目导出 39,850 个唯一 host。下载地址 `https://api.github.com/repos/kagisearch/smallweb/contents/smallweb.txt?ref=main`，Accept 为 `application/vnd.github.raw+json`；源文件 SHA256 `e485d5306374668ae1cb5602818d334a47a447aeb9480429a74d391c05059d41`。feed 推导的根 URL 仍需抓取确认；跳过已知 feed 代理/共享路径，不将 feed 入口本身当 HTML 页。
- 采集器 `preprocess/pipeline_mothers/collect_lightweight_urls.py` 支持 `--source` 定向更新到新目录；只下载目录，不批量访问成员站点，不保存 /now 姓名和位置字段。各池 `manifest.jsonl` 保留原列举 URL、来源目录，`summary.json` 保留源文件哈希和获取时间。目标网站访问规则仍逐站检查；不使用禁止批量挖掘的 Neocities API。
- `url_queue_v4/urls.txt` 按轻量池 → Small Web → 旧 v2 合并，130,154 个唯一 host；三个池的 SHA256 见队列 summary。v1/v2/v3 原快照保留，不能把 v4 队列总量当已尝试数；本次累计尝试上限仍 86,269，成功目标 3,000、并发上限 8。候选来源变化不放宽母本准入。

- 网站母本：优先考虑根 URL 或历史网站候选；灵感池中组件文档、单页 demo 不天然适合主页加子页。按用户当前要求选择，不把某一批“四页、3000 条、并发 8”的参数固化为所有任务规则。
- 保存页面/母本时使用 `crawl-webcoding-pages`；提取在线交互能力时使用 `mine-webcoding-inspiration`；进一步构造或审计训练数据时使用 `build-webcoding-data`。
- 用户只要查找或记录清单时，到文件定位、来源和筛选程度说明为止；需要扩池、去重、重排或抓取时再执行对应请求。

# 物理机历史爬取结果与处置清单（2026-09-09）

## 核验范围与结论

- 2026-09-08，通过 SSH 只读核对抓取/救援相关 run 的 manifest、成功项目目录、HTML 数量、现有截图路径和目录大小；未重跑网页渲染，也未重新评定训练质量。
- 数据产物的处置状态均为**待用户选择**；此次授权仅用于文档迁移清理。上一轮进程查询未发现对应 C/D/Mothers 爬虫在运行，未来操作前应重新核验。
- 已有可直接复用的**抓取产物**：历史 7,200 单页 + 102 多页救援集；272 单页严格联网回放精选集；现代设计画廊/One Page Love 共 1,982 单页灵感快照。
- 对本轮“恰好四页、资源逐项绝对化、全页 lazy/background 覆盖”的要求，物理机新批次已保存 1001 个在线多页候选，其中 **723 个恰好四 HTML**；历史 102 多页救援集另有 **30 个恰好四 HTML**。这些仍是候选，页面角色、需求对齐和正式 Seed 准入需要另行核验。
- 下文大小是整 run 的 du 显示值，包含日志、失败残留和截图。硬链接跨目录共享会影响统计，**不能把各目录大小相加当成删除可释放空间**。

路径缩写仅用于本清单，执行操作前必须展开：

- D1 = `/data1/xieqianqian/webcoding/WebCoding_Data/runs`
- D2 = `/data2/adminweihunj/webcoding/WebCoding_Data/runs`

## 1. 维护入口与历史来源

- 本 skill 的 `references/inventory.md` 是爬取结果、编号和处置记录的维护入口；项目 [资产登记](/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/validation/docs/data/data_assets_registry.md) 保留摘要和链接。
- 2026-09-08 00:44 CST 再次现场复核 A1/A2/B1/B2/B3/B4/C1 的 manifest、成功目录和根 HTML 数，均与下表一致。递归 HTML、截图存在性、warning、token 和大小来自同日上一轮现场盘点，不是本次新渲染。
- 迁移来源为三份本地文档：`物理机数据资产盘点-20260730.md`、`交接-统一代码与PipelineC.md`、`物理机历史爬取结果与处置清单-20260908.md`。相关当前结论与清单集中维护于此；旧文档移入系统废纸篓，非抓取数据删除。
- 策略来源另见项目 `docs/pipeline_c_rich_url_strategy_20260903.md`；URL 输入池由 `webcoding-url-pools` 管理。旧本地 URL 归档定位线索为 `docs/物理机URL清单-20260731/`，本次未核验该归档存在性，不随文档清理删除 URL 文件。

### 历史救援的保真限制

7 月交接记录的救援流程曾把缺失内容图换成 Picsum、缺失 logo/icon 换成 SVG，删除部分远程代码、tracker/cookie 和孤儿文件，并执行 CSS purge/外联。旧模型输入省略 JS 和部分 bundle 正文，使用 60K token；后续“外置依赖后 40K”也不等同于全部代码 40K。因此 A1/A2/A3 是历史已处理网页，**不是原站完整无损捕获**；原审核通过不自动满足当前保真、资源绝对化或 token 要求。此处记录历史行为，不授权新爬虫沿用图片替换策略。

## 2. 优先由用户决定使用/保留的大批量产物

| 编号 | 物理机位置（相对 D1，另注除外） | 实测记录/产物 | 大小 | 用途与边界 | 用户决定 |
| --- | --- | --- | --- | --- | --- |
| A1 | `legacy_rescue_unified_60k_single_5k/projects` | 35,283 次记录；7,200 pass；7,200 项目存在，均单 HTML | run 19G | 历史救援单页底稿；7,200 条原记录的截图、视觉审核状态均 pass | 待定 |
| A2 | `legacy_rescue_unified_60k_multi_3to7/projects` | 9,960 次记录；102 pass、1 pending；目录共 118，只采用 manifest 的 102 | run 558M | 历史多页底稿；102 个成功项目均在，原截图及视觉审核状态均 pass | 待定 |
| A3 | `final_projects_cleaned_40k/data` | 7,200 single_projects + 102 multi_projects | 19G | A1/A2 的清理视图，不是另一批 7,302；名称不能证明符合当前全代码 40K/资源策略 | 待定 |
| B1 | `pipeline_d_rich_external_final_20260903_v2/projects` | 272/272 项目存在；均单 HTML、metadata；544 张源/回放截图存在 | 204M | 严格联网回放记录 render_verified；保存 HTML 均 ≤40K，最大 39,580；依赖原站在线资源/origin，不是四页母本 | 待定 |
| B2 | `pipeline_d_modern_design_gallery_2000_remote_20260904_v1/output/projects` | 3,715 尝试 → 1,416 pass；成功项目和 metadata 均在；2,832 张截图存在 | 1.6G | 单页 inspiration_candidate；489 项有 warning，452 项 HTML ≤40K | 待定 |
| B3 | `pipeline_d_one_page_love_followup_remote_20260904_v1/output/projects` | 904 尝试 → 566 pass；成功项目和 metadata 均在；1,132 张截图存在 | 620M | 单页 inspiration_candidate；186 项有 warning，258 项 HTML ≤40K | 待定 |
| B4 | D2/`pipeline_d_inspiration_domain_apps_seed300_20260907/output/projects` | 实际 71 条记录、42 pass；成功 42 项目均在，目录总共 44 | 35M | 目标名 seed300 不等于完成 300；已有结果为单页灵感候选 | 待定 |
| C1 | D2/`pipeline_c_multipage_mothers_seed300_20260907/output/projects` | 300 尝试 → 4 pass；成功项目均在，目录总共 8 | 58M | 4 个成功项目实际均单 HTML；不能按目录名算多页母本 | 待定 |

B2/B3 成功记录的 source_url 交集为 0，因此两批共有 1,982 条不同 source_url 的成功记录；尚未做最终重定向 URL、域名或内容哈希去重。两批合计 710 条保存 HTML ≤40K，仍不等于母本通过数。二者为宽松灵感策略，不能与 B1 的严格回放状态混算。

A1/A2 为历史清理/救援后的产物，不是原站无损镜像；旧策略包含代码清理和依赖外置等变化。A3 只有 120 条 cleanup 变更记录，不能把该 manifest 行数误读成项目数。

### A2：多页分布和恰好四 HTML 候选

对 manifest 标记 pass 的 102 个项目递归统计 HTML/HTM：

| HTML 数 | 项目数 |
| --- | --- |
| 3 | 34 |
| 4 | 30 |
| 5 | 15 |
| 6 | 8 |
| 7 | 15 |

恰好四 HTML 的 30 个项目 ID（直接位于 A2 表格列出的 projects 目录）：

```text
0001721_bxslider.com
0001718_bloomfields.net.au
0001720_brainviews.com
0001716_blackboxfitnessnm.com
0001725_dailyanswers.net
0001715_bbrdesign.co.uk
0001710_alpaca-attack.com
0001719_bocceballpro.com
0002536_haroldli.ca
0003806_ml5js.org
0003888_mrbios.com
0004182_officetutorials.com
0004580_proactivechiropracticsantafe.com
0004864_rodrigo-silveira.com
0005031_scienceonapostcard.com
0005604_tenxgrowth.co.uk
0006136_verticalsolutionssolar.com
0006530_www.aldrichcpa.com
0006714_www.bankingondreams.com
0006952_www.cdve.org
0006944_www.cavitech-uk.com
0008254_www.loritully.com
0008553_www.nickwang.org
0009031_www.saching.com
0009079_www.scottishmusicreview.org
0009118_www.shakingoffthemadness.com
0009159_www.simphome.com
0009543_www.totalifechanges.com
0009737_www.wfas.net
0009807_www.wusc.cn
```

以上仅是 HTML 文件数量与历史成功记录交集；页面角色、当前在线资源可用性和本轮严格要求尚未复核。没有因此自动升级为 accepted Generate Seed。

## 3. 旧大批量策略与重复视图：单独决定，不直接混入

| 编号 | D1 下 run | 尝试/通过与实际存在性 | 大小 | 建议 |
| --- | --- | --- | --- | --- |
| D1-1 | `pipeline_c_webcode2m_full_20260723` | 11,714 记录、123 pass；123 目录存在，其中 1 个根目录无 HTML | 959M | 旧策略候选，不能按 pass 全量使用 |
| D1-2 | `pipeline_c_webcode2m_remote_policy_full_20260723` | 6,101 记录、85 pass；仅 82 个 pass 目录存在，3 个缺失 | 264M | 旧远程资源策略，需按现存产物筛选 |
| D1-3 | `pipeline_c_absolute_resources_full_20260724` | 111,023 记录、48 pass；48 项目在 | 94M | 旧绝对资源策略对照 |
| D1-4 | `pipeline_c_absolute_resources_proxy_fixed_full_20260724` | 8,556 记录、88 pass；88 项目在 | 137M | 代理修复对照 |
| D1-5 | `pipeline_c_filtered_urls_no_preflight_full_20260724` | 6,743 记录、195 pass；195 项目在 | 325M | 跳过预检对照 |
| D2-1 | `pipeline_d_rich_external_4k_20260903_v2` | 766 抓取、283 pass；283 项目在 | 510M | B1 的 272 个 source_url 全包含于此；优先保留 B1，原 run 保留追溯证据 |
| D2-2 | `pipeline_d_rich_external_4k_20260903_v3` | 146 记录、13 pass；目录总数 18 | 40M | 迭代对照，不能将所有目录当 pass |
| D2-3 | `pipeline_d_rich_external_final_20260903_v1` | 41 记录、26 pass；目录总数 32 | 33M | B1 之前的迭代，按需保留证据 |
| D3-1 | `final_projects_externalized_40k_full_v1` | 7,302 重筛、7,202 pass | 本次未重算 | A 系列依赖外置重筛，不是新来源；旧全代码外置计数口径 |
| D3-2 | `bundle_only_excluded_40k_full_v1` | 7,302 重筛、1,457 pass | 本次未重算 | 排除 bundle 后计数，不能当当前完整代码门禁 |
| D3-3 | `final_projects_full_code_40k_rescreen` | 154 条、31 pass | 本次未重算 | manifest 引用现已缺失的旧 release，不能凭记录认为产物完整 |
| D3-4 | `final_externalized_5k_v1`、`final_externalized_5k_v2` | 实验目录存在；未核验内部 summary 数量 | 本次未重算 | 历史外置实验，非独立抓取主资产 |

D1-1 至 D1-5 的现存成功项目根目录仅见 1–2 HTML（另 1 个无根 HTML），未见本轮四页候选。不同策略会反复抓取相同站点，pass 不相加。
D3 这里只定位历史衍生视图，不重新审核构造和发布数据；确认删除前仍需核对实际引用与共享文件关系。

## 4. 小试跑与清理候选（本次均保留，待选择）

建议先保留 manifest、summary、已有诊断结论，再由用户决定是否删除网页/截图主体；“名称含 pilot”本身不是删除依据。

| 编号 | 范围 | 实测规模 | 建议 |
| --- | --- | --- | --- |
| T1 | D1 下 C 的 nginx 两次、cockos、tcpdump 单样本 run | 各 1 次；合计体积约 2M | 清理候选；体积小，保留关键回归证据成本很低 |
| T2 | D1 下 D 的 external_remote_single v1–v4、htmx、matrix4 v1/v2 | 各 1–4 次，合计约 3.5M | 重复联网回放调试，清理候选 |
| T3 | D1 下 D 的 design_gallery remote_single/getharvest、storybook_single、timeout_recovery | 各 1–3 次 | 失败/单例调试，清理候选 |
| T4 | D1 下 component_gallery_docs_pilot、one_page_love_remote_pilot20 | 9 次/3 pass；12 次/9 pass | 3.6M/11M；先看通过样本是否另有保留再删 |
| T5 | D1 下 design_gallery_remote_matrix30、relaxed_matrix30 | 30 次/16 pass；30 次/4 pass | 13M/8.1M；小矩阵，处置待定 |
| T6 | D1 下 C 的 url_quality_pilot200、complexity_selected30/control30 | 200 次/8 pass；30 次/4 pass；30 次/1 pass | 262M/59M/24M；是成组质量实验，不作为“只试几条”直接删除 |
| T7 | D1 下 C 的 url_complexity_probe200 v1/v2、D rich_external_4k v1 | 探测记录，不是网页成功集合 | 40K/96K/52K；优先保留低成本来源证据 |
| T8 | D2/`online_mothers_20260907_v1` | pilot2 仅 1 条 rejected | 19M；失败调试，清理候选 |
| T9 | D2/`online_mothers_3000_20260908/batch` | `progress.json` complete：target=1,000、passed=1,000、attempted=7,997；manifest 有 1,001 个唯一 pass，恰好 4 HTML 为 723、3 HTML 为 140、2 HTML 为 138 | 当前在线多页母本候选；仍为 `online_mother_candidate`，不等于 accepted Generate Seed |

T1–T7 的精确 run 名与记录数列在附录。URL 候选池、发布集、Generate/Edit/Repair 构造产物不属于本次默认清理范围。

### T9：在线多页母本候选的使用边界

- 运行配置见 `batch/run_config.json`：主页加最多三个同站子页、至少两页、40K 保存代码上限、`image_render_assisted` 依赖分离和无整批总时限。
- 1001 个 manifest pass 项目均有实际项目目录和页面级 source/replay evidence；其中 723 个可作为“恰好四页”优先筛选池。
- 这批产物适合先做页面角色、入口关系、资源闭包和模型输入边界审计，再派生 Edit/Repair。不能只凭四个 HTML 文件直接生成训练记录；应先绑定 Generate GT/query 或明确登记为在线资源母本候选。
- 若采用 image-based Edit/Repair 变体，排除依赖继续只读保留，不进入模型输入，也不能作为 patch、注错或修复目标；Text 全代码任务不能自动沿用该例外。

## 5. 历史存在、现在不可作为现存产物引用

- `/data1/xieqianqian/webcoding/output_full/single_page`：现场不存在；旧文档记录已删除。
- `/data1/xieqianqian/webcoding/output_full/multi_page`：现场不存在；资产台账记录 2026-08-20 按用户要求删除。现 output_full 仅见 _crawl_tmp。
- D1/`pipeline_d_40k_target_10k_20260724`：现场不存在。旧 10,005 个 pass 原本也为 unfiltered 快照，旧报告指出缺截图、空壳和资源路径问题。
- `/data1/xieqianqian/webcoding/WebCoding_Data/releases/edit_repair_construct_v1`：现场不存在；其 7,302 项救援来源及 A3 清理视图仍在，不能说整个历史底稿已丢失。

## 6. 证据入口与后续记录

- A1/A2：run 根 `rescue_manifest.jsonl`；A3：`cleanup_manifest.jsonl` 与 data 目录。
- B1：`accepted_manifest.jsonl`、`projects/`、`render_evidence/`；文件名 accepted 只表示该 D 批次精选，不代表 accepted Generate Seed。
- B2/B3/B4：`output/manifest.jsonl`、`output/projects/`、`output/render_evidence/`。
- C/D 旧批：`preprocess_manifest.jsonl` 或 `output/preprocess_manifest.jsonl`，按附录核对。
- 用户可按 A1、A2、B1、T1 等编号指定“使用/保留/删除”。在本文件记录决定、精确路径、执行日期和结果；任何真正删除之前核对进程、依赖/硬链接、唯一通过样本和可恢复性。
- 当前记录状态：**skill 已集中维护；数据产物的使用/删除决定待定。** 文档清理与数据处置分别记录，不把删除旧文档解释为删除服务器历史 run。
- 2026-09-08 文档处置已执行：用户授权“更新最新结果，写成一个 skill，历史文件可以删掉”；第 1 节列出的三份源文档已从本地仓库 `docs/reports/` 移入 `/Users/woyaochengweikeyandashen/.Trash/webcoding-crawl-docs-20260908.H4HKAL/`，保留原文件名，可从该目录恢复。项目引用已切换至本 skill；物理机数据保持原位。

## 附录：现场抓取 manifest 状态统计

行数为尝试记录数，非去重网站总量；pass 目录存在性以正文及本次只读核验为准。

| Run | 记录数 | 状态计数 |
| --- | --- | --- |
| `D1/pipeline_c_absolute_resources_full_20260724` | 111023 | preflight_rejected=109465；rejected=1507；pass=48；site_timeout=3 |
| `D1/pipeline_c_absolute_resources_proxy_fixed_full_20260724` | 8556 | preflight_rejected=1882；rejected=2020；preflight_network_error=4565；pass=88；site_timeout=1 |
| `D1/pipeline_c_complexity_control30_strict_20260820_v1` | 30 | preflight_rejected=13；rejected=14；preflight_network_error=2；pass=1 |
| `D1/pipeline_c_complexity_selected30_strict_20260820_v1` | 30 | preflight_rejected=3；rejected=23；pass=4 |
| `D1/pipeline_c_complexity_strict_smoke_tcpdump_20260820_v1` | 1 | pass=1 |
| `D1/pipeline_c_filtered_urls_no_preflight_full_20260724` | 6743 | rejected=6545；pass=195；site_timeout=3 |
| `D1/pipeline_c_proxy_retry_remote_cockos_20260820_v1` | 1 | pass=1 |
| `D1/pipeline_c_url_complexity_probe200_20260820_v1` | — | 仅探测，未发现该层抓取 manifest |
| `D1/pipeline_c_url_complexity_probe200_20260820_v2` | — | 仅探测，未发现该层抓取 manifest |
| `D1/pipeline_c_url_quality_pilot200_20260820_v1` | 200 | preflight_rejected=62；rejected=122；pass=8；preflight_network_error=6；site_timeout=2 |
| `D1/pipeline_c_url_quality_remote_single_nginx_20260820` | 1 | rejected=1 |
| `D1/pipeline_c_url_quality_remote_single_nginx_20260820_v2` | 1 | pass=1 |
| `D1/pipeline_c_webcode2m_full_20260723` | 11714 | preflight_rejected=5666；rejected=5724；pass=123；site_timeout=201 |
| `D1/pipeline_c_webcode2m_remote_policy_full_20260723` | 6101 | preflight_rejected=3337；rejected=2630；pass=85；site_timeout=49 |
| `D1/pipeline_d_component_gallery_docs_pilot_remote_20260904_v1` | 9 | pass=3；crawl_failed=5；site_timeout=1 |
| `D1/pipeline_d_component_gallery_storybook_single_remote_20260904_v1` | 1 | crawl_failed=1 |
| `D1/pipeline_d_external_remote_htmx_20260903_v1` | 1 | pass=1 |
| `D1/pipeline_d_external_remote_matrix4_20260903_v1` | 4 | pass=2；crawl_failed=1；token_rejected=1 |
| `D1/pipeline_d_external_remote_matrix4_20260903_v2` | 4 | pass=3；token_rejected=1 |
| `D1/pipeline_d_external_remote_single_20260903_v1` | 1 | crawl_failed=1 |
| `D1/pipeline_d_external_remote_single_20260903_v2` | 1 | crawl_failed=1 |
| `D1/pipeline_d_external_remote_single_20260903_v3` | 1 | crawl_failed=1 |
| `D1/pipeline_d_external_remote_single_20260903_v4` | 1 | token_rejected=1 |
| `D1/pipeline_d_modern_design_gallery_2000_remote_20260904_v1` | 3715 | pass=1416；crawl_failed=2159；site_timeout=140 |
| `D1/pipeline_d_modern_design_gallery_remote_matrix30_20260904_v1` | 30 | pass=16；crawl_failed=13；site_timeout=1 |
| `D1/pipeline_d_modern_design_gallery_remote_relaxed_matrix30_20260904_v1` | 30 | crawl_failed=24；pass=4；site_timeout=2 |
| `D1/pipeline_d_modern_design_gallery_remote_single_20260904_v1` | 3 | crawl_failed=3 |
| `D1/pipeline_d_modern_design_gallery_remote_single_getharvest_20260904_v1` | 1 | pass=1 |
| `D1/pipeline_d_one_page_love_followup_remote_20260904_v1` | 904 | pass=566；crawl_failed=329；site_timeout=9 |
| `D1/pipeline_d_one_page_love_remote_pilot20_20260904_v1` | 12 | pass=9；crawl_failed=3 |
| `D1/pipeline_d_rich_external_4k_20260903_v1` | — | 仅探测，未发现该层抓取 manifest |
| `D1/pipeline_d_rich_external_4k_20260903_v2` | 766 | crawl_failed=420；pass=283；token_rejected=63 |
| `D1/pipeline_d_rich_external_4k_20260903_v3` | 146 | crawl_failed=130；pass=13；token_rejected=3 |
| `D1/pipeline_d_rich_external_final_20260903_v1` | 41 | pass=26；crawl_failed=15 |
| `D1/pipeline_d_rich_external_final_20260903_v2` | 272 | pass=272 |
| `D1/pipeline_d_timeout_recovery_biketime_remote_20260904_v1` | 2 | crawl_failed=2 |
| `D2/pipeline_c_multipage_mothers_seed300_20260907` | 300 | preflight_network_error=43；rejected=183；preflight_rejected=62；site_timeout=8；pass=4 |
| `D2/pipeline_d_inspiration_domain_apps_seed300_20260907` | 71 | crawl_failed=28；pass=42；site_timeout=1 |

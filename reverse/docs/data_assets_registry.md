# WebCoding 数据资产台账

> 0905 的检查策略、已实施证据和未覆盖范围统一见 [0905 数据检查策略与实施记录](../reports/0905_data_check_strategy_implementation_20260912.md)。本台账只维护资产路径、数量、版本和产物证据。

## 历史 20260805 兼容包审计

`webcoding_sft_v2_20260805_compatible` 的 14,094 个 `images/` 文件均为样本监督截图，而非网页运行依赖：Image Edit 3,000 张 clean 图、Image Generate 5,094 张 clean 图、Image Repair 6,000 张 defective/clean 图。该次路径核对中，未被 `src_screenshot` 或 `dst_screenshot` 引用的图片为 0，JSONL 引用缺失为 0。

该包不能作为资源闭包基线：对 Generate response 展开后的静态审计中，Image Generate（5,094 条）有 4,852 个非命名空间 URL、1,767 个外链图片、4,771 个外部脚本/样式；Text Generate（9,094 条）对应为 5,692、1,769、4,799。历史审计只说明旧包现状，新的母本准入以 [Generate 母本门控规范](../evaluation/generate_mother_gate_spec.md) 为准。

## 0905 ModelScope增量交付（2026-09-13）

- 目标：`mistletoe111/webcoding_stf/0905/`；39,845条、47,827文件、16,989,925,934 bytes。六类数量依次12,437 / 11,192 / 3,905 / 4,145 / 4,249 / 3,917，README和索引已更新。
- 相对9.08发布新增6,911图片，替换四个Edit/Repair分片及README/索引；共6,917差异文件、2,550,051,037 bytes。原40,910文件保持，原记录保留；分阶段续传跳过已成功文件。
- 结果：`uploaded_tree_verified`，全量远端路径、大小和SHA256匹配。本地[交付报告](../../runs/delivery_0905_incremental_20260913/result.json)；物理机`/data2/adminweihunj/webcoding/WebCoding_Data/runs/delivery_0905_incremental_20260913/`包含最终manifest、发布README/索引与`upload_workers8.log`。报告的5,891 changed_files为最后一次续传余量，整体差异为6,917文件。

## 0905物理机数据包补量（2026-09-13）

- 路径：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`；合入早期500+500组及4～7项400+400组，共新增3,600条，总计39,845条。六类依次12,437 / 11,192 / 3,905 / 4,145 / 4,249 / 3,917。
- 两批均为物理多页、text/image配对；早期325条Image Edit格式修复已纳入。新增去重实体图片6,911张，沿用原模型输入范围；逐项分布见[当前统计表](../current_state.md#0905正式分片subtask分布2026-09-13合入后)。
- 导入入口：`scripts/merge_0905_multipage.py`；物理机运行根`/data2/adminweihunj/webcoding/WebCoding_Data/runs/0905_multipage_merge_20260913_v3/`，包含`result.json`、`selection.json`、`image_manifest.json`和原分片/索引/README的`backup/`。[本地合并报告](../../runs/0905_multipage_merge_20260913_v3/result.json)保存数量、哈希、去重与检查结果。
- 本次物理机数据包已按上方9.13增量交付记录同步云端；9.08上传记录保留为历史基线。

## 0905 ModelScope交付（2026-09-08，历史上传记录）

- 版本：`mistletoe111/webcoding_stf/0905/`；36,245 条、40,916 文件、14,601,254,675 bytes。
- 交付产物：物理机`/data2/adminweihunj/webcoding/WebCoding_Data/runs/delivery_0905_repair_inputs_20260908/`，其中 `result.json`、`manifest.json`、`dataset_index.json` 和 `upload_attempt5.log` 是交付证据。
- 检查策略、输入契约、实施状态和适用边界只维护于 [0905 数据检查策略与实施记录](../reports/0905_data_check_strategy_implementation_20260912.md)。

## 0805 Generate补充与Repair prompt对齐（2026-09-08）

- 目标仍为`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`。从正式supplement原样追加WebGen-Bench Text Generate 1,300条、ArtifactsBench含至少两个HTML/HTM的Text Generate 541条，按ID和GT代码去重。本轮只追加Text Generate。
- 六类数量依次为12,437 / 11,192 / 3,005 / 3,245 / 3,349 / 3,017，合计36,245。顺序为Text Generate、Image Generate、Text Edit、Image Edit、Text Repair、Image Repair。
- 全部6,366条Repair使用完整官方`Repair_Instruction_Prompt`＋N，补齐XML search_replace输出要求。Text的源码仍在`instruction`；Image的`instruction`同步prompt；GT patch和图片保持。官方prompt源文件SHA256为`5c7da4b2ff292eb2547bdb4b76d316059c432ca1c5c5e9ba6bdba8f9f66ddb83`。
- 导入器为`scripts/update_0805_generate_repair_20260908.py`，默认只读预检查；10项针对性测试通过，包括直接运行官方消息构造方法的文字一致性检查。
- 与原0805全量格式比较：Text Generate、Text Edit字段及类型一致；Image Generate增加9个页面/交互/视觉映射等字段；Image Edit增加`target_reference_images`，`instruction`同时存在list和str，175条`input_images`不同于`src`、59条instruction为空；两类Repair增加`repair_instruction`。六类单GZ分片布局、Generate files和Edit/Repair JSON patch结构保持，ID唯一、图片引用存在、索引数量及哈希检查通过。训练消费Image Edit应读取`input_images`并兼容两种instruction类型。
- 目标release内`generate_repair_update_20260908.json`记录导入ID及保真检查，`format_vs_0805_20260908.json`记录六类格式比较。备份：`/data2/adminweihunj/webcoding/WebCoding_Data/backups/0805_v2_before_generate_repair_update_20260908/`，包含旧索引及三个修改前分片。

## 0805历史Image Edit图片变体导入（2026-09-08）

- 目标：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`，Image Edit 3,005→3,245，六类合计34,404。
- 来源：`/data1/xieqianqian/webcoding/WebCoding_Data/runs/new_gt_edit_repair_bulk_20260821_v1/edit/*/image-edit.v2.jsonl`；source_image 65、target_image 61、source_target_images 55、source_target_images_no_query 59，共240条及2,074张图片。
- 用户指定保留四种输入方式、原instruction（包括59条空列表）和GT patch；ID为`原ID__historic_变体名`。模型图片读取`input_images`，metadata为`image_variant_extension=true`及`model_image_field=input_images`，source/target分别存储以保留角色。
- 检查：240条精确patch回放、2,074张复制图片SHA256、3,005条旧行逐字段保真及新分片索引哈希通过；本轮验证范围为导入保真。
- 导入器：`scripts/import_0805_edit_image_variants.py`；release内证据`historic_edit_image_variants_import_20260908.json`；备份为`/data2/adminweihunj/webcoding/WebCoding_Data/backups/0805_v2_before_historic_edit_variants_20260908/`，保存旧分片、旧索引及图片来源/哈希manifest。

## 物理机统一灵感库（2026-09-08）

- 深度补强诊断（09-08 后续）：同一物理机运行根下 `depth_old_audit_v9`、`depth_full_v10`、`depth_revision_v11` 保存旧例复审、新九项候选及超时修正证据。新版准入链 0，未增加 canonical；旧 v8 在新复审中富文本/看板两项被拒，旧文件及其历史审核不改写。见 [实验记录](edit_chain_webcompass_comparison_20260908.md)。

- 随机 Edit case（09-08 最新）：`/data2/adminweihunj/webcoding/inspiration_library/runs/edit_chain_fix_20260908/tokenwave_random_revision_v8/miner/edit_queries.jsonl`，同一母本随机 N=9，定向修正后 9/9 指令通过结构和语义审核。原候选在 `tokenwave_random_v7`；此前四项链独立保留。用途为 instruction-only 后续构造候选，target 未生成，不计 canonical。官方对照及中文译文见 [专项报告](edit_chain_webcompass_comparison_20260908.md)。

- 检索向量（09-08）：123 张 text-embedding-v4 / 1024 维，位于 `/data2/adminweihunj/webcoding/inspiration_library/runs/edit_chain_fix_20260908/pool/embedded_capability_pool.jsonl`；池 SHA 与 current 一致。最新 TokenWave 指令试跑已复用该池，详见 [交接](handoffs/continuous_edit_instruction_augmentation.md)。
- Edit 指令小样本（09-08）：`/data2/adminweihunj/webcoding/inspiration_library/runs/edit_chain_fix_20260908/tokenwave_review_v6/miner/edit_queries.jsonl`，1 母本/4 条指令，通过结构和 TokenWave 语义审核；完整链、逐项审核位于同目录 `sequences/`、`quality/`。用途为后续 target 构造候选，`target_status=not_generated`、`training_admission=not_eligible`；独立保存，不计入 canonical 训练集。

- 权威入口：`/data2/adminweihunj/webcoding/inspiration_library/current/capability_pool.jsonl`，当前 123 张（local_project 48、url 75），41 张带代码，62 个源码文件；13 份原始池与 167 个记录版本保留。Mac 原始批次 124 个 ID、物理机 13 个 ID，重合 13；1 张明确被替换的旧排序卡仅留归档。
- 两种来源统一通过 `--mode {local_project,url}` 控制，真实挖掘均在物理机运行。盘点范围、版本选择、路径、哈希和验证见 [统一库清单](inspiration_library_inventory_20260908.md)。

## 灵感与局部参考代码修复版（2026-09-08）

- 当前示例池：[`runs/live_mining_repairs_20260908/capability_pool.jsonl`](../runs/live_mining_repairs_20260908/capability_pool.jsonl)，1 个 Ant Design URL、3 张卡：行选择、展开/收起、排序；每张含 DOM/CSS 与官方 TSX。排序使用新的三次点击真实观察和多模态抽取结果，原卡在历史目录保留。
- 物理机：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/live_mining_repairs_20260908/`；本地同相对路径。`pool_manifest.json` 记录合并/替换来源。用途为参考实现；源码、网络异常和复用关系见 [逐项修复报告](live_url_mining_audit_20260905.md)。
- 新增 LLM 调用 1 次、13,378 tokens；107 项本地测试通过，Ant 真实排序＋官方源码探针通过。HTMLElements 独立 demo 已采集到 11 个表单控件，ApexCharts 原入口已恢复访问；两者浏览器观察单独保存，未计入卡数。

## 选择性组件源码候选（2026-09-07）

- 新版参考模式：物理机 `runs/reference_sources_20260907/`（根 `/data2/adminweihunj/webcoding/WebCoding_Data/`），本地同相对路径。`ant_table_direct/capability_pool.jsonl` 为 3 张已有 LLM 灵感卡的源码补充版，含被引用状态的 DOM、匹配 CSS、可定位 JS/公开 TSX 和依赖边界；用途 `implementation_reference`、状态 partial。Calculator.net 的 `business_probe_direct` / `business_probe_dependencies` 为真实单位切换的技术诊断，单独保存，`diagnostic_only=true`，不计入灵感卡数。媒体保留在线；新增 LLM 调用 0。入口、参数及验证见 [专项报告](live_url_mining_audit_20260905.md)。
- 最新 Calculator 诊断 `business_probe_guarded`：单位界面切换、GET 表单提交拦截、局部 HTML/CSS/JS 与 1,711 字符直接依赖函数提取均通过，6.77 秒；结果仍是参考素材，非完整独立组件。

- 来源：已有 Ant Design table 在线观察与 3 张候选卡；入口 `inspiration_library.live_component_sources`。物理机 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/selective_sources_20260907/`，本地镜像 `runs/selective_sources_20260907/`。
- 最新 `table_v2`：2 个目标 demo 中 1 个取得公开 TSX 示例，1,471 bytes，关联 1 张卡；另一 demo 展开超时。保存 `components/` 源码、截图、metadata 和 `extraction_with_sources.json`，媒体/整页 bundle 保留在线，LLM 调用 0。
- 用途：可溯源组件灵感素材；源码依赖 React/antd，独立运行未验收。过程及首轮记录见 [专项报告](live_url_mining_audit_20260905.md)。

## 在线资源多页母本试跑（2026-09-07）

- **2026-09-09 最新现场结果：** 物理机 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/online_mothers_3000_20260908/batch/` 已完成本轮目标。`progress.json` 为 `complete`，`target=1,000`、`passed=1,000`、`attempted=7,997`、`in_flight=0`；manifest 现场统计为 1,001 个唯一 `status=pass` 项目，全部项目目录存在。递归 HTML 分布为恰好 4 页 723、3 页 140、2 页 138；全部记录的 `quality_status=online_mother_candidate`，不是 accepted Seed/Generate GT。入口证据为 `batch/manifest.jsonl`、`batch/progress.json`、`batch/run_config.json`，资源与页面语义仍需按母本 skill 的边界继续验收。
- **本批用途：** 723 个四 HTML 项目可作为 Edit/Repair 母本优先筛选池；当前只证明物理页面结构、保存项目存在和 source/replay evidence，不证明首页入口、页面角色、query–GT 对齐或正式浏览器语义准入。`run_config.json` 使用 `max_child_pages=3`、`min_pages=2`、`max_code_tokens=40000`、`context_policy=image_render_assisted`。

- 2026-09-08 20:15：按用户要求续跑，`mothers-batch-0908-v19` 从820条、累计尝试6,471恢复，实测820/1,000、8个在途、未暂停、`RuntimeMaxUSec=infinity`。新监控 `supervisor_v19.jsonl`、lease `monitor_v19.lease`，输出沿用原 `batch/`。v18于18:57:56因持续网络ConnectError超过300秒停止；现场本机7897代理可用，但SSH转发进程及远端17897监听均已消失，重建无定时退出的SSH `-N`转发后，物理机同代理HEAD探测200。沿用原抓取实现及已通过的单样本证据；并发/目标/资源/心跳/断网保护保持。
- 2026-09-08 16:48：累计目标按用户要求改为1,000，`mothers-batch-0908-v18` 从597条、累计尝试4,326继续；仍为原 `batch/` 输出，监控 `supervisor_v18.jsonl`、lease `monitor_v18.lease`。保持固定8并发、无整批时长上限、原抓取/模型输入口径及尝试预算。此次仅降低目标并同步脚本默认参数，沿用已通过的实现与真实试跑证据；历史2,000/3,000目标被替代，目录名保留。
- 2026-09-08 16:44：按用户要求取消整批运行时长上限，`mothers-batch-0908-v17` 从592条断点继续；实测592/2,000、8个在途、未暂停，`RuntimeMaxUSec=infinity`。爬虫和监控均 `--total-timeout 0`，监控 `supervisor_v17.jsonl`、lease `monitor_v17.lease`；代理17897已改为SSH `-N`转发，不再定时退出。仍保留单站360秒、尝试86,269、固定8并发、24GiB/800%配额、心跳/lease与持续断网300秒保护。20项运行控制测试通过，真实 `pilot_no_deadline_v1` 1/1通过、73.374秒达标正常退出，不计生产。v16及以下总时限均为已废止配置的历史记录。
- 2026-09-08 16:00：`mothers-batch-0908-v16` 已按image_render_assisted新版从523条继续，实测8个在途、target=2,000、`dispatch_paused=false`；原 `batch/` 输出，监控 `supervisor_v16.jsonl`、lease `monitor_v16.lease`，抓取总时限21,600秒、监控22,200秒、cgroup22,800秒。新旧记录按 `context_policy` / 排除manifest区分，旧523条不回写或重复计数。
- 2026-09-08 image-based模型/渲染分离：v15停于523条、累计启动3,628；旧结果保留原口径。新版Mothers将独立CSS/JS≥100,000 bytes或命中bundle特征者保存为只读渲染依赖，正文排除于模型40K与后续输入，不冒称纯公共库。每项目含 `render_dependencies.json`（来源/路径/大小/源与落盘SHA256/原因/只读标记），项目上一级导出 `input_files.json`、`training_context.txt`、`training_context_manifest.json`；含排除项者仅用于image-based Edit/Repair，不能作为patch/注错目标。共享serializer/构造输入读取已支持，构造消费须显式 `image_based=True` 并验证依赖哈希；默认全代码消费拒绝该变体。82项回归及最终2项针对性测试通过。
- 真实 `pilot_render_only_v1`：此前因超限拒绝的echoalex现为2页通过，全部保存代码436,813 tokens、模型输入38,995 tokens；排除semantic CSS（787,806 bytes）、semantic JS（346,199 bytes）、sails.io.js（138,937 bytes），均保留本地并记录SHA256，输入列表与排除列表不重合，保存导航通过。unit正常退出、120.088秒；该试跑不计生产。完整项目位于物理机原run下 `pilot_render_only_v1/attempts/c5da2f16fc2e55e10f80/candidates/c5da2f16fc2e55e10f80/project/`。
- 2026-09-08 14:44：`mothers-batch-0908-v15` 已实际恢复，心跳为449/2,000、8个在途、`dispatch_paused=false`；监控 `supervisor_v15.jsonl`、lease `monitor_v15.lease`，抓取总时限26,700秒。脚本语法和skill校验通过；页数/40K/资源策略沿用此前通过的实现。
- 2026-09-08 目标调整及瓶颈：用户将本批累计目标由3,000改为2,000，`run_remote.sh`默认值已同步；沿用原目录和有效断点449条、尝试2,469，历史数量/参数保留。v14完成315次，30通过（9.5%），平均尝试31.4秒、成功95.4秒；v13为1,311次/350通过（26.7%）、29.4秒/61.9秒。v14的140次40K超限占已完成任务累计占槽时间40.7%，是最大浪费项；示例whatbox最终2页、11次子页失败、205.85秒，反映优先凑4页的额外尝试开销。现场CPU队列140+、CPU压力avg10约71%，内存仍约462GiB可用；59次监控均healthy，未发生网络暂停。阶段耗时尚不能精确拆为网络/解析/回放。只调整累计目标，本次未修改抓取筛选逻辑。
- 2026-09-08 14:20：`mothers-batch-0908-v14` 已从419条断点恢复，实测8个在途、`dispatch_paused=false`；启用上述5秒重试/3次暂停/300秒停批策略。监控 `supervisor_v14.jsonl`、lease `monitor_v14.lease`，输出沿用原 `batch/`。
- 2026-09-08 网络恢复策略：v13于11:39因单次探测ReadTimeout停止，存量419、累计启动2,145。新版监控失败后每5秒重试，连续3次暂停新增派发，持续失败300秒才停批；成功恢复，暂停期间继续监控/续租，在途任务保持原超时。14项针对性测试通过；真实 `pilot_network_v1` 为1/1通过、unit正常退出（56.946秒），试跑不计生产。代理转发已恢复；后续批次使用新unit/log和独立lease，保留固定8并发、至少2页优先4页、40K、目标3,000和累计尝试86,269。
- 2026-09-08 10:13：按用户明确要求改为固定8并发，v12已因负载停止；`mothers-batch-0908-v13` 从69条续跑，爬虫 `--fixed-concurrency --workers 8`、监控 `--ignore-host-load`，保留24 GiB内存/800% CPU配额、磁盘/心跳/代理/硬时限及进程清理。8项针对性测试通过；监控已实测8个在途，10:13:48为71条通过、830次启动、有效槽位8。监控 `supervisor_v13.jsonl`、lease `monitor_v13.lease`；至少2页优先4页、40K、目标3,000及累计尝试86,269保持。
- 2026-09-08 09:53：负载回落后，`mothers-batch-0908-v12` 已实际启动新版，从69条存量继续；`--min-pages 2`、v4队列、目标3,000、尝试上限86,269、并发上限8。启动时负载38.38，实际并发3，后续按负载自动调整；监控 `supervisor_v12.jsonl`、lease `monitor_v12.lease`。v11高负载拒绝启动的日志保留。
- 2026-09-08 09:51：用户将页数改为至少2页；本批优先4页，不足时接收2/3页。`--min-pages 2` 与 metadata 的 `page_count_policy` 记录新口径，40K、资源保真和保存导航保持。实现同站 Chromium 进程复用（页面 context 隔离）、16 MB 原字节下载缓存跨失败回滚复用、非 HTML 候选过滤和页面不足/重复的回放前拒绝。50项回归通过；真实 `pilot_fast_v1`：Cynthia 2页/3,953 tokens/34.04秒，Susam 4页/10,619 tokens/76.08秒，两者导航通过，试跑不重复计入生产。停批有效存量69；`page_count_requeue_v1.json` 将20条旧2/3页拒绝各安排一次重抓，原记录保留。v11 启动前因 `shared_host_load_high` 停止，爬虫未启动；目标3,000、并发上限8、累计尝试86,269保持，负载恢复后用新 unit/log 续跑。速度变化需看新批次实际增长，不从两个试跑外推。
- 2026-09-08 09:28：晨间核验仅 49 个有效结果，3,000 目标未完成；v9 于 03:12:33 因 `monitor_lease_expired` 停止，尝试 688、在途清理为 0。新增独立 `preprocess.pipeline_mothers.supervise`，核验当前心跳/资源/代理后才续期，异常终止且不自动重启。Mothers/D/URL/监控合计 45 项测试通过；真实 `pilot_supervision_v1` 四页通过、进程97.715秒正常退出，调试重复不计入生产。`mothers-batch-0908-v10` 同 cgroup 从原 batch 的49条继续，仍使用 v4、目标3,000、累计尝试86,269、并发上限8；监控 `supervisor_v10.jsonl`、lease `monitor_v10.lease`，90秒失联保护，外层总时限29,400秒。爬取产物和质量口径保持不变。
- 2026-09-08 03:06：新增 `runs/online_mothers_3000_20260908/lightweight_pool_v1`（6,672 host）与 `smallweb_pool_v1`（Kagi 官方 40,634 feed 导出 39,850 host）；本地和 `/data2/adminweihunj/webcoding/WebCoding_Data/` 下同相对路径。`manifest.jsonl` 保留列举 URL/目录来源，summary 保存 SHA256/获取时间；仅 URL 候选，成员站点尚未逐条探测。`collect_lightweight_urls.py` 新增定向来源采集，3 项测试通过。`url_queue_v4` 按轻量池→Small Web→v2 合并为 130,154 host，旧池保留。真实 `pilot_lightweight_v1` 的 Susam 四页通过，10,619 Qwen tokens、保存导航通过；不重复计入生产。v8 停止时有效 24、尝试 576；v9 已用 v4 从同一生产断点继续，目标 3,000、尝试上限 86,269、并发上限 8。资源/40K/四页门槛不变；最新数量读 `batch/progress.json` 和 manifest 最后状态。
- 2026-09-08 02:40：修复 JavaScript 启用时 `noscript` 内未激活标记被当作活动 iframe/代码资源的误判；保留原 HTML，活动 iframe 仍拒绝。39 项回归通过；`pilot_noscript_v1` 的 NLM 越过误判后仍因预算拒绝，IRTF 四页 13,213 tokens、保存导航通过。v7 停止时为 22 条有效结果、333 次启动；v8 从同一断点继续，目标 3,000、并发上限 8，重复试跑单独保存。爬取 skill 已同步并校验。
- 2026-09-08 02:27：公共库识别补齐 jQuery 旧版/未压缩、Bootstrap 未压缩及官方 bundle，全部仍需整文件字节一致。真实 `pilot_library_identity_v2` 的 IRTF 四页通过：13,213 tokens，四页全页相似度 1.0，三条保存页导航通过；外部 Bootstrap CSS 280,715 bytes、JS bundle 207,720 bytes 均记录官方文件 SHA256，比对无业务删除。前一轮 3 个站点仍分别因预算、字体网络和动态代码拒绝，未计为成功。生产有效存量 19；`library_identity_requeue_v2.json` 将 19 个可能受漏识别影响的旧预算拒绝各安排一次重试，保留全部原记录并计入总尝试上限；`mothers-batch-0908-v7` 从同一输出和 URL 队列继续 3,000 目标、8 并发上限。
- 2026-09-08 02:15：v5 因 CSS stylesheet 语法错误未被捕获而保护停批；已将该已知错误转成明确单站拒绝，保留原 CSS。34 项回归通过；`pilot_css_recovery_v1` 真实验证 Project Avalon 正常拒绝后继续到 Lua，四页 32,294 tokens、三条保存页导航通过。生产从 12 条有效存量以 `mothers-batch-0908-v6` 续跑，仍以 3,000 为目标、8 并发为上限；重复调试样本不计入生产数。
- 2026-09-08 02:04：修复首页别名被当作子页的问题，跳过正文/图像资源指纹重复的页面后继续找其他入口；33 项回归及 Lua 新版真实四页复验通过。13 条批量 `pass` 中，Gemology 的根页/`index.html` 重复被更正为 `needs_recrawl`，其 HTML、历史行和 metadata 备份保留；当前有效存量 12，报告 `page_dedup_v1.json`。manifest 按 source URL 最后一条状态计数；v5 从同一清单继续，保持 3,000 目标及 8 并发上限。iframe/frame 文档暂拒绝，避免遗漏其业务代码和内部资源。
- 2026-09-08 01:43：字体跨域修复真实试跑 `pilot_fonts_v1` 的 Xdebug 四页通过，28,799 tokens，8 个原字体文件共 136,624 bytes，保存页导航通过；不替换字体，二进制不计代码。完整回归 29 项及新增真实字体离线来源拦截测试通过。`mothers-batch-0908-v4` 已按 `url_queue_v2` 续跑，目标 3,000、并发上限 8，当前实际 8；负载余量不足时自动减少新增槽位，超硬阈值仍清理停止。此前 32 次批量启动中 24 次已落盘拒绝、8 次因负载中断；实时通过数读取 `batch/progress.json`。
- 2026-09-08 01:23 新版 `runs/online_mothers_3000_20260908/pilot_assets_v7`：Lua 首页、About、News、Start 恰好四 HTML，32,294 Qwen tokens，共享 `lua.css` 保存；四页 localhost 全页资源/画面对照及三条保存页导航通过，状态 `online_mother_candidate`。本地 Mothers/D 回归 25 项通过，含实际修改保存 JS 改变运行行为的测试。前六次真实试跑均未计为合格结果；保留各自诊断记录。
- 当前目标 3,000、并发上限 8；`url_queue_v1` 为 86,269 个按 host 去重的候选，来源顺序为 4K 预筛、12K 历史成功及 WebCode2M 86,740，附原文件 SHA256。01:26 `mothers-batch-0908-v1` 因物理机负载 64.65 在启动站点前保护停止，`batch` 尝试/通过均 0；后续状态读取同目录 `progress.json` 与 unit。
- 入口：`preprocess.pipeline_mothers.main`；完整 HTML、原始在线 CSS/JS/图片/字体、最多 4 页。保留 C 内容预检和 40K 保存代码筛选；在线回放采用 Chromium 原 URL 文档拦截。
- 物理机：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/online_mothers_20260907_v1/pilot2`。Shadergif 首页、About、Editor selector、Terms 共 4 页分别通过 strict 在线回放；269,121 保存代码 tokens，因超过 40K 拒绝，候选 HTML 和截图保留。付费视觉调用 0，整站导航因 token 门槛提前结束而未在该网站执行。
- 本地真实四页浏览器测试及 D 回归共 18 项通过；包括外链/完整 DOM 保留、保存页面跳转和损坏链接拒绝。批量采集尚未用此入口恢复。

最后现场核验：2026-09-06（0805 增强 v2）

### 0805 Image Generate 增强 v2（2026-09-06）

- 最新追加：API 批次完成后，从正式 `0805_supplement` 的 Image Generate 分片筛出并合入 Vision2Web L1/L2、Flame-VLM-Code、Interaction2Code，共427条（Vision2Web 74/67、Flame-VLM-Code 143、Interaction2Code 143）和427张实体图。目标 release `/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2` 的 Image Generate 从10,765增至11,192；已有ID重复0，GT response SHA-256变化0，图片缺失0，软链接0。导入脚本为 `scripts/import_0805_supplement_image_generate_sources.py`，备份位于 `/data2/adminweihunj/webcoding/WebCoding_Data/backups/0805_v2_before_selected_image_generate_sources_import_20260906/`，release 内保存 `image_generate_source_import_20260906.json`。

- 21:10 从正式 `0805_supplement` 直接加入 WebCompass 来源、`generation_contract.page_mode=multi_page` 的 1,502 条 Text Generate，以及按 `source_instance_id` 对应的 487 条 Image Generate 和 2,012 张实体图。合并时两类为 10,596/10,551；GT 哈希变化 0、旧记录变化 0、重复 ID 0、缺图 0。入口为 `scripts/import_0805_supplement_webcompass_mp_generate.py`，备份位于物理机 `backups/0805_v2_before_webcompass_mp_generate_import_20260906/`，release 内保存导入与验证 JSON；该条为后续 API 批次结束前快照。

- 20:00 2 并发实时 supplement 计数 339/250，运行中 `unmerged=31`。同一增强 v2 的严格多 HTML图片覆盖审计为：Image Edit 14 条中 9 条不完整，Image Repair 25 条中 8 条不完整；其余新增 5/17 条已按页面完整覆盖。该审计只标记待补图，不删除或改写记录。

- 19:02 临时状态口径已对齐 WebCompass 的多图交互推断：接受任何稳定、可观察、截图有实质差异的同页状态，不再要求目标初始隐藏。新规则真实 API＋浏览器首例 transient 通过并写入；批次以 4 并发从断点继续。此刻 `dataset_index.json` 为总 31,089、Image Generate 9,619，独立模式总计 1,988/1,723/317/497；其中 supplement API 运行计数为 208/133，目标仍为 500/500。

- 18:50 最低目标为 supplement 独立新增 1,988/1,500/500/500。多页 1,988、普通交互 1,723 已正式纳入；API 实时后两类为 200/114。当前 release 为 31,041 条、Image Generate 9,571；API 4 并发继续至后两类各 500。

- 18:20 扩批快照：总 29,238、Image Generate 7,768。supplement 存量 2,195 条、API pilot 1 条和扩批浏览器通过 5 条已合入；普通交互 16 并发扫描、两类 API 4 并发续跑中。最终数量以完成后的 `dataset_index.json` 为准。

- 18:07 最新：总 27,037、Image Generate 5,567；新付费调用 1 次，保存回答零 API 回放后追加 sequence 1 条。批次已暂停，余 19 次未调用，在途/未合并均 0；其余任务数量不变。

- 路径：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v2`；来源为增强 v1、reversed v4 中原 0805 同 GT 输入和历史成功截图。
- 新 API 启动前 27,036 条：Text/Image Generate 9,094/5,566，Text/Image Edit 3,005/3,005，Text/Image Repair 3,349/3,017。沿用六目录、每类一个 gzip JSONL、实体图片；大小待批次结束登记。
- 237 条原图输入更新、472 条独立衍生记录；普通交互 1,500 条已覆盖，其中 1,318 条本次补图。调试新图补入已有母本，独立 ID 去重。
- 产物状态：合并包，继承母本 GT/资源/单多页属性；迁移验证 GT 保真与图片引用，新 API 通过真实浏览器截图后追加。尚非全量新质量审计或发布。
- 入口：`scripts/migrate_0805_image_generate.py`、`scripts/finish_0805_image_inputs.py`；依据：包内 `image_generate_migration.json`、`historical_interaction_merge.json`、`debug_merge.json`、`validation.json`；API 批次 `runs/0805_image_generate_batch20_20260906`（最多 20 次、并发 1）。详细状态见训练退化专项报告。

## 使用规则

### Generate 多 HTML 候选盘点（2026-09-06）

- 新 Generate 试产根：物理机 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/generate_multi_html_tokenwave_trial_20260906_v1`；本地新需求与预先固定检查位于 `datasets/generate_multi_html_pilot_20260906/`。用户授权 10 条，TokenWave `gpt-5.5` 并发 1、零自动重试；首个非流式请求在 60.24 秒返回 HTTP 504，代码产出 0、usage 未返回，服务已停止。已保存请求、回执与日志；本地流式调整通过 41 项测试，真实重试待授权。误用 Qwen 的停止记录独立保留于 `runs/generate_multi_html_trial_20260906_v1`。
- 本地清单：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/logs/generate_multi_html_inventory_20260906/`，含候选 JSONL、统计 JSON 和两个原始 query 例子；来自物理机 `releases/0805_supplement` 两个 Generate 分片的只读扫描。
- Text 632、Image 297，完整 GT 代码去重为 635 个版本、633 个源码路径；Text 的 2/3/4/5 HTML 分布 44/139/409/40。状态为结构候选，用于后续母本验证与 query 对齐分析。
- 清单只含 ID、HTML 路径、源码定位与需求长度，GT、图片、资源继续使用来源数据；query 长度仅统计 `<user_request>` 正文。此清单替代此前六分片并集作为母本来源，数量不代表已验收或已生成。

本文件是 WebCoding 数据产物的统一入口。`datasets/`、`runs/`、`releases/`、远端归档或外部发布中每新增一份逻辑数据，都必须追加记录，不得只在聊天、日志或目录名中说明。

每条记录至少包含：

- 数据名称、绝对路径、负责人或产生脚本；
- 来源数据、生成日期、样本数和物理/逻辑大小；
- schema、任务类型、单页/多页构成；
- HTML/CSS/JS 的保留和 token 统计口径；
- 图片、字体和其他二进制资源策略；
- 远程 URL、bundle、占位资源策略；
- manifest、日志、截图和审计文件位置；
- 当前状态：原料、预检查、候选、正式发布、失败证据、已删除；
- 已知缺陷和允许的后续用途。

目录名中的 `full`、`cleaned`、`40k`、`pass` 不能替代上述字段。使用数据前必须读取 manifest，并对会漂移的路径和数量做现场核验。

## 当前存储边界

- 物理机：`adminweihunj@36.213.175.38:65022`
- 当前项目数据根：`/data1/xieqianqian/webcoding/WebCoding_Data`
- 本地仓库只保留代码、文档、配置和小型审计结果；大规模数据以物理机为准。
- 2026-08-29 核验时 `/data1` 只剩 8.1G 可用，不能再承载完整合并包；`/data2` 约有 3.0T 可用，当前合并 release 放在 `/data2/adminweihunj/webcoding/WebCoding_Data/releases/`。

## 在线灵感挖掘审计候选（2026-09-05）

### 修复后独立复验（2026-09-07）

- 物理机：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/live_mining_fix_20260907/`；本地：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/runs/live_mining_fix_20260907/`，约 343 MiB。入口沿用 `mine_live_url_capability_pool.py` 与单 case supervisor。
- 同一 Ant Design 单页面来源、3 张 `webcoding-seed-capability-extraction-v1` 候选卡，紧凑池保留 observation_evidence。引用 3/3 合法；核心行勾选/展开已人工核对，排序完整性和逐卡完整语义待验；非训练发布。
- 2 次真实语义调用、33,781 tokens；首次格式解析失败保留在 `table_full/`，修复后 `table_resume/` 复用原响应完成，新增调用 0。原始观察、响应、extractions 和 pool_manifest 在 `table_full/miner/`。
- 保存 DOM/AX/HTML 状态、截图和差异，资源仍为在线访问，训练工程 token 口径不适用。说明见 [修复记录](live_url_mining_audit_20260905.md)。

### 原审计记录（2026-09-05）

- 生产入口：`inspiration_library/utils/mine_live_url_capability_pool.py`，监管入口 `inspiration_library/utils/run_live_url_audit_case.py`；来源为 v2 URL 池的 Ant Design、HTMLElements、ApexCharts 三个页面。
- 物理机根：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/live_url_mining_audit_20260905/`；本地证据副本：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/runs/live_url_mining_audit_20260905/`，约 430 MiB、28 张 PNG（含副本）。
- 结果：3 个直连 full 失败；同一 Ant Design 代理对照生成 9 张 `webcoding-seed-capability-extraction-v1` 原始候选卡。单页面来源的多状态观察，不是 SP/MP 训练样本；4 张卡存在无效状态引用，允许用于排查/清洗。
- 资源口径：保存浏览器 DOM/AX/HTML 快照、截图与操作差异；网页外链照常访问，不产出 HTML/CSS/JS 训练工程或本地 resources 闭包，训练 token 口径不适用。两次语义调用合计 37,353 tokens。
- 证据：各 case 的 `supervisor_result.json`、`stdout.log`、`events.jsonl`；成功结果在 `table_proxy_full/miner/{pool_manifest.json,extractions/table_ant.json,provider/usage.jsonl,browser_deep/table_ant/observation.json}`。说明见 [试跑审计](live_url_mining_audit_20260905.md)。

## 当前正式或接近正式的数据

### 0805 WebCompass 类型定向增强（2026-09-06）

- 2026-09-06 API 调试候选独立保存于 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/image_generate_debug_20260906_v2/candidates/image-generate/`：`candidate_records.jsonl` 共 2 条（transient 1、sequence 1），6 张实体图片；母本来自本增强包的 webdev_814，GT、资源与代码 token 口径继承母本。两种真实 Chromium 回放及 Codex 关键帧观察通过；属于待合并候选。生产入口 `debug_image_generate_tokenwave.py`，证据见运行根和 `logs/image_generate_debug_20260906/`。

- 路径：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/0805_webcompass_aligned_20260906_v1`。原始 0805 基础 26,520 条，新增 44 条，共 26,564 条；六类分别为 9,094 / 5,094 / 3,005 / 3,005 / 3,349 / 3,017。实体截图 14,241 张。
- 来源：原始 `webcoding_sft_v2_20260805_compatible`；supplement 按 `(8–12 项 OR 至少两个 HTML) AND 全部子任务属于官方类型` 选择整条。新增 Edit 每模态 5 条，Repair 每模态 17 条；8–12 项整条通过数 0。新增 Image Edit 采用 v4 补图记录，源码/指令/答案一致。
- Repair 输入：6,366 条均包含官方 11 类公共定义＋N，具体标签保留为隐藏元数据；Text Repair 读 `repair_instruction` 与 `instruction` 代码，Image Repair 读 `repair_instruction`、`input_files` 和前后截图。输出 patch schema 沿用来源。
- 六目录、单 gzip shard、包内实体截图；代码、GT、外链、bundle 与资源策略继承来源，模型代码 token 未重算。来源选择不代表重新通过网页质量验收。
- 状态：打包完成，约 8.4 GiB；`validation.json` 为 packaging_pass，`preservation_validation.json` 六类全量 exact_record_pass。用于以 0805 为基础的后续训练准备；上传另行授权。
- 生产脚本：`reverse/utils/build_0805_aligned_enhanced.py`；验证脚本：`scripts/verify_0805_aligned_enhanced.py`。7 项单元测试、10 条真实 pilot 通过。根目录保存 `selection.jsonl`、`selection_summary.json`、`lineage.jsonl`、`dataset_index.json`。
- 详细记录与版本关系：[0805 增强与训练问题报告](reversed_edit_repair_training_regression_20260906.md)。本地审计副本：`logs/0805_aligned_enhanced_20260906/`；物理机运行日志：`runs/0805_aligned_enhanced_pilot_20260906/{build,verify}.log`。

### reversed Image Generate 输入更新 pilot（2026-09-03）

- 状态：候选 pilot，未合入正式 release；零 LLM 调用，不修改 GT。
- 物理机路径：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_image_generate_input_refresh_20260903_pilot12/`；本地截图副本：`runs/reversed_image_generate_input_refresh_20260903_pilot12/`。
- 当前结果：6 条多页入口标注通过；6 条交互候选中人工接收 4 条、弱差异拒绝 2 条。3% 差异门替换运行因物理机 SSH 连续 reset 暂停。
- 生产脚本：`scripts/pilot_refresh_reversed_image_generate.py`；计划与接收口径见 `docs/reversed_image_generate_input_refresh_plan_20260903.md`。

### reversed v4 Image Generate 原地扩充（2026-09-04）

- **当前运行状态：保护暂停。** `reversed_api_2way_20260905` 8 个 API 父样本提交，实际截图 transient 1/3、sequence 2/5；全部 3 条成功已追加，Image Generate 10,773 行、独立两类 283 / 396。HTTP 400 `Request body is empty` 触发停止，服务 inactive、在途 0；保存失败，不自动重试，规划通过率尚低于 80% 目标。
- **API 首批追加：** 同一运行内 3/3 实际截图通过，transient 新增 1、sequence 新增 2；Image Generate 共 10,773 行，两类独立行 283 / 396，六任务 63,438 行。不可用空计划过滤问题修正后继续原批次，运行中的未合并候选数量以心跳为准。
- **2026-09-05 API 批跑启动快照：** 真正的 API 计划重放又追加 1 条 sequence；v4 Image Generate 共 10,770 行、32,132 张图，独立两类 282 / 394，六任务共 63,435 行。当前 shard SHA-256 `3307bf9dc62446afa590d1c6b760aeaf5c5018e671c1760625e124d93d3f62cf`。新增运行根 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_api_2way_20260905/`：`gpt-5.5` 源码规划、浏览器状态与截图验证、同 v4 幂等追加；用户授权并发 2，每类目标 2,000。运行心跳、API usage、失败与 manifest 均在该根；成功候选和已追加行仍分开计数，完整质量复核另计，详见交接。
- **2026-09-05 最新写入：** 用户要求临时状态、连续步骤各 2,000 条独立训练记录；同一母本两类均可行则生成两条独立 ID/图片/指令记录。现有 v4 已追加 675 条（282 / 393），Image Generate 共 10,769 条，六任务合计 63,434 条；配额按 `metadata.image_generate_primary_mode` 与独立行统计。
- 写入位置：`/data2/adminweihunj/webcoding/WebCoding_Data/releases/reversed_20260903_v4/`；保持六任务目录、Image Generate 单 gzip shard 和原有 10,094 行。新增行复用母本 GT，图片独立物理复制。写后审计确认原行摘要一致、全量图片引用有效、2,189 张新图可解码且无软硬链接；图片文件共 32,129 个，索引匹配，其他五类任务索引保持。
- 当前 shard SHA-256：`7ee1cc8925c82add6ad59a154280f22155892e33504ba221ea1d3e6fdec12a72`。备份位于 `/data2/adminweihunj/webcoding/WebCoding_Data/backups/reversed_v4_before_independent_probe_20260905/` 和同级 `reversed_v4_before_independent_existing_20260905/`，各有追加日志和图片清单。生产入口 `apply_image_generate_overlays_in_place.py` 默认独立追加，23 项测试及真实探针通过。追加验收不替代逐条完整质量复核。
- 最新目标（2026-09-05 用户确认）：已有多页 2,000、普通交互 1,500 条候选全部保留，只补临时状态、连续步骤各至少 2,000 条；源码预筛后实际尝试截图通过率目标至少 80%，按 `(mode, parent_instance_id)` 去重，GT 可跨类复用，原图外链失败可保留。15:57 联合三处 manifest 的唯一成功数为 282 / 393，分别还差 1,718 / 1,607；启动器改为每分区目标 250 并纳入 pilot 去重。
- 最新选择性校准：旧 16 worker 已停止，保留 transient 275、sequence 383 条候选。`/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_selective_pilot20_20260905/{transient,sequence}` 保存两类固定各 10 次真实回放及失败：8/10、10/10，通过候选 18 条、54 张图，GT 哈希变化 0，使用计划 `configs/reversed_selective_capture_pilot_20260905.jsonl` 和 `image_generate_capture_plan.py`。继承原训练 row/schema，计划与断言仅存旁路 evidence；允许保留原图外链失败。成功结果已按独立行追加入 v4；校准通过率非全量随机通过率。源码审核的本地 HTML/JS 副本在 `logs/reversed_selective_source_review_20260905/`，代表预览在 `logs/reversed_selective_pilot20_20260905_preview/`。

以下为历史运行快照，当前行数与执行状态以上方 2026-09-05 独立追加记录为准。
- 最新运行（2026-09-05 14:54）：用户授权扩到 16 worker，两类各 8 分区。旧候选 transient 226、sequence 280 只读保留，新增候选根 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_image_generate_guarded_16way_20260905/`，日志 `logs/reversed_guarded_16way_20260905/`，由 `start_reversed_image_generate_guarded_worker.sh` 启动。每分区成功配额 125 含旧结果，累计尝试上限 1,400。新增结果沿用旧 manifest/截图 schema，保持源 GT 和资源引用；状态为待复核候选，后续与旧候选根联合合并。两类 16 并发替代下面历史 4/9 worker 快照。
- 2026-09-05 SSH 恢复后现场候选快照：multipage 2,000、interaction 1,500、transient 174、sequence 216；旧 worker 均已结束。当前恢复 transient/sequence 各 2 个 shard，共 4 个 systemd worker，每个 cgroup 内存硬限 2 GiB，日志 `/data2/adminweihunj/webcoding/WebCoding_Data/logs/reversed_guarded_4way_20260905/`。正式 shard 仍待本轮结果复核合并。
- 两次原地写入已完成；停止前累计的 2,387 个 accepted mode 结果已全部处理。当前实际类型计数为 2,022 / 335 / 103 / 102；Image Generate 图片 29,940 个，缺失引用 0，GT 相对合并前备份变化 0。
- 运行证据：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_image_generate_minimum_16way_20260904_v1/`。interaction/sequence 卡点修复后于 2026-09-04 23:52 先恢复 2 个 worker；主机空闲后于 2026-09-05 00:25 分批增加 7 个未完成 shard，当前共 9 个低优先级 worker。原 2 个日志位于 `logs/reversed_image_generate_resume_guarded_20260904_v3/`，新增 7 个日志位于 `logs/reversed_image_generate_resume_guarded_20260905_v4/`。单条样本在独立进程内执行，父进程保留 120 秒硬超时、30 秒心跳和子进程组清理。内部目录不是训练分片。
- release 外备份：`/data2/adminweihunj/webcoding/WebCoding_Data/backups/reversed_20260903_v4_before_image_generate_refresh_20260904_v1/`。
- 第二次合并备份：`/data2/adminweihunj/webcoding/WebCoding_Data/backups/reversed_20260903_v4_before_image_generate_refresh_merge_20260904_v2/`；合并后 Image Generate shard SHA-256 为 `8ace057859d40cb11a98165cdbc2cb4b94f4652098ca6f9ccae45121739f336b`。当前未授权更新 ModelScope。

| 数据 | 物理机路径 | 数量/大小 | 口径与资源 | 当前结论 |
| --- | --- | --- | --- | --- |
| WebCompass 6503 SFT v2 | `releases/webcompass_6503_sft_v2_20260806` | 6.1G；六任务分别为 9,094 / 5,094 / 3,000 / 3,000 / 3,332 / 3,000 | 6,503 个项目中 6,502 个通过全代码 Qwen 40K；带任务 JSONL、assets 和 provenance | `audit_summary.json` 当前为 `fail`，image-repair 大量 pixel-ratio metadata 不一致；不能按正式通过发布 |
| WebCoding SFT v2 兼容布局 | `releases/webcoding_sft_v2_20260805_compatible` | 8.4G；数量与上项一致；14,102 个文件 | 上项的 ModelScope/v2 兼容布局；图片任务分别有 5,094 / 3,000 / 6,000 个图片文件 | schema 和图片路径已有 `dataset_index.json`；质量继承源 release，不能因重新打包视为修复 |
| 0805 supplement 六任务正式包 | `releases/0805_supplement` | text/image generate 15,000 / 5,000；text/image edit 2,974 / 2,974；text/image repair 5,918 / 4,373；图片共 38,677 张 | 0805 任务目录、gzip JSONL、任务本地图片和统一 `dataset_index.json`；本地与 ModelScope Git tree 的 38,685 个文件完全一致 | 已上传到 `mistletoe111/webcoding_stf/0805_supplement`，远端 commit `048282458cdfd2a06cfbfc252a9264e93c01d3c9` |
| reversed v4：Image Edit 全页面图 + Image Generate 原地扩充 | `/data2/adminweihunj/webcoding/WebCoding_Data/releases/reversed_20260903_v4` | API 批跑启动快照：六任务 63,435 条；Image Generate 32,132 张图、10,770 条 | 六目录/单 gzip shard；保留原行，独立临时状态 282、连续步骤 394 行；GT 复用母本，图片为物理文件 | API/截图并发 2 已启动，每 50 条及运行结束时追加，最新数量查索引；完整质量复核另计；ModelScope 最后验收仍为 v3 |
| reversed：0805 + supplement 合并训练包 | `/data2/adminweihunj/webcoding/WebCoding_Data/releases/reversed_20260829_v3` | 六任务 24,094 / 10,094 / 5,974 / 5,974 / 9,250 / 7,373；62,759 条；52,771 张图；13,476,946,664 bytes | 保持 0805 v2 六目录/单 gzip shard 布局；Image Generate 10,094 条均使用同一截图驱动通用提示词；Repair 只告知 N，`task_type` 值为隐藏元数据；52,780 个普通文件，软/硬链接均为 0 | 已上传并验收到 `mistletoe111/webcoding_stf/reversed`；本地/远端文件均为 52,780，大小差异 0；见 `reversed_combined_release_20260829.md` |
| ShareGPT provenance fixed v2 | `releases/sharegpt_0805_provenance_fixed_20260817_v2` | 843M；3 个 JSONL：10,503、1,000、7,503 行 | ShareGPT 文本序列与 complex1k 组合版本 | 当前只核验了文件与行数；正式使用前还需 schema、去重和 provenance 审计 |
| ShareGPT provenance fixed 空目录 | `releases/sharegpt_0805_provenance_fixed_20260817` | 4K；0 个文件 | 无有效产物 | 空壳目录，不得计入数据规模 |

六任务顺序为：text-generate、image-generate、text-edit、image-edit、text-repair、image-repair。

## 网页底稿与 40K 实验

### 灵感 URL v2：替换与均衡优先队列（2026-09-05）

- 位置：`datasets/url_lists/balanced_inspiration_v2_20260905/`，见 [使用说明](../datasets/url_lists/balanced_inspiration_v2_20260905/README.md)。由 `scripts/rebalance_inspiration_links.py` 生产，来源配置 `configs/inspiration_rebalance_20260905.json`。
- 15,609 条唯一 URL、9,003 个 host、145 个来源组；从原 15K 保留 13,724，移出 1,276，新增 1,885；原池保留。目录约 27 MiB，URL/元数据约 16.9 MB。当前为灵感候选，按独立页面 URL 组织，SP/MP 按后续观察确定。
- `manifest.jsonl` / `urls.txt` 为全池；`added.jsonl` / `replaced.jsonl` 保存增补和逐条原因。`collected_sources.jsonl` 与 `source_indexes/` 保存 46 个公开来源入口的索引证据；HTML/CSS/JS 模型内容和 token 统计在后续网页处理阶段产生，资源策略为保留外链。
- `edit_priority_sources.jsonl`：1,869 条定向候选，含唯一主目标、Construct 要求和来源依据。`balanced_core_sources.jsonl` 为其 URL 子视图，共 144 条，WebCompass 16 类各 4、其他 40 类各 2，每类至少两个 host；两种视图按 URL 去重使用。
- 38 项相关测试和实际 URL/来源/loader/配额检查通过；`validation.json` 保存结果，`edit_balance.json` 保存逐类剩余缺口。全池真实功能分布与浏览器验收由后续观察确认。SHA-256：`3370cb4669c0413f577f8c3ddfab2d141ede5b7dfd87e538bb7d529229abe9a2`。

### 15K 灵感 URL 与 56 类优先队列（2026-09-05）

- 位置：`datasets/url_lists/diverse_inspiration_15000_20260905/`，见 [使用说明](../datasets/url_lists/diverse_inspiration_15000_20260905/README.md)。保留原 10K 并新增 5K；15,000 条标准化去重 URL、8,910 个 host、132 个来源组。
- 分布：画廊 4,612、领域应用 4,445、组件文档 4,332、交互示例 1,611。`urls.txt` / `added_urls.txt` / `manifest.jsonl` / `urls.csv` 提供完整及增量视图。
- `edit_priority_sources.jsonl` / `edit_priority_urls.txt`：135 条定向入口，类型和完整观察要求来自 Construct；`edit_coverage_matrix.json` 为 56 类逐项提供至少两个不同站点的主/备用来源。来源准备状态 `targeted_sources_ready`，行为验收状态 `browser_validation_pending`。
- 验证：25 项相关测试通过；实际 15K 的前缀保留、唯一性、视图对齐、统计和135条 loader 检查通过。SHA-256 `784024b1416a2147a7a8f782d68ec3ddb37c5b1945b5197d97821a0fde422102`。用途为在线灵感候选与定向探索计划。

### 多来源灵感 URL 10K（2026-09-05）

- 位置：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/datasets/url_lists/diverse_inspiration_10000_20260905/`；生成脚本 `scripts/build_diverse_inspiration_links.py`，来源配置 `configs/inspiration_url_expansion_20260905.json`。
- 规模：原 4,000 条保留，新增 6,000 条；合计 10,000 条标准化去重 URL，7,041 个 host，65 个来源组。画廊 4,010、领域应用 3,124、组件文档 2,154、交互示例 712；最大来源占 8.66%。
- 来源：6 个设计画廊、25 套组件/设计系统、14 个交互示例来源、20 个应用/领域目录与人工入口组。新增公共数据、国际教育、中文产品、医疗、生物、气候能源、数字人文、地图和创意工具等方向。
- 文件：`urls.txt` 349,381 bytes、`added_urls.txt`、`urls.csv`、`manifest.jsonl`、`source_distribution.csv`、四类分组 TXT、`summary.json` 和来源索引证据。完整清单 SHA-256 `d574b35f89db3f9df46ad1e721bdfe55aa0a102aa505a715435744a8bf821f7c`。
- schema：沿用原 4K URL/provenance 字段，新增项包含领域组、目录栏目、入口信息及明确来源风格线索；资源策略为 URL 引用，状态 `source_listed_url_only`。
- 验证：6 项测试通过；完整/增量数量、标准化唯一性、原 4K 记录保留、TXT/CSV/JSONL 对齐及分组统计均通过。详见 [`10K 清单 README`](../datasets/url_lists/diverse_inspiration_10000_20260905/README.md)。
- Edit 缺口增量：`edit_gap_supplement.jsonl` / `.txt`，23 条官方定向入口，与原 10K 去重，合计 10,023 条候选。记录来源、目标类型、观察重点、可加载的 `seed_id` / `entry_url`；23/23 HTTP 200，状态为 `source_checked_browser_pending`。逐项审计见同目录 `edit_type_coverage.md`。

### 多来源灵感 URL 4K（2026-09-05）

- 位置：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft/datasets/url_lists/diverse_inspiration_4000_20260905/`；生成脚本：`scripts/build_diverse_inspiration_links.py`。
- 规模：4,000 条去重链接，2,632 个 host，27 个来源组；组件文档与示例 1,381、领域应用 1,100、设计画廊原站 1,519。领域标签 106 个，目录 Demo 地址 288 条。
- 来源：19 套官方组件系统的 sitemap/导航目录，5 个已有设计画廊原站 manifest，Awesome Selfhosted、无需登录 Web Apps 目录及人工领域入口。
- 文件：`urls.txt` 136,955 bytes，`urls.csv`、`manifest.jsonl`、三个分组 TXT、`summary.json` 与来源索引快照。文件大小以当前目录为准；完整清单 SHA-256 `2c9d7eb997a28f4cf00e9aebc6dea07ff4f5773bab1c1b7a510fca8fe03df6e3`。
- schema：URL、来源、目录类别、入口形态、用途及出处；状态为 `source_listed_url_only`，用于在线灵感提取。资源策略为 URL 引用；本轮处理内容为来源索引和链接清单。
- 验证：3 项选择/去重测试通过；4,000 条 TXT、CSV、JSONL 顺序与内容一致，分组数量合计正确。说明见 [`清单 README`](../datasets/url_lists/diverse_inspiration_4000_20260905/README.md)。

| 数据 | 路径 | 数量/大小 | 代码与资源策略 | 当前结论 |
| --- | --- | --- | --- | --- |
| 已清洗 7,302 项底稿 | `runs/final_projects_cleaned_40k` | 19G；7,200 单页 + 102 多页 | 7,650 HTML、85,875 CSS、75,335 JS、7,650 PNG；PNG 主要是截图。历史清洗已删除部分 tracker、cookie 和代码依赖 | 历史救援集当前最有价值的视图之一，但目录名不证明所有项目已按最终全代码 40K 口径通过，也不是原网页逐字镜像 |
| 40K 全外置实验 | `runs/final_projects_externalized_40k_full_v1` | 7.0G；7,302 候选，7,202 pass、100 reject | `max_code_tokens=40000`、`externalize_all_code_dependencies=true`；目录只有 7,650 HTML、83,525 CSS、110,700 JS，无图片和字体文件；manifest 仍有 `bundle_files_omitted` | 正是“CSS/JS 受 40K 实验约束、图片等未下载”的数据。抽样 HTML 仍指向 `picsum.photos`；无最终离线截图，只作实验参考，不进入训练 |
| 排除 bundle 的 40K 实验 | `runs/bundle_only_excluded_40k_full_v1` | 4.1M manifest/summary；1,457 pass、5,845 reject | 40K 统计排除 36,713 个 bundle，共约 3.86GB | 不符合“所有保留代码都计入 40K”的最终口径，只作门禁对照 |
| 全代码 40K 重筛片段 | `runs/final_projects_full_code_40k_rescreen` | 60K manifest；31 pass、123 reject | HTML/CSS/JS 全部计数，40K；只有审计 manifest，项目路径仍指向已不存在的旧 release | 不能作为独立数据集；用于证明全代码口径会显著降低通过率 |
| 单页 60K 历史救援 | `runs/legacy_rescue_unified_60k_single_5k` | 19G；历史正式通过 7,200 项 | 旧 60K 与历史资源清洗策略 | 保存追溯和重筛价值，不按当前 40K 直接训练 |
| 多页 60K 历史救援 | `runs/legacy_rescue_unified_60k_multi_3to7` | 558M；历史正式通过 102 项 | 3–7 页多页底稿，旧 60K 策略 | 多页结构有价值；使用前重跑当前资源、全代码和视觉门禁 |

### 40K 全外置实验的现场证据

- `summary.json`：`total=7302`、`pass=7202`、`max_code_tokens=40000`、`externalize_all_code_dependencies=true`。
- 文件类型现场统计中没有 PNG、JPG、WebP、SVG、WOFF、WOFF2、TTF、OTF。
- 抽查 `0004994_sarahburgard.com/news.html`，图片仍使用 `https://picsum.photos/...`。
- manifest 的 `code_tokens` 不能解释为最终“全部代码”口径，因为同一记录还写有 `bundle_files_omitted`。

## URL、query 与小型研究数据

### 0805 系列真实多页复用池盘点（2026-08-27）

- 状态：已完成只读盘点，尚未启动新增付费构造；物理机结果位于 `logs/true_mp_reuse_inventory/true_mp_reuse_inventory_20260827_v2/`，候选 manifest 为 `candidates.jsonl`，汇总为 `summary.json`。
- 口径：只有完整模型输入中至少两个独立 `.html`/`.htm` 文档才计为 MP；单 HTML hash-route/SPA 归为 SP。脚本为 `scripts/inventory_true_mp_reuse_pool.py`，同时记录 clean-code hash、source project、截图覆盖和 Repair patch 回放。
- 0805 物理 MP：text/image generate 36/14、text/image edit 9/9、text/image repair 10/8；0805_supplement 物理 MP：632/297、194/194、359/292。
- 可复用性：两套 release 共 677 个不同 clean-code 物理多页项目，其中 supplement 为 638 个；已有 clean/canonical 图片的不同 clean-code 项目为 508 个。651 个不同 `source_project` 路径现场均存在；Repair 物理多页记录 patch 回放失败数为 0。
- 代码修正：母本池、`infer_page_bucket`、构造筛选、导出 `page_type` 和跨页 patch 门已统一使用独立 HTML 数量；旧逻辑把 route 数量当页面数，是 1,580 条 supplement Edit `mp→sp` 误标的根因。相关测试 78 passed。
- 失败证据：`true_mp_reuse_inventory_20260827_v1` 在读取数据前因物理机无全局 `uv` 退出；v2 改用项目 `web-coding-agent/.conda/lora/bin/python` 并成功完成。v1 不含候选数据。
- 第 3 项生产目标（2026-09-06 更新）：Edit/Repair × MP/SP 四组各 1,000，按官方 MP 4–12 项、SP 8–12 项条件分布分配。当前缓存全池母本 Edit MP/SP 194/1,200、Repair MP/SP 292/1,721；多页扩充/复用策略待确认。`datasets/0805_webcompass_edit_repair_plan_20260906_v1/` 为历史各 150 计划，含 1,086 个尝试位，远端源码目录及 canonical 截图存在，状态 `planned_not_run`；v2 工作清单待生成。详细配额见训练退化报告第 3 项。

### 页面状态关系连续 Edit query 小试（2026-08-28）

- 状态：query 规划实现与真实 Seed 小试；不是训练 release。最终 run 为 `runs/state_hypergraph_edit_workflow_20260828/cold_chain_v7/`，持久日志为 `logs/state_hypergraph_edit_workflow/cold_chain_v7/`。
- 原料：`runs/counterexample_history_causal_pilot_3_20260824_v1/seeds/cmtt-seed-cold-chain/`，4 个本地文件、22,383 bytes，内容 SHA-256 `3a6783e4458e913d2577bcdf602d7d689192cb1c977e59a5d4ab361eb97a39a8`。这是本地静态 pilot Seed，业务数据为 hardcoded fixtures，不是线上生产快照。
- 输入与入口：`configs/state_hypergraph_edit_workflow/cold_chain_seed.json`、`configs/state_hypergraph_edit_workflow/cold_chain_verified_capabilities.json`；实现为 `inspiration_library/state_hypergraph.py`；CLI 和 runner 为 `scripts/run_state_hypergraph_edit_workflow.py`、`scripts/run_state_hypergraph_edit_workflow.sh`。
- 产物：4 条 Edit query 计划，结构为一条共同前驱、两个 sibling 分支和一条读取两分支输出的后续 Edit；`queries.jsonl` SHA-256 `9d1ece1e490083d880014a9bf2329a4d639a1771db72865836a8be8b650f1dde`。模型/API 调用为 0。
- 结构检查：带类型状态覆盖率 100%，缺失类型 0；最终 merge 仅保留两个 sibling parents，共同祖先通过 `state_provenance` 追踪；Q2/Q3 因共享三个写入文件标记为仍需浏览器顺序审核。
- 浏览器证据：只重新验证了原始 Seed。desktop/mobile、CC-204 release、离线资源、无 console/page error 均通过；结果与截图在 `cold_chain_v7/source_browser_verification/`。Q2–Q4 的 source 尚未物化，4 个 target 均未生成。
- 质量结论：独立 Codex 只读审查对 query 规划给出 `ACCEPT`，四条平均 4.6/5；训练准入为 `REJECT / not eligible`。`quality_audit.json` 保存三轮问题与修正、长度参照和缺失门禁。
- 训练边界：Query 1 source 为 `verified_seed`，Query 2–4 source 为 `planned_version_not_materialized`；所有 target 为 `not_generated`，所有记录均为 `training_admission=not_eligible`，不得计入数据量或训练集。
- 报告：`docs/state_hypergraph_edit_workflow_pilot_20260828.md`。

### 连续 Edit 完整 target 单例（2026-08-28）

- 状态：本地研究单例，4 条训练记录全部通过当前准入；不是批量 release。路径为 `runs/full_state_edit_materialization_20260828/cold_chain_full_v1/`，持久日志为 `logs/full_state_edit_materialization/cold_chain_full_v1/`。
- 原料：同一冷链静态 Seed、`cold_chain_verified_capabilities.json` 与 `cold_chain_v7/queries.jsonl`。自动 Seed 观察与 Top-5 donor 召回另存于 `runs/automatic_state_edit_workflow_20260828/cold_chain_auto_v1/`，避免把自动得到的 `join` 计划与预先核验的 `fork_join` 四步计划混为一谈。
- 页面版本：Q1、Q2、Q3、Q2→Q3、Q3→Q2、Q4 共 6 个；Q2→Q3 与 Q3→Q2 均通过累计能力检查和 7 组 Seed 回归，选择修改量更小的 Q3→Q2 作为 Q4 source。
- 数据：`training_records.jsonl` 共 4 行，均为 `status=ok` 和 `training_admission.status=eligible`；每条保存真实 source/target 路径、query、状态输入输出、donor 证据和七项准入结果。
- 模型：target 阶段使用 Doc API `qwen3.8-max` 7 次，其中 6 次生成、1 次 Q4 定点 Repair；所有请求 `sdk_retries=0`、`outer_retries=0`，request/response/usage 全部保存在 run 的 `provider/`。成功后断点重跑未增加 usage 行。
- 浏览器与补丁：所有 target 的累计新能力、原功能回归和离线资源检查通过；6 个页面版本各自完成 1440×1000 与 390×844 布局检查，共 12 个 viewport，无横向溢出、远程请求或浏览器错误。全部生成补丁和 Q4 Repair 补丁可独立重放。失败检查和失败 target 保留在原版本目录，没有覆盖。
- 审计：`quality_audit.json` 为 `status=ok`，6/6 stage 的生成/Repair patch、target digest 和浏览器证据通过；7/7 provider 日志和 4/4 训练准入通过。`layout_audit.json` 为 `status=ok`。审计入口为 `scripts/audit_full_state_edit_materialization.py` 与 `scripts/audit_full_state_edit_layouts.py`。
- 入口：生成与恢复为 `scripts/run_full_state_edit_materialization.py`、`scripts/run_full_state_edit_materialization.sh`；报告为 `docs/continuous_edit_full_materialization_pilot_20260828.md`。
- 边界：只有一个 hardcoded 本地业务 Seed；尚未证明多 Seed 产率、等预算成本或下游 WebCompass 训练收益。

### 部分双能力 Edit 冷链回测（2026-08-28）

- 状态：生产控制逻辑与真实浏览器回测通过，不是训练 release。最终路径为 `runs/mixed_capability_edit_20260828/cold_chain_partial_dual_v3/`，日志为 `logs/mixed_capability_edit/cold_chain_partial_dual_v3/run.log`。
- 输入：复用冷链 Seed、四张已核验能力卡、自然 Edit query 和 `runs/full_state_edit_materialization_20260828/cold_chain_full_v1/` 的 accepted 页面版本；新增付费 LLM 请求 0，新增 target 0。
- 数据形态：5 轮预算示例中 3 个单能力槽、2 个双能力槽；该比例只用于验证上限，不是生产配额。硬依赖 `structured_release_history→destination_release_summary` 只物化可行方向，反向因缺少 `release_events` 在生成前拦截。
- 真换序：`destination_release_summary→saved_release_views` 与反向顺序的两个真实终态均通过 3 项累计新增能力和 7 项 Seed 回归；结果说明该对顺序兼容，不是硬依赖。
- 浏览器：单能力、硬依赖终态和两个换序终态合计 37 条 target/回归检查通过；原始 Seed 上 2 条新增能力路径按预期失败，合计保存 39 张截图。远程请求、console error 和 page error 均为 0。
- 实现片段：3 个 accepted 能力打包 22 个精确补丁片段、24,323 个参考字符；每组补丁从 source 顺序重放后与 accepted target 文件逐字一致，训练指令不可见。
- 代码与测试：`instruction_augmentation/mixed_capability_edits.py`、`scripts/run_mixed_capability_edit_pilot.py`、`scripts/run_mixed_capability_edit_pilot.sh`；新增纯逻辑测试 9 项通过。报告为 `docs/mixed_capability_edit_pilot_20260828.md`。
- 准入边界：复合双能力 query 尚未独立自然度审核，run 标记 `training_admission=not_eligible_pilot_evidence_only`；没有证明多 Seed 产率、代码片段降本、最佳双能力比例或下游训练收益。

### Critical-pair 状态细化指令扩增 pilot（2026-08-25）

- 配置：`configs/critical_pair_state_refinement_pilot_3_20260825.json`；生成入口：`scripts/critical_pair_state_refinement.py`；独立审计入口：`scripts/audit_critical_pair_state_refinement.py`；运行包装：`scripts/run_critical_pair_state_refinement_pilot.sh`。
- 稳定生产入口：runner 的默认 stage 为 `pipeline`。它先做零调用 `interaction_spec` 准入和稳定选择器覆盖检查，再按追加式状态机执行生成、验证、有限修复、合成和审计；默认 `max_attempts=1`、`max_browser_repairs=1`、`max_model_calls=9`。修复项目哈希不变或浏览器失败指纹重复时立即熔断，全部调用使用版本化日志。
- 候选范围：三个本地静态 Ground Truth 页面上的四个临界对候选，包括植物比较×保存视图、新闻购物车×促销、能源比较×保存场景，以及植物比较×归档资格。每条保留原始指令、两个组件组、A→B/B→A 中间项目、浏览器见证和逐次修复证据；只有满足完整接收契约的候选才导出训练任务。
- 接收契约：两个组件组先分别通过独立浏览器检查；初始双路径必须在配置指定的业务观察维度上出现差异；新增协调指令分别作用于两条路径后，两个实现均通过 A/B/C 检查且同一轨迹的 URL 与产品可见状态完全汇合。storage 表示差异只作诊断证据。
- 伪冲突控制：金额和日期区间使用类型化观察，CSS/DOM 挂载、稳定选择器范围和横向溢出先作为普通实现缺陷处理；修复后自然汇合的三个候选被拒绝。植物比较×归档候选保留了 3 个产品可见分叉维度并成为唯一接收样本。
- 接收样本：`output/critical_pair_state_refinement/20260825_botanical_archive_real_qwen38max/`；日志在同名 `logs/critical_pair_state_refinement/` 目录。初始见证为 A→B 的 `1 selected` 对 B→A 的 `2 selected`；协调后两路均为 `selected_count=1`、`archived_selected_count=0`，fresh semantic delta 为空。
- 最终数据：`canonical/botanical_compare_archive_eligibility/task_view.json` 与追加式 `canonical/task_views.jsonl`，分别 SHA-256 `76211cbc9e6a4be3d87d0757bf846e7cc2169fb9a3c75bd9cd7ef2c3e54b5251`、`e7fe33d36f9ed4da7391a002ff473e99eb70c8ec0f69e4cbe53f3b72d13e1cd4`。扩增指令 2,436 字符，原指令 346 字符。
- 独立审计：`audit/summary.json` 为 `status=ok`。两条最终实现各自通过比较、归档、恢复、协调和见证检查，无 console/page error、失败请求或远程请求；精确 Qwen 全代码 token 为 12,046 与 12,608，均未排除 bundle 且低于 40K。
- 模型与人工边界：组件、双路径、协调契约和两条最终规范化实现使用真实 `qwen3.8-max`，没有 mock LLM。普通路径修复在真实模型连续失败后包含版本化的最小 DOM 修复，元数据明确标记为 `manual_minimal_dom_contract_repair_after_qwen_exhaustion`；最终参考代码仍由协调阶段真实模型生成。
- 其他运行：植物保存视图 `20260825_pilot3_real_qwen38max_dashscope`、新闻促销 `20260825_civic_real_qwen38max`、能源场景 `20260825_grid_real_qwen38max`，均只保留为拒绝/调试证据，不计入训练样本。
- 稳定性回放：`20260825_stable_pipeline_preflight_v1` 对四候选得到 3/4/4/13 分，前三条在模型调用前拒绝；`20260825_stable_pipeline_low_gate_v1` 证明完整 `pipeline` 对低价值候选以 0 调用退出；`20260825_stable_pipeline_resume_replay_v1` 从复制的真实历史节点自动恢复，以 0 个新增模型调用重新完成全套浏览器检查和 fresh 独立审计，audit 为 `status=ok`。
- 稳定版全新真实运行：`20260825_stable_pipeline_fresh_real_v1` 使用 `qwen3.8-max`，组件组 A/B、A→B/B→A、协调契约和两条最终实现共 7 次模型调用，所有阶段均为第一次生成通过，普通修复与最终规范化修复均为 0。初始产品差异为 3 项，最终 semantic delta 为空；fresh audit 为 `status=ok`，两路全代码 token 为 12,206 / 12,886，canonical SHA-256 为 `c4da67090a0c6f06932e30f465d0fb495f58ebfb577dbfe15cbecd9221b7af2e`。
- 当前结论：工程闭环和一个理想单例成立，研究新意仍是有文献依据的假设。该 pilot 不计入规模化正式 release；下游收益、跨框架稳定性和与等预算累积测试的对照仍未完成。

### ArtifactsBench 高审美母本候选（2026-08-24）

- 路径：`tmp/premium_mother_candidates_20260824/`；当前为人工确认前的候选，不计入正式数据规模。
- 已实现 `ArtifactsBench:benchmark:14` 日本和服 SVG 母本：自包含 HTML/SVG/CSS/JS，无远程资源；包含青海波、麻叶、樱花纹样、季节切换、hover 与风动动画。
- 真实本地 HTTP 浏览器验证：canonical 截图为 `artifactsbench_14_kimono/canonical.png`，季节切换与风动状态生效，控制台 error 为 0；静态验证脚本为 `validate_candidate.py`。
- `shortlist.json` 保存 8 条高审美 ArtifactsBench 原始 query；第二母本 `ArtifactsBench:benchmark:1582` 非遗文化长页面已实现为本地多文件项目，主视觉素材 SHA256 为 `825b66a748712a77562b2402fc4912f40912b9388b871beffa1de4936247fe7b`。
- 第二母本真实浏览器验证：桌面首屏、三艺、匠心、图志、观展和 390×844 移动端截图均已保存；tab 切换、accordion、预约 modal/form/toast 均生效，页面 console error 为 0。浏览器内置 full-page 拼接对该长页产生重复首屏，因此 canonical 使用正常 viewport 截图，并额外保存四张章节截图，异常拼接图未保留为 canonical。
- 状态：两个母本均已由用户通过截图确认，并已用于下述 premium image Edit/Repair 单例数据。

### `0805_supplement_premium_examples_v2`（2026-08-25）

- 状态：本地正式单例；路径为 `releases/0805_supplement_premium_examples_v2/`，格式与 `0805_supplement` 对齐。
- 数据量：image-edit 1 条、image-repair 1 条，均为单页且各含 5 个 task type；Edit 为 Tab Switch、Modal、Hover、Animation、Conditional Rendering，Repair 为 Background Rendering、Layout Collapse、Typography Overflow、Contrast Regression、Content Occlusion。
- 构造：Edit 使用 `ArtifactsBench:benchmark:14` 和服 SVG clean mother，7 个 exact patch 生成目标；Repair 使用 `ArtifactsBench:benchmark:1582` 非遗页面，5 个 rule injection 形成 defective 输入，再由 5 个 exact patch 恢复 clean target。Repair instruction 固定为 `Repair the provided web project.`，不包含缺陷描述。
- 图片：image-edit 正式输入仅含编辑前图，编辑后图保存在 `image-edit/audit/`；image-repair 含 defective src 与 clean dst。截图实际浏览器内容区域均为 1265×712，Edit/Repair 前后变化像素占比分别为 0.197936 / 0.555591。
- 验证：0805 schema 校验、patch round-trip、资源闭包、5 个 task type 唯一性和 Qwen 40K code-token gate 均通过；Edit/Repair code tokens 为 6,360 / 7,815，浏览器 console error 为 0；结果见 `quality_report.json`。测试为 9 passed。
- 构造入口：`scripts/build_premium_image_edit_repair_examples.py`；审计入口为 `scripts/run_premium_image_tasks_audit.sh`。早期 `releases/0805_supplement_premium_examples/` 因把应用内浏览器内容截图错误写死为 1280×720 而终止审计，仅保留为失败证据，不用于交付。

### 视觉 benchmark 的纯文本替代扩增（2026-08-20）

- 计划：`configs/visual_benchmark_text_proxy_7k_20260820.json`。
- pilot：`datasets/benchmark_query_research/visual_benchmark_text_proxy_pilot_v2_20260820/`；人工查看版为 `docs/visual_benchmark_text_proxy_7k_pilot_review_20260820.md`。
- 目标：新增 7,000 条 generation-only 纯文本网页 PRD，与现有可用 8,088 条合计约 15,088 条。
- 覆盖：九个原生视觉输入 benchmark；其中 Vision2Web 为 3,000 条 L1 多视口文本需求和 600 条 L2 多页前端需求。
- 构造边界：论文任务分类与代表性官方 seed metadata 只用于确定网站类型和能力约束；本阶段不下载完整图片语料、不逐图 caption，最终 query 不依赖截图或 prototype。
- 运行边界：`qwen3.8-max`，每个 query 恰好一次 LLM 调用，无 LLM 重试和生成后内容校验；ground truth 与 Playwright 截图均未开始。
- 正式构造于 2026-08-20 18:16（Asia/Shanghai）在物理机以 32 并发、流式模式启动；PID `1557803`，输出目录为 `datasets/benchmark_query_research/visual_benchmark_text_proxy_7k_single_call_20260820/`。该状态只表示任务已启动，不能在完成审计前把 7,000 条记为已产出。

### 14 榜 Generation prototype 缺口补齐 8K（2026-08-20）

- 状态：2026-08-20 20:42（Asia/Shanghai）已在物理机启动正式候选构造；PID `1529122`。启动不等于 8,000 条已经成功，最终数量以逐条 `status` 审计为准。
- 计划：`configs/benchmark_generation_gap_8k_20260820.json`，目标 8,000 条；与上一轮计划选入的 7,000 条合计新增 15,000 条。
- 范围：WebCompass 800、DesignBench 400、Interaction2Code 1,000、Vision2Web L2 400、ArtifactsBench 1,800、Design2Code 300、Flame-VLM-Code 600、WebGen-Bench 1,800、FullFront 500、ComUIBench 400。
- prototype：ArtifactsBench 九类、WebGen-Bench 十三类、Interaction2Code 十类状态变化，并补充 WebCompass 弱覆盖领域、Vision2Web L2 页面图、跨页组件复用和视觉结构轴。
- 运行契约：仅 generation query；`qwen3.8-max`；每条恰好一次流式 LLM 调用；SDK 重试为 0；不做生成后内容校验；32 并发；结果逐条追加并按 job ID 断点续跑。
- 预检查路径：首版 `datasets/benchmark_query_research/benchmark_generation_gap_8k_pilot_20260820/`；修订 prompt 后的 v2 为 `datasets/benchmark_query_research/benchmark_generation_gap_8k_pilot_v2_20260820/`，10 个榜单各 5 条、共 50 条均为真实 `qwen3.8-max` 单轮 `ok`；针对元话语、跨页流和 WebGen 四句模板的最终 v4 定向检查为 `datasets/benchmark_query_research/benchmark_generation_gap_8k_targeted_probe_v4_20260820/`，4/4 `ok`。正式路径：`datasets/benchmark_query_research/benchmark_generation_gap_8k_single_call_20260820/`；物理机为权威数据位置。
- 后端边界：不超过 WebCompass；WebGen 的认证、实时、AI、CRUD、API、大数据和文件类只构造浏览器可见的本地 mock、bundled fixtures 或本地 UI 状态。
- 已完成：真实单条流式 API；每榜五条 pilot；定向 prompt 修订检查；32 并发正式启动。未完成：正式批跑完成、数量审计、去重、质量抽查、ground truth 和 Playwright 截图。

| 数据 | 路径 | 数量/大小 | 用途与状态 |
| --- | --- | --- | --- |
| WebCode2M 过滤 URL | `datasets/pipeline_c/webcode2m_filtered_urls_86740.txt`（本地及物理机仓库） | 2026-09-08 核验 86,740 行/唯一 host，文件 2,488,457 字节 | 从物理机同步本地并核对 SHA256；全部来自 111,023 行原始池且符合当前静态过滤规则；URL 候选清单，HTTP/浏览器可用性另验 |
| Pipeline C URL 质量来源快照 | `datasets/pipeline_c/url_quality_sources_20260820_v1` | 7,230 个历史唯一 host；Tranco `JZ8PY` 1,000,000 行 | 候选来源快照；Tranco 生成于 2026-08-19。只作 URL 选择和 provenance，不是网页训练数据 |
| Pipeline C URL 质量 pilot v2 | `datasets/pipeline_c/url_quality_pilot_20260820_v2` | 7,199 历史候选，其中 625 当前 Tranco 活跃；13,924 个 WebCode2M×Tranco 候选；正式试跑清单 200 条 | 100 条历史曾通过且当前活跃 + 100 条 WebCode2M×Tranco；每条有 source/rank。v1 抽样含 92 条未排名历史域名且未用于抓取，只保留调试证据 |
| Pipeline C 复杂度探测候选 v2 | `datasets/pipeline_c/url_complexity_probe_20260820_v2` | 200 条；100 历史 + 100 WebCode2M×Tranco；200 个独立 Top-100K pay-level domain | 与首轮 200 个域名无重叠；用于真实冷启动浏览器复杂度探测。v1 未排除首轮域名，只保留 candidate-only 调试证据 |
| Pipeline C 复杂度选中/对照 v2 | `datasets/pipeline_c/url_complexity_selected_control_20260820_v2` | 30 条阈值选中 + 30 条未入选分层随机对照 | 选中依据为正文、请求数、第三方请求及传输体积；对照两来源各 15、seed 20260822。候选/预检查清单，不是训练数据 |
| Pipeline C 代理对照清单 | `datasets/pipeline_c/proxy_retry_pilot_20260820_v1` | 20 条；四个失败类型各 5 条 | 从 200 条失败中分层抽取，用本机 SOCKS 对照；不是独立训练数据 |
| Pipeline C 丰富网页候选池 | `datasets/pipeline_c/rich_url_candidates_20260903_v1` | 12,000 条；12,000 个 source domain；历史来源中 35,656 条 `ok` | 来自历史 Pipeline B 成功记录并做风险路径、注册域去重和来源/排名/多页 provenance；只是预检输入池 |
| 丰富网页 4K URL 队列 | `datasets/pipeline_c/rich_url_preflight_20260903_v1` | 当前实测 8,000 条；HTTP/结构 pass 4,592；策略过滤 96；最终 4,000 条 | 4,000 个不同 source domain、最终 URL 和最终 host；robots 均明确 allowed 或 missing。六类结构仅用于初筛；后续按 WebCompass 16 类 Edit 候选能力和原子 UI 特征细分。可作为 Pipeline C 或 D 的输入，不是训练样本；详见 `pipeline_c_rich_url_strategy_20260903.md` |
| 0805 text-generate query | `datasets/benchmark_query_research/0805_coverage_20260819/source_queries.jsonl.gz` | 10,503 行的 gzip 快照 | query 研究/构造输入；旧表中的未压缩路径当前本地不存在；不能把 query-only 当作带答案训练集 |
| 0805 coverage sample | `datasets/benchmark_query_research/0805_coverage_sample25_20260819.jsonl` | 25 行 | 人工审查小样本，不计入正式规模 |
| 14 榜 Generation 原始 15K 重组后活动目录 | `datasets/benchmark_query_research/fourteen_benchmark_generation_15k_single_call_20260820/raw` | 8,117 条，全部 `ok` | 2026-08-20 已按用户要求原子重组：删除 29 条历史 error，加入 12 条 WebCompass 与 17 条 Vision2Web Route 2 替代，分离 6,883 条旧图片绑定式 query。活动 raw 不再含 error/useless；重组前完整 15K 及 recovery supplement 位于 `_archive/fourteen_benchmark_generation_15k_before_reorganization_20260820T132847Z` |
| 旧图片绑定式 useless 独立集 | `datasets/benchmark_query_research/fourteen_benchmark_useless_visual_asset_bound_6883_20260820/queries.jsonl` | 6,883 条；SHA256 `1a6e8cb15fa47b242c33a7e364a3a91d7c92a925cf544eaa940a43881d36ff72` | 已从原始 15K 活动 JSONL 完全移出；仅供历史审计/可能回收，默认不生成 GT、不进入训练 |
| GT-ready 主批次中间集 | `datasets/benchmark_query_research/fourteen_benchmark_gt_queries_combined_19009_20260820/queries.jsonl` | 19,009 条，全部 `ok`、query 唯一、instance_id 唯一；SHA256 `767080d18d9e4e373df0499862ecb5428df4e8548364ecffc684f65e1594aea6` | 8,088 原纯文本有效 + 29 错误替代 + 10,892 后续 Route 2；继续保留为来源账本，不再单独作为正式 GT 输入 |
| GT-ready 全量统一 query 来源账本 | `datasets/benchmark_query_research/fourteen_benchmark_gt_queries_combined_21109_20260820/queries.jsonl` | 21,109 条，全部 `ok`、query 唯一、instance_id 唯一；SHA256 `e515ebc787bfafabda9b2a6b51d48526d518a9d1f50bd483f2f058788a7a2a6e` | 19,009 条主批次 + 2,100 条 prototype 缺口补齐；保持不可变，作为 15K 活动集的完整来源账本 |
| 14 榜 Generate GT 活动 15K 与移出集 | `datasets/benchmark_query_research/fourteen_benchmark_gt_queries_selected_15000_20260821/` | `selected_15000.jsonl` 15,000 条，SHA256 `fd169d931807106acdc495bcdc7e04411ea82901121611fe79a690eb62b16192`；`excluded_6109.jsonl` 6,109 条，SHA256 `3ff3648646211656d714578757e4d0511dce65060d59f3ea0cf56ad8efe69c3b`；另含 `selection_meta.json` | 当前正式 GT 输入为 15K；保留筛选前全部 1,631 个成功 GT 和 3,000 条 Vision2Web 多视口 query。为满足 profile 保底，实际配额为 ArtifactsBench 1,636、WebCompass 2,164，其余保持原定值；原集合与两分区已核验零重叠、零缺失 |
| 物理多页母本候选水库 v1 | 物理机 `runs/ground_truth/physical_mp_candidate_reservoir_20260830_v1/` | 11,749 条、instance ID 唯一；`reservoir.jsonl` SHA256 `8219a5c1c1605c0b9a0c718931475917a725554f223966520c1f18f1a071d37b` | 300 条冻结校准前缀 + 6,464 条活动 15K 剩余项 + 4,985 条完整账本保留项；排除历史 60 条试产/校准 query。只用于按序生成候选，不是 accepted 母本或训练数据；每个付费结果无论成功失败都视为 attempted，不自动重试 |
| 视觉来源 Route 2 文本替代批次 | `datasets/benchmark_query_research/visual_benchmark_text_proxy_7k_single_call_20260820` 及两个 supplement run | 10,892 条成功 | 先形成自包含文本描述再扩增的替代 query：主 run 10,656，236 supplement 成功 228，tail supplement 成功 8。它们是新增独立记录，不会覆盖或删除旧 6,883 条 `useless` 行 |
| 14 榜缺口 prototype 补齐批次 | `datasets/benchmark_query_research/benchmark_generation_gap_8k_single_call_20260820` | 2,100/2,100 `ok` | 针对后来复核出的生成任务/prototype 缺口补造；名称保留历史 `8k`，实际完成规模为 2,100 |
| 0805 ArtifactsBench hold-out 现场审计 | `docs/remote_0805_artifacts_exclusion_audit_20260820.md` | 原 6,503 中 1,409 条，原文件仍在物理机 | 因直接测试集来源继续保持排除；不得重新合并进训练集 |
| WebUI 小型检查集 | `datasets/webui_all_small` | 67M；含 10 条 Pipeline C 运行及修复版、日志和 manifest | 预检查/研究数据；README 明确提示版权和原数据抓取超时问题 |

## Pipeline C 抓取运行

2026-09-08 00:44 CST 复核：救援 7,200 单页/102 多页及清理视图仍在（其中 30 项恰好四 HTML）；D 精选 272 项、设计画廊 1,416 项、One Page Love 566 项均有现存成功项目。后两批为单页 inspiration candidate，取代下表旧运行中数量快照。详细路径、旧策略限制及处置编号统一维护于 [webcoding-crawl-results 结果清单](/Users/woyaochengweikeyandashen/.codex/skills/webcoding-crawl-results/references/inventory.md)；数据处置决定待用户选择。

以下目录是运行产物，不等同于通过质量门禁的数据集：

| 运行 | 大小/已知信息 | 状态 |
| --- | --- | --- |
| `runs/pipeline_c_webcode2m_full_20260723` | 959M | WebCode2M 全量尝试；需以 `output/preprocess_manifest.jsonl` 逐条判断 |
| `runs/pipeline_c_webcode2m_remote_policy_full_20260723` | 未在本次重算大小 | 远程资源兼容策略实验，不是严格资源闭包 |
| `runs/pipeline_c_absolute_resources_full_20260724` | 未在本次重算大小 | 绝对资源策略实验 |
| `runs/pipeline_c_absolute_resources_proxy_fixed_full_20260724` | 137M | 修复代理后的绝对资源实验；仍需 manifest 和离线资源审计 |
| `runs/pipeline_c_filtered_urls_no_preflight_full_20260724` | 未在本次重算大小 | 跳过 preflight 的对照实验，不可仅按目录名合并 |
| `runs/recent_pipeline_cd_40k_audit_20260724` | 审计目录 | Pipeline C/D 40K 对照证据 |
| `runs/pipeline_c_strict_single_slim_20260820` | 860K；1/1 pass；12factor 5,856 Qwen token | 真实最小样本。HTML/CSS/JS 全计数；图片/字体本地化；瘦身前后本地回放及最终截图通过。调试入口保留拒绝目录的策略不影响本条 pass |
| `runs/pipeline_c_strict_matrix_final_20260820` | 8.4M；8 URL；1 final pass、3 个渲染通过但 40K 淘汰、1 个渲染失败、2 个质量预检拒绝、1 个预检网络错误 | 动态/传统站点兼容性调试，不是正式数据集。实际进入完整爬取的 5 条中 4 条瘦身前后离线渲染通过；完整逐条证据见 `docs/pipeline_c_strict_resource_debug_20260820.md` |
| `runs/pipeline_c_strict_lightweight_final3_20260820` | 6.4M；125 文件；8 URL；4 final pass | 对最终代码复跑的轻量矩阵候选：12factor、Zig、curl、Vim pass，token 为 5,856 / 8,396 / 11,136 / 14,836；均有 resource manifest、training context、前后回放和截图。其余为 2 个质量预检拒绝、1 个资源 404、1 个 52,729-token 淘汰；只允许调试/候选研究，不按正式 release 使用 |
| `runs/pipeline_c_url_quality_pilot200_20260820_v1` | 物理机 262M；200 URL；8 pass、122 rejected、62 preflight rejected、6 preflight network error、2 timeout | 使用物理机 HTTP 代理、8 workers、180 秒硬超时、单页、全资源闭包和全代码 Qwen 40K；历史活跃来源 7/100，WebCode2M×Tranco 1/100。无视觉 LLM；8 张截图已人工核验为可读非空白。只作预检查，不按正式 release 使用 |
| `runs/pipeline_c_url_quality_pilot200_20260820_v1_remote_audit` | 本地约 15M；包含 200 条 manifest、8 个 pass 完整项目、截图和日志 | 上述物理机 run 的小型审计副本；聚合报告和人工视觉分级见内部 `analysis_v1` 与 `manual_visual_review.jsonl` |
| `runs/pipeline_c_proxy_retry_local_socks20_20260820_v2` | 20 条代理失败对照；1 pass、4 preflight network error、5 preflight reject、10 reject | 本机 SOCKS 复跑额外恢复 `cockos.com`（12,768 tokens）；证明物理机 run 含代理假阴性，但多数样本在网络恢复后仍被质量/资源/渲染门禁拒绝。v1 是被本机进程组清理的空启动证据 |
| `runs/pipeline_c_url_complexity_probe200_20260820_v2` | 物理机正式探测；200 条，177 ok、23 error/timeout；30 条满足 v1 阈值 | 每 URL 独立冷启动 Chromium、HTTP 代理、25 秒导航/40 秒硬超时、逐条落盘和断点续跑。v1 的 65 条复用 context，可能有缓存偏差，只作失败证据 |
| `runs/pipeline_c_complexity_selected30_strict_20260820_v1` | 物理机 59M；30 条；4 pass、23 rejected、3 preflight rejected | 阈值选中组；4 pass 全代码 token 为 4,769–13,816，资源闭包和离线截图门禁通过。人工视觉 1 高/2 中/1 低；只作 pilot，不是正式 release |
| `runs/pipeline_c_complexity_control30_strict_20260820_v1` | 物理机 24M；30 条；1 pass、14 rejected、13 preflight rejected、2 preflight network error | 同批未入选分层随机对照；唯一 pass `ubu.com` 3,059 tokens，正常但视觉稀疏。证明预筛会漏召回 |
| `runs/pipeline_c_complexity_selected30_strict_20260820_v1_remote_audit`、`runs/pipeline_c_complexity_control30_strict_20260820_v1_remote_audit` | 本地约 4.4M + 小型对照副本；含 5 个 pass 完整项目、manifest、统计、截图与人工视觉记录 | 本地审计副本；正式大目录仍以物理机为准。完整结论见 `docs/pipeline_c_complexity_prefilter_pilot_20260820.md` |
| `runs/pipeline_c_rich_regression_matrix_20260903_v1` | 本机 3 URL；3 pass | 当前 Pipeline C 的真实回归矩阵；12factor、Zig、curl 均通过 40K、资源闭包和离线回放，token 为 5,856 / 8,396 / 11,135 |
| `runs/pipeline_c_rich_local_matrix_20260903_v2` | 本机 2 个现代复杂 URL；0 pass | HTMX 离线渲染闭包通过但 83,262-token 淘汰；11ty 图片后缀和 island import 问题已修，仍因运行时同源 HTML fragment 未闭合而拒绝；保留 debug project |
| `runs/pipeline_c_rich_browser_probe20_20260903_v1` | 最终 4K 前 20 条；19 probe ok；9 条进入 bounded-rich 选中 | 独立 Chromium 验证 HTTP 预检后的真实请求、组件、交互、代码传输代理和 challenge；标题内容门禁淘汰伪装成普通域名的赌博页 |
| `runs/pipeline_c_rich_selected_strict3_20260903_v1` | bounded-rich 中 3 条；0 pass | UVM 触发目录页质量门禁，ConfirmTkt 字体 CDN 403，Open.Video 广告运行时代码产生公网请求；证明 4K HTTP 队列不能当作 strict 样本量 |
| `runs/pipeline_external_webcompass_probe20_20260903_v3` | 最终 4K 前 20 条；20 probe ok；WebCompass 候选能力命中 2 次 | 二次收紧后的 16 类 Edit 能力候选探测；没有强证据命中的页面按原子 UI 特征细分。只作选样证据，动态能力仍须动作验证 |
| `runs/pipeline_d_external_single_20260903_v1` | 1 URL；1 render-verified | 12factor 外链模式：项目内资源文件 0；15 个联网外部请求；正文保留率与截图相似度均 1.0；无资源失败、页面异常或破图 |
| `runs/pipeline_d_external_matrix_20260903_v1` | 3 URL；1 pass、2 reject | HTMX 通过；Open.Video 因脚本错误/破图拒绝，UVM 因页面异常/破图拒绝。项目不下载站点资源，截图仅作项目外 QA 证据 |
| 物理机 `runs/pipeline_d_external_remote_matrix4_20260903_v2` | 4 URL；3 render-verified、1 token reject | HTMX、Zig、curl 通过且资源文件为 0、正文/首屏一致、无破图；12factor 因代理地区 Cookie DOM 达 49,200 tokens 被 40K 门禁淘汰。回放保持原 origin，避免 CORP 同源资源误杀 |
| 物理机 `runs/pipeline_d_rich_external_4k_20260903_v2` | 4,000 probe；3,673 ok；766 selected；283 pass、63 token reject、420 crawl failure | 已完成的高召回运行与阈值调试证据；项目不保存站点资源。其 283 pass 仍含 11 个低相似度/正文重复边界项，不直接作为 final |
| 物理机 `runs/pipeline_d_rich_external_final_20260903_v2` | 272 URL/项目；204MB；544 项目文件 | 当前 final 外链网页集：每项目仅 `index.html`+`metadata.json`，无资源文件或软链接；全部 40K 内、origin-preserving render-verified、零破图/关键资源失败，首屏相似度 ≥0.858006，正文保留率 0.8227–1.146。来源和能力覆盖见 `pipeline_c_rich_url_strategy_20260903.md` |
| `datasets/pipeline_d/source_trials_20260903_v1/`、`runs/pipeline_d_source_trials_20260903_v6_final/` | 7 类来源、14 URL；14/14 probe ok；最终 0/14 pass | CrUX、HTTP Archive 上游代理、Lapa Ninja、Godly、One Page Love、Awwwards、Common Crawl 各 2 条。10 条因最终 DOM 261,191–792,333 tokens 淘汰，4 条因脚本失败、loading shell 或首屏不一致拒绝；证明新来源更现代，但需要先实现浏览器验证的 HTML/hydration 瘦身 |
| `runs/pipeline_d_source_trials_20260903_v5_final_gate/` | 3 URL；1 pass、1 token reject、1 render reject | Pipeline D 新门禁真实回归：Zig 3,745 tokens 通过；Raycast 现代首屏完整显示但 396,242 tokens 淘汰；Davesocozy loading shell 拒绝。对应单元测试 9 项通过 |
| `runs/pipeline_d_source_trials_20260903_v7_unlimited/` | 14 URL；8 pass、5 crawl failure、1 timeout | Pipeline D 灵感库取消 40K 硬淘汰后的同源复跑；8 个通过项目为普通 `index.html`+`metadata.json`，资源仍只保留外链，精确 token 261,198–578,786。其余仍按脚本、破图、首屏完整性/一致性和超时门禁拒绝；不把放宽 token 等同于放宽渲染质量 |
| `runs/pipeline_d_inspiration_admission_test_20260904_v1/` | 本机 3 URL；1 inspiration candidate、2 reject | 新 `inspiration` 准入真实矩阵：Cal 主体回放相似度 0.999901，CloudFront 第三方脚本失败降为 warning 后通过；Davesocozy 仍因源/回放 loading shell 拒绝；Trevor Noah 因源首屏不完整、正文膨胀和截图差异拒绝。项目资源仍只保留外链 |
| `runs/pipeline_d_inspiration_admission_test_20260904_strict_v1/` | 本机 1 URL；0 pass | 同一 Cal URL 的 `strict` 对照仍因关键资源/视口破图门禁拒绝，确认宽松策略只作用于明确选择的 inspiration profile |
| `runs/pipeline_d_inspiration_admission_test_20260904_v2/` | 本机 3 URL；2 inspiration candidate、1 reject | 动态初态策略复跑：Cal 通过并保留第三方脚本/小破图 warning；Trevor Noah 的交付回放首屏完整，源动画初态稀疏、正文增长和截图差异降为 warning 后通过；Davesocozy 源与回放均为 loading shell 且有显著破图，继续拒绝 |
| `datasets/pipeline_d/modern_inspiration_urls_4000_20260904_v2/` | 4,000 URL；4,000 唯一注册域 | Pipeline D 抓取候选而非 accepted 数据：10 条来自现代设计来源试验，3,990 条来自 2026-09-03 实时 HTTP/结构预检通过池的重新排序；后者全部 robots 明确允许/缺失即允许、结构分 ≥15，已过滤已知成人、博彩、作业代写、代理销售等风险域名。结构分布为表单/工具 1,907、视觉画廊 1,378、交互 UI 412、数据/表格 135、分区 landing 79、结构化内容 79，另有 10 条设计来源待细分 |
| `runs/pipeline_d_modern_inspiration_4000_sample20_20260904_v1/` | 上述 4K 前 20 条；17 inspiration candidate、3 reject | 真实 Chromium 联网回放：17 条通过；Chase4Senate 因大面积破图拒绝，aThemes 因正文膨胀及核心资源失败拒绝，LTBoosters 因核心资源失败拒绝。该 85% 仅是有意把 10 条现代试验 URL 放在队首后的小样本结果，不能外推 4K 总通过率 |
| `datasets/pipeline_d/design_gallery_sources_20260904/`、`datasets/pipeline_d/design_gallery_candidates_6000_20260904_v2/` | 5 个现代设计画廊 sitemap；7,784 详情页解析；7,773 成功；6,000 个唯一原站候选 | 主来源为 Minimal Gallery、Landing Love、Curated Design、Seesaw、Web Design Awards；按可用日期优先，保留详情页 provenance、sitemap 哈希和 robots 快照。来源分布 2,010 / 1,623 / 1,497 / 673 / 197；只是候选，不是成功爬取样本 |
| `datasets/pipeline_d/design_gallery_preflight_6000_20260904_v1/` | 6,000 检查；3,166 结构通过；3,095 robots eligible | 实时正文安全、HTTP、结构和 robots 预筛；剔除 19 条高置信不安全内容。结构分布：视觉画廊 1,823、表单/工具 772、交互 UI 241、结构化内容 136、分区 landing 82、数据/表格 41；仍须 Pipeline D 浏览器门禁 |
| `runs/pipeline_d_design_gallery_preflight_browser_pilot30_20260904_v1/`、`runs/pipeline_d_hatch_sparse_gate_regression_20260904_v1/` | 30 URL 浏览器矩阵 24 pass；Hatch 反例 0/1 | 收紧 inspiration 空壳门禁后的真实 Chromium 证据。Hatch 源/回放虽一致但主体长期空壳，以 `source_incomplete_viewport` 和 `replay_incomplete_viewport` 拒绝；30 条矩阵据此得到 80% pass，仅作正式批次容量估计 |
| `runs/pipeline_d_modern_design_gallery_2000_20260904_v1/` | 本机调试残留；173 URL、最新状态 93 pass，已停止 | 用户确认正式爬取只在物理机执行后停止；该目录仅保留调试证据，不计入物理机正式 2K 结果 |
| 物理机 `runs/pipeline_d_modern_design_gallery_2000_remote_20260904_v1/` | 物理机正式运行；2026-09-04 23:37 CST 快照为尝试 1,381、pass 547、crawl failure 756、timeout 78；目标 `pass=2,000`，主队列 3,715 URL | 先跑 3,095 条严格 HTTP/结构/robots 预筛候选，再跑 620 条补充候选；8 workers、单站 120 秒、0 token 上限、inspiration profile，保留 launcher/crawler PID、心跳日志、队列哈希、逐条 manifest 和断点续跑；主队列结束后 coordinator 再尝试 One Page Love 去重补充队列。完成前不得把队列量或阶段 pass 外推为 2K |
| `datasets/pipeline_d/component_gallery_design_system_docs_pilot_20260904/`、物理机 `runs/pipeline_d_component_gallery_docs_pilot_remote_20260904_v1/` | 9 个外部官方组件文档页；3 pass、5 crawl failure、1 timeout | The Component Gallery 因自身 robots 声明 `ai-train=no,use=reference`，只用于定位设计系统，未把其页面收为 Seed。分别核验 shadcn/ui、PatternFly、Web Awesome robots 后测试 data table、calendar、carousel、tree view、file upload、wizard、dialog、rating；通过项为 shadcn/ui Data Table、PatternFly Wizard、Web Awesome Rating。另有 400 条外部 Storybook iframe 候选，但 Spectrum 单条因动态 bundle 回放缺失失败，不能记作 accepted 数据 |
| 物理机 `datasets/pipeline_d/design_gallery_preflight_relaxed_6000_remote_20260904_v1/`、`runs/pipeline_d_modern_design_gallery_remote_relaxed_matrix30_20260904_v1/` | 6,000 URL 中 3,478 条宽松预筛 eligible；新增层浏览器矩阵 4/30 pass | 宽松静态阈值只用于补召依赖 JS 的页面；4/30 表明该层质量显著低于严格队列，不能替代浏览器门禁或作为主要容量估计 |
| `datasets/pipeline_d/one_page_love_sources_20260904/`、物理机 `datasets/pipeline_d/one_page_love_candidates_3000_remote_20260904_v1/`、`datasets/pipeline_d/one_page_love_preflight_1948_remote_20260904_v1/` | One Page Love 公开 sitemap 共 9,477 个详情页；较新 4,000 个详情页解析为 1,948 个唯一原站；严格预筛后 1,100 条 robots eligible | 普通 crawler 未被 robots 禁止；只把详情页作为 provenance，解析其 Demo 重定向后的真实原站。20 个解析试验得到 20 个唯一原站；严格预筛 12 条，真实浏览器回放 9/12 pass。与首批正式队列去重后剩 904 条，已由物理机 coordinator 在首批完成后按总 pass 缺口继续运行 |

### 2026-08-20 Pipeline C 调试迭代

- 中间/失败证据目录：`runs/pipeline_c_strict_single_20260820_retry`、`runs/pipeline_c_strict_matrix_20260820`、`runs/pipeline_c_strict_matrix_slim_20260820`、`runs/pipeline_c_strict_failures_retry_20260820`、`runs/pipeline_c_strict_failures_retry2_20260820`、`runs/pipeline_c_strict_python_retry3_20260820`、`runs/pipeline_c_strict_lightweight_final_20260820`、`runs/pipeline_c_strict_lightweight_final2_20260820`。
- 空启动证据：`runs/pipeline_c_strict_single_20260820` 仅创建空目录，首次后台启动未进入 Python；不可计为样本。
- 这些目录记录 MIME、动态 import、RequireJS `data-main`、prefetch、tracker、子页上限和本地 404 的修复过程。失败/旧实现结果不得与 final3 的 4 个 pass 合并统计。
- schema：逐 URL `preprocess_manifest.jsonl`，含 `status`、`reason`、`resources.resource_manifest`、`baseline_validation`、`slimming`、`validation`、`token_usage`、`final_contract`、`screenshots`；每个 pass 项目另含 `resource_manifest.jsonl`、`training_context.txt`、`training_context_manifest.json`。
- 生成入口：`preprocess/pipeline_c/run_strict_local_debug.sh`；完整命令、日志、退出状态在 `logs/pipeline_c_strict/<run_id>/`。

## 构造、审计和定向运行索引

这些目录必须保留各自身份，禁止把审计、预检查和正式数据混合统计：

| 目录 | 类型 | 使用说明 |
| --- | --- | --- |
| `runs/artifactsbench_3k_qwen3.7max_20260804` | query/构造实验 | 模型、prompt、状态以 run manifest 为准 |
| `runs/construct_context_audit_7302_20260723` | 上下文审计 | 记录 7,302 项 serializer/token 口径 |
| `runs/construct_edit_repair_0721` | edit/repair 构造 | 旧构造运行；与当前全代码口径区分 |
| `runs/final_externalized_5k_v1`、`v2` | 外置实验 | 小规模/版本对照，不作为正式数据 |
| `runs/legacy_rescue_audit_10000`、`20000` | 救援审计 | 审计证据，不是额外样本量 |
| `runs/quality_generate_0805` | Generate 质量抽检 | 预检查和正式结论按内部 manifest 分开 |
| `runs/linear_edit_query_augmentation_20260828/pilot_10_v3` | 线性多轮 Edit query 试生产 | 从 0805/0805supplement 已有质量记录中构造 100 个候选、固定随机抽 10 个；每个 Seed 生成 Q1–Q5 五轮线性历史，共 50 条 query。7 个完整序列/35 条 query 通过语义审核，3 个完整序列/15 条拒绝。未生成 target，`training_admission=not_eligible`；10 个 Seed 中仅 3 个通过当前严格离线基线。报告见 `docs/linear_edit_query_augmentation_pilot_20260828.md` |
| `runs/linear_edit_query_augmentation_20260828/topk_pilot_1_20260901_v1` | 一次 Top-K + 项目源码切片接线的 1-Seed 预检查 / 配额停止证据 | 真实 embedding 已从 43 张合并池召回 Top-8，并为 8 张卡解析出 14 个带行号和 SHA-256 的真实项目源码切片；缓存预检创建并命中 7,062 tokens。唯一一次 Q1–Q5 生成请求返回 HTTP 429 `insufficient_quota`，零自动重试，没有序列、审核或 query 产物，不可训练。当前 runner 已移除第二个审核模型；该旧失败 run 保持不变。报告见 `docs/linear_edit_topk_integration_20260901.md` |
| `runs/capability_library_confirmation_20260904/deepseek_q10_scope_goal_fix_3cases_v1`、`deepseek_q10_scope_goal_fix_case4_v1`、`deepseek_q10_scope_goal_fix_rich_case_v1` | 对象作用域、已有目标与依赖位置修正的小规模调试 | 5 个 Seed 各至多 1 轮 LLM 深层探索，零自动重试；论坛、落地页和档案馆 3 条 Q1–Q10 完成确定性结构导出，下载页与文章页保留失败响应。均未生成 target，全部 `training_admission=not_eligible`。人工语义复核仍发现隐藏/多余依赖和时间内容矛盾，不能把 30 条结构通过记录计作已接收数据。报告见 `docs/linear_edit_topk_integration_20260901.md`。 |
| `runs/capability_library_audit_20260901/` | 灵感库卡片精简与 FixFlow 深度浏览器排查 / 不可训练研究证据 | `fixflow_compact_v1` 将 FixFlow 的 6 张旧卡全部转为精简字段并定位 12 个真实源码切片，0 张未定位；`fixflow_deep_browser_v2` 的三轮本地 Chromium 分别完成 3、5、1 条状态路径，验证搜索/路由、筛选与数量同步、比较阈值、刷新保持、批量清空、跨路由 shortlist 以及第 4 项超限反馈。无付费 LLM、无 target、不可训练。日志在 `logs/capability_library_audit/`，报告见 `docs/capability_library_building_audit_20260901.md` |
| `runs/dynamic_capability_retrieval_20260828/pilot_5_pool_q1q5_v1` | 每轮重新召回能力的单 Seed Q1–Q5 旧小试 / 拒绝证据 | 从 5 个 0805supplement Seed 提取 33 张候选能力卡，与 10 张历史已验证卡合并为 43 张、28 类。对 FixFlow host 的 Q1–Q5 分别重新生成检索文本并召回，5 个 query hash、5 个选中能力均不同。模型自审全接收，但源码和真实浏览器证明 Q4 已在 source 中存在，Q5 又依赖被拒绝的 Q4；`independent_admission_review.json=status:reject`。无 target，全部不可训练。该 run 保留当时读完整源码和 donor 验证信息的历史事实，当前代码已改为多状态 DOM / AX 观察、结构角色对应、不做 donor 检查，并在 target 前执行 source-gap 浏览器检查。报告见 `docs/dynamic_capability_retrieval_pilot_20260828.md` |
| `runs/dynamic_capability_retrieval_20260828/source_gap_retrofit_20260828/q4` | 当前 source-gap 实现的旧 Q4 真实浏览器回测 | 在原 FixFlow source 上运行“选中技师→筛选隐藏→比较状态仍保留”的正向检查；setup 成功且全部新行为断言通过，因此正确返回 `source_already_has_behavior`。`source_observation_with_paths/dom_ax_states.jsonl` 另保存了基线、进入发现页、选中技师和筛选隐藏后共 4 个去重 DOM / AX 状态。无远程请求、console error 或 page error。本次未调用付费 LLM，不产生 target 或训练数据；日志位于 `logs/source_gap_retrofit/q4_20260828/run.log` |
| `runs/mixed_capability_edit_20260828/cold_chain_partial_dual_v3` | 部分双能力 Edit 生产控制回测 | 单能力默认、5 轮最多 2 个双能力的预算示例；真实验证硬依赖 A→B、生成前拦截 B→A、两个可行顺序的实际终态和 accepted 精确代码片段。37 条 target/回归通过、2 条 source 缺口按预期失败、39 张截图，无新付费调用或新 target，`training_admission=not_eligible_pilot_evidence_only`。报告见 `docs/mixed_capability_edit_pilot_20260828.md` |
| `runs/cross_seed_component_fusion_pilot_10_20260821` | Generate 扩增原始 run / 失败证据 | 3 个不同单页 Seed 的组件组融合为 1 个新单页 query–GT；真实 Qwen 10/10 生成。保留 v3 2/10、v4 7/10 的浏览器证据，不作为最终可训练版本 |
| `runs/cross_seed_component_fusion_pilot_10_20260821_v2` | Generate 扩增验证候选 | 10 条，3 个缺陷在新目录中非覆盖修复；真实 Chromium `repaired_v1` 10/10 通过桌面交互、390px、离线与错误门禁。仅证明小样本工程可行，未完成重复度、人工盲评与下游训练收益验证 |
| `runs/targeted_nessim_input`、`targeted_nessim_v9` | 定向单例实验 | v9 为 1 条且 reject；不能计入规模 |
| `runs/task_project_splits_5k` | split/清单 | 数据组织，不是独立底稿副本 |
| `runs/webcompass_6503_construct_precheck_20260805` | 预检查 | 不能替代正式构造验收 |
| `runs/webcompass_6503_debug8_20260805` | 调试 | 8 条级别调试证据 |
| `runs/webcompass_6503_production_20260805` | 生产构造 | 是 release 的来源之一；最终状态仍由 release audit 决定 |

### `releases/0805_supplement_premium_examples_v3_hard_clean_inputs`

- 状态：2 条高难度单例候选，用于展示、逐条人工复核和模型难度校准；不是规模化正式 release。
- 来源与日期：ArtifactsBench 1582 底稿；2026-08-26；构造脚本为 `scripts/build_premium_bc_harder_v3_release.py`。
- 样本：Image Editing 1 条（5 个 task type、11 个 patch）；Image Repair 1 条（5 个 repair type、8 个缺陷、8 个 patch、5 组状态截图）。两条均为单页、多文件项目。
- 输入代码：每条严格只含 `index.html`、`styles.css`、`script.js`；图片资源为本地 `assets/heritage-panorama.png`。该版本修复了原 `v3_hard_final` 的 C 记录误含 `harness_snippet.html` 和 `test_harness.html` 的输入泄漏，原目录保留为历史问题证据。
- 验证：patch 精确回放和浏览器验收通过；相关测试 9 passed。Qwen 盲测 B 未完成 2 项要求，C 修复 6/8；Kimi 新版盲测因 API 余额不足未执行。
- 证据：`dataset_index.json`、`quality_report.json`、各任务 `audit/`、源码/ground-truth 项目和状态截图均位于 release 内；人工整理见 `docs/reports/premium_bc_hard_cases_20260826.md`。
- 允许用途：教学展示、案例审查、WebCompass Edit/Repair schema 讨论和困难样本校准。

### `runs/webcompass_official_bc_20260827`

- 状态：新版 B/C 四组 Claude Code 产物的 WebCompass 官方流程评测，4/4 judge 成功；不是新训练数据 release。
- 被测系统：CC+Qwen3.8-Max 的 B/C（原 run `ok`），以及 CC+Kimi K3 的 B/C（两条原 run 均为 `error_max_turns`，评分结束时已落盘的部分完成工作区）；被测工作区保持原样。
- 评测实现：官方仓库 commit `d5fe352e065f6dcf87aca605babf01499b2b12a3`，官方 worktree 干净；使用官方 CodeJudge、Edit/Repair prompt、截图函数和调和平均。judge 按用户要求统一为 Doc API `qwen3.8-max`。
- 适配边界：Claude Code 直接编辑工作区，因此新增适配器把最终代码重建为精确 search/replace blocks；四组 3 个代码文件均通过官方 `apply_search_replace` 零错误逐字回放。官方评测逻辑未修改。
- 分数（/10）：Qwen-B 8.8380、Qwen-C 3.2234、Kimi-B 7.8603、Kimi-C 2.4324。
- 运行安全：历史正式评测前的 75-token 隐式缓存预检未命中，且当时正式 4 次请求未记录原始 usage。2026-08-27 已修复为显式缓存：缓存边界设在“官方 system rubric + 当前 case 的任务/缺陷说明”之后；真实两请求验证第一次创建 1,183 tokens、第二次命中 1,183 cached tokens。后续 runner 追加保存 `usage.jsonl`；SDK 与外层自动重试仍为 0。
- 证据：`adapter_manifest.json`、`verification.json`、`official_scores_qwen_judge.json`、`judge_runs.jsonl`、四份 `judge.json` 和四份官方 full-page 截图；缓存修复证据位于 `logs/webcompass_official_bc/webcompass_qwen_judge_cache_precheck_explicit_case_prefix_20260827T022747/`；报告见 `docs/reports/webcompass_official_bc_qwen_judge_20260827.md`。

### `runs/premium_bc_tokenwave_20260827/claude_opus_5_max_v2` 与 `runs/webcompass_official_bc_tokenwave_20260827_v2`

- 状态：TokenWave `claude-opus-5` 的新版 B/C Claude Code 10-request 正式小批量及 WebCompass 官方流程评测。该批次内 GPT 使用了错误凭据而未启动；正确 OpenAI key 的后续正式结果见下一节。
- Agent 结果：B/C 均为 `error_max_turns`，各转发 10 个不同供应商请求，工具配置含 Read/Edit/Write/Bash，但轨迹仅执行读取和图像检查，工作区与 pristine 完全一致，0 个修改块。CC 记录费用合计 $0.73383225。
- 官方分数（Doc API `qwen3.8-max` Judge）：Opus-B 1.0000、Opus-C 1.0000；所有子项原始三维分数均为 0，官方 `low_bound=1` 后 HM 为 1。SDK、Judge、CLI 守卫与外层自动重试均为 0。
- 历史 GPT 阻塞证据：当时的错误凭据在 Anthropic wire 返回 HTTP 502、Responses wire 返回 HTTP 503；这些日志只保留为失败 provenance，不代表当前 GPT 可用性。
- 证据：Agent `provider_requests.jsonl`、`claude_code_events.jsonl`、`guard_summary.jsonl`；评测 `adapter_manifest.json`、`judge_runs.jsonl`、`usage.jsonl`、两份 `judge.json`、`official_scores_qwen_judge.json` 和 `run_summary.json`。报告见 `docs/reports/webcompass_tokenwave_gpt_opus_bc_20260827.md`。

### `runs/premium_bc_tokenwave_20260827/gpt_5_6_sol_max_v1` 与 `runs/webcompass_official_bc_tokenwave_gpt56sol_20260827_v1`

- 状态：2026-08-27 正式小批量。Claude Code 经本地 Anthropic→Responses 适配调用 TokenWave `gpt-5.6-sol`，B/C 各最多 10 个不同上游请求，全部自动重试为 0。
- Agent 结果：B 生成 10 个修改块并修改 3 个文件，C 零 patch；两项均以 `error_max_turns` 结束。B/C 的 Claude Code 记录费用分别为 `$1.839017`、`$0.657210`，cache read 分别为 290,304、300,800 tokens。
- WebCompass：官方 commit `d5fe352e065f6dcf87aca605babf01499b2b12a3`，Doc API `qwen3.8-max` Judge。B/Edit HM `5.2985702271`，C/Repair HM `1.0`。
- 证据：Agent `provider_responses.jsonl`、`provider_request_*.json`、`claude_code_events.jsonl`、`guard_summary.jsonl`；评测 `adapter_manifest.json`、`judge_runs.jsonl`、`usage.jsonl`、两份 `judge.json` 和 `official_scores_qwen_judge.json`。报告见 `docs/reports/webcompass_tokenwave_gpt_opus_bc_20260827.md`。

## 已删除的 C3 / ISGG / BCMO 指令扩增资产（2026-08-27）

- 状态：用户明确要求直接删除，不再保留为历史方案或可复用 pilot。
- 已移除：归档研究全文和说明、2 份配置、15 个生成/验证/修复/导出 launcher 与实现、6 个单测、`runs/web_instruction_augmentation_pilot_9_20260822_v1/` 及对应持久日志。
- 历史计数只用于防止误报：被删除的 pilot 曾包含 9 个 target 和 18 个共享 lineage 的 Generate/Edit/Repair 视图；这些记录不属于当前本地资产、候选集或训练 release。
- 恢复边界：项目内已无对应实现入口、canonical manifest、网页项目或截图。后续不得依据旧报告或记忆恢复、重命名或计入数据量，除非用户重新明确授权并从头验证。

## 与旧三方案解耦的 Web 指令扩增 pilot（2026-08-23）

### `disjoint_instruction_augmentation_pilot_9_20260823_v1`

- 状态：小型研究 pilot；最终 9 个 canonical target 通过真实 Chromium 功能门和人工截图检查，可用于新方法展示与后续 SFT 对照；当前不是规模化正式 release。
- 路径：`runs/disjoint_instruction_augmentation_pilot_9_20260823_v1/`；母 Seed 位于 `seeds/`，原始 target 位于 `cases/`，非覆盖修复依次位于 `repairs/`、`repairs_v2/` 至 `repairs_v4/`。
- 策略：3 个 Information-Gain Requirement Speciation、3 个 Perceptual–Accessibility Semantic Twins、3 个 Content-Shape Distribution Inversion。它们分别改变需求不确定性、AX/键盘语义和内容分布；本 pilot 明确排除组件/跨 Seed 融合、状态图嫁接、主题/断点变形及其改名版本。
- 生成时间与模型：2026-08-23，本地构造；真实 `qwen3.8-max` streaming API，无 mock LLM。API 控制结果在 `logs/api_precheck/disjoint_aug_control_20260823_013003/`。
- 配置与入口：`configs/disjoint_instruction_augmentation_pilot_9_20260823.json`；生成、验证、Repair、导出脚本分别为 `scripts/pilot_disjoint_instruction_augmentation.py`、`scripts/pilot_disjoint_instruction_augmentation_verify.py`、`scripts/repair_disjoint_instruction_augmentation.py`、`scripts/export_disjoint_instruction_augmentation.py`；runner 为 `scripts/run_disjoint_instruction_augmentation_pilot.sh`。
- 显式训练视图：`runs/disjoint_instruction_augmentation_pilot_9_20260823_v1/exports/task_views_v1/task_views.jsonl`；schema `webcoding-disjoint-instruction-augmentation-v1`，共 15 条（Generate 9、Edit 3、Repair 3），全部 `status=ok`；Edit/Repair 6/6 完成 exact patch replay；SHA-256 `c5599fea141032d69ce886f7370b86252f374b10dc0ebeaa0f7af93e6617ee36`。
- manifest：`runs/disjoint_instruction_augmentation_pilot_9_20260823_v1/exports/task_views_v1/canonical_manifest.json`，`status=ok`，记录每条 canonical project、repair depth、target SHA 和最终验证 variant。
- 验证：最终全矩阵 9/9 通过；desktop 1440×1000 与 mobile 390×844 共 18 个基础门，HTTP 200、无横向溢出、无 console/page error、无远程请求；PAST 3/3 默认像素相似度 `1.0`，并保存 AX snapshot；9 张最终桌面图和每策略 1 张移动图已人工检查。
- 用量：3 个母 Seed 20,654 tokens；9 个初始派生 target 81,349 tokens；11 次完整 Repair 调试 lineage 159,939 tokens；全 pilot 261,942 tokens。派生 target 平均 completion 约 1,689 tokens，较完整母 Seed 平均约 6,497 低约 74%，但因完整源代码输入和 Repair 调试，尚未证明总费用低于同等 full regenerate。
- 已知边界：证明了 9 条高质量工程闭环；没有完成 full-regenerate 成本 A/B、去重率、规模成功率或下游训练收益。创新性结论只能按 `to the best of our knowledge` 表述，不能宣称已证明全世界无人做过。
- 研究报告：原 `docs/disjoint_web_instruction_augmentation_research_and_pilot_20260823.md` 已按用户要求删除；本条仅保留 run provenance，不再把 IGRS / PAST / CSDI 作为当前方法。

## 浏览器语义原生 Web 指令扩增 pilot（2026-08-23）

### `browser_native_instruction_augmentation_pilot_9_20260823_v1`

- 状态：小型研究 pilot；9 个 canonical target 已通过真实 Chromium 专属语义门与人工视觉复核，可用于方法展示和后续 SFT 对照；当前不是规模化正式 release。
- 路径：`runs/browser_native_instruction_augmentation_pilot_9_20260823_v1/`，约 5.9M、198 个文件；保留 mother seeds、raw model attempts、original targets、非覆盖 Repair、query 对齐 overlay、验证日志、截图与 canonical export。
- 策略：Browser-Observational Quotient Sampling、Layout Constraint Boundary Mining、Event-Order Counterfactual Synthesis 各 3 条，分别作用于前端代码空间、浏览器几何约束空间和异步完成顺序空间；明确排除已经删除的三条旧路线、IGRS/PAST/CSDI 与组件重组。
- 生成时间与模型：2026-08-23，本地构造；真实 `qwen3.8-max` streaming API，无 mock LLM。4 个 mother seed 中 EOCS v1 因初态/视觉问题保留为 rejected，canonical 使用 v2。
- 配置与入口：`configs/browser_native_instruction_augmentation_pilot_9_20260823.json`；生成、验证、Repair、导出脚本分别为 `scripts/pilot_browser_native_instruction_augmentation.py`、`scripts/pilot_browser_native_instruction_augmentation_verify.py`、`scripts/repair_browser_native_instruction_augmentation.py`、`scripts/export_browser_native_instruction_augmentation.py`；runner 为 `scripts/run_browser_native_instruction_augmentation_pilot.sh`。
- 显式训练视图：`runs/browser_native_instruction_augmentation_pilot_9_20260823_v1/canonical_v2/task_views.jsonl`；schema `webcoding-browser-native-instruction-augmentation-v1`，共 13 条（Generate 9、Edit 3、Repair 1），全部 `status=ok`；Edit/Repair 4/4 完成 exact patch replay；SHA-256 `b0ec33c40b508b90d442317ed1236c17909771f89c82daab24140598d6e7aac5`。`canonical_v1` 为发现 query single-file 与三文件 GT 冲突前的调试导出，不用于训练。
- manifest：`canonical_v2/canonical_manifest.json`，SHA-256 `4760790d31b06d13c990abe38cbdfd22caa496ef2f3866ceb35fd114fbe2b5ed`；candidate selection 显式选择 BOQS-02 original 与 LCBM-01 repair_v2，未把 evaluator-selector bug 触发的两轮 BOQS Repair 混入训练集；`query_overrides.json` 记录一次真实 Qwen packaging-only 修订和原始 query。
- 验证：最终全矩阵 9/9 通过；desktop 1440×1000 与 mobile 390×844 无 document-level 横向溢出、console/page error 或远程请求。BOQS 三条 pixel similarity 均接近或等于 1.0 且 interaction observation 相等；LCBM 覆盖 host width、双轴 sticky、clipping/top layer/focus；EOCS 三条均在 newer-last 与 newer-first 两种完成顺序下通过。
- Repair：`lcbm-01-intrinsic-split-boundary` 的 original 在 520/420px 失败，repair_v1 使 520px 通过但 420px 仍失败，repair_v2 在 960/760/620/520/420 全通过；canonical Repair view 只导出 repair_v1 → repair_v2。
- 人工视觉：九张 canonical desktop 截图全部检查，并额外检查每个 mother 页面的一张 mobile canonical 截图；结果为 9/9 accepted，记录在 `verification_v1/manual_visual_review.json`。
- 测试：生成、验证、Repair、query 对齐、导出相关 19 tests 通过；最终 Chromium 全矩阵 9/9 通过。
- 用量：全 pilot 28 次真实调用、241,985 tokens（含 rejected Seed、failed case attempts、evaluator bug 触发的未选 Repair和一次 query packaging 对齐）；canonical lineage 加 query 对齐 122,283 tokens。派生 target 的平均 completion 约 1,131 tokens，较被采用完整 Seed 平均约 6,281 低约 82%，但完整源代码 prompt 仍大，尚未证明总 API 成本低于 full regenerate。
- 已知边界：当前证明 9 条工程闭环与三个浏览器原生算子的可执行性；尚未完成规模成功率、full-regenerate 成本 A/B、去重与下游训练收益。创新性结论仅按定向检索范围表述。
- 研究报告：`docs/browser_native_instruction_augmentation_research_and_pilot_20260823.md`。

## Evidence Transduction Web 指令扩增 pilot（2026-08-24）

### `counterexample_history_causal_pilot_3_20260824_v1`

- 状态：当前小型研究 pilot；3 个 target 与 3 个 counterfactual fault 已通过真实 Chromium、exact replay、泄漏/去重审计和人工视觉检查；可用于方法展示与下一轮对照实验，当前不是规模化正式 release。
- 路径：`runs/counterexample_history_causal_pilot_3_20260824_v1/`；raw seed/target/fault attempts、rejected faults、repair overlays、验证结果、截图和 canonical 均分层保留。
- 方法：Counterexample-Guided Contract Closure、Render-History Confluence Synthesis、Causal Mutation Trace Transduction 各 1 个 target，分别从反例契约、构造历史和因果 DOM sink 产生联合 query–GT–oracle 变换。
- 生成时间与模型：2026-08-24，本地构造；真实 `qwen3.8-max` streaming API，无 mock LLM。首次内网请求超时 75.296 秒并保留记录，随后使用真实可用 route 完成。
- 配置与入口：`configs/counterexample_history_causal_pilot_3_20260824.json`；生成、验证、导出、审计和截图脚本为 `scripts/pilot_counterexample_history_causal_augmentation.py`、`scripts/verify_counterexample_history_causal_augmentation.py`、`scripts/export_counterexample_history_causal_augmentation.py`、`scripts/audit_counterexample_history_causal_canonical.py`、`scripts/capture_counterexample_history_causal_review_states.py`；runner 为 `scripts/run_counterexample_history_causal_pilot.sh`。
- 显式训练视图：`canonical_v1/task_views.jsonl`，schema `webcoding-evidence-transduction-v1`，exactly 9 条（Generate/Edit/Repair = 3/3/3）；Edit/Repair 6 条均 exact patch replay；SHA-256 `98451910658a5ca901e412451cf3089f71ae51c12df3d1425d420fd501ebd676`。
- manifest：`canonical_v1/canonical_manifest.json` 为 `status=ok`；3 个 target SHA 分别为 `07433076e9251a1f9b4237056c70458acdb1477f21cbb55e130ce458b0890ee2`、`7786f5bc6f304e20db61b5960cf38167d11c9c718109a254ebd49f26b6b3fe84`、`730c1167a91d40acc536fab81643c0a9e15bb182faf7348603137dcda2b970d1`。
- 验证：最终 3/3 target pass、3/3 fault rejected、3/3 fault claim alignment pass；desktop 1440×1000 与 mobile 390×844 无远程请求、console/page error 或页面级横向溢出。12 张 target/fault 交互后截图人工复核为 accepted。
- canonical 审计：9 条 instruction 唯一、3 个 target 唯一，最大 instruction token Jaccard 0.2568；process leakage、Repair answer hint、external runtime、target hash、dedup 全部 pass；canonical 中无 `webcompass` 字样。
- 用量：全部成功尝试 36 次、251,179 tokens，其中 prompt cache 167,936；accepted canonical lineage 为 8 次真实 LLM + 1 次零 token RHCS operator、54,784 tokens。fault search 28 次、191,359 tokens，当前尚未证明端到端低成本。
- WebCompass 边界：只对齐公开的 Generate/Edit/Repair task shape 与自然故障描述风格；没有读取或改写 WebCompass 原始实例、target、patch 或隐藏 evaluator 信息。n=9 不作统计分布匹配声明。
- 研究报告：`docs/web_instruction_augmentation_research_and_pilot_20260824.md`。

## 已删除或当前缺失的数据

| 数据 | 最后已知信息 | 当前状态 |
| --- | --- | --- |
| `/data1/xieqianqian/webcoding/output_full/multi_page` | 25,163 个一级项目、约 302G；CSS/JS 在 resources，图片主要是截图且页面仍有远程引用 | 2026-08-20 按用户明确要求直接删除；未进回收站，不可从回收站恢复 |
| `runs/pipeline_d_40k_target_10k_20260724` | 历史报告：10,005 token pass、约 651M；只有 HTML/metadata、无本地资源闭包 | 2026-08-20 现场核验路径不存在；不能作为现存数据引用 |
| `releases/edit_repair_construct_v1` | 历史报告：7,302 项、约 19G，很多 run 仍引用其路径 | 2026-08-20 现场 releases 列表中不存在；依赖该绝对路径的 manifest 已悬空 |
| `datasets/pipeline_a/useful` | 历史记录：31,765 项 WebRenderBench useful | 当前物理机路径未找到；不得根据旧文档声称仍在盘上 |

## 新数据登记模板

```markdown
### <dataset_name>

- 状态：原料 / 预检查 / 候选 / 正式发布 / 失败证据 / 已删除
- 路径：
- 来源与生成脚本：
- 生成时间与负责人：
- 样本数、任务类型、单页/多页：
- 大小与文件数：
- schema：
- HTML/CSS/JS 保留策略：
- code-token tokenizer、serializer、阈值：
- 图片/字体/媒体资源策略：
- 外链、bundle、占位资源策略：
- manifest / 日志 / 截图 / 审计：
- 已完成验证：
- 未完成验证与已知缺陷：
- 允许用途与禁止用途：
```

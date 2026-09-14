---
name: mine-webcoding-inspiration
description: 从本地网页项目或公开 URL 挖掘 WebCoding 灵感和局部参考代码，构建或管理 capability pool 时使用。两种 mode 均在物理机执行；不等同于整站下载或 Edit/Repair 母本抓取。
---

# 灵感与参考代码挖掘

## 用途与入口

从本地项目或真实 URL 观察组件、视觉和交互，抽取可迁移到新网页的灵感及局部参考代码，供 Edit 指令规划/检索。若只要保存网页，转 `crawl-webcoding-pages`。

## 两种 mode 与统一运行位置

统一入口为 `scripts/mine_live_url_capability_pool.py --mode {local_project,url}`；沿用已有文件名，默认 `url` 兼容旧命令。单样本监管入口 `scripts/run_live_url_audit_case.py` 接收相同 `--mode`。mode 表示**数据来源**，不表示运行在哪台机器。

| mode | sources JSONL 每行 | 参考代码 |
|---|---|---|
| `local_project` | `seed_id`＋物理机上的绝对 `project_path` | 从实际项目定位源码，写入 `source_slices`；当前浏览器入口要求可直接运行的 `index.html` 项目 |
| `url` | `seed_id`＋公开 `entry_url` | 局部 DOM/CSS、可定位 JS 与公开示例/官方文件；默认 `--source-mode reference` |

同一行不混用 project_path 和 entry_url；同一批选择一种 mode。无法取得完整局部代码时保留实际已取得的内容，不由 LLM 补写缺失源码。旧 `mine_seed_capability_pool.py` 已删除，本地项目和 URL 均使用统一入口。

用户要求之后**两种 mode 的真实挖掘均在物理机执行**，包括浏览器采集、LLM 调用和源码提取。`local_project` 是“读取物理机本地项目”，不是在 Mac 运行。项目只在 Mac 时先同步所选项目；Mac 用于编辑代码、单元测试和查看结果。

- SSH：`ssh -p 65022 adminweihunj@36.213.175.38`；凭据使用受保护来源。
- 统一库根：`/data2/adminweihunj/webcoding/inspiration_library`；`current/capability_pool.jsonl` 是当前汇总视图，`current/modes/{local_project,url}.jsonl` 是两种来源的分库。
- 新运行写入该根的 `runs/<新run_id>/`；汇总快照写入 `snapshots/<版本>/`，验证后更新 `current`。保留原始批次与历史版本。
- 当前部署入口在该根的 `code/`；Python 使用 `/data1/xieqianqian/webcoding/WebCoding_Data/.venv/bin/python`，先核验运行时。代码优先在 Mac 的项目仓库修改、测试后同步。
- 库规模和两端重合统计以项目 `docs/inspiration_library_inventory_20260908.md` 与当前 manifest 为准；不把 URL 候选清单数或重复副本行数当作灵感数。

项目定位起点 `/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft`。先读上层及项目 AGENTS、`inspiration_library/README.md`、`docs/data_assets_registry.md` 和当前实现：

- `scripts/mine_live_url_capability_pool.py`：两种来源 mode、scan/full、能力池输出。
- `scripts/run_live_url_audit_case.py`：受控单来源 supervisor。
- `inspiration_library/production_browser.py`：真实在线观测与动作。
- `inspiration_library/deep_browser_exploration.py`：浏览器优先探索及可选模型补充探索。
- `inspiration_library/dynamic_capability_retrieval.py`：能力抽取、schema 校验、合并。
- `inspiration_library/doc_api.py`：实际模型、协议、用量和重试设置。

构造或修改训练数据流程时同时使用 `build-webcoding-data`。以下是 2026-09-08 代码口径，执行时核对，不盲用默认值。

## 输入

sources JSONL 每行必需唯一 `seed_id` 和对应 mode 的唯一来源字段；可选 `target_edit_types` 字符串数组、`mining_focus` 字符串、`expected_observations` 类型名到观察问题的字典，其键必须属于 target_edit_types。URL 还支持 `ready_selector`。
优先复用已有清单：`datasets/url_lists/balanced_inspiration_v2_20260905/` 的 `balanced_core_sources.jsonl`、`edit_priority_sources.jsonl` 是定位线索；查 registry 确定当前版本。不得将普通 urls.txt 直接冒充 sources JSONL。
目标类型和期待观察只是探索方向，不是已经存在的能力。保留来源追溯，按来源/功能多样性选取，不能只偏好最短或最容易访问的页。

## 构建流程

### 当前产品流程升级（2026-09-09）

用户已要求针对产品演化Session更新灵感库，并用已有URL清单补充新来源、构造小型测试库。沿用来源输入和实际浏览器采集，增加产品用途、核心对象、相连用户流程及功能卡分类。

`mine_live_url_capability_pool.py --product-patterns` 输出新版 `product_patterns.jsonl` 和带 product_id/classification 的 `capability_pool.jsonl`。产品层每条 workflow 引用真实功能卡；来源不足时记录实际部分，不能编造完整流程。目标Seed的Transformation Direction由下游提出，不能当作来源观察事实。

产品流程抽取仅向模型传入功能描述、动作、状态关系和观察引用。完整 source_slices、bundle 与组件产物留在已保存的参考结果中，不重复塞入产品分类提示词；恢复旧失败请求时使用新的提示词版本 ID。

`run_live_url_audit_case.py --product-patterns` 支持受控 full 和复用实际观察的 extract；`assemble_product_inspiration_library.py` 合并明确选中的来源快照，保留原库。约3个真实产品/演示、12–24张卡是本次小试范围，数量以观察支持为准。先完成一来源真实小样本再扩大。

如果实际记录只有文档外层操作，应从已观察到的 embedded_documents 定位真实演示入口，保留父URL和来源，再采集演示本身。初始加载未完成时，可按真实观察到的控件设置 ready_selector。静态阅读、打开页面和初始加载使用 user_actions=[]；只有实际执行的操作才能作为交互能力依据。

旧消费者仍可读取 capability_pool；新增产品层用于新Session消费者。当前用户要求优先于此前固定旧输出的约束，相关schema和字段需同步说明和测试。

当前方法基线及固定输入输出的改进讨论见项目 `docs/inspiration_library_method_baseline_20260908.md`。

```text
project_path / URL 清单 → 物理机桌面/移动基线 → 浏览器自动探索 + LLM 多步探索
→ 保存 DOM、AX、截图、布局、storage 和操作前后状态
→ LLM 抽取完整用途的灵感 → 获取局部参考代码
→ 物理机 capability_pool.jsonl + 参考文件 → 下游 Top-K / Edit 指令规划
```

`full` 自带基线观察。每张卡在建库时就对应一个完整功能任务，粒度参考 `inspiration_library/edit_taxonomy.py` 的 WebCompass 16 类定义，也允许同等粒度的扩展功能。同一组件和同一批业务对象上的相关操作即使可单独使用，也合成一个功能系统：例如表格的增删、选择、排序、筛选与分页构成一张记录管理卡，编辑器的格式操作构成一张编辑器卡，通知中心的已读、删除和未读数构成一张通知中心卡；不按按钮或动作拆卡。只有不同组件系统或不同端到端流程才分卡。交互须有实际触发和有意义的结果；视觉效果须有实际时间或滚动变化。只观察到初始样式、属性、空容器、安装说明或未访问的示例时返回空卡池和具体原因，不编造完整行为。

优先探索目标组件内部并沿状态变化继续操作；文档 Header、Support、代码工具栏和外围导航仅在明确作为目标时保留。抽取模型在原有单次调用中完成语义合并与取舍，不增加逐卡审核模型。输入仍为 URL/本地项目，输出文件及字段结构保持不变；取码按当前运行配置，本轮在线生产使用 `--source-mode none`。修改流程后先以真实浏览器和指定 LLM 跑出完整功能样本，并验证片段来源可以正常跳过，再恢复原并发批次。单来源空结果或失败不停止整批，历史产物保留。

1. `scan`：按 mode 调用 observe_project / observe_url，保存 browser_scan、scan_results.jsonl、scan_summary.json。该阶段不创建 LLM client，不需要 API key；扫描成功表示完成浏览器采集。
2. `full`：按 mode 调用 deep_explore_project / deep_explore_url，先 baseline，再浏览器生成动作路径，随后可选 0–2 轮模型规划探索；`--exploration-rounds=0` 只关闭模型规划轮，不关闭最终 LLM 抽取。动作以实际观察到的 selector 为依据，保存动作前后状态并合并观测，然后模型抽取、schema 校验、附代码并合并卡池。
3. 原始 miner 默认 exploration-rounds=1、max-paths=10、max-actions=6、API timeout=180s。路径/动作限制不是总 API 调用数或整批硬超时；执行前单独约束总尝试、样本和费用。
4. 两种 mode 都保存 browser_deep、extractions、provider 请求/响应/用量、capability_pool.jsonl、pool_manifest.json；都将实际源码放入 source_slices。URL 的 full 默认 `--source-mode reference --max-source-regions 4`，另存 components；`examples` 只取公开示例，`none` 只抽灵感，仅适用于 URL。片段按参考代码使用，缺少模块依赖或闭包不阻止保存灵感。结果统一保存在物理机。
5. 已保存 observation/extraction/response 可用于受控续跑；改变 URL、目标、模型或 prompt 时核验缓存身份，必要时用新 run-dir，不能复用陈旧证据。full 异常会中断，不能把中断前局部结果当完整池。

### Closure-aware reference capture

当用户希望同时获得“实现该功能/交互/组件的代码片段”时，沿用当前
`extract-web-component-closure` skill 的策略，作为 `reference` 模式的内部增强，不改变
sources 输入、capability card、`source_slices` 或下游检索接口：

- 探索前安装事件与 shadow-root 记录器；直接监听目标、委托监听中的实际 selector 线索参与
  browser-first exploration，涵盖非标准点击、悬停、shadow 与可见 iframe 控件。按
  `observation_evidence` 的 selector 定位结构 owner；不让模型凭标题猜组件边界。
- 按证据动作序列重放到对应状态，在当前页面/iframe 内直接取码；缓存按 region 和 state 区分，
  取码先于打开示例代码面板。每个 region 旁追加可用 closure artifact：保留 body ancestor context 的 HTML，
  用 CSSOM 筛选目标/后代/相关祖先规则、CSS variables、state/pseudo/media/keyframe/font 规则，
  并用运行时事件记录、目标 identity token 和已加载 ESM import 选择 JS。
- 先给每张有观察区域的卡一次取码机会，再按卡轮转分配额外区域。`max-source-regions` 是常规不同区域预算；不足以覆盖所有卡的首个区域时，只提升到首轮覆盖所需数量。相同区域/状态复用缓存，不能由前几张卡耗尽预算而跳过后面的首轮机会；没有可定位观察区域时如实说明，不编造源码。
- 重放先匹配原 selector 与观察到的 tag/role/text；ID 改变时使用原始动作前 DOM 导出的结构路径，等控件初始化后再操作。暂时加载失败只恢复一次，并保留恢复原因。基线、移动端、before/after、reload 状态均可按实际 source_anchors 获取参考；静态卡无需虚构动作，移动状态沿用原 viewport。无唯一局部锚点时保留页面级参考并说明范围。
- 跨域 stylesheet 使用 Playwright 捕获的响应正文在 detached CSSStyleSheet 中按原顺序解析；CSS `url()` 必须按
  stylesheet 自己的 URL 解析。图片、字体等二进制默认只写入 manifest，不自动下载。
- closure 输出放在该 region 的 `closure/` 下，并以 `closure_html`、`closure_css`、`closure_js`
  作为普通 implementation-reference slices；`component_artifacts` 记录 manifest 路径和
  `dependency_closure: available`。保留 page example、runtime DOM、listener slices 与具体依赖说明。
- reference 模式保留已加载 bundle 和动态模块，单脚本上限 20MB；JS import 用语法树定位并重写。
  超过内联片段长度的完整文件仍在 closure 目录。Shadow DOM 保存声明式模板；iframe 在对应 frame 内取码。
  canvas/WebGL 使用实际脚本和区域截图作参考，不将截图冒充交互实现。
- 默认直接交付可用灵感和参考片段，明显错误直接修复并针对性验证；确实无法修复时说明具体受影响部分。
  `available` 表示参考可用，不等同于独立运行或训练集正式发布。

探索优化只做低成本的内部调整：保留现有“browser-first → 状态去重 → 可选有限 LLM 规划”顺序，
自动探索最多四轮共享原两轮的总路径预算；已改变/新启用的控件继续探索，排除已执行路径，无新增时停止。
优先补充尚未覆盖的交互状态/区域，再为最终 capability cards 抓取 closure；不要为了闭包
额外增加逐卡审核、编译测试、视觉 judge 或新的付费模型调用。普通灵感结果仍以浏览器采集完成、
卡片可读取、保存内容与观察相符为完成口径。


在线批量入口 `scripts/run_inspiration_batch.py` 复用单来源 supervisor，显式指定来源上限和 1–2 并发，每次尝试默认 600 秒，整批无累计时限。明确浏览器/API 网络异常每来源最多 3 次尝试，间隔 5、10 秒；每次独立保存日志、请求及产物，重试计入用量。耗尽后记录失败，不终止其他任务；暂停派发并对最多两个来源站点做非付费连通探测，可达则继续，不可达每 60 秒再探测，期间保留心跳和资源保护。robots 获取失败同样最多 3 次，不绕过访问限制。鉴权/额度、实现错误、资源危险和用户取消仍停止。results.jsonl 追加记录，状态按每来源最新结果统计；成功来源不重跑，明确诊断后的失败/中断用 `--retry-seed-id` 恢复，累计最多 3 次。部署使用 systemd 控制组清理及 watchdog，保留至少 16GiB 可用内存和 50GiB 磁盘；先用一来源完成真实测试再扩大。

代码、配置、提示词或数据流程修改后，必须在物理机跑一个真实来源的完整小样本：实际浏览器探索 → 用户指定供应商的真实 LLM 抽取 → 参考代码与卡池保存。即使修改集中在浏览器或取码侧，也不能只用本地 fixture 代替这次端到端测试。记录供应商/模型、请求用量、supervisor 与产物结果；失败修复后在原授权范围内继续。纯 skill/文档改动或展示已有 case 不制造无关 API 调用。

优先使用单样本 supervisor，核验当前 help 后执行：

```bash
python scripts/run_live_url_audit_case.py \
  --mode url \
  --sources <sources.jsonl> --seed-id <真实存在的ID> \
  --run-dir <新的运行目录> --stage scan --seconds 480
```

full 使用同入口 `--stage full`，需要当前任务 API 授权；已有授权覆盖范围内调试和有界重试，无需逐次确认。supervisor 当前限制一个来源、一次尝试、并发 1、总时限 1–600 秒、15 秒心跳、进程组清理；内部配置一轮模型探索、3 路径、4 动作、API timeout 90 秒。必要时使用已验证的 `--browser-proxy`，不要把浏览器代理混作 API 代理。extract 阶段可对真实保存 observation 做独立抽取诊断。

本地项目只将上例换成 `--mode local_project` 和包含物理机 project_path 的 sources；仍在物理机运行。mode 写入运行身份，切换 mode 使用新的 run-dir。汇总工具 `scripts/inventory_inspiration_library.py`、`scripts/consolidate_inspiration_library.py` 仅整理已有卡，不调用 API；原始池归档、同 ID 的版本保留在 index/versions，已有源码内容按哈希保存为物理机文件。当前视图优先含代码的记录、再按批次日期选版本；只有已有 manifest 明确记录的 supersession 才退出当前视图，历史仍保留。灵感 ID 去重不等于语义去重。
物理机批量任务必须先通过真实单样本，再有总尝试/样本/并发上限、单次尝试硬超时、心跳和可靠中断；整批不设累计时限；裸 miner 的顺序循环不等于安全批量调度。运行前读项目 batch/environment 文档、查看 CPU/内存/I/O。网络故障按上述恢复策略处理，不一律停批。

## 简洁的卡片与完成口径



卡片保留有用内容：`capability_id/change_type/summary/requires/user_actions/produces/visible_result/future_uses`，以及来源 URL/ID 和已取得的 `source_slices`。原始浏览器记录、截图、参考代码在本地保存，按需引用，避免把整份证据与重复内容塞进每张卡。

新建或调整输出时，不添加或保留 `behavior_validation_status`、`browser_check_status`、`visual_evidence_status` 这类流程状态。不用 `pending_semantic_review`、`needs_compilation`、`dom_layout_only_screenshots_not_interpreted` 挂起已完成的爬取。历史文件中的这些字段不作为完成条件；修改 skill 不顺带重写历史产物。

`requires` 用简单字符串列表。模型返回 `[{"role":"data_table_row"},{"role":"row_selection_checkbox"}]` 的含义是“需要表格行和行选择复选框”，可无损转为 `["data_table_row","row_selection_checkbox"]`；普通格式兼容就地处理，不增加包装字段。

抽取中的 evidence、visible_result 如返回字符串段落列表，保留全部段落并以换行合成规范字符串；未知对象结构仍拒绝，不猜测其含义。source_anchors 去除重复引用，操作序列保留原顺序及重复动作。格式修复后可用监管入口 extract 阶段的 --extraction-response 复用匹配同一来源和观察的已返回响应，再继续产品层抽取，避免重复付费。

描述实际爬到的内容，期待观察的问题不写成网页事实。爬取失败报告实际错误，成功续跑后以对应续跑日志为准，不把首次失败日志与续跑后的卡池误认为同一次尝试。交付简述来源数、卡数、内容和本地路径；有失败或实际费用时补充即可。

展示 case 优先给来源、截图、几条灵感及参考代码，不罗列内部审核标签。示例：Ant Design Table → 勾选行、展开/收起详情、点击排序列 → 保存三条灵感与局部参考代码 → 下游在课程列表生成“展开课程查看介绍”的 Edit → 生成网页后再测试展开/收起。

已有案例入口：`runs/reference_sources_20260907/ant_table_direct/`，包括卡池、`components/region_2/region.png` 与对应 TSX 示例；最新结果按当前运行记录定位。已有观察可用以下入口补代码，无需再次调用 LLM：

```bash
PYTHONPATH=. python -m inspiration_library.live_component_sources \
  --extraction <extractions/seed.json> \
  --observation <browser_deep/seed/observation.json> \
  --output <新目录> --max-regions 2 --seconds 180
```




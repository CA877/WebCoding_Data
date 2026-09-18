# edit / repair 构造交付说明

## 0905多页4～7项补量（2026-09-12）

22:27用户将Edit从GLM4+TokenWave2降为GLM2+TokenWave2；Kimi因5小时额度403停用。TokenWave仍通过
本机7890代理，先完成本批真实Edit图文配对再开两路；后续各档复用本档成功证据。

用户确认Edit、Repair各按4/5/6/7项新增100组，共800组、1600条text/image记录。
仅用`freeze_0905_multipage_492.py`冻结的492个爬取母本，至少两个独立HTML/HTM，
精确Qwen全代码不超过40K；复用既有逐页截图，同档内母本不重复，跨档可复用。
`run_0905_density_4to7.sh edit|repair pilot|production`按档独立配额，7项先做真实小样本，
通过后两任务并行、各自4→5→6→7推进。Edit GLM2、Repair GLM2+TokenWave4，
GLM合计最多4路。每case上限480秒；4/5项输出8192 tokens，6/7项16384 tokens，
至多2次内容验证请求，每请求传输最多尝试5次；详情见下方混合供应商续跑规则。
任一档未达100则停止该任务后续档位，保留断点。
图文ID、答案、subtask数和图片输入齐全才计配对，Repair仍要求至少一页像素差异。
输出`runs/0905_multipage_density_4to7_20260912/<task>_<count>/`，各档`progress.json`
记录进度；不含先前500+500组，不追加浏览器功能验收或独立审核。

后续用户授权给Edit加入Kimi，20:23调整为：`--providers glm kimi --glm-workers 2 --kimi-workers 4`，
Kimi使用`k3-256k`及`https://api.kimi.com/coding/v1`，stream开启、清除代理，凭据仅来自
`KIMI_API_KEY`进程环境。真实5项Edit首轮图文配对成功后接入，试跑计入原edit_5配额。
共享队列和配额不变；切换时中断记录通过`--retry-diagnosed`在原尝试上限内恢复。
续跑复用同任务、同模型已实际导出的图文配对作为供应商验证证据；Edit各档通过
`--provider-evidence`引用edit_5账本，样本配额仍分档独立计算。内容/格式/patch失败
只记录该case，不再因连续三条样本失败停用供应商；单独pilot-only最多尝试三条。

## 0905 Repair 混合供应商续跑

`scripts/run_0905_repair_pool.py` 复用本构造器和已冻结母本，GLM `glm-5.2`
最多8路、TokenWave `gpt-5.5` 最多4路，共享母本队列和500组图文配对目标。
当前用户指定 `--glm-workers 4 --tokenwave-workers 4`。
每个供应商先完成真实单样本配对验证再扩并发，TokenWave通过本机7890代理。
每case独立目录、480秒进程硬超时、最多2次带验证反馈的构造请求；10秒状态心跳，
API配额/鉴权或明确运行异常暂停相应供应商派发，子进程组统一清理。
连接错误、超时、429、5xx或过载在当前请求内最多尝试5次，退避约1/2/4/8秒加抖动；
监督器不截断这些请求内重试，也不因连续传输失败停用供应商。耗尽后记录该case，
继续其他样本；正常运行不为传输失败另行重排整case。case硬超时仍480秒，可在
原上限内重排一次；诊断续跑最多两次case尝试。每case最多两次内容验证请求、
每请求最多五次传输尝试，均受硬超时约束；SDK重试关闭。日志记录实际请求次数、
成功/失败及重试原因；供应商未返回token用量时明确记录unknown/not_reported。
`GLM_API_KEY`、`TOKENWAVE_API_KEY` 仅通过进程环境传入。
运行目录中的 `plan.json`、`events.jsonl`、`progress.json` 保存配置、断点和实时状态；
此运行器产出待追加的构造记录，0905 release追加仍按既有交付流程处理。
2026-09-12 实测：两供应商均完成4页、4问题的真实图文配对样本；GLM 8路与
Edit并行时出现429，先用1路续跑；随后按用户要求改为
`--glm-workers 4 --retry-diagnosed`；随后两供应商分别改为4路。
快速退出的API错误在进程结束后再检查一次；续跑保留并跳过未写完的JSONL末行，
JSON字符串内的Unicode分隔符保持原样，完整但损坏的行仍报错；含超时隔离与供应商故障计数的9项回归测试通过。
实际活跃数和后续成功量以 `production_repair_glm8_tw2_20260912/progress.json` 为准。
当前构造器未保存供应商计费token数，`llm_metadata`记录实际模型及验证尝试编号。

0805补量复用其Generate GT，不复用旧Edit/Repair答案。`prepare_0905_0805_mothers.py`
核对独立HTML、源码与发布GT一致、缓存代码/图片哈希及逐页覆盖，复用已有截图。
运行器用`--project-list`、`--canonical-screenshot-dir`、`--target-pairs`指定补量；
`--task edit`复用同一监督器构造Edit，`--pilot-only`只做真实小样本。
本次缺口为Edit 20组、Repair 85组，分别独立输出和计数，不覆盖0805母本。

## 构造规则

- 每条样本支持 1–12 个 task；Edit 的 task type 不重复。WebCompass Repair 与官方数据一致，
  12 项样本允许 11 类缺陷中出现重复类别，但重复项必须描述不同问题。
- 每个 task 必须对应 1–10 个 patch；每个 patch 带自己的 `task_type`。重复 Repair 类别的
  patch 数不得少于该类别的问题数。
- 每个 search 必须在完整输入文件中非空、精确且唯一匹配；构造后强制做正反向恢复验证。
- **旧交付包的构造器**仍使用 HTML（移除脚本）+ 作者 CSS、60K 的历史口径，不能作为最终 WebCompass 对齐版本。
- 默认全代码口径：完整HTML、内联CSS/JS及本地CSS/JS全部进入模型上下文，Qwen最大40K。2026-09-08新增image-based渲染辅助模式：依据 `render_dependencies.json` 将bundle/大型CSS/JS正文排除于输入和40K，但保留只读文件供渲染，不能用于patch或注错；不得伪装为纯公共库或直接导出同口径Text记录。`build_generation_data(..., image_based=True)`显式启用消费，默认拒绝含此类依赖的项目；读取时验证依赖哈希，`dst_code`/`full_code`/`model_context`均为模型可见集合，`resources`仅含依赖描述、不含正文。
- 当前构造器已经使用 40K 全代码 serializer；批量生产前仍必须对目标项目清单运行精确 tokenizer 门禁。
- 输出为可恢复追加的 `records.jsonl`。只使用 `status=ok` 行构造训练集。
- Edit 只允许正向构造。WebCompass 对齐的 image-edit 复用母本全部 canonical source screenshots：每个独立 HTML 页面各一张，不按本轮 edit 是否影响该页面过滤；不渲染 target、不执行 browser action，patch 精确回放是接受条件。
- Repair 复用母本 canonical clean 截图，只重渲染 defective 状态，并核对视口与页面集合一致。所有精确 patch 成功的记录进入 text-repair；达到配置像素差异门的记录才进入 image-repair。本轮只构造 `controlled_repair`，暂不构造 Natural Repair。
- text-repair 最终输入只有缺陷代码，不提供指出 bug 类型的 query；审计元数据保留 defect type，但不进入训练指令。
- 并发按“在途单条 LLM API 调用”计数，不按 shard/进程计数。shard 仅用于配额和输出分区；
  后续 runner 必须使用全局 case 队列与原子 quota reservation，在少量 shard 的尾部仍持续补满
  LLM 调用槽。浏览器截图和 rule injection 使用独立队列，不占 LLM 调用槽。

## Interaction-rich Edit / Repair 扩展

训练输出保持不变：输入为现有代码、自然指令和可选图片，输出仍然只有精确 patch。

当前构造器已增加：

- click、hover、focus、input、select、toggle、tab、accordion、dropdown、modal、tooltip、carousel、drag/drop、sort、filter、pagination、navigation、validation、conditional rendering、loading、toast、animation；
- Interaction2Code、ArtifactsBench、FrontendBench 三套扩展能力 profile；`balanced` 按项目轮转，FrontendBench 只作能力参考；`webcompass` 单独固定为官方 16 类 Edit；
- image-edit 固定使用 `source_image`：当前完整代码 + edit query + 全部独立 HTML 页面的 canonical 当前/source screenshots；单页为一张，多页为每页一张，`dst_screenshot` 为空；
- interaction edit 不执行浏览器动作、不生成编辑后截图，构造验收只检查多文件 patch 能精确应用并可逆恢复；
- Runtime Repair、Visual Repair、Interaction Repair、Quality Refinement 四类 Repair，并写入 `repair_family`、`repair_subfamily`、`defect_type`、`benchmark_alignment`；同一记录的 leaf defect 必须属于同一个 family；
- family 采用不同的真实证据门：Runtime 要有 clean 中不存在的浏览器错误，Visual 要通过截图差异阈值，Interaction 要证明 clean action contract 通过且 defective 失败，Quality 要产生可度量 DOM/accessibility regression；
- 多页源项目始终启用跨页 patch 门：至少修改两个 HTML 页面或修改被多页共享的 CSS/JS/TS；`--page-scope mp` 可用于只筛多页项目。
- `mp` 严格表示项目至少包含两个独立 `.html`/`.htm` 文档；单 HTML 的 hash-route/SPA 保留为 `sp`。route 仍用于交互构造和截图，但不计入 WebCompass 多页配额。母本池、构造筛选、导出 `page_type` 和跨页 patch 门使用同一物理页面定义。
- 付费构造默认只有一次请求机会：`--max-retries 1`、`CONSTRUCT_TRANSPORT_ATTEMPTS=1`、OpenAI SDK `max_retries=0`。提高任一外层尝试数需要用户明确授权重复付费请求。

完整设计和小规模真实样本矩阵见
`docs/0805_edit_repair_interaction_expansion_plan_20260820.md`。TaskSpec 是构造与验收层；训练输出仍为 patch，browser contract、截图阈值和 repair 诊断不得泄漏到训练指令。

新母本批跑必须在 canonical 质检完成后构造 shard。使用
`scripts/run_build_new_gt_edit_repair_mother_pools_v10.sh` 可冻结已验收的
5K image-generate 母本，同时只从存在 `canonical_v2/<project>/screens.json`
的项目中补齐 Edit/Repair 候选，避免把截图拒绝项送入付费构造。
Doc API 单次请求由 `CONSTRUCT_API_TIMEOUT` 设置硬超时；case 内默认只提交一次，
失败逐条记录并停止该 case，不自动重复付费提交。

对历史 release 重新筛选真实多页母本时，使用
`scripts/inventory_true_mp_reuse_pool.py`。该工具直接读取六任务 gzip，按完整代码中的
独立 HTML 数量筛选，并记录 clean-code hash、source project、截图覆盖和 Repair patch
回放状态；输出文件采用新建写入，不覆盖历史结果。

0805_supplement 的官方类型密集任务使用
`scripts/build_0805_webcompass_edit_repair_plan.py` 和
`reverse/run_0805_webcompass_edit_repair_supplement.sh`。四组默认成功目标各 1,000；
MP 按官方 4–12 项分布，SP 按官方 8–12 项条件分布。
当前 v1 是各 150 的历史候选计划；新版 v2 工作清单待母本扩充/复用策略确定后生成，运行器默认指向 v2。
计划中 MP 只接收多个物理
HTML/HTM，SP 只接收一个 HTML 且原记录标记为 SP；`--instance-id-prefix` 防止复用母本时
与旧记录撞 ID，`--skip-attempted` 保证中断续跑不会重复提交已经付费尝试过的母本。
先以 `MODE=pilot` 跑 Edit/Repair × SP/MP 四条真实样本；确认后才可设置
`MODE=bulk CONFIRM_BULK=1`。pilot 与 bulk 共用追加输出，已通过的 pilot 不会重跑。

例子：

```bash
# 四个 interaction 来源按项目轮转；image-edit 固定复用 canonical source 图
EDIT_PROFILE=balanced IMAGE_INPUT_VARIANTS=source_image \
  TASKS=edit bash reverse/run_edit_repair_batch.sh

# 只构造多页 interaction edit
EDIT_PROFILE=balanced EDIT_PAGE_SCOPE=mp TASKS=edit \
  bash reverse/run_edit_repair_batch.sh

# 四类 Repair 的 leaf taxonomy；多页 Repair 可将 REPAIR_PAGE_SCOPE 设为 mp
REPAIR_PROFILE=taxonomy REPAIR_PAGE_SCOPE=any TASKS=repair \
  bash reverse/run_edit_repair_batch.sh
```

## 6,503 条 WebCompass 原始样本

当前 edit/repair 的正确原始来源是物理机上的
`train_sharegpt_webcompass_only_6503.jsonl`，不是历史 7,302 网页底稿或旧 5K split。

先将每条 GPT 回复中的 `# 文件名` + Markdown code fence 无损恢复为项目目录：

```bash
python reverse/utils/materialize_sharegpt_web_projects.py \
  --input-jsonl /data1/xieqianqian/webcoding/data/20260804/all_merged_instructions/sft_train/train_sharegpt_webcompass_only_6503.jsonl \
  --output-dir runs/webcompass_6503/source_projects \
  --audit-jsonl runs/webcompass_6503/materialize_audit.jsonl \
  --project-list runs/webcompass_6503/materialized_projects.txt
```

使用 `reverse/utils/filter_construct_projects_40k.py --allow-missing-screenshot` 对所有完整文件做
40K 硬门禁；超过上限直接淘汰，不截断、不丢文件。随后生成 image-generate 截图，
并用 `reverse/utils/select_construct_quotas.py` 固定 edit 3,000 清单与 repair 候选顺序。

## 一条命令批量运行

现有 `construct_context_audit_7302_20260723/*eligible_5k.txt` 是旧来源、旧 token
口径，不能用于本轮构造。对刚恢复的 6,503 项目用精确 Qwen tokenizer 预筛：

```bash
python3 reverse/utils/filter_construct_projects_40k.py \
  --project-list runs/webcompass_6503/materialized_projects.txt \
  --tokenizer .cache/qwen3-tokenizer.json \
  --output-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --audit-jsonl runs/webcompass_6503/token_precheck.jsonl \
  --allow-missing-screenshot

python3 reverse/utils/prepare_clean_screenshots.py \
  --project-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --browser-proxy http://127.0.0.1:7890 --width 1920 --height 1080

python3 reverse/utils/select_construct_quotas.py \
  --eligible-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --edit-list runs/webcompass_6503/edit_projects.txt \
  --repair-list runs/webcompass_6503/repair_projects.txt \
  --manifest runs/webcompass_6503/selection_manifest.json --edit-count 3000
```

```bash
cd /data1/xieqianqian/webcoding/WebCoding_Data
# 默认 launcher 使用受保护的 Doc API 凭据源；具体路径通过 DASHSCOPE_API_DOC 显式指定，
# 读取 key 后直连 DashScope OpenAI-compatible endpoint，模型固定 qwen3.8-max。
# 不再使用旧 Idealab/Kimi .env 路由。
# 两份清单必须来自 eligible_40k_final.txt；可相同，也可按实验方案拆分。
EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
REPAIR_PROJECT_LIST=runs/webcompass_6503/repair_projects.txt \
bash reverse/run_edit_repair_batch.sh
```

脚本默认使用 `API_PROFILE=dashscope_doc_direct`，清除所有代理变量后直连；可用 `DASHSCOPE_API_DOC=/path/to/项目用api.pdf` 指定文档位置。key 不写入 Bash、README、JSONL 或交付包。`API_PROFILE=env` 仅作为显式兼容入口，不是默认生产路径。

物理机环境若没有 PDF 解析依赖，可由本机从同一受保护 PDF 读取 key，通过 SSH 标准输入只注入远端进程环境，并使用 `API_PROFILE=inherited_doc`；不得为此生成远端 `.env`。正式批量前先运行 `reverse/run_edit_repair_quality_pilot.sh`，再用 `reverse/utils/audit_edit_repair_taxonomy_quality.py` 独立复核。

默认输出到 `runs/construct_edit_repair_<运行日期>/`：

```text
text_edit/records.jsonl
text_edit/text-edit.v2.jsonl
text_edit/image-edit.v2.jsonl
text_repair/records.jsonl
text_repair/text-repair.v2.jsonl
text_repair/image-repair.v2.jsonl
images/image-edit/<项目名>/
images/image-repair/{clean,defective}/<项目名>/
```

可按环境变量调整：

```bash
TASKS=edit EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
  EDIT_WORKERS=1 OUTPUT_ROOT=runs/construct_edit_trial \
  bash reverse/run_edit_repair_batch.sh

# 不调用 API，只检查参数、项目清单和最终命令
EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
REPAIR_PROJECT_LIST=runs/webcompass_6503/repair_projects.txt \
DRY_RUN=1 bash reverse/run_edit_repair_batch.sh
```

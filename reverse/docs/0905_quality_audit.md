# 0905 Edit / Repair 数据质量审计

审计对象：物理机 `/root/wc_work/0905_official_results/` 下的四个 0905 分片。

审计时间：2026-09-18。

## 判定口径

- `keep`：`judge_result.task_scores` 完整，截图和 `ans/` 产物可解析；每个 task 的三个评分维度均大于 3；样本 task 平均分不低于 7/10。
- `rebuild`：结构完整，但存在至少一个 task 的关键维度不高于 3、三项全零，或样本平均分低于 7。保留母本和任务元数据，重新生成对应 Edit/Repair 结果。
- `remove`：缺失 judge、judge 结构损坏，或截图等必要证据缺失，当前不能进入数据集。这里的 remove 指从当前 0905 数据集移出，不是立即删除物理机原始目录。

`apply_errors` 不作为单独删除条件：部分样本仍有其他任务成功完成，最终以 task 级评分和产物完整性判断。

## 汇总

| 分片 | 总样本 | keep | rebuild | remove |
|---|---:|---:|---:|---:|
| Edit text | 300 | 56 | 242 | 2 |
| Edit image | 300 | 59 | 238 | 3 |
| Repair text | 300 | 51 | 249 | 0 |
| Repair image | 300 | 47 | 252 | 1 |

## 主要结论

### Edit

Edit text/image 的 task 平均分分别约为 5.14 和 4.89。两个分片都有约 500 个 task 三项全零，且大量 judge reasoning 明确说明“没有代码修改”“没有 JavaScript 交互实现”或“没有对应 search/replace block”。因此 Edit 不能按样本平均分整体保留；除 `keep` 外的结构完整样本都应重新构造。

按类型看，`Page Transitions` 是两个 Edit 分片中最低的类型（约 3.99 和 4.06/10）；`Drag & Drop Interface`、`Async Form Validation`、`Rich Text Editor`、`Tree View` 也有较多全零任务。重造时应优先补这些交互型类型，确保生成 JavaScript 而不是只追加 HTML/CSS。

### Repair

Repair text/image 的 task 平均分约为 7.28 和 7.26，整体明显好于 Edit，但仍不能全量保留。约 500 个 task 三项全零，常见 judge 结论是 patch 未命中根因、修改了无关位置，或根本没有对应修改。

最需要重造的 Repair 类型：

- `Crowding`：平均约 4.24--4.55/10，是最严重的弱项；
- `Color Contrast`：平均约 6.48--6.60/10；
- `Missing Attributes`：平均约 5.62--5.69/10；
- `Occlusion`、`Semantic Error`、`Alignment`：仍存在较多全零 task。

`Overflow`、`Text Overlap`、`Nesting Error`、`Loss of Interactivity` 的平均分较高，但仍需移除其中 task 级失败样本，不能按类型整体放行。

## 必须移出当前数据集的结构问题

### Edit text

- `sp/2876672_pragmata.institute_en_L11_1`：缺失 judge，且截图引用无法解析。
- `sp/993724_vivalamovie.com_L5_2`：缺失 judge。

### Edit image

- `sp/2655223_www.ChamplainAssistedLiving.com_L10_2`：缺失 judge，且截图引用无法解析。
- `sp/3010631_www.bw-nde.com__L4_2`：缺失 judge。
- `sp/5089991_www.jonidbendo.com__L4_0`：缺失 judge。

### Repair image

- `sp/2695592_www.usbioclean.com_L11_2`：缺失 judge。

Repair text 未发现结构性缺失样本。

## 协议检查

- 所有有 judge 的样本中，`info.json.task_type` 与 judge 的 `task_scores[].task_type` 顺序完全一致。
- Edit 没有发现重复类型。
- Repair 的重复缺陷类型是现有构造允许的组合，不应仅因重复类型删除；应检查每个重复项是否对应不同的实际缺陷和有效 patch。
- 四个分片的 task 数量均落在 4--12 个范围内。

## 执行建议

1. 先将上表 `remove` 样本从 0905 可用索引移出，保留原始目录作为追溯证据。
2. 对 `rebuild` 样本保留母本，按当前已对齐 WebCompass 的构造脚本重新生成，不在原目录覆盖旧结果。
3. Edit 重造优先覆盖交互逻辑；Repair 重造优先覆盖 `Crowding`、`Missing Attributes`、`Color Contrast`。
4. 重造完成后，仍按 task 级评分和 patch 根因命中情况验收，不使用样本平均分单独放行。

## Text Generate 静态退化清理（0905）

这次清理针对 0905 Text Generate / Image Generate 的原始 Generate response，使用
`reverse/web_coding_demo/synthetic/supplement_0905.py` 中的 `rejected()` 规则逐条检查，未调用 LLM，未进行浏览器渲染或功能语义验收。

### 判定规则

- `piece_gt_50k`：Generate response 中任意单个文件的 `code` 字段长度大于 50,000 个字符。
- `repeated_8line_candidate`：对每个文件按连续 8 行滑动取块；块长度至少 200 个字符，且同一完整 8 行块出现至少 3 次。

命中任一规则即移出清理副本；同一记录可以同时命中多个原因，因此原因计数之和不一定等于移除记录数。规则只识别明显的输出膨胀或重复代码候选，不能单独证明页面渲染、交互或需求语义一定错误。

### 结果

| 任务 | 清理前 | 保留 | 移除 | 原因计数 |
|---|---:|---:|---:|---|
| Text Generate | 12,437 | 12,275 | 162 | `repeated_8line_candidate`: 143；`piece_gt_50k`: 20 |
| Image Generate | 11,192 | 11,030 | 162 | `repeated_8line_candidate`: 138；`piece_gt_50k`: 26 |

Text/Image Generate 各移除 162 条，用于保持配对关系。被移出的 Text Generate 样本及原因保存在
`Webcoding-Model-Project/experiments/2026-09-13-8b-2ep-0905/问题分析/0905修复证据/removed.jsonl`；汇总数量和原因保存在同目录的 `cleanup.json`。原始发布源未被覆盖，移除记录保留用于追溯。

### 边界

这 162 条属于“命中静态退化启发式规则”的清理结果，不应表述为已经完成浏览器、功能、视觉或人工语义质量验收。后续若要把它们恢复或进一步确认，应对具体样本执行协议解析、浏览器渲染和核心交互检查。

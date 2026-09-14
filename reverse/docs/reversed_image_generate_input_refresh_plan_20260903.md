# reversed Image Generate 输入更新计划

## 1. 范围

本轮只更新 `reversed_20260903_v4` 的 Image Generate 输入图片及其映射信息，不重新生成 ground truth，不修改 GT 功能，不新增 harness，不处理 `webcompass_generation_domain`。更新直接写回原有 10,094 条记录及其单 gzip shard，不新增派生记录或训练分片；写回前在 release 外保存备份。

多页按页面级导航定义：主页至少有两个真实入口，两个入口均可点击并进入内容明显不同的页面级视图；SPA 和物理多 HTML 都可接收。

Image Generate 使用可多选字段 `image_generate_visual_types` 记录截图覆盖类型。一条样本可以同时包含多个值：

| 值 | 含义 |
|---|---|
| `multi_page` | 多个可由真实入口到达的页面级视图；接受物理多 HTML、pathname/hash 路由和 SPA 页面切换 |
| `same_page_interaction_states` | 同一页面执行交互前后的两个或多个可见状态 |
| `multi_step_interaction_sequence` | 同一任务从开始到完成的连续关键步骤，至少三个有序状态 |
| `transient_ui_state` | 弹窗、下拉菜单、筛选面板、hover、主题切换等临时 UI 状态 |

字段只记录输入图片实际覆盖的类型，不根据文件数量或 GT 能力猜测。四类都纳入补充范围，但不要求每条样本同时覆盖四类。

## 2. 现有多页样本的标注更新

以 GT 实际实现的页面清单为准：有几页就覆盖几页，包含物理页面和经浏览器确认的 SPA 页面级视图。先确定子页及其截图，再在主页上标出通往这些子页的入口，编号与子页截图一一对应。其他链接、页内锚点和局部交互保持原样。标注数量由实际子页决定。

处理顺序：

1. 启动现有 GT，根据源码、已有页面信息及浏览器行为核实真实页面清单；
2. 确认主页至少有两个可点击的真实页面入口；
3. 为清单中每个子页选择主页上的对应入口，在截图前临时向 DOM 叠加编号框；
4. 用浏览器真实点击入口，记录入口编号、入口文字/定位、目标 URL/route 和目标截图；
5. 将原主页截图替换为 `annotated_home`，保留 GT 全部真实页面的截图；
6. 更新 `input_images` 的稳定顺序，并写入 `page_entry_mapping`；
7. 对缺少主页入口的子页记录实际到达路径并列入复核；旧链接遍历产生的截图另行核实是否属于真实页面。

建议记录：

```json
{
  "visual_input_type": "multipage_navigation",
  "image_generate_visual_types": ["multi_page"],
  "input_images": ["annotated_home.png", "page_01.png", "page_02.png"],
  "page_entry_mapping": [
    {
      "marker": 1,
      "source_image": "annotated_home.png",
      "entry_text": "Catalog",
      "target_route": "#/catalog",
      "target_image": "page_01.png"
    }
  ]
}
```

样本页面多于两个时，继续保留其余页面截图和映射，不因对齐 WebCompass 的标注样式而截断 GT 覆盖范围。

## 3. 交互关键帧补充

2026-09-05 最新目标：多页、普通交互、临时状态、连续步骤各 1,000 条有效截图任务，按 `(mode, parent_instance_id)` 去重计数。同一 GT 可跨类别复用，多标签计数仅作覆盖统计。用户已认可四个本地示例，并接受原图外链加载失败。先核对并复用已有结果，再补齐缺口；超额历史结果保留，本轮清单每类选取 1,000 条。等待用户通知 SSH 恢复后执行，总并发最多 4，先单 worker 验证资源情况；任务暂存本地。

交互关键帧只从 GT 已经实现的交互中提取，绝不修改 GT，也不让 LLM 补功能。补充时覆盖普通交互前后、多步骤连续状态和临时 UI 状态；多页截图作为第四种形态单独统计，允许与前三种共存。

优先选择点击后有稳定、明显视觉变化的交互：弹窗开关、accordion、下拉菜单、Tab 切换、筛选结果、表单校验、购物车反馈、主题切换及可稳定停止的动画状态。

处理顺序：

1. 在初始状态保存 `frame_00_before`；
2. 执行一次真实浏览器动作；
3. 等待现有页面进入稳定状态并保存 `frame_01_after`；
4. 仅在动作成功、前后存在明显可见差异且无致命运行错误时导出；
5. 将关键帧追加到原 Image Generate 记录的 `input_images`，保持原 `instance_id`、GT 和样本总数不变。

建议记录：

```json
{
  "visual_input_type": "interaction_keyframes",
  "image_generate_visual_types": ["same_page_interaction_states", "transient_ui_state"],
  "input_images": ["frame_00_before.png", "frame_01_after.png"],
  "interaction_mapping": {
    "action": "click",
    "target": "Open filters",
    "before": "frame_00_before.png",
    "after": "frame_01_after.png"
  }
}
```

## 4. 最小验证

本轮不做复杂语义评分，只执行：

- 多页：主页两个真实入口均可点击，入口编号与目标截图对应，目标页面级视图明显不同；
- 关键帧：动作实际执行成功，前后截图有明显可见变化；
- 通用：截图可解码、路径闭合、页面没有白屏或致命运行错误。

SPA 功能正常时直接保留。只有入口失效、目标视图为空、不同路由实际相同或发生致命运行错误时进入后续修复清单；本轮不做 SPA 转物理多页。

## 5. 执行顺序

1. 先选 6 条现有多页样本，覆盖 SPA 与物理多页，生成带标注的主页和完整页面映射；
2. 再选 6 条已有明显点击交互的 GT，生成 before/after 派生样本；
3. 人工只检查 12 条最终输入图片是否能看懂对应关系和状态变化；
4. 修正确定性截图或映射问题后扩到目标数量；
5. 根据现场资源确定受限并发，worker 产生内部截图证据和断点记录，接收结果合并回原有单 shard；
6. 每次写回保持 10,094 条、原 `instance_id` 和 GT 哈希不变，并检查全部 `input_images` 路径存在。

## 6. 2026-09-03 首轮运行

- 零 LLM 调用；GT 代码未修改；正式 `reversed_20260903_v4` 未覆盖。
- 新增脚本：`scripts/pilot_refresh_reversed_image_generate.py`。
- 物理机首轮目录：`/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_image_generate_input_refresh_20260903_pilot12/`。
- 6 条多页标注均成功，主页编号清楚，目标页面截图与入口映射完整；代表样本 `WebGen-Bench.prompt_1660` 从原单张输入补为标注主页加 4 个目标页面。
- 6 条交互候选均由真实点击产生；人工总览后接收 4 条明显变化，拒绝 2 条肉眼变化偏弱的 Search/Start over。
- 交互 changed-ratio 门从 `0.005` 收紧为 `0.03` 后启动替换运行；物理机 SSH 连续 reset，已停止继续扫描，待主机恢复后只补 2 条，不重复多页部分。

## 7. 2026-09-04 原地扩充

- 最低目标：`multi_page=2000`、`same_page_interaction_states=1500`、`transient_ui_state=600`、`multi_step_interaction_sequence=300`；类型允许重叠。
- 正式数据仍位于 `/data2/adminweihunj/webcoding/WebCoding_Data/releases/reversed_20260903_v4/`，Image Generate 保持 `train-00000-of-00001.jsonl.gz` 单 shard 和 10,094 条记录。
- 第一次原地写入触及 512 条原记录：多页 overlay 419、普通交互 57、临时状态 28、多步骤 33；写回后实际类型计数为多页 438、同页交互 95、临时状态 28、多步骤 33。样本数 10,094→10,094，缺失图片 0，GT 哈希未变。
- Image Generate 当前图片文件数 20,600，gzip SHA-256 为 `efd071a61c6c6ae943ea0a71892cc5ddf4622a7064b634faf782725df0deb89a`。
- 写回前备份：`/data2/adminweihunj/webcoding/WebCoding_Data/backups/reversed_20260903_v4_before_image_generate_refresh_20260904_v1/`。
- 续跑采用 16 并发内部截图工人；运行证据位于 `/data2/adminweihunj/webcoding/WebCoding_Data/runs/reversed_image_generate_minimum_16way_20260904_v1/`，日志位于 `/data1/xieqianqian/webcoding/WebCoding_Data/logs/reversed_image_generate_minimum_16way_20260904_v1/`。内部目录不作为训练 shard。
- 2026-09-04 20:52 现场快照：累计接收多页 904、普通交互 123、临时状态 53、多步骤 60；其中第一次写入后的新增候选尚待下一次原地合并。按当时吞吐量，截图生产和最终写回预计还需约 2—3 小时；临时状态若候选池提前耗尽，需要扩大确定性 DOM 候选后再补，保守按 3—5 小时完成最低量。

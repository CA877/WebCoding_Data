# WebCoding 当前状态

- **2026-09-13 0905增量上传完成**：ModelScope `mistletoe111/webcoding_stf/0905/`已更新为39,845条、47,827文件、16,989,925,934 bytes；全量远端路径、大小、SHA256核验通过，README与索引同步。相对9.08发布共6,917个差异文件（6,911新增图片＋4分片＋README/索引），差异文件大小2,550,051,037 bytes，原40,910个未变文件跳过，保留所有旧记录。AccessToken保存在仓库外受保护文件，位置见发布手册；更新凭据后鉴权成功，同精确列表路径的真实单图上传及哈希验证通过。上传由2并发调至8并发，保留断点成功文件；最后一次续传覆盖5,891个剩余差异文件。[交付结果](../runs/delivery_0905_incremental_20260913/result.json)及发布README/索引已保存本地，物理机同名运行目录保留完整manifest和`upload_workers8.log`。以下鉴权阻塞为已恢复的历史过程。

更新时间：2026-09-13。此页只保留下一步所需的事实；运行中的精确进度以对应 `manifest`、`progress.json`、事件账本和发布索引为准。

## 数据包

- 本地 0905 发布清单为 **39,845** 条：Text/Image Generate 为 **12,437 / 11,192**，Text/Image Edit 为 **3,905 / 4,145**，Text/Image Repair 为 **4,249 / 3,917**。
- 0905 多页补量已合入物理机 release；图文配对、patch 回放和图片哈希检查均已执行。完整检查边界见 [0905 检查记录](../validation/docs/reports/0905_data_check_strategy_implementation_20260912.md)。
- ModelScope 增量上传尚未写入云端：直连返回 AccessToken 错误。取得新凭据后，从物理机 `runs/delivery_0905_incremental_20260913/` 的 manifest 续跑。

## 两条生产路线

- **逆向构造**：以 [数据构造规范](../validation/docs/data/construction_spec.md) 和 [当前流程](../web-coding-agent/docs/synthesis/pipeline.md) 为准；候选、已写入、基础检查和正式验收必须分开统计。
- **正向 Harness**：产品 Session 的当前方向和证据见 [product_edit_session.md](../web-coding-agent/docs/product_edit_session.md)；连续 Edit 已具备浏览器检查、保护边界和自然 Repair 记录，但新样本仍需按实际浏览器结果决定是否可导出。

## 当前优先级

1. 更新 ModelScope 凭据并完成 0905 增量上传核验。
2. 以 release 索引和浏览器证据继续核对 Generate 母本、页面语义和自然 Repair；不要把候选或服务存活当作 accepted 数据。
3. 继续产品 Session 时，保持已验收 Edit 前缀不变；只对当前状态生成下一步指令。

## 入口

- 版本、数量和允许用途：[data_assets_registry.md](../validation/docs/data/data_assets_registry.md)
- 浏览器与正式评测口径：[evaluation_protocol.md](../Benchmark_evaluation/docs/evaluation/evaluation_protocol.md)
- 批处理、API 和发布：[operations/](operations/)

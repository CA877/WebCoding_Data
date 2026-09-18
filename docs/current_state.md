# WebCoding 数据

- **2026-09-13 0905增量上传完成**：ModelScope `mistletoe111/webcoding_stf/0905/`已更新为39,845条、47,827文件、16,989,925,934 bytes；全量远端路径、大小、SHA256核验通过，README与索引同步。相对9.08发布共6,917个差异文件（6,911新增图片＋4分片＋README/索引），差异文件大小2,550,051,037 bytes，原40,910个未变文件跳过，保留所有旧记录。AccessToken保存在仓库外受保护文件，位置见发布手册；更新凭据后鉴权成功，同精确列表路径的真实单图上传及哈希验证通过。上传由2并发调至8并发，保留断点成功文件；最后一次续传覆盖5,891个剩余差异文件。[交付结果](../runs/delivery_0905_incremental_20260913/result.json)及发布README/索引已保存本地，物理机同名运行目录保留完整manifest和`upload_workers8.log`。以下鉴权阻塞为已恢复的历史过程。

更新时间：2026-09-13。此页只保留下一步所需的事实；运行中的精确进度以对应 `manifest`、`progress.json`、事件账本和发布索引为准。

## 数据包

- 本地 0905 发布清单为 **39,845** 条：Text/Image Generate 为 **12,437 / 11,192**，Text/Image Edit 为 **3,905 / 4,145**，Text/Image Repair 为 **4,249 / 3,917**。
- 0905 多页补量已合入物理机 release；图文配对、patch 回放和图片哈希检查均已执行。完整检查边界见 [0905 检查记录](../validation/docs/reports/0905_data_check_strategy_implementation_20260912.md)。


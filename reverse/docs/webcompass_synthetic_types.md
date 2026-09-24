# WebCompass Synthetic 类型

本文件记录官方 WebCompass synthetic 的 Edit/Repair 类型和构造口径。类型定义及详细 guideline 由 `web_coding_demo/synthetic/edit.py` 与 `repair.py` 直接提供，构造代码不再维护第二份类型表。

## Edit

官方类型为：Data Table、Rich Text Editor、Drag & Drop Interface、Tree View、Real-time Dashboard、Infinite Scroll、Async Form Validation、File Upload with Progress、Parallax Scrolling、Page Transitions、Particle Effects、Skeleton Loading、Shopping Cart、User Authentication、Multi-step Wizard、Notification Center。

## Repair

官方类型为：Occlusion、Crowding、Text Overlap、Alignment、Color Contrast、Overflow、Sizing Proportion、Loss of Interactivity、Semantic Error、Nesting Error、Missing Attributes。

## 数量与抽样

每个实例从 4--12 个子任务中抽取一个数量。Edit 使用官方 `random.sample`，同一实例内类型不重复；Repair 使用官方 `random.choices`，允许类型重复。

## 构造边界

官方 prompt、XML 解析、task type 校验、Repair search/replace 应用和重试逻辑直接复用 `web_coding_demo/synthetic`。当前 reverse 只保留现有输入、JSONL 输出、截图素材和 Edit 的 `dst_code` patch 适配。

Repair 的 clean/defective 截图差异只记录为统计证据，不设置像素差异准入阈值。

# WebCompass Synthetic 类型

本文件记录构造器对齐 WebCompass synthetic 时使用的官方类型集合。类型集合不再扩展为项目自定义 taxonomy，也不在任务 prompt 中追加项目专属类别。

## Edit

Data Table、Rich Text Editor、Drag & Drop Interface、Tree View、Real-time Dashboard、Infinite Scroll、Async Form Validation、File Upload with Progress、Parallax Scrolling、Page Transitions、Particle Effects、Skeleton Loading、Shopping Cart、User Authentication、Multi-step Wizard、Notification Center。

## Repair

Occlusion、Crowding、Text Overlap、Alignment、Color Contrast、Overflow、Sizing Proportion、Loss of Interactivity、Semantic Error、Nesting Error、Missing Attributes。

## 数量和筛选口径

每个 Edit/Repair case 的 task 数使用 WebCompass synthetic 的 `4-12` 范围。Edit 类型按官方 synthetic 的不重复抽样；Repair 类型按官方 synthetic 的有放回抽样，因此允许同一缺陷类型重复出现。

Repair 不设置 clean/defective 截图像素差异阈值。截图可以作为 Image Repair 输入和统计证据，但不作为样本准入门禁。

上述内容是数据构造口径记录，不向模型额外暴露项目自定义的 taxonomy、family、severity、跨页或浏览器检查要求。

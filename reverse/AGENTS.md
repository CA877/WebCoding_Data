# reverse 目录规则与文档索引

## 职责

`reverse/` 从清洁网页项目受控构造六类 WebCoding 数据：Text/Image × Generate/Edit/Repair。这里维护构造器、任务 schema、patch/截图配对和 release 资产边界，不承接 harness 的正向轨迹生产。

## 权威文档

- `README.md`：当前构造/补量交付说明与运行约束。
- `docs/construction_spec.md`：长期构造语义、六类输入输出、页面/图片/Repair 口径。
- 当前 release、数量、状态和允许用途：以 `validate/docs/` 与 release manifest 为准。
- `web_coding_demo/README.md`、`CLAUDE.md`：仅限旧 demo 子项目的运行说明。

## 核心不变量

- 数据以完整网页项目为单位；Generate 输出完整文件集合，Edit/Repair 输出可精确回放的 XML `search_replace` patch。
- Edit 是正确 source 到正确 target 的正向变化；Repair 是 defective 到 clean 的修复。隐藏缺陷标签、位置、答案和验收断言不得进入模型输入。
- Image 输入严格按 `input_images` 及角色顺序记录；多页必须保留页面清单与 route/入口/截图映射，不能用截图张数或 HTML 数单独证明页数。
- image-based 只读渲染依赖必须有哈希和 `model_input=false`/`editable=false` 标记，不能成为 patch 或注错目标。
- `candidate`、`basic_pass`、`accepted`、`canonical`、`published` 不能互相推断；正式状态以 release manifest 和运行证据为准。

## 修改与验证

保持现有 schema、模型协议和数据 lineage；不要为局部检查改写数据语义。构造代码、配置、prompt 或数据流程修改后，必须做真实 LLM 的最小端到端样本，并保留实际配置、结果和用量。发布使用 `publish-dataset` skill，未经授权不上传或覆盖远程资产。

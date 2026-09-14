# 训练数据检查策略与实施记录
更新日期：9.13

## 需要确认的内容
1. 格式和modelscope上的0805数据集对齐，因为训练仓库里的训练脚本是针对0805数据格式的。
2. generate；Edit/Repair 多页优先多个 HTML，并保证页数正确。


## 普遍适用
1. Generate多页：接收单HTML（例如SPA的形式）；Edit/Repair母本：多页按物理 `.html`/`.htm` 文件计数。
2. 图像任务只以 `input_images` 作为模型可见图像列表，确认一下当前的训练脚本是否可以接收超过一张图作为输入（目前已经更改了数据适配，已解决）
3. 暂时不做 query—GT的检查。之后如果要做检查的话，六类任务一定要分开来逐个检查，而不是试图一下子用统一的逻辑、脚本进行检查。
4. 上传数据的时候可以优先增量上传（仅适用于补充数据）


## Edit
## Image Edit

模型图像输入：统一读取 `input_images`，兼容 list/str 两种 `instruction`。其中 59 条空 instruction 是允许的目标图输入变体。
但是也可能包含编辑后的截图，所以不包含instruct。不同的形式需要有

## Repair
1. 原6,366条Text/Image Repair已核对官方 `Repair_Instruction_Prompt + N`，9.13合入的1,800条沿用同一公共模板，总计8,166条；其中 `N=len(task_type)`，Image的 `instruction` 与 `repair_instruction` 同步。官方prompt源SHA256为 `5c7da4b2ff292eb2547bdb4b76d316059c432ca1c5c5e9ba6bdba8f9f66ddb83`。（已完成）
2. Edit/Repair 的 source/target 关系与全量 patch 回放。（已完成）
3. Image Edit source图按物理HTML逐页核对；Image Repair defective/clean图按构造时截图范围成对核对。本次新增900组Repair中20组采用affected-pages子集，保留完整源码与原图像输入；全部新增图片引用及哈希核对通过，复用原记录至少一页有差异的证据。（已完成）
### Image Repair 
模型图像输入统一读取 `input_images`：2,517条为current+target，1,400条为current-only（原500条＋本次900条）；current-only不自动追加 `dst_screenshot`。

## 暂时不做（未来再说）

1. Generate 的 query—GT 语义一致性、页面角色、交互和结果覆盖。
2. Edit/Repair任务的patch也存在 query—GT 语义一致性的检查需求



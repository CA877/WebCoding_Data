# 按任务核对 WebCompass

仅在实施相应任务时读取相关源文件/原始记录；不是要求每次下载整个benchmark。

## 1. 官方来源与读取顺序

- [官方数据卡](https://huggingface.co/datasets/NJU-LINK/WebCompass)：配置、split、资产目录。
- [官方代码](https://github.com/NJU-LINK/WebCompass)：对应版本的runner和消息构造。
- 优先使用项目中固定版本的官方副本；检查git版本或下载revision及文件摘要。无法确认版本时标明“本地快照”，不要冒称最新。

| 工作 | 官方数据位置 | 官方实现入口 |
| --- | --- | --- |
| Text Generate | `text/generation/data.jsonl`，config `text-generation/train` | `generation/prompts.py::TEXT_TO_WEB_PROMPT` |
| Image Generate | `image/generation/data.jsonl`，`image/{id}/screenshots/`，config `image-generation/train` | `generation/inference/image_to_web.py::_build_document`、`generation/prompts.py::IMAGE_TO_WEB_PROMPT` |
| Text/Image Edit | `editing/{sp,mp}/data.jsonl`＋`{instance_id}/src/` | `editing_repair/llm/mllm/mllm_chat.py::construct_messages_for_edit`、同目录`prompt.py` |
| Text/Image Repair | `repair/{sp,mp}/data.jsonl`＋`{instance_id}/{src,dst}/` | `mllm_chat.py::construct_messages_for_repair`、`prompt.py::Repair_Instruction_Prompt` |

Text/Image Edit共用editing记录，Repair同理，由mode选择是否加图。数据字段并不等于实际模型输入。

## 2. 已实查的关键实现细节（2026-09-06）

- Edit拼接完整 `Task编号 - task_type: description` 与所有 `src_code`，image模式逐张发送存在的source图，不接收Edit target图。
- Repair只用 `len(description)` 产生N，发送公共11类定义和故障代码；本例description正文不发送。image模式先全部current图，再全部target图，每张附角色和文件名。
- 原始图名可同为 `screenshot_index.jpg`，但分别在src/dst目录；必须按目录＋页面/状态解析，不按basename去重。
- 官方Generate runner的主要格式为“`# 相对文件路径`＋完整代码块”；Edit/Repair为 `<search_replace path="…"><search>…</search><replace>…</replace></search_replace>`。`editing_repair`目录另有Generate XML prompt，不能误当成所有Generation runner的实际格式。项目内部JSON文件列表可保留，接线时明确转换。
- 官方Edit公开记录可有空 `dst_code` 和空 `label_modified_files`；这不是SFT样本允许缺GT。自行构造训练数据仍须生成并保存正确target和答案。
- 修复patch块数可以大于问题数；12个问题可以重复同一缺陷类别。不要通过去重task_type计算N。
- 官方MP本地原始快照：Edit/Repair各150条，每条4HTML；各144条有4张source，6条有3张。Edit dst为空；Repair对应4+4或3+3。全页面是主流，不是每条都完整，也不是每页都必须修改。
- 官方Text Generate样例694按页面内容、交互和视觉组织长需求；Image Generate样例114无内容型instruction，由runner生成通用说明。114主页图确有红蓝彩框和1/2编号。这些只用于理解协议，不复制样例内容造训练数据。

## 3. 本项目约定，不能标成官方硬规定

- 多页按真实页面角色/导航；“主页至少两个入口”是本项目已有资格规则。物理多HTML、优先四页是部分补充批次约束。
- Image Generate覆盖已有GT全部页面，并显式提供入口/动作关系；独立派生记录与父ID是本项目存储策略。
- 同页状态通常两帧，连续步骤至少三帧是当前生产分类；“临时状态”已放宽到稳定可观察的同页变化。
- 不固定所有query长度、截图尺寸/格式、帧水印或像素差阈值；按实际任务和已确认实现处理。不要从单个样本推导全局要求。

## 4. 项目定位与入口

从当前目录向上找包含 `WebCoding_Data` 和 `数据集构造目标细节.md` 的项目根。本机已知根为：

`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft`

换机器时以当前checkout为准，不创建同名空目录或把旧绝对路径当数据源。

- 长期规则：根 `AGENTS.md`。
- 类型详细定义：根 `数据集构造目标细节.md`，仅读当前任务相关章节。
- 数据版本/状态：`validation/docs/data/data_assets_registry.md`、`docs/current_state.md`；批跑与环境细则看项目实际 `docs/operations/batch_jobs.md`、`docs/operations/remote_environment.md`。
- 本地官方代码：`Benchmark_evaluation/WebCompass_official/`，先确认目录存在与版本，不混用不同副本的差异。
- 构造：`reverse/README.md`、`reverse/v2_records.py`；图像派生：`scripts/apply_image_generate_overlays_in_place.py`；最终输入打包：`scripts/repackage_reversed_webcompass_inputs.py`、`scripts/build_0805_aligned_enhanced.py`。
- 已有证据：`docs/reversed_vs_webcompass_six_task_input_gap_audit_20260904.md`、`docs/webcompass_official_repair_screenshot_difference_audit_20260824.md`、`docs/reversed_edit_repair_training_regression_20260906.md`；旧报告的“当前”须与实际版本核对。

本skill创建时直接读取了本地官方SP/MP四份Edit/Repair JSONL、Text/Image Generate记录和主页标注图，并核对上述runner。缓存位于 `/tmp/webcompass_compare/`，可随时失效，不作为skill运行依赖；`WebCompass`代码副本当时HEAD为 `4a0fda3`。无新增API数据生产。

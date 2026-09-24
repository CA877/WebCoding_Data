---
name: publish-dataset
description: 整理、打包、上传或发布 WebCoding 数据集到 ModelScope 等目标仓库，并核验远端文件、索引和哈希；用户未授权具体源版本、目标仓库或覆盖范围时，不执行上传。
---

# 发布数据集

用于“上传数据”“发布数据集”“交付 release”“同步 ModelScope”以及发布后的远端核验。只负责已存在数据的交付，不在本流程中改写数据语义、schema、prompt 或质量结论；如需构造、筛选或字段对齐，转用 `synthesize-data`。

## 发布前必须确认

先读取：

1. 项目根 `AGENTS.md`；
2. `reverse/docs/data_assets_registry.md`；
3. 用户指定 release 的 manifest、README、`dataset_index.json` 和运行报告；
4. 本 skill 相关的上传脚本实现及其 `--help`。

确认以下授权边界后才允许远端写入：

- 源 release 的明确路径、版本和快照；
- 目标仓库 `namespace/name`、目标目录/版本；
- 是否允许覆盖已有路径、替换文件或删除文件；
- 是否为完整发布、增量发布、续传或仅探测上传。

缺少会改变发布对象的信息时，只询问缺项。不要沿用历史仓库、目录、token、覆盖授权或旧 release 的数量假设。

## 本地 release 检查

优先复用现有 release 和索引，不重复打包。发布目录通常包含：

```text
release/
├── README.md
├── dataset_index.json
├── text-generate/*.jsonl.gz
├── text-edit/*.jsonl.gz
├── text-repair/*.jsonl.gz
├── image-generate/{*.jsonl.gz,images/}
├── image-edit/{*.jsonl.gz,images/}
└── image-repair/{*.jsonl.gz,images/}
```

检查：

- 六类任务、分片路径、条数、SHA256、图片根和图片数量与实际文件一致；
- 图片必须是真实文件，不能依赖软链接、外部绝对路径、缓存、临时分片或日志；
- 图片字段全部保留，包括扩展字段如 `target_reference_images`；
- README 说明版本、六类数量、用途、读取方式和兼容差异；
- 只迁移路径时保留 instruction、源码、GT、图片角色/顺序、ID 和 metadata；
- 不因目录兼容而删除数据、统一 prompt、添加 `training_messages` 或改变 schema；
- 修改已有 release 前先备份受影响的分片和索引，转换输出写入新的明确目录。

若使用 `scripts/convert_release_to_legacy_v2_layout.py` 或其他转换器，先阅读其输入格式、图片字段覆盖和路径假设，再做小范围本地验证。

## ModelScope 上传

凭据只能从仓库外受保护文件读取：

- 本机：`/Users/woyaochengweikeyandashen/.config/modelscope/access_token`；
- 物理机：`/home/adminweihunj/.config/modelscope/access_token`。

不要把 token 写入代码、文档、manifest、日志或提交。SDK 产生的 `git_token` 与用户 AccessToken 分开保存；上传脚本的 `--token-file` 使用受保护的 AccessToken 文件。

优先复用 `WebCoding_Data/scripts/upload_0805_combined_modelscope.py` 及已有远端比较逻辑，但不能原样套用于新 release：先核对并参数化旧版的数量、release 身份、默认仓库/前缀、并发度和 prompt 校验。不得为了通过旧校验篡改当前 release。

上传策略：

- 先只读比较远端路径、大小和 SHA256；一致文件跳过；
- 完整发布不得删除远端未授权文件；增量发布只能替换用户明确允许的文件并保留旧记录；
- 先用精确文件列表做单文件试传和哈希验证，再启动有界并发；
- 每个上传单元设置硬超时，保留成功记录、manifest、日志和可续传状态；
- 不对已成功阶段无界重试；鉴权、额度、资源危险和用户取消单独停止；
- 网络/网关临时错误只在现有预算内有界重试，重试原因和结果写入运行记录。

目标 release 若提供专用交付脚本（例如 `deliver_*_modelscope.py`），先运行其 `--prepare` 或只读检查模式，再按脚本的 manifest 和授权参数执行；`--probe-only` 只做试传，不得被当作发布完成。

## 发布后核验与交付

上传结束后：

1. 全量比较远端文件清单、路径、大小和 SHA256；
2. 核对远端 README、索引、分片数量和图片数量；
3. 检查目标仓库没有超出授权范围的替换或删除；
4. 更新远端 README，说明数据版本、主要变化、用途和兼容差异；
5. 保存本地 release、上传 manifest、远端 commit/版本、核验报告和运行目录；
6. 向用户报告源版本、目标仓库/路径、覆盖范围、实际文件/字节数量、跳过数量、远端版本和任何未核验边界。

“上传命令返回成功”不能替代远端清单和哈希核验。若单个文件失败，保留已成功文件和失败证据并提供续传入口；只有鉴权/额度、数据损坏、资源危险或用户取消等系统性问题才暂停整批。

---
name: publish-dataset
description: 打包、核对或发布现有 WebCoding 数据集到用户指定目标时使用；不用于修改数据语义、prompt 或训练 schema。
---

# Publish Dataset

先读取 [发布运行手册](../../../docs/operations/publishing.md)、[数据资产登记](../../../validation/docs/data/data_assets_registry.md)和目标 release 的 manifest。确认用户授权的源版本、目标仓库、目标路径和覆盖范围后，再执行任何上传。

保留记录语义、schema、图片角色和现有数据；需要字段或 prompt 对齐时转用 `synthesize-data`。发布后核验文件清单、索引、哈希与远端结果，并报告版本、目标和兼容边界。

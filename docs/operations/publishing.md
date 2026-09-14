# 数据集发布运行手册

本手册描述数据集打包、0805 兼容布局、ModelScope 上传和发布后核验。发布当前状态和具体目标以当次 release、manifest 与用户授权为准。

# WebCoding 数据交付

交付目标：数据按0805目录组织，用户指定版本上传到指定ModelScope数据仓库及路径，上传后有可核验的文件清单和结果。

## 1. 确定本次交付对象

- 项目本地根：`/Users/woyaochengweikeyandashen/Documents/codes_vsc/web_coding_sft`。
- 先读项目 `AGENTS.md` 与 `docs/README.md`。
- 原始0805目录参照位于物理机：`/data1/xieqianqian/webcoding/WebCoding_Data/releases/webcoding_sft_v2_20260805_compatible`。
- 物理机连接入口：`ssh -p 65022 adminweihunj@36.213.175.38`；


## 2. 对齐0805目录

```text
<release>/
├── README.md
├── dataset_index.json
├── text-generate/train-00000-of-00001.jsonl.gz
├── text-edit/train-00000-of-00001.jsonl.gz
├── text-repair/train-00000-of-00001.jsonl.gz
├── image-generate/
│   ├── train-00000-of-00001.jsonl.gz
│   └── images/...
├── image-edit/
│   ├── train-00000-of-00001.jsonl.gz
│   └── images/...
└── image-repair/
    ├── train-00000-of-00001.jsonl.gz
    └── images/...
```

- 六任务目录、每类单个gzip JSONL分片、图片位于对应任务的`images/`。保留必要的版本报告，不把“目录对齐”理解为必须删除其他说明文件。
- 图片字段中的`images/...`相对当前任务目录解析；保留所有实际使用的图片字段，包括扩展的`target_reference_images`，不能只改三个旧字段而漏掉新增字段。
- 交付包含真实图片文件，不能依赖机器上的软链接或外部绝对路径。目标目录只放交付文件，排除凭据、缓存、临时分片、日志目录和备份。
- README说明版本、六类数量、用途、读取方式和已知兼容差异；索引中的分片路径、数量、SHA256、图片根及已维护的图片数量与实际文件一致。
- **目录对齐不授权修改记录语义或schema。** 保留原instruction类型、需求、源码、GT、图片角色/顺序、ID和metadata；不自行增加`training_messages`或统一prompt。路径迁移只调整对应引用，并核对文件内容哈希。
- 如还要求字段或prompt对齐，另按该任务范围使用`synthesize-data`；不把它混进默认交付步骤。字段与0805有差异时列出兼容说明，不擅自删数据或转字段。

### 打包与最小验证

1. 已符合目录时直接复用，不重复打包。需要转换时输出到新的明确目录，保留原数据；改已有release前先备份受影响分片和索引。
2. 复用项目现有转换、索引和验证工具。`scripts/convert_release_to_legacy_v2_layout.py`用于`jsonl/<task>.jsonl`＋`assets/...`输入；使用前核对其图片字段覆盖和路径假设是否适合当前版本。


## 3. 上传ModelScope

- AccessToken从仓库外受保护文件读取：本机`/Users/woyaochengweikeyandashen/.config/modelscope/access_token`，物理机`/home/adminweihunj/.config/modelscope/access_token`；目录700、文件600。文档和代码仅记录路径。SDK生成的`git_token`与用户AccessToken分开保存，上传入口的`--token-file`使用后者。
- 执行上传前必须确定用户授权的源release、ModelScope数据仓库`namespace/name`、目标目录/版本，以及本次是否覆盖已有路径。已明确给出的信息不重复询问；缺少会改变发布对象的信息时只问缺项。
- 不沿用历史仓库、目录或上传授权。优先独立版本目录；目标已存在时先只读比较，未获明确覆盖授权不得覆盖、删除或清理远端文件。
- 优先复用`WebCoding_Data/scripts/upload_0805_combined_modelscope.py`及其已有上传/远端比较逻辑，但**不得原样直接套用新版本**：该脚本含旧版EXPECTED_COUNTS、release身份限制、默认仓库/前缀、32 workers及旧prompt校验。先读实现，按当次release参数化或做最小适配，在本地测试后同步；不要为了通过旧校验而篡改新包prompt或身份。


## 4. 核验并交付
上传到modelscope之后，应当更新modelscope上的readme文档，说清楚当前数据版本以及基本特点，例如补充了什么数据、删除了什么数据等。

### 0905多页补量增量入口（2026-09-13）

`scripts/deliver_0905_modelscope.py --prepare`核对39,845条六类分片并生成发布manifest/README/索引；上传使用`--incremental --resume-authorized --previous-manifest <上次发布manifest>`。只允许替换四个Edit/Repair分片及README/索引、追加本批内容寻址图片，旧文件必须保留。按云端路径/大小/SHA256跳过已一致文件，先通过相同精确文件列表路径单图上传及哈希验证，再按256文件/8并发增量上传，最后更新README/索引并全量核验远端。每上传单元900秒硬超时，无整批总时限；监控须持续更新工作目录的`monitor.lease`（150秒失联保护）。`--probe-only`仅执行单图试传后退出；续跑再次比较远端，保留已成功文件。

初版11项测试通过；更新AccessToken后真实单图精确列表上传与远端SHA256验证通过，8并发路径亦完成真实单图验证。API按远程环境手册清除代理，保持TLS校验；凭据从受保护文件读取。现场进展见`current_state.md`。

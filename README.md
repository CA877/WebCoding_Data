# WebCode2M 训练集构造

基于 WebCode2M 数据集构造七类 Web Coding 训练样本。

## 流程概览

```
原始数据 (HuggingFace xcodemind/webcode2m)
    │
    ▼  下载样本 (参见 preprocess/WebCode2M_10条样本下载方法.md)
    │
preprocess/webcode2m_clean_pipeline.py
    │  ─ 去除外链和远程渲染依赖
    │  ─ 下载可用资源 / 生成本地 SVG 占位符
    │  ─ 去除追踪脚本和噪音标签
    │  ─ 调用官方 WebCode2M purification
    │  ─ 爬取真实站内子页，扩展为多页项目
    │  ─ 确保离线可渲染、无裂图
    ▼
清洁的多页项目 (local_trials/webcode2m_official_multipage_10/)
    │
    ▼
construct/construct_webcode2m_dataset.py
    │  ─ text-generation:   VLM 生成 PRD 文档作为指令
    │  ─ image-generation:  多视口截图作为指令
    │  ─ video-generation:  录制人类交互视频作为指令
    │  ─ text-editing:      LLM 合成编辑需求 + search/replace 实现
    │  ─ image-editing:     在 text-editing 基础上截图
    │  ─ text-repair:       反向注入缺陷 + 修复标签
    │  ─ image-repair:      在 text-repair 基础上截图
    ▼
训练集 (local_trials/webcode2m_formal_7x10_ppapi_smoke/)
    7 类 × 10 条 = 70 条已验证样本
```

## 清洗质量要求

- 零远程渲染依赖 (remote_hit_count = 0)
- 无裂图 — 图片本地化或使用 SVG 占位符
- 无追踪/噪音 — analytics, ads, tracking pixel, dns-prefetch 全部移除
- 代码量合理 — 不内联巨型 base64，不保留 CMS 模板噪音
- 无 provenance 泄漏 (provenance_hit_count = 0)

详细清洗策略见 [preprocess/CLEANING_GUIDE.md](preprocess/CLEANING_GUIDE.md)。

## 快速上手

### 1. 环境准备

```bash
cp .env.example .env
# 编辑 .env 填入 API key 和 base_url
pip install playwright beautifulsoup4 python-dotenv
playwright install chromium
```

### 2. 清洗样本

```bash
python3 preprocess/webcode2m_clean_pipeline.py \
  --input raw_samples.jsonl \
  --output local_trials/webcode2m_official_multipage_10
```

### 3. 构造七类任务 (smoke 10 条)

```bash
python3 construct/construct_webcode2m_dataset.py \
  --input-dir local_trials/webcode2m_official_multipage_10 \
  --output-dir local_trials/webcode2m_formal_7x10_ppapi_smoke
```

### 4. 验证

```bash
python3 construct/validate_webcode2m_task_dirs.py \
  --root local_trials/webcode2m_formal_7x10_ppapi_smoke \
  --expected-per-task 10
```

## 目录结构

```
.
├── README.md
├── AGENTS.md                    # Agent 工作原则
├── .env.example                 # API 凭据模板
├── preprocess/
│   ├── webcode2m_clean_pipeline.py   # 清洗主脚本
│   ├── CLEANING_GUIDE.md             # 清洗策略文档
│   └── WebCode2M_10条样本下载方法.md  # 样本获取方法
├── construct/
│   ├── construct_webcode2m_dataset.py  # 七类任务构造入口
│   ├── construct_common.py             # 共享工具库 (VLM/LLM, 截图, 合成器)
│   ├── construct_text_generation.py    # text-generation 构造
│   ├── construct_image_generation.py   # image-generation 构造
│   ├── construct_video_generation.py   # video-generation 构造
│   ├── construct_text_editing.py       # text-editing 构造
│   ├── construct_image_editing.py      # image-editing 构造
│   ├── construct_text_repair.py        # text-repair 构造
│   ├── construct_image_repair.py       # image-repair 构造
│   ├── human_like_playwright_record.py # 人类交互视频录制
│   └── validate_webcode2m_task_dirs.py # 输出验证器
├── local_trials/
│   ├── webcode2m_official_multipage_10/      # 清洗后的输入项目
│   └── webcode2m_formal_7x10_ppapi_smoke/   # 验证通过的 smoke 输出
└── WebCompass评测代码/                        # WebCompass 评测框架 (独立)
```

## 模型配置

在 `.env` 中配置:

| 变量 | 用途 | 当前值 |
|------|------|--------|
| TEXT_MODEL | 文本 LLM (editing/repair) | qwen3.7-max |
| VISION_MODEL | 视觉模型 (PRD 生成) | qwen3-vl-235b-a22b-instruct |
| API_BASE_URL | API endpoint | https://app-hk.ppapi.ai/v1 |
| API_KEY | API 密钥 | (本地配置) |

## 凭据和数据

不要提交 API key、`.env`、生成结果截图/视频或日志。

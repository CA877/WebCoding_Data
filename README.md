# WebCoding_Data — 70K Web Coding 训练集构造

基于 WebRenderBench + WebCode2M 构造七类 Web Coding 训练样本，目标刷 4 个榜单：WebCompass、Design2Code、Vision2Web、FLAME-VLM-Code。

## 流程概览

```
数据获取与清洗 (preprocess/)
  │
  ├─ WebRenderBench 31,765 个 MHTML 快照
  │    → expand（扩展为多页）
  │    → clean（图片本地化、去噪、中和外链）
  │    → add_js（LLM 生成 Vanilla JS）
  │    → validate（Console 错误检查）
  │
  ├─ WebCode2M 域名重爬
  │    → extract_webcode2m_urls.py（提取域名 URL）
  │    → crawl（Playwright 爬取，自带 clean + JS 保留）
  │    → validate（Console 错误检查）
  │
  ▼
清洁的自包含项目 (~70K 个，含 HTML + CSS + JS + resources/)
  │
  ▼
任务构造 (construct/)
  │
  ├─ text-generation:   VLM 生成 PRD 文档作为指令
  ├─ image-generation:  多视口截图作为指令
  ├─ video-generation:  录制人类交互视频作为指令
  ├─ text-editing:      LLM 合成编辑需求 + search/replace 实现
  ├─ image-editing:     在 text-editing 基础上截图
  ├─ text-repair:       反向注入缺陷 + 修复标签
  └─ image-repair:      在 text-repair 基础上截图
  │
  ▼
训练集: 7 类 × 10K = 70K 样本
```

## 快速上手

### 1. 环境准备

```bash
cp .env.example .env
# 编辑 .env 填入 API key、base_url、model
pip install playwright beautifulsoup4 python-dotenv openai Pillow
playwright install chromium
```

### 2. 预处理（以 WebRenderBench 为例）

```bash
# 扩展为多页
python3 preprocess/playwright_crawl.py \
  --browser-proxy "socks5://PROXY" \
  --requests-proxy "socks5h://PROXY" \
  --max-pages 4 --concurrency 5 \
  expand --input-dir /data/webrenderbench/ --output-dir /data/expanded/

# 清洗
python3 preprocess/playwright_crawl.py \
  --requests-proxy "socks5h://PROXY" --concurrency 10 \
  clean --input-dir /data/expanded/

# 添加 JS（WebRenderBench 专用，用 LLM 生成）
python3 construct/add_js.py \
  --input-dir /data/expanded/ --output-dir /data/expanded_with_js/ --concurrency 5

# 验证 Console 错误
python3 preprocess/playwright_crawl.py --concurrency 5 \
  validate --input-dir /data/expanded_with_js/
```

### 3. 构造七类任务

```bash
python3 construct/construct_webcode2m_dataset.py \
  --input-dir /data/all_clean_projects/ \
  --output-dir /data/70k_dataset/ \
  --limit 10000
```

### 4. 验证

```bash
python3 construct/validate_webcode2m_task_dirs.py \
  --root /data/70k_dataset/ \
  --expected-per-task 10000
```

## 目录结构

```
.
├── preprocess/
│   ├── playwright_crawl.py              # 主力脚本（crawl/expand/clean/validate）
│   ├── extract_webcode2m_urls.py        # 从 WebCode2M 提取域名 URL
│   └── README.md                        # 预处理详细文档
├── construct/
│   ├── construct_webcode2m_dataset.py   # 七类任务构造入口
│   ├── construct_common.py              # 共享工具库
│   ├── construct_text_generation.py     # text-generation
│   ├── construct_image_generation.py    # image-generation
│   ├── construct_video_generation.py    # video-generation
│   ├── construct_text_editing.py        # text-editing
│   ├── construct_image_editing.py       # image-editing
│   ├── construct_text_repair.py         # text-repair
│   ├── construct_image_repair.py        # image-repair
│   ├── add_js.py                        # LLM 生成 Vanilla JS
│   ├── human_like_playwright_record.py  # 视频录制
│   └── validate_webcode2m_task_dirs.py  # 输出验证器
├── .env.example                         # API 凭据模板
├── AGENTS.md                            # 工作原则 + 服务器信息
├── CLAUDE.md                            # Claude 指令
└── 数据构造规划.md                        # 完整构造规划
```

## 模型配置

在 `.env` 中配置：

| 变量 | 用途 |
|------|------|
| `OPENAI_API_KEY` | API 密钥 |
| `OPENAI_BASE_URL` | API endpoint |
| `OPENAI_MODEL` | 文本 LLM（editing/repair/add_js） |
| `VISION_OPENAI_API_KEY` | 视觉模型 API 密钥（可选，默认同上） |
| `VISION_OPENAI_BASE_URL` | 视觉模型 endpoint（可选，默认同上） |
| `VISION_MODEL` | 视觉模型（PRD 生成） |

## 凭据和数据

不要提交 API key、`.env`、生成结果截图/视频或日志。

详细构造规划见 [数据构造规划.md](数据构造规划.md)。

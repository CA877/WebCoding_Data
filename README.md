# WebCoding Data

这个目录存放 WebCoding / WebCompass 风格训练数据的构造脚本和方案文档。

当前主线不是“补齐七套脚本”，而是按决策价值整理为 5 条底层构造线：

1. `text-generation`
2. `image-generation`
3. `video-generation`
4. editing pair，派生 `text-editing` / `image-editing`
5. repair pair，派生 `text-repair` / `image-repair`

详细方案见：

- `TRAINSET_REVERSE_CONSTRUCTION_GUIDE.md`

## 目录说明

```text
WebCoding_Data/
  README.md
  TRAINSET_REVERSE_CONSTRUCTION_GUIDE.md
  .env.example
  prepare_webrender_pools.py
  human_like_playwright_record.py
  validate_render.py
  validate_render_relaxed.js
  preprocess/
    generate_webrender_full.py
    rescue_inline_assets.py
```

主要文件：

- `prepare_webrender_pools.py`：合并 WebRenderBench train/test，并为 `text`、`image`、`video` generation 划分互不重合的 clean project 池。
- `preprocess/generate_webrender_full.py`：当前 text/image/video generation 的主参考脚本；会输出 JSONL manifest 和截图/视频 assets。
- `human_like_playwright_record.py`：更接近人类浏览路径的视频录制参考，可用于复杂交互样本增强。
- `validate_render.py` / `validate_render_relaxed.js`：页面渲染检查工具。
- `preprocess/rescue_inline_assets.py`：资源修复辅助脚本。

## 凭据和数据

不要提交 API key、云盘密码、`.env`、生成结果、截图、视频或日志。

运行时凭据放在本地 `.env` 中，可以从示例复制：

```bash
cp WebCoding_Data/.env.example WebCoding_Data/.env
```

如需使用 HuggingFace、npm、Playwright 等外部资源，优先配置中国镜像。

## Generation 快速 smoke

先准备互不重合的数据池：

```bash
python WebCoding_Data/prepare_webrender_pools.py \
  --train-dir /path/to/train_webpages \
  --test-dir /path/to/test_webpages \
  --output WebCoding_Data/output/trainset_v1/selected_pools.json \
  --link-root WebCoding_Data/output/trainset_v1/pools \
  --target-per-task 10000 \
  --seed 506
```

每类先跑 10 条，不要直接扩到 10k：

```bash
python WebCoding_Data/preprocess/generate_webrender_full.py \
  --page_dirs WebCoding_Data/output/trainset_v1/pools/text \
  --output_dir WebCoding_Data/output/trainset_v1/generation/text_smoke \
  --task text \
  --limit 10
```

```bash
python WebCoding_Data/preprocess/generate_webrender_full.py \
  --page_dirs WebCoding_Data/output/trainset_v1/pools/image \
  --output_dir WebCoding_Data/output/trainset_v1/generation/image_smoke \
  --task image \
  --limit 10
```

```bash
python WebCoding_Data/preprocess/generate_webrender_full.py \
  --page_dirs WebCoding_Data/output/trainset_v1/pools/video \
  --output_dir WebCoding_Data/output/trainset_v1/generation/video_smoke \
  --task video \
  --limit 10
```

输出仍是中间格式：

```text
text_generation.jsonl
image_generation.jsonl
video_generation.jsonl
manifest_text.jsonl
manifest_image.jsonl
manifest_video.jsonl
assets/
```

正式 SFT 数据建议再转换为 `info.json + src/dst + input_screenshots/input_videos` 的目录结构，具体 schema 见 `TRAINSET_REVERSE_CONSTRUCTION_GUIDE.md`。

## 当前缺口

1. generation 需要补 JSONL/assets 到最终目录格式的转换器，或直接改脚本落目录。
2. editing 需要把 `web_coding_demo/synthetic/edit.py` 的 description 生成升级为“生成并应用 search/replace patch”。
3. repair 需要把 `web_coding_demo/synthetic/repair.py` 接入 WebRenderBench clean project，并统一输出 schema。
4. 所有构造都要先 10 条人工抽检，再扩 1k，最后才考虑 10k。

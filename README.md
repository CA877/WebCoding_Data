# WebCoding Data

这个仓库只放 WebCoding / WebCompass generate 任务的数据合成代码。

代码来源包括两部分：

- 从 `CA877/WebCodingSft` 拆出来的原始 `data_pipeline` 构造脚本。
- 针对 WebRenderBench 重新实现的全项目逆向构造 pipeline。

## 目录说明

- `data_pipeline/batch_generate.py`：原始批量逆向构造入口。
- `data_pipeline/image_reverse.py`：截图逆向构造相关工具。
- `data_pipeline/video_generate.py`：视频和帧序列逆向构造相关工具。
- `data_pipeline/validate_render.py`：基于 Playwright 的页面渲染检查工具。
- `data_pipeline/prepare_webrender_pools.py`：合并 WebRenderBench train/test，并划分 text/image/video 三个互不重合的数据池。
- `data_pipeline/generate_webrender_full.py`：最新 WebRenderBench 全项目构造脚本，用于生成 text、image、video 三类 generate 任务。
- `docs/0506.md`：任务理解、构造策略和阶段性记录。

## 凭据和数据

不要把 API key、云盘密码、`.env`、生成结果、截图、视频或日志提交到仓库。

运行时凭据放在本地 `.env` 中，可以从 `.env.example` 复制一份再填写：

```bash
cp .env.example .env
```

生成结果默认写到 `data_pipeline/output/`，该目录已经被 `.gitignore` 忽略。

## 最新构造策略

目标是生成三类 generate 任务，每类 10k，总计 30k：

- `text`：用 Playwright 截取一个原始项目的全部 HTML 页面，覆盖 desktop/tablet/mobile 三种视口；再用可读图模型生成 WebCompass 风格的完整 PRD / instruction。
- `image`：用 Playwright 截取一个原始项目的全部 HTML 页面，保留完整截图作为视觉任务输入，不转文字。
- `video`：用 Playwright 对每个 HTML 页面滚动录屏，尽量覆盖完整页面。

三类任务使用互不重合的原始项目。候选池同时使用 WebRenderBench 的 train 和 test 两部分。

## 准备 30k 数据池

先把 train/test 合并并划分为三个互不重合的池：

```bash
python -m data_pipeline.prepare_webrender_pools \
  --train-dir /path/to/train_webpages \
  --test-dir /path/to/test_webpages \
  --output data_pipeline/output/generate_30k_v2/selected_pools.json \
  --link-root data_pipeline/output/generate_30k_v2/pools \
  --target-per-task 10000 \
  --seed 506
```

执行后会得到：

```text
data_pipeline/output/generate_30k_v2/pools/text
data_pipeline/output/generate_30k_v2/pools/image
data_pipeline/output/generate_30k_v2/pools/video
```

这三个目录是 symlink pool，可以分别作为后续构造脚本的输入。

## 运行构造

text-based：

```bash
python -m data_pipeline.generate_webrender_full \
  --page_dirs data_pipeline/output/generate_30k_v2/pools/text \
  --output_dir data_pipeline/output/generate_30k_v2/text \
  --task text
```

vision/image-based：

```bash
python -m data_pipeline.generate_webrender_full \
  --page_dirs data_pipeline/output/generate_30k_v2/pools/image \
  --output_dir data_pipeline/output/generate_30k_v2/image \
  --task image
```

video-based：

```bash
python -m data_pipeline.generate_webrender_full \
  --page_dirs data_pipeline/output/generate_30k_v2/pools/video \
  --output_dir data_pipeline/output/generate_30k_v2/video \
  --task video
```

小规模测试时可以加 `--limit`：

```bash
python -m data_pipeline.generate_webrender_full \
  --page_dirs data_pipeline/output/generate_30k_v2/pools/text \
  --output_dir data_pipeline/output/generate_30k_v2/text_smoke \
  --task text \
  --limit 5
```

## 输出

每类任务会生成对应 JSONL 和 manifest：

```text
text/text_generation.jsonl
text/manifest_text.jsonl
image/image_generation.jsonl
image/manifest_image.jsonl
video/video_generation.jsonl
video/manifest_video.jsonl
```

截图和视频会保存在对应输出目录的 `assets/` 下。所有这些生成产物都不进入 git。

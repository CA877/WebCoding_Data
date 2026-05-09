# WebCoding Data

Data construction code for WebCoding/WebCompass-style generation tasks.

This repository is intentionally scoped to data synthesis only. It contains the original `data_pipeline` scripts from `CA877/WebCodingSft` plus the WebRenderBench full-project reverse-construction pipeline.

## Contents

- `data_pipeline/batch_generate.py`: original batch reverse-construction entry point.
- `data_pipeline/image_reverse.py`: screenshot-based reverse construction utilities.
- `data_pipeline/video_generate.py`: video/frame-based reverse construction utilities.
- `data_pipeline/validate_render.py`: Playwright render validation utilities.
- `data_pipeline/prepare_webrender_pools.py`: combines WebRenderBench train/test projects and creates non-overlapping text/image/video pools.
- `data_pipeline/generate_webrender_full.py`: WebRenderBench full-project pipeline for text, image, and video generate tasks.
- `docs/0506.md`: task notes and construction plan.

## Secrets

Do not commit API keys, cloud-disk passwords, generated data, screenshots, videos, or logs. Put runtime credentials in a local `.env` file copied from `.env.example`.

## WebRenderBench Full-Project Pipeline

The full-project pipeline treats each original website/project as one sample and covers all HTML pages in that project.

Prepare non-overlapping 10k pools for text, image, and video:

```bash
python -m data_pipeline.prepare_webrender_pools \
  --train-dir /path/to/train_webpages \
  --test-dir /path/to/test_webpages \
  --output data_pipeline/output/generate_30k_v2/selected_pools.json \
  --link-root data_pipeline/output/generate_30k_v2/pools \
  --target-per-task 10000 \
  --seed 506
```

Then run each task against its own symlink pool:

```bash
python -m data_pipeline.generate_webrender_full \
  --page_dirs data_pipeline/output/generate_30k_v2/pools/text \
  --output_dir data_pipeline/output/generate_30k_v2/text \
  --task text \
  --limit 10
```

Supported tasks:

- `text`: full-page screenshots across desktop/tablet/mobile are sent to a vision-language model to produce a WebCompass-style PRD/instruction.
- `image`: full-page screenshots across all pages and viewports are saved as the task ground truth.
- `video`: Playwright records each HTML page while scrolling through the full page.

Generated outputs are ignored by git under `data_pipeline/output/`.

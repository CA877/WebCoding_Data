#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT=/data2/adminweihunj/webcoding/WebCoding_Data/runs/online_mothers_3000_20260908
TASK_CODE="$TASK_ROOT/code"
TASK_PYTHON=/data1/xieqianqian/webcoding/WebCoding_Data/web-coding-agent/.conda/lora/bin/python
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export PYTHONPATH="$TASK_CODE:$TASK_CODE/.deps"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1
cd "$TASK_CODE"
exec "$TASK_PYTHON" -m crawl.pipeline_mothers.main \
  --urls "$TASK_ROOT/url_queue_v1/urls.txt" --output "$TASK_ROOT/batch" \
  --qwen-tokenizer /data1/xieqianqian/webcoding/WebCoding_Data/.cache/qwen3-tokenizer.json \
  --limit 86269 --target 1000 --workers 8 --child-attempts 12 \
  --context-policy image_render_assisted --render-only-min-bytes 100000 \
  --site-timeout 360 --total-timeout 0 --wait-ms 1000 \
  --browser-proxy http://127.0.0.1:17897 "$@"

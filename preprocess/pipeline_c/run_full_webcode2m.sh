#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

: "${KIMI_API_KEY:?KIMI_API_KEY must be set for the official visual gate}"

PYTHON_BIN="${PYTHON_BIN:-/data1/xieqianqian/webcoding/venv/bin/python}"
RUN_ROOT="${RUN_ROOT:-runs/pipeline_c_webcode2m_full_20260723}"
URLS="${URLS:-webcode2m_all_urls.txt}"
TOKENIZER="${QWEN_TOKENIZER_JSON:-.cache/qwen3-tokenizer.json}"

export KIMI_BASE_URL="${KIMI_BASE_URL:-https://api.moonshot.cn/v1}"
export VISION_MODEL="${VISION_MODEL:-moonshot-v1-128k-vision-preview}"
export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
export SSL_NO_VERIFY="${SSL_NO_VERIFY:-1}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONPATH=".deps/qwen_tokenizers:.:${PYTHONPATH:-}"

mkdir -p "$RUN_ROOT"

/usr/bin/time -f 'PIPELINE_WALL_SEC=%e' \
  "$PYTHON_BIN" -m preprocess.pipeline_c.main \
    --urls "$URLS" \
    --output "$RUN_ROOT/output" \
    --browser-proxy http://127.0.0.1:7890 \
    --qwen-tokenizer "$TOKENIZER" \
    --max-training-code-tokens 40000 \
    --max-child-pages 0 \
    --site-timeout 120 \
    --sample-preflight \
    --preflight-timeout 12 \
    --workers 16 \
    --visual-review \
    --exclude-render-bundles \
    2>&1 | tee -a "$RUN_ROOT/pipeline.log"

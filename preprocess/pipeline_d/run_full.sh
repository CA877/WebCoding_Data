#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

PYTHON_BIN="${PYTHON_BIN:-/data1/xieqianqian/webcoding/venv/bin/python}"
URLS="${URLS:-datasets/pipeline_c/webcode2m_filtered_urls_86740.txt}"
RUN_ROOT="${RUN_ROOT:-runs/pipeline_d_direct_full_20260724}"
TOKENIZER="${QWEN_TOKENIZER_JSON:-.cache/qwen3-tokenizer.json}"
TARGET_PASSES="${TARGET_PASSES:-0}"

export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
export SSL_NO_VERIFY="${SSL_NO_VERIFY:-1}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

mkdir -p "$RUN_ROOT"
"$PYTHON_BIN" -m preprocess.pipeline_d.main \
  --urls "$URLS" \
  --output "$RUN_ROOT/output" \
  --browser-proxy http://127.0.0.1:7890 \
  --workers 16 \
  --wait-ms 3000 \
  --site-timeout 120 \
  --qwen-tokenizer "$TOKENIZER" \
  --max-code-tokens 40000 \
  --target-passes "$TARGET_PASSES" \
  2>&1 | tee -a "$RUN_ROOT/pipeline.log"

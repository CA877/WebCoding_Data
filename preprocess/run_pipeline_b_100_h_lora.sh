#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"
PROJECT_DIR="$ROOT/WebCoding_Data"
DATASET_DIR="$ROOT/datasets"
INPUT_URLS="${INPUT_URLS:-$DATASET_DIR/webcode2m_preflight_passed_urls.txt}"
RUN_NAME="${RUN_NAME:-pipeline_b_100_lora_$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="$DATASET_DIR/$RUN_NAME"
URL_FILE="$RUN_DIR/webcode2m_preflight_passed_urls_100.txt"
LOG_DIR="$RUN_DIR/logs"

mkdir -p "$RUN_DIR" "$LOG_DIR"
head -n 100 "$INPUT_URLS" > "$URL_FILE"

set +u
source ~/.bashrc >/dev/null 2>&1 || true
set -u
conda activate lora

cd "$PROJECT_DIR"

PROXY="${BROWSER_PROXY:-${https_proxy:-${http_proxy:-}}}"
REQUESTS_PROXY_VALUE="${REQUESTS_PROXY:-${https_proxy:-${http_proxy:-}}}"

{
  echo "run_name=$RUN_NAME"
  echo "started_at=$(date -Is)"
  echo "project_dir=$PROJECT_DIR"
  echo "input_urls=$URL_FILE"
  echo "output_dir=$RUN_DIR/crawled"
  echo "python=$(which python)"
  python --version
  echo "proxy=$PROXY"

  python preprocess/playwright_crawl.py \
    --browser-proxy "$PROXY" \
    --requests-proxy "$REQUESTS_PROXY_VALUE" \
    --max-pages 4 \
    --wait 3000 \
    --concurrency 20 \
    --site-timeout 90 \
    crawl \
    --url-file "$URL_FILE" \
    --output-dir "$RUN_DIR/crawled"

  python preprocess/playwright_crawl.py \
    --concurrency 10 \
    --site-timeout 90 \
    validate \
    --input-dir "$RUN_DIR/crawled"

  echo "finished_at=$(date -Is)"
} 2>&1 | tee "$LOG_DIR/pipeline_b.log"

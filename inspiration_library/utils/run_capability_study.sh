#!/usr/bin/env bash
# 能力抽取对比研究的运行入口（在物理机上执行）。
#
# 三个数据集共用同一个抽取器与 adapter：
#   webchain            95 条（100 条子集中 5 条无 axTree）
#   webworld_autonomous 100 条
#   webworld_random     100 条
#
# 用法：
#   bash inspiration_library/utils/run_capability_study.sh pilot          # 10 条，验证链路与卡片质量
#   bash inspiration_library/utils/run_capability_study.sh full           # 全量 295 条
#   bash inspiration_library/utils/run_capability_study.sh dry            # 只做转换与证据统计，不调 LLM
#   bash inspiration_library/utils/run_capability_study.sh summarize      # 汇总已有结果
#   bash inspiration_library/utils/run_capability_study.sh breadth        # 量交互广度（纯结构，不调 LLM）
#   bash inspiration_library/utils/run_capability_study.sh candidates     # 抓候选池 axTree 并量广度
#      候选池由本地生成后同步到 $STUDY/data/webchain/（全量 raw 只在本地），
#      用 CAND_NAME 指定池名，默认 candidates_48
#
# 可用环境变量覆盖：REPO STUDY VENV WORKERS API_TIMEOUT CAND_NAME

set -euo pipefail

MODE="${1:-pilot}"

REPO="${REPO:-/data2/adminweihunj/webcoding/inspiration_library/code_debug_20260914}"
STUDY="${STUDY:-/data2/adminweihunj/webcoding/dataset_capability_study_20260914}"
VENV="${VENV:-$STUDY/venv}"
WORKERS="${WORKERS:-6}"
API_TIMEOUT="${API_TIMEOUT:-300}"

PY="$VENV/bin/python"
RUN_ID="$(date +%Y%m%d_%H%M)"
OUT_DIR="$STUDY/runs/capability_study/$MODE"
LOG_DIR="$STUDY/logs/capability_study/${MODE}_${RUN_ID}"
mkdir -p "$OUT_DIR" "$LOG_DIR"

if [ "$MODE" = "dry" ]; then
  OUT_DIR="$STUDY/runs/capability_study/dry"
  LOG_DIR="$STUDY/logs/capability_study/dry_${RUN_ID}"
  mkdir -p "$OUT_DIR" "$LOG_DIR"
fi

cd "$REPO"

if [ "$MODE" = "pilot" ]; then
  PILOT_DIR="$STUDY/data/pilot"
  echo "选 pilot 样本 -> $PILOT_DIR"
  "$PY" inspiration_library/utils/select_capability_study_pilot.py \
    --webchain-subset "$STUDY/data/webchain/subset_100.jsonl" \
    --axtrees-dir "$STUDY/data/webchain/axtrees" \
    --webworld-autonomous "$STUDY/data/webworld/autonomous_100.jsonl" \
    --webworld-random "$STUDY/data/webworld/random_100.jsonl" \
    --out-dir "$PILOT_DIR" --n-webchain 4 --n-webworld 3 \
    | tee "$LOG_DIR/pilot_selection.json"
  WC_IN="$PILOT_DIR/webchain_pilot.jsonl"
  AUTO_IN="$PILOT_DIR/webworld_autonomous_pilot.jsonl"
  RAND_IN="$PILOT_DIR/webworld_random_pilot.jsonl"
elif [ "$MODE" = "full" ] || [ "$MODE" = "dry" ]; then
  WC_IN="$STUDY/data/webchain/subset_100.jsonl"
  AUTO_IN="$STUDY/data/webworld/autonomous_100.jsonl"
  RAND_IN="$STUDY/data/webworld/random_100.jsonl"
else
  if [ "$MODE" != "summarize" ] && [ "$MODE" != "breadth" ] && [ "$MODE" != "candidates" ]; then
    echo "unknown mode: $MODE" >&2
    exit 2
  fi
fi

if [ "$MODE" = "candidates" ]; then
  CAND_NAME="${CAND_NAME:-candidates_48}"
  POOL="$STUDY/data/webchain/$CAND_NAME.jsonl"
  if [ ! -f "$POOL" ]; then
    echo "missing candidate pool: $POOL（本地生成后同步过来）" >&2
    exit 2
  fi
  echo "pool $POOL ($(wc -l < "$POOL") 条)"
  "$PY" inspiration_library/utils/fetch_webchain_axtrees.py --subset "$POOL" \
    --out-dir "$STUDY/data/webchain/axtrees_$CAND_NAME" \
    --concurrency 8 --retries 3 --timeout 90 2>&1 | tee "$LOG_DIR/fetch.log"
  "$PY" inspiration_library/utils/measure_webchain_interaction_breadth.py --subset "$POOL" \
    --axtrees-dir "$STUDY/data/webchain/axtrees_$CAND_NAME" \
    --out "$STUDY/runs/capability_study/breadth/$CAND_NAME.jsonl" 2>&1 | tee "$LOG_DIR/breadth.log"
  exit 0
fi

if [ "$MODE" = "summarize" ]; then
  "$PY" inspiration_library/utils/summarize_capability_study.py --runs-dir "$STUDY/runs/capability_study" \
    --out-dir "$STUDY/runs/capability_study/report" 2>&1 | tee "$LOG_DIR/summarize.log"
  exit 0
fi

if [ "$MODE" = "breadth" ]; then
  # 纯结构指标：从已有 axTree 里数「唤醒了多少种交互 / 漏掉多少种」，不调 LLM
  for SUBSET in webchain/subset_100; do
    "$PY" inspiration_library/utils/measure_webchain_interaction_breadth.py \
      --subset "$STUDY/data/$SUBSET.jsonl" \
      --axtrees-dir "$STUDY/data/webchain/axtrees" \
      --out "$STUDY/runs/capability_study/breadth/$(basename "$SUBSET").jsonl" \
      2>&1 | tee "$LOG_DIR/breadth.log"
  done
  exit 0
fi

DRY_FLAG=""
[ "$MODE" = "dry" ] && DRY_FLAG="--dry-run"

for DATASET in webchain webworld; do
  case "$DATASET" in
    webchain) IN="$WC_IN";  BUCKET="webchain";            EXTRA=(--axtrees-dir "$STUDY/data/webchain/axtrees") ;;
    webworld) IN="$AUTO_IN"; BUCKET="webworld_autonomous"; EXTRA=() ;;
  esac
  echo "=== $BUCKET <- $IN" | tee -a "$LOG_DIR/run.log"
  "$PY" inspiration_library/utils/run_trajectory_capability_extraction.py \
    --dataset "$DATASET" --input "$IN" --bucket "$BUCKET" \
    --out "$OUT_DIR/$BUCKET.jsonl" ${EXTRA[@]+"${EXTRA[@]}"} \
    --workers "$WORKERS" --api-timeout-seconds "$API_TIMEOUT" $DRY_FLAG \
    2>&1 | tee -a "$LOG_DIR/${BUCKET}.log"
done

echo "=== webworld_random <- $RAND_IN" | tee -a "$LOG_DIR/run.log"
"$PY" inspiration_library/utils/run_trajectory_capability_extraction.py \
  --dataset webworld --input "$RAND_IN" --bucket webworld_random \
  --out "$OUT_DIR/webworld_random.jsonl" \
  --workers "$WORKERS" --api-timeout-seconds "$API_TIMEOUT" $DRY_FLAG \
  2>&1 | tee -a "$LOG_DIR/webworld_random.log"

echo "results -> $OUT_DIR"
echo "logs    -> $LOG_DIR"

#!/usr/bin/env bash
# Phase 1: repair + generate 并行跑（edit 暂不跑）
set -uo pipefail

# ============ 必须配置 ============
INPUT_DIR="${INPUT_DIR:-./single_page}"
# 服务器端存数据的根路径
DATA_ROOT="${DATA_ROOT:-/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data}"

# API 配置
export OPENAI_API_KEY="${OPENAI_API_KEY:?请设置 OPENAI_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:?请设置 OPENAI_BASE_URL}"
export OPENAI_MODEL="${OPENAI_MODEL:-kimi-k2.6}"

# ============ 可选配置 ============
LIMIT="${LIMIT:-0}"                    # 0=不限制
SEED="${SEED:-0}"
WORKERS="${WORKERS:-1}"               # 并发线程数
REPAIR_MIN_TASKS="${REPAIR_MIN_TASKS:-4}"
REPAIR_MAX_TASKS="${REPAIR_MAX_TASKS:-12}"
MAX_RETRIES="${MAX_RETRIES:-3}"
OVERWRITE="${OVERWRITE:-}"            # 设置为 1 则覆盖已有

# 代理（按需设置）
if [ -n "${ALL_PROXY:-}" ]; then
    export ALL_PROXY HTTPS_PROXY HTTP_PROXY
    export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"
fi

# ============ 初始化 ============
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OVERWRITE_FLAG=""
[ -n "$OVERWRITE" ] && OVERWRITE_FLAG="--overwrite"
LIMIT_FLAG=""
[ "$LIMIT" -gt 0 ] 2>/dev/null && LIMIT_FLAG="--limit $LIMIT"

# 输出路径（对应数量安排.md）
REPAIR_OUTPUT="$DATA_ROOT/repair/sp"    # 单页 repair 5k
GEN_OUTPUT="$DATA_ROOT/generate/sp"     # 单页 generate 5k

# ============ 分区：前 5K repair，后 5K generate ============
REPAIR_LIMIT="${REPAIR_LIMIT:-5000}"
GEN_LIMIT="${GEN_LIMIT:-5000}"

echo "=== 项目分区（前${REPAIR_LIMIT} repair + 后${GEN_LIMIT} generate）==="
python3 -c "
from pathlib import Path
import os

input_dir = Path('$INPUT_DIR')
src_dir = Path('$DATA_ROOT') / '_src'

repair_src = src_dir / 'text-repair'
gen_src = src_dir / 'text-generation'
for d in (repair_src, gen_src):
    d.mkdir(parents=True, exist_ok=True)

projects = sorted(d for d in input_dir.iterdir() if d.is_dir() and (d/'index.html').exists())

repair_projs = projects[:$REPAIR_LIMIT]
gen_projs = projects[$REPAIR_LIMIT:$REPAIR_LIMIT+$GEN_LIMIT]

for proj in repair_projs:
    dst = repair_src / proj.name
    if not dst.exists():
        os.symlink(proj.resolve(), str(dst), target_is_directory=True)

for proj in gen_projs:
    dst = gen_src / proj.name
    if not dst.exists():
        os.symlink(proj.resolve(), str(dst), target_is_directory=True)

print(f'  text-repair:     {len(repair_projs)} projects')
print(f'  text-generation: {len(gen_projs)} projects')
"

LOG_DIR="$DATA_ROOT/_logs"
mkdir -p "$LOG_DIR"

# ============ repair + generate 并行 ============
echo ""
echo "=== text-repair + text-generation 并行启动 (workers=$WORKERS) ==="

python3 WebCoding_Data/construct/construct_text_repair.py \
    --input-dir "$DATA_ROOT/_src/text-repair" \
    --output-dir "$REPAIR_OUTPUT" \
    --min-tasks "$REPAIR_MIN_TASKS" \
    --max-tasks "$REPAIR_MAX_TASKS" \
    --seed "$SEED" \
    --max-retries "$MAX_RETRIES" \
    --workers "$WORKERS" \
    $LIMIT_FLAG $OVERWRITE_FLAG \
    >"$LOG_DIR/repair.log" 2>&1 &
PID_REPAIR=$!

python3 WebCoding_Data/construct/construct_text_generation.py \
    --input-dir "$DATA_ROOT/_src/text-generation" \
    --output-dir "$GEN_OUTPUT" \
    --workers "$WORKERS" \
    $LIMIT_FLAG $OVERWRITE_FLAG \
    >"$LOG_DIR/generate.log" 2>&1 &
PID_GEN=$!

echo "  repair   PID=$PID_REPAIR → $REPAIR_OUTPUT"
echo "  generate PID=$PID_GEN → $GEN_OUTPUT"
echo "  日志: $LOG_DIR/repair.log"
echo "        $LOG_DIR/generate.log"
echo ""
echo "等待两个任务完成…（可用 tail -f $LOG_DIR/*.log 查看进度）"

# 等待两个任务完成
wait $PID_REPAIR
RC_REPAIR=$?
wait $PID_GEN
RC_GEN=$?

echo ""
echo "=== Phase 1 完成 ==="
echo "text-repair:     $REPAIR_OUTPUT (exit=$RC_REPAIR)"
echo "text-generation: $GEN_OUTPUT (exit=$RC_GEN)"
echo "text-editing:    (暂未执行)"
echo "完整日志: $LOG_DIR/{repair,generate}.log"

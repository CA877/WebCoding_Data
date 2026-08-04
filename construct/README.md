# edit / repair 构造交付说明

## 构造规则

- 每个项目随机生成 2–10 个不同 task type；2–5 合计约 80%，6–10 合计约 20%。
- 每个 task type 至少一个 patch，可有多个 patch；每个 patch 必须带自己的 `task_type`。
- **旧交付包的构造器**仍使用 HTML（移除脚本）+ 作者 CSS、60K 的历史口径，不能作为最终 WebCompass 对齐版本。
- 已确认的新最终口径是：完整 HTML、内联 CSS/JS、作者外部 CSS/JS、以及保留在最终项目内的本地第三方 bundle 全部进入模型上下文；使用精确 Qwen tokenizer，最大 **40K**。超过上限直接淘汰，不能截断或隐藏 bundle。
- 当前构造器已经使用 40K 全代码 serializer；批量生产前仍必须对目标项目清单运行精确 tokenizer 门禁。
- 输出为可恢复追加的 `records.jsonl`。只使用 `status=ok` 行构造训练集。
- image-editing 不重新截图，只验证并引用项目根目录的已审核 PNG；repair 在缺陷注入后只截一张 desktop 视口图（`<项目名>/index__desktop.jpg`），不再做 clean/defective 多视口对比与视觉变化量门禁（patch 应用已保证代码级改动，视觉 delta 对 text-repair 训练无增益）。

## 6,503 条 WebCompass 原始样本

当前 edit/repair 的正确原始来源是物理机上的
`train_sharegpt_webcompass_only_6503.jsonl`，不是历史 7,302 网页底稿或旧 5K split。

先将每条 GPT 回复中的 `# 文件名` + Markdown code fence 无损恢复为项目目录：

```bash
python scripts/materialize_sharegpt_web_projects.py \
  --input-jsonl /data1/xieqianqian/webcoding/data/20260804/all_merged_instructions/sft_train/train_sharegpt_webcompass_only_6503.jsonl \
  --output-dir runs/webcompass_6503/source_projects \
  --audit-jsonl runs/webcompass_6503/materialize_audit.jsonl \
  --project-list runs/webcompass_6503/materialized_projects.txt
```

先用 `scripts/filter_construct_projects_40k.py --allow-missing-screenshot` 做 40K
预筛，再对预筛清单运行 `scripts/prepare_clean_screenshots.py` 生成 desktop
clean screenshot，最后不带 `--allow-missing-screenshot` 严格复筛。把复筛后的
edit/repair 清单显式传给批处理入口；批处理脚本不再提供旧 7,302 清单的默认值。

## 一条命令批量运行

现有 `construct_context_audit_7302_20260723/*eligible_5k.txt` 是旧来源、旧 token
口径，不能用于本轮构造。对刚恢复的 6,503 项目用精确 Qwen tokenizer 预筛：

```bash
python3 scripts/filter_construct_projects_40k.py \
  --project-list runs/webcompass_6503/materialized_projects.txt \
  --tokenizer .cache/qwen3-tokenizer.json \
  --output-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --audit-jsonl runs/webcompass_6503/token_precheck.jsonl \
  --allow-missing-screenshot

python3 scripts/prepare_clean_screenshots.py \
  --project-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --browser-proxy http://127.0.0.1:7890 --width 1920 --height 1080

python3 scripts/filter_construct_projects_40k.py \
  --project-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --tokenizer .cache/qwen3-tokenizer.json \
  --output-list runs/webcompass_6503/eligible_40k_final.txt \
  --audit-jsonl runs/webcompass_6503/final_gate.jsonl
```

```bash
cd /data1/xieqianqian/webcoding/WebCoding_Data
cp construct/.env.example .env
# 编辑 .env，填写对方自己的 KIMI_API_KEY（或 OPENAI_API_KEY）。
# 两份清单必须来自 eligible_40k_final.txt；可相同，也可按实验方案拆分。
EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
REPAIR_PROJECT_LIST=runs/webcompass_6503/repair_projects.txt \
bash construct/run_edit_repair_batch.sh
```

脚本会默认读取仓库根目录的 `.env`；若对方的凭据文件在别处，可用 `API_ENV_FILE=/path/to/secret.env` 覆盖。key 不写入 Bash、README、JSONL 或 ModelScope 交付包。

默认输出到 `runs/construct_edit_repair_<运行日期>/`：

```text
text_edit/records.jsonl
image_edit_records.jsonl
text_repair/records.jsonl
image_repair/repair_defect_screenshots/<项目名>/
```

可按环境变量调整：

```bash
TASKS=edit EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
  EDIT_WORKERS=1 OUTPUT_ROOT=runs/construct_edit_trial \
  bash construct/run_edit_repair_batch.sh

# 不调用 API，只检查参数、项目清单和最终命令
EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
REPAIR_PROJECT_LIST=runs/webcompass_6503/repair_projects.txt \
DRY_RUN=1 bash construct/run_edit_repair_batch.sh
```

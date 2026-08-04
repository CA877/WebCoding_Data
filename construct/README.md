# edit / repair 构造交付说明

## 构造规则

- 每条样本指定 1–7 个不同 task type；按固定项目清单序号严格均衡分配，不受并发完成顺序影响。
- 每个 task type 必须对应 1–10 个 patch；每个 patch 带自己的 `task_type`。
- 每个 search 必须在完整输入文件中非空、精确且唯一匹配；构造后强制做正反向恢复验证。
- **旧交付包的构造器**仍使用 HTML（移除脚本）+ 作者 CSS、60K 的历史口径，不能作为最终 WebCompass 对齐版本。
- 已确认的新最终口径是：完整 HTML、内联 CSS/JS、作者外部 CSS/JS、以及保留在最终项目内的本地第三方 bundle 全部进入模型上下文；使用精确 Qwen tokenizer，最大 **40K**。超过上限直接淘汰，不能截断或隐藏 bundle。
- 当前构造器已经使用 40K 全代码 serializer；批量生产前仍必须对目标项目清单运行精确 tokenizer 门禁。
- 输出为可恢复追加的 `records.jsonl`。只使用 `status=ok` 行构造训练集。
- Edit 只允许正向构造。LLM 与 patch 验证成功后，再渲染原始项目的 1920×1080 Playwright 截图；同一次构造同时落盘 text-edit/image-edit v2 记录。
- Repair 在同一流程渲染 clean、defective 和第二次 clean 稳定性检查图。所有精确 patch 成功的记录进入 text-repair；仅 clean/defective 像素差异 ≥1% 且 clean 重渲染漂移 ≤0.2% 的记录进入 image-repair。
- text-repair 最终输入只有缺陷代码，不提供指出 bug 类型的 query；审计元数据保留 defect type，但不进入训练指令。

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

使用 `scripts/filter_construct_projects_40k.py --allow-missing-screenshot` 对所有完整文件做
40K 硬门禁；超过上限直接淘汰，不截断、不丢文件。随后生成 image-generate 截图，
并用 `scripts/select_construct_quotas.py` 固定 edit 3,000 清单与 repair 候选顺序。

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

python3 scripts/select_construct_quotas.py \
  --eligible-list runs/webcompass_6503/eligible_40k_preclean.txt \
  --edit-list runs/webcompass_6503/edit_projects.txt \
  --repair-list runs/webcompass_6503/repair_projects.txt \
  --manifest runs/webcompass_6503/selection_manifest.json --edit-count 3000
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
text_edit/text-edit.v2.jsonl
text_edit/image-edit.v2.jsonl
text_repair/records.jsonl
text_repair/text-repair.v2.jsonl
text_repair/image-repair.v2.jsonl
images/image-edit/<项目名>/
images/image-repair/{clean,defective}/<项目名>/
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

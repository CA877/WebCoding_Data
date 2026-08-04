# edit / repair 批量构造（当前可交付）

## 历史固定样本清单（不要用于当前 6,503 路线）

以下 7,302 底稿清单仅供历史复现。当前 edit/repair 必须从
`train_sharegpt_webcompass_only_6503.jsonl` 恢复项目并重新做 40K 门禁。

历史物理机目录：`/data1/xieqianqian/webcoding/WebCoding_Data/runs/task_project_splits_5k/`

- `edit_projects.txt`：5,000 个项目。
- `repair_projects.txt`：5,000 个项目。
- `split_metadata.json`：固定 seed、来源与重叠统计。

两份各 5K；现有最终合格项目共 7,302，因此交集 **2,698** 是数学最小值。多页 102 个被完全错开（edit 51 / repair 51）。

## 多 task 合约

- 每样本 2–10 个不同 `task_type`：2–5 合计约 80%，6–10 合计约 20%（可由 `--min-tasks/--max-tasks` 调整）。
- 每个 task type 有至少一个 `<search_replace>` patch，可有多个。
- 每个 patch 带显式 `task_type`；生成后强制验证 task/patch 映射和 patch 在模型可见源码中的可应用性。
- 输入：60K 内的 HTML + 作者 CSS + manifest；不输入 JS/bundle 正文。

## 运行

```bash
export ALL_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export NO_PROXY=localhost,127.0.0.1
export SSL_NO_VERIFY=1
export KIMI_API_KEY='...'
export KIMI_MODEL=kimi-k2.6
export CONSTRUCT_API_TIMEOUT=600

# 项目必须先从 6,503 JSONL 恢复、通过 40K 门禁并生成 clean screenshot。
# 使用物理机项目自带的 lora Python 环境。
LORA_PYTHON=web-coding-agent/.conda/lora/bin/python
$LORA_PYTHON construct/construct_text_editing.py \
  --project-list runs/webcompass_6503/edit_projects.txt \
  --output-dir runs/construct_edit --min-tasks 2 --max-tasks 10 --workers 1

$LORA_PYTHON construct/construct_text_repair.py \
  --project-list runs/webcompass_6503/repair_projects.txt \
  --output-dir runs/construct_repair --min-tasks 2 --max-tasks 10 --workers 1
```

构造器 JSONL 会以 `status=ok/error` 逐条落盘，可直接恢复；不要把 error 视为训练样本。

批量交付使用唯一入口 `construct/run_edit_repair_batch.sh`，不再使用旧的 `run_phase1_api.sh`、`run_phase2a_independent.sh`、`run_phase2b_dependent.sh`。旧脚本依赖已删除的 fake_url 分区和 `info.json` 目录格式，无法表达当前的项目清单、统一 JSONL 与项目内截图约定。

```bash
export KIMI_API_KEY='...'
EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
REPAIR_PROJECT_LIST=runs/webcompass_6503/repair_projects.txt \
bash construct/run_edit_repair_batch.sh
# 仅检查命令和路径，不发 API 请求：
EDIT_PROJECT_LIST=runs/webcompass_6503/edit_projects.txt \
REPAIR_PROJECT_LIST=runs/webcompass_6503/repair_projects.txt \
DRY_RUN=1 bash construct/run_edit_repair_batch.sh
```

## image-editing / image-repair

- `image-editing` 不再重新 Playwright 截图：`construct_image_editing.py` 读取统一 records JSONL 并复用源项目根目录的 `<样本名>*.png`。
- `text-repair` 在生成缺陷代码后截取单张 1920×1080 desktop 缺陷图；当前文本修复合同不实施视觉差异门禁。若要将同一结果用于 image-repair，必须另行执行同尺寸 clean/defective 视觉验收，不能仅依据 text-repair 的 `status=ok`。
- `image-editing` 读取/验证统一 JSONL；`image-repair` 的旧 `info.json` 兼容入口仍保留，但新的批量交付应直接使用 text-repair 输出的统一 JSONL。

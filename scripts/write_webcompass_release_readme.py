#!/usr/bin/env python3
"""Write the trainer-facing README for the six-task WebCompass release."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def distribution(records: list[dict]) -> dict[int, int]:
    return dict(sorted(Counter(len(record.get("task_type", [])) for record in records).items()))


def method_counts(records: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(
        str(record.get("metadata", {}).get("bug_injection_method", "unspecified"))
        for record in records
    ).items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--source-count", type=int, default=6503)
    parser.add_argument("--eligible-count", type=int, default=6502)
    parser.add_argument("--excluded-artifacts-generate", type=int, required=True)
    parser.add_argument("--extra-text-generate", type=int, default=0)
    args = parser.parse_args()
    root = args.release_root
    jsonl = root / "jsonl"
    names = ["text-generate", "image-generate", "text-edit", "image-edit", "text-repair", "image-repair"]
    records = {name: load_jsonl(jsonl / f"{name}.jsonl") for name in names}
    counts = {name: len(value) for name, value in records.items()}
    edit_distribution = distribution(records["text-edit"])
    repair_distribution = distribution(records["text-repair"])
    image_repair_distribution = distribution(records["image-repair"])
    text_methods = method_counts(records["text-repair"])
    image_methods = method_counts(records["image-repair"])

    lines = [
        "# WebCoding 六任务 SFT 数据集（Release v2）",
        "",
        "## 1. 数据集用途",
        "",
        "本 release 用于训练网页代码生成、编辑和修复模型，包含文本条件与图像条件两种输入形式。六类任务共享统一的网页项目来源、代码文件格式和严格的 search/replace patch 监督协议。数据已经过 Qwen 40K token 门槛、精确 patch 往返校验、Playwright 渲染检查和 release 级审计。",
        "",
        "本目录是自包含训练包。JSONL 中所有图片路径均相对于 release 根目录；训练时不要依赖生产目录中的绝对路径。",
        "",
        "## 2. 数据规模",
        "",
        "| 任务 | JSONL | 样本数 |",
        "|---|---|---:|",
    ]
    for name in names:
        lines.append(f"| `{name}` | `jsonl/{name}.jsonl` | {counts[name]} |")
    lines += [
        "",
        f"原始候选为 {args.source_count} 个项目；完整读取所有训练代码文件后，{args.eligible_count} 个项目满足 Qwen token 数不超过 40,000。超过门槛的项目整条丢弃，不做截断。",
        "",
        f"原 6,503 批次的 generation release 排除了 {args.excluded_artifacts_generate} 个 `instance_id` 以 `artifacts` 开头的 ArtifactsBench 测试样本。另并入 {args.extra_text_generate} 条独立 text-generate（ABQ 3k + complex 1k）；它们是文本条件生成数据，不要求配套图片，因此 text-generate 数量多于 image-generate。该过滤不会因为 WebCompass edit/repair 测试任务而排除 WebCompass generation 样本。",
        "",
        "## 3. 六类任务定义",
        "",
        "### text-generate",
        "",
        "输入是自然语言网页需求，目标是生成完整项目代码。记录不包含 patch；生成目标位于 `response`/输出代码字段。",
        "",
        "### image-generate",
        "",
        "覆盖原 6,503 批次中过滤测试集后保留的项目，输入条件只有原始网页的 Playwright 全页面截图，不提供文本 query。`input_images` 指向 `assets/<instance_id>/clean.png`。新增 ABQ 3k + complex 1k 仅作为 text-generate，不在本任务中重复造图。",
        "",
        "### text-edit",
        "",
        "输入为原始完整项目代码和明确的编辑 query；输出为把原项目正向修改成目标项目的 patches。每条包含 1–7 个不同 task，每个 task 对应 1–10 个 patches。编辑功能是正向构造，而不是先删除已有功能再逆向恢复。",
        "",
        "### image-edit",
        "",
        "与 text-edit 一一配对，使用相同 query、代码和 patches，并增加原始网页全页面截图。该原图直接复用 image-generate 的 canonical clean image，不重复渲染或存储第二份内容。",
        "",
        "### text-repair",
        "",
        "输入是注入 bug 后的完整项目代码，不提供指出 bug 的 query；输出 patches 将 buggy code 修复回原始 clean code。bug 既可能由 LLM 构造，也可能由确定性规则注入。",
        "",
        "### image-repair",
        "",
        "是 text-repair 的严格视觉子集。输入增加注入 bug 后的 Playwright 全页面截图，`dst_screenshot` 为复用的 image-generate clean 全页面图。只有 buggy/clean 截图真实像素差不低于 1% 的样本才进入本任务。",
        "",
        "## 4. 关键字段",
        "",
        "- `instance_id`：项目唯一 ID。",
        "- `task`：任务名。",
        "- `task_type`：该样本的细粒度任务/bug 类型数组；edit/repair 长度为 1–7，元素不重复。",
        "- `instruction`：模型输入。不同任务可能是文本 query、代码数组或结构化对象，必须按对应任务读取。",
        "- `input_files`：图像条件 edit/repair 的完整输入代码文件数组，每项含 `path` 与 `code`。",
        "- `input_images`：模型可见的输入图片路径。",
        "- `src_screenshot` / `dst_screenshot`：修改或修复前后的视觉状态；路径相对于 release 根目录。",
        "- `response` / `patches`：监督目标 patches。两者在 edit/repair 中内容等价。",
        "- `file_manifest` / `resources`：项目文件与资源清单。",
        "- `metadata.task_count`：task 数量。",
        "- `metadata.patch_count`：patch 总数。",
        "- `metadata.patch_count_by_task`：每种 task 对应的 patch 数。",
        "- `metadata.prompt_tokens`：构造输入的 Qwen token 计数。",
        "- `metadata.bug_injection_method`：repair bug 来源，值为 `llm` 或 `rule`。",
        "- `metadata.bug_injection_engine`：具体 LLM 名称或规则引擎版本。",
        "- `metadata.visual_difference.max_changed_ratio`：image-repair 的实际像素变化比例。",
        "",
        "## 5. 目录与图片去重",
        "",
        "```text",
        "jsonl/",
        "  text-generate.jsonl",
        "  image-generate.jsonl",
        "  text-edit.jsonl",
        "  image-edit.jsonl",
        "  text-repair.jsonl",
        "  image-repair.jsonl",
        "assets/",
        "  <instance_id>/",
        "    clean.png",
        "    repair_defective.jpg",
        "```",
        "",
        "同一个 `instance_id` 的 clean 图片只打包一次。image-generate 的输入图、image-edit 的原图以及 image-repair 的 clean/destination 图都明确指向同一个 `assets/<instance_id>/clean.png`。repair 的 defective 图片内容不同，因此单独存为 `assets/<instance_id>/repair_defective.<ext>`。所有路径都是相对于 release 根目录的路径。",
        "",
        "## 6. Patch 协议",
        "",
        "每个 patch 结构如下：",
        "",
        "```json",
        '{"path":"styles.css","task_type":"Color Contrast","search":"exact buggy/source substring","replace":"exact repaired/edited substring"}',
        "```",
        "",
        "应用规则：",
        "",
        "1. 按数组顺序依次应用 patches。",
        "2. `search` 必须在当前文件状态中恰好出现一次。",
        "3. 用 `replace` 完整替换该唯一匹配。",
        "4. edit 方向是 original → edited；repair 方向是 buggy → clean。",
        "5. 将 patches 逆序并交换 `search`/`replace` 后，必须逐字节恢复输入代码。",
        "6. 不要进行模糊匹配、正则替换或自动空白归一化。",
        "",
        "## 7. 分布与构造来源",
        "",
        f"- text-edit task-count 分布：`{json.dumps(edit_distribution, ensure_ascii=False)}`",
        f"- text-repair task-count 分布：`{json.dumps(repair_distribution, ensure_ascii=False)}`",
        f"- image-repair task-count 分布：`{json.dumps(image_repair_distribution, ensure_ascii=False)}`",
        f"- text-repair bug 来源：`{json.dumps(text_methods, ensure_ascii=False)}`",
        f"- image-repair bug 来源：`{json.dumps(image_methods, ensure_ascii=False)}`",
        "",
        "text-repair 的 release 选择会在保留全部 image-repair 配对 ID 的前提下，将 1–7 task-count 分布严格拉平。image-repair 本身也按 1–7 task-count 配额构造。",
        "",
        "规则注入覆盖 11 类：Occlusion、Crowding、Text Overlap、Alignment、Color Contrast、Overflow、Sizing Proportion、Loss of Interactivity、Semantic Error、Nesting Error、Missing Attributes。",
        "",
        "## 8. 图片协议",
        "",
        "- 浏览器：Playwright Chromium。",
        "- 基础 viewport：1920×1080。",
        "- 保存方式：`full_page=True`，因此最终图片高度可随页面内容变化。",
        "- clean 原图：generation/edit/repair 共享同一 canonical PNG。",
        "- defective 图：从实际 buggy code 重新渲染，不能由 clean 图做图像编辑得到。",
        "- image-repair 门槛：RGB 通道差最大值至少为 8 的像素计为变化像素；变化比例必须 ≥0.01。若 bug 改变页面宽高，比较时在共同画布上对齐并补白。",
        "",
        "## 9. 过滤与防泄漏规则",
        "",
        "- 所有代码文件合计超过 Qwen 40K token：整条排除。",
        "- 原 6,503 批次 generation 中 `instance_id.startswith(\"artifacts\")`：排除。",
        "- 新增 ABQ 3k + complex 1k：完整并入 text-generate；不并入 image-generate。",
        "- WebCompass generation 不因 WebCompass edit/repair 测试任务而额外排除。",
        "- edit/repair 不应用上述 ArtifactsBench generation 前缀过滤。",
        "- 构造失败、patch 不唯一、patch 无法逆向恢复、缺少 task↔patch 映射或 image-repair 像素差不足 1% 的记录不会进入对应 release。",
        "",
        "## 10. 训练读取建议",
        "",
        "- 建议按 `task` 分别建立 dataloader，再按目标训练比例混合，避免样本量较大的 generation 完全主导 batch。",
        "- 文本任务只加载代码/文本；图像任务同时加载 `input_images`。",
        "- image-repair 的 clean `dst_screenshot` 可用于审计或辅助目标；主要模型输入是 buggy `input_images`。",
        "- patch 模型应保持 JSON 数组输出，并保留 patch 顺序。",
        "- 数据未预先划分 train/validation；如需划分，应按 `instance_id` 分组，避免同一项目的不同任务或模态跨 split。",
        "- 不要把绝对生产路径写入训练缓存；以 release 根目录解析相对图片路径。",
        "",
        "## 11. 审计与可追溯文件",
        "",
        "- `manifest.json`：任务数量、JSONL 路径与 SHA-256。",
        "- `audit_summary.json`：严格 schema、数量、patch、分布和图片审计结果。",
        "- `provenance/token_gate_audit.jsonl`：6503 个源项目的 token 门槛结果。",
        "- `provenance/eligible_40k.ids.txt`：通过 40K 门槛的项目 ID。",
        "- `provenance/edit_3000.ids.txt`：edit 选择 ID。",
        "- `provenance/repair_candidates.ids.txt`：repair 候选 ID。",
        "- `provenance/extra_text_generate.ids.txt`：新增 ABQ 3k + complex 1k 的 4,000 个 text-generate ID。",
        "",
        "训练前建议首先校验 `manifest.json` 中的 SHA-256，并确认 `COMPLETE` 文件存在。没有 `COMPLETE` 表示 release 尚未通过全部交付检查。",
        "",
    ]
    (root / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(root / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

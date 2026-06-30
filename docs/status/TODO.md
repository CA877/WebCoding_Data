# TODO

## Pipeline B — 前 224 条需重跑

- **原因**：首次启动时并发过高（30→80），Chromium 大量 EPIPE 崩溃，导致前 224 条 URL 被错误标记为 `site_timeout`/`empty_page`
- **影响**：这 224 条已写入 manifest，续跑时会被跳过，实际产出率仅 2.2%（正常应为 ~40%）
- **解决**：当前 run 跑完后，删除这 224 条的 manifest 条目及其输出目录，重新处理
- **manifest 路径**：`datasets/pipeline_b/runs/run_b15000/output/pipeline_b_results.jsonl`
- **创建时间**：2026-06-02

## Pipeline A — 待完成

- [ ] add_js API 验证通过（glm-5.1 @ app.ppapi.ai）
- [ ] expand 成功率待确认
- [ ] 正式跑全量

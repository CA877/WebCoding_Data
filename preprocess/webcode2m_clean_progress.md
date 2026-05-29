# WebCode2M 当前进展

## 当前版本

- 清洗脚本：`WebCoding_Data/preprocess/webcode2m_clean_pipeline.py`
- 七类构造入口：`WebCoding_Data/construct/construct_webcode2m_dataset.py`
- 验证器：`WebCoding_Data/construct/validate_webcode2m_task_dirs.py`
- LLM 模型：`qwen-latest-series-invite-beta-v23`
- VLM/PRD 模型：`qwen-latest-series-invite-beta-v23`
- 正式 smoke：`WebCoding_Data/local_trials/webcode2m_formal_7x10_ppapi_smoke`

## 已完成

1. 官方 WebCode2M 清洗代码已接入。
2. 多页扩展改为真实站内 HTML 子页，不再模板造页。
3. 首页和子页都走官方清洗。
4. 七类任务已拆分成独立构造脚本。
5. `text-generation` 使用代码 + 截图生成 PRD。
6. `edit` 使用 `web_coding_demo/synthetic/edit.py` 的 16 类任务逻辑。
7. `repair` 使用 `web_coding_demo/synthetic/repair.py` 的 11 类缺陷逻辑和 reverse construction。
8. 已生成 70 条正式 smoke 样本。
9. 已通过 validator。
10. 代码和结果已推送到 GitHub commit：`c635a6b`。

## 当前验证结果

```json
{
  "ok": true,
  "task_counts": {
    "text-generation": 10,
    "image-generation": 10,
    "video-generation": 10,
    "text-editing": 10,
    "image-editing": 10,
    "text-repair": 10,
    "image-repair": 10
  },
  "info_json_count": 70,
  "remote_hit_count": 0,
  "provenance_hit_count": 0,
  "small_video_count": 0
}
```

## 当前问题

1. `text-editing` 对 LLM search/replace 精确性敏感，失败样本必须丢弃或换样本补齐。
2. 批量扩展前需要先用新模型 `qwen-latest-series-invite-beta-v23` 重跑小批次确认质量。
3. `local_trials` 里历史试验目录较多，建议只保留正式结果和必要复现输入。
4. 当前 ppapi 能列出 `qwen-latest-series-invite-beta-v23`，但 chat/responses 探针不可调用，需要确认模型权限或接口路由。

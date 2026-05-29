# WebCode2M 7x10 最新执行方案

## 当前结论

1. 旧 prototype 方案废弃。
2. 当前正式入口是 `construct_webcode2m_dataset.py`。
3. 七类任务必须拆分脚本，不写进一个大文件。
4. 文本 LLM 使用 `qwen3.7-max`。
5. 视觉/PRD 使用 `qwen3-vl-235b-a22b-instruct`，图片输入走 OpenAI 标准 `image_url`。
6. `qwen3.7-max` 的图片探针格式可通过但读图不可靠，不用于 VLM。
7. 输出保留在 `local_trials/webcode2m_formal_7x10_ppapi_smoke`。

## 已做事项

1. 用官方 WebCode2M 清洗代码处理首页和真实子页。
2. 多页扩展只使用真实站内 HTML 链接。
3. 生成 10 个多页 clean project。
4. 七类任务各跑 10 条。
5. `text-generation` 用代码 + 截图生成 PRD。
6. `edit` 使用 `web_coding_demo/synthetic/edit.py` 的 16 类任务。
7. `repair` 使用 `web_coding_demo/synthetic/repair.py` 的 11 类缺陷。
8. `image-editing` / `image-repair` 复用 text pair 并补截图。
9. `video-generation` 使用 Playwright 录制页面浏览视频。
10. validator 已通过。

## 当前运行命令

```bash
python3 WebCoding_Data/construct/construct_webcode2m_dataset.py \
  --input-dir WebCoding_Data/local_trials/webcode2m_official_multipage_10 \
  --output-dir WebCoding_Data/local_trials/webcode2m_formal_7x10_ppapi_smoke \
  --limit 10 \
  --edit-task-count 1 \
  --repair-task-count 1 \
  --max-retries 3 \
  --overwrite
```

## 当前验证命令

```bash
python3 WebCoding_Data/construct/validate_webcode2m_task_dirs.py \
  --root WebCoding_Data/local_trials/webcode2m_formal_7x10_ppapi_smoke \
  --expected-per-task 10 \
  --report WebCoding_Data/local_trials/webcode2m_formal_7x10_ppapi_smoke/report.json
```

## 当前验证结果

```text
ok: true
text-generation: 10
image-generation: 10
video-generation: 10
text-editing: 10
image-editing: 10
text-repair: 10
image-repair: 10
remote_hit_count: 0
provenance_hit_count: 0
small_video_count: 0
```

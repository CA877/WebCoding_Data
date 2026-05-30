# WebCode2M 清洗指南

## 目标

将 WebCode2M 原始样本清洗为**离线可渲染、无外部依赖、代码量合理**的多页项目，作为七类任务构造的输入。

## 清洗质量要求

1. **零远程渲染依赖** — 无远程 CSS、JS、图片、字体影响视觉输出
2. **无裂图** — 图片要么本地化成功，要么使用 SVG 占位符
3. **无追踪/噪音** — 删除 analytics、ads、tracking pixel、dns-prefetch、pingback、RSS feed
4. **代码量合理** — 不内联巨型 base64，不保留无关 CMS 模板代码
5. **多页来自真实链接** — 不模板造页，扩展失败则保留 single page
6. **无 provenance 泄漏** — 不含 metadata.json、原始截图

## 清洗流程

```
WebCode2M 原始 HTML (HuggingFace rows API)
    │
    ▼ webcode2m_clean_pipeline.py
    │
    ├─ 1. 解析 HTML (BeautifulSoup)
    ├─ 2. 去除追踪脚本 (GA, Yandex, Facebook Pixel...)
    ├─ 3. 处理媒体引用:
    │     ├─ 远程可下载 → 下载到 assets/ (8MB 上限, 12s 超时)
    │     ├─ 下载失败 → 本地 SVG 占位符 (visual/icon/avatar)
    │     └─ 追踪/噪音 → 直接移除
    ├─ 4. 移除噪音 <link> (dns-prefetch, preconnect, canonical, alternate, manifest)
    ├─ 5. 重写 CSS url() 和 srcset
    ├─ 6. 导航链接中和为 #
    ├─ 7. 调用官方 WebCode2M purification (formatHtml, formatCss, mergeHtmlCss)
    ├─ 8. 爬取同站真实子页 (最多 6 页), 每页走相同清洗
    └─ 9. 输出 clean project:
          index.html / page_*.html / assets/ / metadata.json
```

## 已知问题与注意事项

| 问题 | 状态 | 处理 |
|------|------|------|
| 远程资源残留 | 已解决 | 构造阶段 `sanitize_render_text()` 兜底 |
| provenance 文件泄漏 | 已解决 | 过滤 metadata.json + 原始截图 |
| 单页硬造多页 | 已解决 | 只接受真实站内子页 |
| LLM search/replace 不精确 | 需注意 | 失败样本丢弃，不硬算成功 |
| 无 HTML 的资源目录 | 需注意 | 不能进入视觉任务 |
| 图片路径不可解析 | 需注意 | 使用分类占位符 (generated-visual/icon/avatar.svg) |

## 资源分类策略

下载时对每个远程引用分类:

- **noise** — tracking pixel, analytics, ads → 移除
- **css** — 远程样式表 → 下载到 assets/ 或移除
- **font** — web font → 下载或 fallback 系统字体
- **image** — 内容图片 → 下载到 assets/
- **icon** — 小图标/favicon → 下载或用 icon 占位符
- **avatar** — 头像/社交图 → 下载或用 avatar 占位符

## 验证

```bash
python3 construct/validate_webcode2m_task_dirs.py \
  --root local_trials/webcode2m_formal_7x10_ppapi_smoke \
  --expected-per-task 10
```

通过条件: `remote_hit_count = 0`, `provenance_hit_count = 0`, `small_video_count = 0`

## 下载样本

参见 [WebCode2M_10条样本下载方法.md](WebCode2M_10条样本下载方法.md)

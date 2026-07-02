# 训练数据完整 Pipeline 与质量检查

> 当前版本：2026-06-29。完整数据主要在 ssh/服务器上；本地仅有轻量样本、脚本和历史预检查记录。

## 1. 目标数据形态

当前有效主线已经从早期 7 类任务逐步收敛到统一 schema 的 6 类 SFT 数据：

- `text-generation`
- `image-generation`
- `text-editing`
- `image-editing`
- `text-repair`
- `image-repair`

其中：

- generation：输入是文本/截图，输出完整网页代码。
- editing：输入是待编辑网页代码和编辑需求，输出 search/replace patches。
- repair：输入是 buggy 网页代码和缺陷描述，输出 buggy -> fixed patches。
- image-editing：在 text-editing 的基础上，只额外加入编辑前截图作为视觉输入。
- image-repair：在 text-repair 的基础上，加入 repair 前 buggy 截图和 repair 后 fixed 截图。

## 2. 数据来源与筛选

### 2.1 WebRenderBench / WebCode2M 预处理线

入口仍在 `preprocess/`：

```text
WebRenderBench useful projects
  -> expand
  -> clean
  -> add_js
  -> validate

WebCode2M URL
  -> filter_webcode2m_urls.py
  -> preflight_webcode2m_urls.py
  -> pipeline_b_sample_level.py / playwright_crawl.py
  -> postprocess_webcode2m_crawl.py
```

已实现或记录过的筛选逻辑：

- URL 形态过滤：过滤明显奇怪的 URL、资源 URL、统计/CDN/临时域名。
- preflight：用便宜 HTTP 请求剔除安全挑战页、停放页、默认服务器页、非 HTML 资源、空页面。
- 语言过滤：早期只保留中/英文的逻辑在 crawler 文档中有规划，但当前生产数据疑似漏掉，需要补做全量审计。
- 资源清洗：远程图片本地化；远程 CSS 内联；外链中和；删除 iframe/audio/video；去掉 analytics/challenge 残留。
- 断点续跑：Pipeline B 通过 manifest 跳过已处理 URL；失败样本可单独重跑。

### 2.2 OSS / unified 数据处理线

当前更有效的训练数据处理在 `scripts/`：

```text
raw OSS JSONL
  -> normalize_oss_webcoding_jsonl.py
       - 统一字段
       - 对 edit/repair patch 做唯一匹配校验
       - repair 统一为 input_files=buggy, output_files=fixed, patches=buggy->fixed
  -> image link policy / content QC
       - 不再合成图片占位 URL
       - 图片保留原始链接或真实本地化
       - picsum/loremflickr 等历史占位 URL 进入拒绝或人工复核
  -> build_oss_image_editing_dataset.py
       - 基于 text-editing success JSONL
       - 渲染 input_files，截图编辑前页面
  -> build_oss_image_repair_dataset.py
       - 基于 text-repair success JSONL
       - 渲染 buggy input_files 得到 src_screenshot
       - 渲染 fixed output_files 得到 dst_screenshot
  -> organize_release_sft_6tasks_v1.py / prepare_hf_release_sft_6tasks.py
       - 组织 Hugging Face 发布格式
```

## 3. 已实现的补救逻辑

### 3.1 图片链接与本地截图补救

历史排查确认：不能用早期 live URL 截图证明本地 HTML 可截图，image-based 数据必须本地重渲染。

当前截图脚本基线修复包括：

- 触发懒加载和滚动事件。
- 不再把缺失图片或远程图片替换为 `picsum` / `loremflickr` 等合成占位图。
- 图片要么真实下载到本地并改写为本地资源路径，要么保留原始 URL 并由 QC 决定是否接受。
- 对无效 `<picture><source srcset="null">`、`srcset="#"`、本地缺失 `srcset` 做清理，避免浏览器优先选择坏候选。
- 对残留 `/userfiles/...`、`/images/...` 等没有 assets 的路径做统计和 QC，不合成新图片 URL。
- 不强制给 Chromium 走 `127.0.0.1:7890`，因为小规模验证中无代理更稳定。
- 图片统计不只看 `document.images.length`，同时报告：
  - `loadable_image_count`
  - `loaded_loadable_image_count`
  - `visible_loadable_image_count`
  - `loaded_visible_loadable_image_count`

### 3.2 字体和截图卡死补救

已复现过 `Page.screenshot: waiting for fonts to load` 卡死。

补救：

- 设置 `PW_TEST_SCREENSHOT_NO_FONTS_READY=1`。
- 尽量移除或拦截远程 font 与 `@font-face`。
- 每个样本设置 `--site-timeout` 硬超时。
- 对 image-repair 额外实现 `retry_image_repair_hard_timeout.py`，每条样本独立子进程，超时就杀掉并只重跑失败样本。

### 3.3 patch 匹配补救

`normalize_oss_webcoding_jsonl.py` 已经做了几层补救：

- 对 `search` 尝试 `exact`、`html_unescape`、`strip_cdata`、组合变换。
- 必须唯一匹配；0 次和多次都视为失败或风险。
- repair 支持两种输入情况：
  - 当前代码已是 buggy：直接应用 buggy -> fixed。
  - 当前代码是 clean：反向注入 bug，再统一输出 buggy -> fixed。
- 图片链接本地化或清理后再次验证 patch 是否仍能在 `input_files` / `output_files` 中匹配。

### 3.4 失败样本补救原则

- 不动已经成功的样本。
- 只对 failed JSONL / manifest 中的失败样本做补救重跑。
- 输出新目录，不覆盖旧生产目录。
- 小规模先跑 1-3 条，再 10-20 条，再 100 条。

## 4. 已知问题与应纳入全量 QC 的新问题

用户已发现的问题：

| 问题 | 风险 | 建议处理 |
|---|---|---|
| 非中英文页面漏筛 | 训练目标偏离，视觉/文本分布污染 | 全量语言检测；只保留 zh/en；其他语言进 failed/reject |
| adult/dating/escort/casino/porn/call-girls 等风险域名或页面 | 安全和发布风险 | 域名、路径、页面文本、title、alt 全字段关键词黑名单 |
| image-repair 前后截图差异小 | 视觉输入无信息，任务退化为 text-repair | 计算 src/dst 图像差异；低差异样本降级为 text-repair 或剔除 image-repair |
| edit/repair patch 找不到唯一匹配 | 监督不可执行，模型学到错误 patch | patch search 必须在 input code 唯一匹配；replace 应在 output code 出现 |

进一步需要发掘/统计的问题：

- challenge/captcha/security check 页面残留。
- parked domain/domain-for-sale/under-construction 页面。
- 远程 URL 残留，尤其是 CSS/JS/font/video。
- 图片未加载、可见图片未加载、截图大面积空白。
- `srcset=null`、`/null`、`#` 图片候选。
- `input_files` / `output_files` 缺失或空。
- patch 数量为 0、patch 路径不存在、patch 作用方向错误。
- duplicate instance_id。
- 同域名/同模板重复过多。
- generation 输出代码过短、空 body、缺 `<html>/<body>`。
- 成人/博彩词只出现在路径或 alt/title 中，不能只看正文。
- 页面语言混杂：少量英文导航 + 大量其他语言正文。
- image-repair 的 defect type 本身视觉不可见，例如 Missing Attributes；这类样本不一定错，但不适合视觉诊断训练。

## 5. 新增质量审计脚本

已新增：

```text
scripts/audit_webcoding_dataset_quality.py
```

用法：

```bash
python3 scripts/audit_webcoding_dataset_quality.py \
  /path/to/text-generation.unified.success.jsonl \
  /path/to/text-editing.unified.success.jsonl \
  /path/to/text-repair.unified.success.jsonl \
  /path/to/image-editing.unified.success.jsonl \
  /path/to/image-repair.unified.success.jsonl \
  --dataset-root /path/to/dataset_root \
  --out-dir /path/to/quality_audit_YYYYMMDD
```

输出：

- `quality_audit.json`
- `quality_audit.md`

当前脚本统计：

- language heuristic：`likely_non_zh_en` 等。
- adult/sensitive keyword。
- challenge/captcha。
- placeholder/parked domain。
- remote URL residual。
- schema 缺字段。
- edit/repair patch 唯一匹配。
- image-repair src/dst screenshot 差异。

## 6. 本地小样本审计结果

已在本地 6 任务 × 10 样本上跑通脚本：

```text
docs/status/local_10sample_quality_audit_20260629/
├── quality_audit.json
└── quality_audit.md
```

注意：本地 10 样本是轻量发布版，text-edit/text-repair 中不一定保留完整 `input_files` / `output_files`，所以 patch 唯一匹配只能在服务器 unified JSONL 上做准确统计。

本地小样本已经能看到的风险包括：

- adult/sensitive keyword：例如 `1teenporn.com`、casino、bet 等。
- placeholder/parked/captcha 页面命中较多。
- image-repair 部分缺 `dst_screenshot` 或无法解析差异。
- 旧格式样本中 patch 无法校验，因为没有输入代码。

这些结果不能代表全量比例，但说明 QC gate 必须补上。

## 7. 远端完整数据检查状态

尝试连接：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 h-liu ...
```

当前本机报错：

```text
ssh: Could not resolve hostname h.pjlab.org.cn
```

因此本轮未能直接读取服务器完整 JSONL，也不能给出全量真实比例。待 DNS/网络恢复后，应在服务器上执行 `scripts/audit_webcoding_dataset_quality.py`，并把输出同步回本地 `docs/status/remote_quality_audit_YYYYMMDD/`。

## 8. 推荐的完整生产 QC Gate

```text
raw/preprocessed data
  -> URL/domain blacklist
  -> language detection zh/en only
  -> adult/gambling/dating blacklist
  -> challenge/parked/placeholder detection
  -> code/resource schema validation
  -> resource slimming
       - 删除未引用的孤儿 resources 文件
       - 删除内容完全重复的 resources 文件
       - 被引用的第三方库/blob 只在允许 CDN 且提供映射时外链化
       - HTML、内联 CSS/JS、作者脚本保留
       - 对 vendor/blob 识别分置信度：明确第三方库可生成 CDN 候选；疑似 vendor bundle 只标记不自动改；混合作者代码默认保留
  -> patch normalization and unique-match validation
  -> image URL audit/localization and patch re-validation
  -> local render + image load stats
  -> screenshot blank/low-content detection
  -> image-repair src/dst diff threshold
  -> duplicate/domain/template distribution check
  -> final success/reject JSONL split
```

建议处理规则：

- 非中英文：剔除。
- adult/gambling/dating：剔除，不进入 release。
- patch 不唯一：剔除或回到构造阶段重生成。
- orphan/duplicate resources：清理并记录删除清单。
- referenced vendor/blob：默认保留并标记；允许 CDN 且映射确认后按显式映射外链化。
- unclear vendor bundle：只进入审计报告，不自动外链化，避免误删作者代码。
- image-repair 低视觉差异：不进入 image-repair；可保留 text-repair。
- challenge/parked/placeholder：剔除或人工复核。
- remote URL：图片不使用替代占位 URL；真实图片可保留或本地化并进入 QC，CSS/JS/font/video 远程依赖应剔除或本地化。

## 9. Generate 代码面一致性

当前合作者反馈：`image-generate` 和 `text-generate` 的代码输入面可能不一致。

- `text-generate` 往往来自 full code JSONL，可能带大量 `resources`。
- `image-generate` 当前 fake-url 构造链只读取 `index.html`，`resources=[]`，因此 token 明显更短。

这不是模型任务天然差异，而是构造链差异。后续 release 应记录并统一 `target_format`：

- `single_html`
- `multi_file_with_resources`
- `slimmed_multi_file`

若短期不重构，需要在质量报告中单独标注 `image-generate` 是 single-html 特例，不把它的 token 分布当作 full-code generate 的代表。

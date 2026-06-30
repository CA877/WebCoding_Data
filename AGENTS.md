# AGENTS.md

## 终极目标

构建 **70K 训练集**（7 类任务 × 10K），使模型在以下 4 个榜单上取得高分：

| 榜单 | 输出格式 | 评测要点 |
|------|----------|----------|
| **WebCompass** | 多文件项目（index.html + styles.css + script.js） | Docker 内 http.server 渲染 |
| **Design2Code** | 单 HTML，CSS inline | 视觉相似度 |
| **Vision2Web** | 多文件项目 | Visual Score + Functional Score |
| **FLAME-VLM-Code** | React 组件 | 渲染截图 cosine similarity |

所有榜单都不要求模型输出远程 URL。训练数据统一用 `assets/` 本地相对路径。

## 数据来源与处理

- **Pipeline A** — WebRenderBench 31,765 个单页 HTML，expand → clean → add_js（LLM 生成 43 种 JS 功能之一，ratio=0.5）
- **Pipeline B** — WebCode2M 28K URL，Playwright 爬取 → postprocess（保留网站原生 JS，无 LLM 调用）
- 两条 Pipeline 并行执行，入口: `preprocess/run_server.sh`
- 预计产出 ~30K 可用项目 → 构造 70K 训练样本

---

## 运行实验原则：决策价值导向

1. 实验应以假设和决策价值为导向，而不是为了补齐路径、填满表格，或让 ablation 看起来完整。每组实验都应回答一个明确假设，或支持一个后续决策。

2. 不在低边际信息增益的方向上穷举。如果可以预见某组实验对性能提升、方向判断或后续改进没有明显贡献，尤其只是重复确认"不可行 / 无效果"，应停止该方向，不做穷举式验证。

3. 当某个方向已经表现很差时，不要把它在所有条件下跑满后才给出相同结论。应尽早记录已有证据、停止追加实验，并把资源转向更可能改变决策的方向。

4. 设计数据构造或模型评测任务时，优先说明该实验会改变什么判断：例如是否继续扩量、是否修改 schema、是否切换构造方法、是否保留某类任务。

5. 例如 huggingface 等请使用中国镜像网站。

## 远程脚本工作流

1. 涉及远程服务器 / H 集群的脚本修改，必须先在本地仓库里编辑和检查脚本，再通过 `rsync` 同步到 SSH 服务器上执行。

2. 不直接在远程服务器上临时手写或改脚本；除非只是查看状态、启动已有脚本、杀进程、检查日志等操作。

3. 从 GitHub 同步别人的代码更新后，应立即将本地仓库同步到 H 集群的项目目录，保证本地与 `h-liu` 上的代码一致。

4. 如果在 H 集群上跑小规模测试，应将测试结果打包并同步回本地，方便用户在本地检查结果。

5. 连接 H 集群使用：

```bash
ssh -CAXY main.liujiaheng.ailab-colab.ws@h.pjlab.org.cn
```

本机 SSH 配置中可使用别名：

```bash
ssh -CAXY h-liu
```

对应的 `rsync`：

```bash
rsync -e 'ssh -CAXY' ...
```

6. H 集群项目目录：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

7. H 集群上所有 WebCoding_Data 相关写入都必须放在 `xieqianqian` 项目目录下，即：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

不要写入历史临时测试目录或其他非 `xieqianqian` 工作目录。历史临时测试目录只允许只读排查，不作为新实验输出位置。除非用户明确指定其他项目，否则新脚本、日志、数据、临时文件都只能写入上述 `webcoding_data` 目录及其子目录。

8. 在 H 集群运行 WebCoding_Data 相关脚本时，使用 `lora` 环境，不使用系统 Python 或其他临时环境。

9. 新实验、脚本、日志、目录和结果包命名禁止使用 `smoke`；小规模验证统一称为“小规模测试”或“预检查运行”。

10. Pipeline A 使用 H 集群上的 WebRenderBench useful 数据构造，不使用 `webrenderbench_raw` 原始数据目录。useful 数据目录为：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/datasets/pipeline_a/useful
```

该目录已确认包含 31,765 个项目目录，且 31,765 个项目目录均包含 `index.html`。旧路径
`/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/h_rebuild/webrenderbench_clean_split/useful`
保留为指向该目录的 symlink，仅用于兼容历史脚本。

11. Pipeline A / Pipeline B 的样本级预处理与爬取必须设置硬超时保护，避免单个 worker 卡死导致整批任务挂住。100 条小规模预检查运行建议先用 `--site-timeout 600`。

## 数据盘与排查安全红线

1. 排查远程物理机或数据盘问题时，首要目标是定位根因并可复现地解决问题，不得为了快速验证而破坏数据盘状态。

2. 禁止删除 `/data1/xieqianqian` 及其子目录中的任何原始数据、历史产物、JSONL、截图、资源文件或中间结果。除非用户明确指定某个新建测试目录可以清理，否则不要执行 `rm -rf`、覆盖式移动、批量删除、清空目录等破坏性操作。

3. 禁止删除 `/data1/xieqianqian` 以外的数据盘内容。对数据盘上未知目录只允许只读排查，不能整理、迁移、重命名或清理。

4. 新增脚本、日志、预检查输出、截图试验结果必须写到明确的新目录中，目录名要体现日期、任务和小规模验证含义；不要复用或覆盖已有生产目录。

5. 截图、渲染、转换、爬取等问题排查必须从少量 case 开始。通常先跑 1-3 个代表样本，确认假设后再跑 10-20 个样本，只有小规模结果稳定且用户认可后才能扩大到 100 条或更多。

6. 本地样本截图问题的排查重点是确认根因：代码与截图是否对齐、资源是否本地可用、外链是否可访问、懒加载是否触发、代理是否实际进入浏览器、截图脚本使用的是 live URL 还是本地 HTML。不能只用旧 live screenshot 证明本地样本可截图。

7. 每次解决重大问题或确认重要结论后，应把结论写回 `AGENTS.md` 或对应的当前 pipeline 文档，避免后续重复考古。

## 2026-06-23 本地样本截图排查结论

1. `output_full` 中历史 `screenshot.png` / `*_screenshot.png` 更像是早期 Pipeline B 打开 live URL 时截的图，不能作为“清洗后的本地 HTML 能成功截图”的证据。当前 image-based 数据构造必须以本地 HTML 重新渲染截图为准。

2. 2026-06-23 对 OSS edit 样本做小规模本地重渲染验证时，`picsum.photos` 与 `loremflickr.com` 在无代理 Chromium 下均可成功返回图片；显式走 `127.0.0.1:7890` 代理反而会显著降低图片加载成功率。默认截图不要强制加该代理。

3. `10kcards.com__support` 复现过 `Page.screenshot: waiting for fonts to load` 卡死。根因是 Playwright 截图前默认等待 `document.fonts.ready`，部分样本的字体状态会长期 pending。截图脚本必须设置 `PW_TEST_SCREENSHOT_NO_FONTS_READY=1`，并尽量移除/拦截远程 font 与 `@font-face`，避免单样本卡死。

4. 图片统计不能只看 `document.images.length` 与 `naturalWidth`。部分样本含无 `src/srcset` 的空 `<img>`，浏览器会把当前页面 URL 作为 `currentSrc`，导致误判为图片未加载。质量统计应同时报告 `loadable_image_count`、`loaded_loadable_image_count`、`visible_loadable_image_count`。

5. 已验证小规模结果：`scripts/build_oss_image_editing_pilot.py` 在 `loremflickr` 版 edit 样本前 10 条上本地 HTTP 渲染成功，`ok=10, failed=0`，所有有 URL 的图片均加载成功。验证输出目录为 `/data1/xieqianqian/webcoding/diagnostics/local_render_20260623_build_10cases_final`。

6. 继续排查 100 条 edit 样本时确认过三类额外根因：
   - `<picture><source srcset="null">` 或页面 JS 会让浏览器最终选择 `/null`，即使 `<img src>` 是可用图片也会空图。
   - 清洗后的本地 HTML 可能残留 `/userfiles/...`、`/images/...` 等相对图片路径，但 JSONL 没有对应 assets；本地 HTTP 渲染时会 404。
   - 部分样本含 `src="#"` 或 `srcset="# 534w, # 237w"` 这类锚点式无效图片候选，浏览器会优先使用无效 `srcset`，导致 `src` 中的替代图也不显示。

7. 当前本地截图脚本的基线修复包括：运行时触发懒加载；把缺失的本地相对图片引用按元素尺寸替换为 `loremflickr`；移除无效 `<picture><source>` 和无效/本地/锚点式 `srcset`；拦截字体；设置 `PW_TEST_SCREENSHOT_NO_FONTS_READY=1`；截图前动态等待图片加载进展稳定。

8. 最终 100 条预检查结果：`scripts/build_oss_image_editing_pilot.py` 在 `/data1/xieqianqian/webcoding/diagnostics/local_render_20260623_build_100cases_final_hash_wait` 产出 `ok=100, failed=0`，总计 `image_count=1595`、`loaded_image_count=1595`、`loadable_image_count=1595`、`loaded_loadable_image_count=1595`、`visible_loadable_image_count=810`、`loaded_visible_loadable_image_count=810`，`miss_count=0`。代表截图已人工查看，`5mv.com__search`、`GoriLaw.Com__trust-funds`、`PhoenixEmergencyLockAndDoor.com` 均不再出现大片空图。

9. `image-editing` 训练集组织方式：以 `text-editing.unified.success.jsonl` 为输入，保留 `input_files`、`output_files` 和 `patches: [...]` 作为训练监督，只额外加入 edit 前本地 HTML 截图。正式字段包括 `task="image-editing"`、`input_images=["images/{instance_id}/src_screenshots/screenshot_index.jpg"]`、`src_screenshot` 同步指向同一路径，`metadata.base_task="text-editing"`、`metadata.screenshot_state="before_edit"`。不要把 edit 后截图作为 image-edit 的输入监督。

10. 已新增正式构造脚本 `scripts/build_oss_image_editing_dataset.py`。脚本默认拒绝写入非空输出目录，避免覆盖已有数据；输出 `image-editing.unified.success.jsonl`、`image-editing.unified.failed.jsonl`、`manifest_image_editing.jsonl`、`images/` 和 `_summary.json`。按安全要求，脚本不删除数据盘上的旧目录或历史文件。

11. `image-editing` 小规模验证结果：基于 `/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/pilot_1100_for_url_stats/text-editing.unified.success.jsonl`，先跑 20 条到 `/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_editing_v1_precheck_20`，再跑 100 条到 `/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_editing_v1_precheck_100`。100 条结果为 `ok=100, failed=0`，`image_count=1595`、`loaded_image_count=1595`、`loadable_image_count=1595`、`loaded_loadable_image_count=1595`、`visible_loadable_image_count=810`、`loaded_visible_loadable_image_count=810`，`miss_count=0`，schema 校验 `schema_errors=0`，`patch_count` 范围为 1 到 8。

12. 验证 JSONL 时不要使用 `Path.read_text().splitlines()` 来切分记录；网页代码中可能含 Unicode 行分隔符，`splitlines()` 会把单条 JSON 误切开。应使用 `for line in open(..., "rb")` 或文本文件对象逐物理行读取。

13. `image-repair` 训练集组织方式：以 `text-repair.unified.success.jsonl` 为输入，当前统一后的 repair 语义是 `input_files=buggy code`、`output_files=fixed code`、`patches=[buggy -> fixed]`。因此不要再反向注入 bug；直接对 `input_files` 截 repair 前 buggy 图，写入 `input_images` 和 `src_screenshot`；对 `output_files` 截 repair 后 fixed 图，写入 `dst_screenshot`。输出仍然保留 `patches: [...]` 作为训练目标。

14. 已新增正式构造脚本 `scripts/build_oss_image_repair_dataset.py`。输出字段包括 `task="image-repair"`、`input_images=["images/{instance_id}/src_screenshots/screenshot_index.jpg"]`、`src_screenshot`、`dst_screenshot=["images/{instance_id}/dst_screenshots/screenshot_index.jpg"]`、`input_files`、`output_files`、`patches`。脚本支持 `--workers` 并发和 `--site-timeout` 单样本硬超时。

15. `image-repair` 小规模验证结果：基于 `/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/pilot_1100_for_url_stats/text-repair.unified.success.jsonl`，5 条预检查目录为 `/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_repair_v1_precheck_5`，20 条预检查目录为 `/data1/xieqianqian/webcoding/datasets/oss/data-disclosure/opencoder/xwh/webcoding260622_processed/image_repair_v1_precheck_20`。20 条结果为 `ok=20, failed=0`，src/dst 两侧图片均 `279/279` 加载，`src_miss_count=0`、`dst_miss_count=0`，schema 校验 `errors=0`，`patch_count` 范围为 1 到 2。注意部分 repair 类型如 Missing Attributes 视觉前后可能几乎一致，属于任务属性而非截图失败。

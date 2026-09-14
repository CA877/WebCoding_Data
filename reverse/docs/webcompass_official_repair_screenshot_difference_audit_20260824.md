# WebCompass 官方 Repair 注入前后截图差异抽查

日期：2026-08-24

## 结论

基于 WebCompass 官方数据集固定版本 `bde80d4f4cc09f9cfa763fd3bb047d3cdb302eb0` 的分层随机抽查：

- 单页 Repair：抽查 10 条，10/10 条的官方 `src/dst` Playwright 截图存在像素差异。
- 多页 Repair：抽查 10 条、共 40 页，10/10 条样本至少有一页存在差异；34/40 页存在差异，6/40 页完全一致。
- 多页 Repair 中只有 6/10 条做到每一页都有差异；另外 4/10 条分别有 1—2 页没有任何截图差异。

因此，抽查支持两个不同层级的判断：

1. 这 10 条多页 Repair 样本在样本级都有可见变化。
2. 多页 Repair 不保证每一页都有可见变化。

这是一项 10+10 条样本抽查，不能据此断言官方全部 150 条单页和 150 条多页数据均满足同样比例。

## 数据与口径

- 数据源：[NJU-LINK/WebCompass](https://huggingface.co/datasets/NJU-LINK/WebCompass)
- 固定 revision：`bde80d4f4cc09f9cfa763fd3bb047d3cdb302eb0`
- Repair 总体：`sp=150`、`mp=150`
- 抽样：先按 `instance_id` 排序，再以固定种子无放回随机抽取；`sp` 使用种子 `20260824`，`mp` 使用种子 `20260825`
- 方向：`src_code/src_screenshot` 是缺陷注入后的 faulty source；`dst_code/dst_screenshot` 是注入前的 clean destination。[WebCompass 论文](https://arxiv.org/abs/2604.18224)将 Repair 描述为先以 clean prototype 作为 destination，再注入可观察前端缺陷构造 source；Repair patch 是该过程的逆操作。
- 主审计对象：数据集随样本发布的官方 `src_screenshot` 与 `dst_screenshot`，而不是当前网络环境下重新加载远程站点得到的图。
- 页面对应：`screenshot_<page>.jpg` 与 `<page>.html` 一一配对。
- 判定：解码为 RGB 后，只要尺寸不同或至少一个像素不同，就记为“存在差异”；同时记录 changed-pixel ratio、normalized RMSE、差异包围盒和文件 SHA-256。

全部 50 对页面截图成功完成比较，错误数为 0。差异最小的页面也检查了放大差分图；其变化集中在具体文本或控件区域，而不是整图 JPEG 噪声。

## 单页样本结果（10 条）

| instance_id | 有差异页/总页数 | 每页均有差异 | 改变像素比例 |
|---|---:|:---:|---:|
| `2655223_www.ChamplainAssistedLiving.com_L4_2` | 1/1 | 是 | 0.1143% |
| `2655223_www.ChamplainAssistedLiving.com_L5_0` | 1/1 | 是 | 49.7090% |
| `2727192_boecore.com__L5_0` | 1/1 | 是 | 1.3186% |
| `2744024_www.fforum.se_L5_0` | 1/1 | 是 | 42.7309% |
| `2876076_www.juuduu.com_L12_2` | 1/1 | 是 | 30.3875% |
| `3007421_thomannasphalt.com_L8_0` | 1/1 | 是 | 22.0728% |
| `4035856_www.glas-zo.nl_L7_0` | 1/1 | 是 | 14.4581% |
| `4035856_www.glas-zo.nl_L9_1` | 1/1 | 是 | 36.0483% |
| `5035858_www.botmancreatief.nl_L4_1` | 1/1 | 是 | 2.3175% |
| `993724_vivalamovie.com_L11_2` | 1/1 | 是 | 45.7921% |

## 多页样本结果（10 条，每条 4 页）

| instance_id | 有差异页/总页数 | 每页均有差异 | 完全一致页面 |
|---|---:|:---:|---|
| `1047829_www.evolvemediallc.com_L12_0` | 4/4 | 是 | — |
| `2663214_lpdengineering.com_L5_2` | 2/4 | 否 | `about.html`, `services.html` |
| `2695592_www.usbioclean.com_L11_0` | 4/4 | 是 | — |
| `2758208_www.somocreative.co.nz_L8_1` | 4/4 | 是 | — |
| `2761982_www.constructionbyaffinity.com_L11_1` | 3/4 | 否 | `services.html` |
| `2847874_owaves.com_L10_0` | 4/4 | 是 | — |
| `2847874_owaves.com_L4_1` | 4/4 | 是 | — |
| `2876076_www.juuduu.com_L4_1` | 4/4 | 是 | — |
| `2876672_pragmata.institute_en_L7_0` | 2/4 | 否 | `contact.html`, `index.html` |
| `4010739_www.aboveair.com_L5_1` | 3/4 | 否 | `services.html` |

## 六个“完全一致页”的复核

这 6 对 `src/dst` 图片满足以下全部条件：相同尺寸、改变像素数为 0、RMSE 为 0、差异包围盒为空、文件 SHA-256 相同。它们不是“变化很小”或“低于阈值”，而是官方发布的两张截图文件完全相同。

| instance_id / page | 页面代码是否改变 | 代码变化为何可能不改变静态截图 |
|---|:---:|---|
| `2663214_lpdengineering.com_L5_2/about.html` | 是 | 删除图片 `alt`，属于无障碍语义变化，正常渲染时不改变像素。 |
| `2663214_lpdengineering.com_L5_2/services.html` | 是 | 注入的覆盖层节点在该页面最终样式/状态下没有形成可见差异。 |
| `2876672_pragmata.institute_en_L7_0/contact.html` | 是 | 移除 `lang`、禁用链接指针事件，主要影响语义与交互。 |
| `2876672_pragmata.institute_en_L7_0/index.html` | 是 | `hreflang` 和嵌套链接结构发生变化，但官方静态全页截图不变。 |
| `2761982_www.constructionbyaffinity.com_L11_1/services.html` | 是 | 禁用链接点击、改变链接内部结构，主要影响交互/DOM 语义。 |
| `4010739_www.aboveair.com_L5_1/services.html` | 否 | 该多页样本只修改 `about.html`、`contact.html`、`index.html`。 |

由此可见，至少存在两类“某页没有截图差异”的机制：该页没有被修改；该页被修改，但修改是语义/交互型或在当前静态渲染状态中不可见。

## 本地重渲染诊断与主结论边界

另行使用 Chromium/Playwright 以 1280×720、full-page、每个状态重复两次的方式重渲染了 50 个页面；该实验用于检查代码可运行性与动态截图噪声。50 页均成功渲染，声明的本地资源缺失数为 0，只有 2 页出现非零重复捕获波动。

部分 HTML 仍引用站点远程 CSS。离线重渲染阻断远程请求后，页面外观可能与数据集制作时不同，因此本地重渲染结果不作为“官方注入前后截图是否有差异”的主口径。最终统计完全来自数据集发布的官方 `src/dst` Playwright 截图。

## 可复核产物

- `runs/webcompass_official_repair_visual_diff_sample20_20260824_v1/sample_manifest.json`：固定 revision、抽样 ID 与原始记录
- `runs/webcompass_official_repair_visual_diff_sample20_20260824_v1/official_screenshot_audit_results.jsonl`：50 页逐页结果
- `runs/webcompass_official_repair_visual_diff_sample20_20260824_v1/official_screenshot_audit_summary.json`：样本级与 split 级汇总
- `runs/webcompass_official_repair_visual_diff_sample20_20260824_v1/official_screenshot_diffs/`：50 张四倍放大差分图
- `runs/webcompass_official_repair_visual_diff_sample20_20260824_v1/audit_results.jsonl`：本地重复重渲染诊断
- `scripts/audit_official_webcompass_repair_visual_diffs.py`：下载、抽样、渲染与比较脚本
- `tests/test_audit_official_webcompass_repair_visual_diffs.py`：8 项单元测试
- `logs/webcompass_official_repair_visual_diff/webcompass_official_repair_visual_diff_sample20_20260824_v1/`：各阶段持久化日志与退出状态

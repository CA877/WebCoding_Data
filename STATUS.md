# Pipeline 状态总结（2026-06-02）

## 整体目标

构建 70K 训练集（7 类任务 × 10K），当前阶段：预处理 31,765 个 WebRenderBench 项目（Pipeline A）和 45,477 个 URL（Pipeline B）。

---

## 代码改动（已 push GitHub）

| 文件 | 改动 |
|------|------|
| `pipeline_a_sample_level.py` | --no-expand 跳过 expand，单页 add_js 先跑，timeout 40s，LLM API 直连 |
| `pipeline_b_sample_level.py` | 单页/多页分离存储 |
| `playwright_crawl.py` | snapshot_page 双重策略（commit→domcontentloaded），累计失败 3 次停，validate 阈值 200→50 |
| `add_js.py` | retry 从 [10,30,60] 降到 [5]，加 invalid token 检测 |
| `run_pipeline_a_fast.sh` | 新：clean+add_js 跳过 expand，30 并发，300s 超时，JS 全量 |
| `run_pipeline_a_fast_test.sh` | fast 模式 10 样本测试 |
| `run_pipeline_a_clean_only.sh` | 纯 clean 不调 LLM |
| `.env` | 配好代理和 API key |

---

## 已验证的发现

### 1. API（glm-5.1 @ app.ppapi.ai）
- **50 并发 100% 成功**，avg 7s，max 11s
- 直连不走代理即可，`httpx.Client(proxy=None)`

### 2. clean 步骤
- **真的在干活**：bviyachtsales.com 下载了 39 个文件、8MB，0 残留远程引用
- 重型项目 ~120s（通过代理下载），轻型 ~5s
- `MAX_RESOURCES_PER_PAGE=50` 限制不会无限等

### 3. expand 步骤
- **纯 HTML expand 很快**：20s 内搞定 3 个子页面
- 域名死的是真死了，活的有内容（38KB~679KB）
- bviyachtsales.com 域名 curl 200 但 Playwright 打不开（反爬/代理兼容性）

### 4. 网络
- h-liu 可直连外网（Google/GitHub/Wikipedia 全通）
- 代理 `httpproxy-headless.kubebrain.svc.pjlab.local:3128` 对浏览器流量兼容性一般
- CDN（jQuery/Bootstrap）全活着
- 图片下载需要走代理（picsum.photos 直连超时）

---

## 待解决问题

### 🔴 add_js 全部失败（当前阻塞）
- `build_code_context` 返回 0 字符，`read_code_bundle` 找不到文件
- 根因：`construct/construct_common.py` 的 `CODE_EXTS` 导入在子进程中失败
- 大概率是 `__pycache__` 没清干净
- **修复**：彻底清 pycache 后重启

### 🟡 Pipeline B 前 224 条被污染
- 首次跑并发过高，Chromium EPIPE 崩溃，这 224 条被错误标记
- 已写在 `TODO.md`，后续需重新处理

### 🟡 expand 策略待最终确定
- 纯 HTML expand 只需 20s，可以加到 fast 模式后面
- 但需要先修好 add_js 才能跑全量

### 🟢 服务器容量
- 17GB 内存，130+ Chromium 会崩（之前验证过）
- 安全并发：纯 clean+add_js 30-50 并发；expand 模式 10-15 并发

---

## 当前产出

| 来源 | 样本数 | 位置 |
|------|:--:|------|
| run_a15000 | ~1,300 单页 + 19 多页 | `pipeline_a/runs/run_a15000/` |
| run_single | 887 单页（全超时） | `pipeline_a/runs/run_single/` |
| run_a_fast | ~30 单页（add_js 失败） | `pipeline_a/runs/run_a_fast/` |
| run_b15000 | 315 单页 + 131 多页 | `pipeline_b/runs/run_b15000/` |

**有效可用**：约 1,765 样本（需清掉被污染的重新跑）

---

## 下一步

1. **立即**：清 pycache → 重启 `run_pipeline_a_fast.sh`（clean+add_js）
2. **之后**：验证 add_js 成功率，确保 31K 单页产出
3. **再后**：跑 expand 追加拿页 → B 重新跑 → 合流进入 construct 阶段

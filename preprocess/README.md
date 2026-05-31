# preprocess/ — 数据预处理流水线

## 目标

把原始网页数据变成**离线可渲染的自包含项目**，供后续 `construct/` 构造训练任务。

每个输出项目长这样：
```
project_dir/
  index.html       ← 主页（CSS 已 inline，图片已本地化）
  about.html       ← 子页面（可选，多页项目才有）
  services.html
  resources/       ← 下载的图片/字体
```

用浏览器直接 `file://` 打开 `index.html` 就能完整渲染，不需要任何网络。

---

## 数据来源

| 来源 | 说明 | 贡献 |
|------|------|------|
| WebRenderBench | 已有 31,765 个单页 HTML 快照 | SP（单页）主力 |
| WebCode2M | HuggingFace 上 300 万条 HTML 样本 | 提取域名 → 重爬新站 |

---

## 两个脚本

### `extract_webcode2m_urls.py`

从 WebCode2M 的 HuggingFace API 批量取样本，提取其中的域名 URL。

```bash
export ALL_PROXY=socks5h://127.0.0.1:13659
python3 preprocess/extract_webcode2m_urls.py \
  --output webcode2m_urls.txt \
  --max-rows 100000
```

输出：一个文本文件，每行一个 URL。预期 ~35,000 个可爬取域名。

### `playwright_crawl.py`

主力脚本，三个子命令：

| 子命令 | 输入 | 输出 | 做什么 |
|--------|------|------|--------|
| `crawl` | URL 列表 | 新项目目录 | 访问网站，截取首页 + 子页面 |
| `expand` | 现有单页项目 | 多页项目 | 给已有项目追加子页面 |
| `clean` | 任何项目 | 原地清洗 | 下载远程图片、去噪、中和外链 |

---

## 完整流程（按执行顺序）

### Step 0: 准备 WebRenderBench 数据

假设你有 WebRenderBench 31,765 个项目在 `/data/webrenderbench_31765/`，每个目录里有一个 `index.html`。

### Step 1: 扩展为多页（expand）

从 index.html 中发现导航链接，用 Playwright 真实浏览这些链接，把子页面截取下来。

```bash
python3 preprocess/playwright_crawl.py \
  --browser-proxy "socks5://127.0.0.1:13659" \
  --requests-proxy "socks5h://127.0.0.1:13659" \
  --max-pages 4 --wait 4000 --concurrency 5 \
  expand \
  --input-dir /data/webrenderbench_31765/ \
  --output-dir /data/expanded/
```

**这一步做了什么（通俗解释）：**
1. 打开 index.html，找到页面上的导航菜单（"关于我们"、"服务"、"联系"这些链接）
2. 用真实浏览器访问每个链接，等页面渲染完
3. 把渲染后的 HTML 保存为 `about.html`、`services.html` 等
4. 把页面间的链接改成互相指向本地文件（不再指向互联网）
5. 如果一个项目找不到导航链接或所有子页面都打不开，就跳过

### Step 2: 清洗（clean）

把所有项目（不管是扩展后的还是原始的）统一清洗：

```bash
python3 preprocess/playwright_crawl.py \
  --requests-proxy "socks5h://127.0.0.1:13659" \
  --concurrency 10 \
  clean \
  --input-dir /data/expanded/
```

**这一步做了什么（通俗解释）：**
1. **图片本地化**：找到 HTML 里所有 `<img src="https://...">` 的远程图片
   - 能下载的 → 保存到 `resources/` 目录，HTML 改为 `src="./resources/xxx.jpg"`
   - 下载失败的 → 替换为 `https://picsum.photos/id/42/800/600` 这种稳定占位 URL
   - 每页最多下载 50 张（防止超大页面卡住），超过的用 picsum URL
2. **删除脚本**：移除所有 `<script>` 标签（训练不需要 JS）
3. **删除 iframe**：移除嵌入的 YouTube、地图等
4. **删除音视频**：移除 `<video>`/`<audio>`（太大）
5. **中和外部链接**：所有 `<a href="https://...">` 改为 `href="#"`
6. **内联远程 CSS**：如果有 `<link rel="stylesheet" href="https://...">` 还没内联的，下载并内联
7. **清理特殊属性**：移除 `data-cke-saved-src`、`nitro-lazy-src` 等泄露远程 URL 的属性

### Step 3: 爬取新站（crawl）

用 Step 0 的 URL 列表爬取全新的网站：

```bash
python3 preprocess/playwright_crawl.py \
  --browser-proxy "socks5://127.0.0.1:13659" \
  --requests-proxy "socks5h://127.0.0.1:13659" \
  --max-pages 4 --wait 3000 --concurrency 5 \
  crawl \
  --url-file webcode2m_urls.txt \
  --output-dir /data/crawled/
```

**这一步做了什么：**
1. 对每个 URL，用 Playwright 打开网站首页
2. 等待页面渲染，用 JS 把所有 CSS 内联到 HTML 里（不再依赖外部 .css 文件）
3. 检测语言（只保留中/英文）
4. 找导航链接，继续爬子页面（最多 4 个）
5. 下载图片到 `resources/`
6. 输出一个完整的多页项目

爬完之后，再跑一遍 `clean` 确保干净。

---

## 顺序很重要

```
expand（需要真实外链来找子页面）
  → clean（中和外链、下载图片）
```

**不能反过来！** clean 会把外部链接改成 `#`，之后 expand 就找不到导航链接了。

---

## 代理配置

本项目需要通过代理访问外网（Mac 上使用 AliMgrSoc SOCKS5 代理）：

| 用途 | 参数 | 格式 | 原因 |
|------|------|------|------|
| Playwright/Chromium | `--browser-proxy` | `socks5://127.0.0.1:13659` | Chromium 不支持 socks5h |
| requests 库 | `--requests-proxy` | `socks5h://127.0.0.1:13659` | h=远程 DNS，绕过 DNS 污染 |

服务器如果有直连网络，两个参数都传空字符串 `""`。

---

## 图片处理策略

| 情况 | 处理方式 |
|------|---------|
| 远程完整 URL 图片 | 通过代理下载到 `resources/` |
| 下载失败 | 用 `https://picsum.photos/id/{N}/800/600` 占位 |
| 超过 50 张/页 | 超出的用 picsum URL（不删除标签，保护布局） |
| Base64 data: URI | 保留不动 |
| CSS background-image | 同上逻辑下载/替换 |

picsum.photos 使用固定 ID 池 (10-110)，同一网站只有 ID 数字不同，方便模型记忆 URL 模式。

---

## 质量保证

清洗后每个项目满足：
- ✅ 零远程图片引用（全部本地化或 picsum 占位）
- ✅ 零远程 CSS（全部 inline）
- ✅ 零外部链接（全部 `#` 或本地文件）
- ✅ 零 JavaScript
- ✅ 文本内容 ≥ 50 字符
- ✅ 语言为中文或英文

---

## 并发与性能

| 参数 | Mac M4 16GB | 服务器 64GB |
|------|-------------|-------------|
| `--concurrency` | 3-5 | 15-20 |
| expand 耗时/项目 | 30-60s | 10-20s |
| clean 耗时/项目 | 5-15s | 3-8s |

所有子命令都支持 `--concurrency` 参数。断点续传：已完成的项目会自动跳过。

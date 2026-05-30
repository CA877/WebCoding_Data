# 数据爬取 Pipeline 说明

## 总目标

构造 70K 训练样本（7 类任务 × 10K），每类任务由单页(SP)和多页(MP)组成。

## 数据量规划

| 任务 | SP | MP | 合计 |
|------|----|----|------|
| text-gen | 6K | 4K | 10K |
| image-gen | 6K | 4K | 10K |
| video-gen | 8K | 2K | 10K |
| text-edit | 5K | 5K | 10K |
| image-edit | 5K | 5K | 10K |
| text-repair | 5K | 5K | 10K |
| image-repair | 5K | 5K | 10K |
| **合计** | **40K SP** | **30K MP** | **70K** |

## 底层页面需求

- SP 和 MP 是不同样本（同一个项目扩展成 MP 后，原始 SP 版本仍然有效）
- 同一个页面可以跨模态复用（text-gen 和 image-gen 用同一个页面合理）
- **不允许**同类型任务内复用

### 来源与预期数量

| 来源 | SP 贡献 | MP 贡献 | 备注 |
|------|---------|---------|------|
| WebRenderBench 已筛选 | 31,765 SP | — | 直接可用 |
| WebRenderBench 扩展 | — | ~15K MP | 50% 扩展成功率 |
| WebCode2M 域名重爬 | +15K SP | +15K MP | 每个站首页=SP, 子页面=MP |
| **合计** | ~47K SP | ~30K MP | 充足 |

## 三步流水线

### Step 1: WebRenderBench 清洗与扩展

```bash
# 扩展已有项目为多页
python3 preprocess/playwright_crawl.py \
  --browser-proxy "socks5://127.0.0.1:13659" \
  --requests-proxy "socks5h://127.0.0.1:13659" \
  --max-pages 4 --wait 4000 \
  expand \
  --input-dir /path/to/webrenderbench_31765/ \
  --output-dir /path/to/expanded/

# 清洗未扩展的项目（下载远程图片）
python3 preprocess/playwright_crawl.py \
  --requests-proxy "socks5h://127.0.0.1:13659" \
  clean \
  --input-dir /path/to/webrenderbench_31765/
```

### Step 2: 从 WebCode2M 提取域名 URL

```bash
# 从 HuggingFace API 提取可爬取的域名
python3 preprocess/extract_webcode2m_urls.py \
  --output webcode2m_urls.txt \
  --max-rows 100000 \
  --proxy "socks5h://127.0.0.1:13659"
```

预期输出：~35,000 个可用 URL（100K rows × 35% yield）。

### Step 3: 爬取新网站

```bash
# 从 URL 列表批量爬取
python3 preprocess/playwright_crawl.py \
  --browser-proxy "socks5://127.0.0.1:13659" \
  --requests-proxy "socks5h://127.0.0.1:13659" \
  --max-pages 4 --wait 3000 --concurrency 5 \
  crawl \
  --url-file webcode2m_urls.txt \
  --output-dir /path/to/crawled/
```

## 代理配置

### 当前 Mac（M4 笔记本）

代理软件：AliMgrSoc，监听 `127.0.0.1:13659`（SOCKS5）

- Playwright/Chromium: `--browser-proxy "socks5://127.0.0.1:13659"`
  - 必须用 `socks5://`（不带 h），因为 Chromium 不支持 socks5h
  - 本地 DNS 解析域名，然后通过代理建立连接
- requests 库: `--requests-proxy "socks5h://127.0.0.1:13659"`
  - `socks5h://` 让 DNS 解析也通过代理（远程 DNS）
  - 这对于被 DNS 污染的域名更可靠

### 服务器配置（需要确认）

如果服务器有直接互联网访问：
```bash
python3 preprocess/playwright_crawl.py \
  --browser-proxy "" \
  --requests-proxy "" \
  ...
```

如果服务器也需要代理：
```bash
# 替换为服务器上的代理地址
python3 preprocess/playwright_crawl.py \
  --browser-proxy "socks5://SERVER_PROXY_IP:PORT" \
  --requests-proxy "socks5h://SERVER_PROXY_IP:PORT" \
  ...
```

## 性能与并发

| 环境 | 推荐并发 | 每项目耗时 | 15K 项目估计 |
|------|---------|-----------|-------------|
| Mac M4 16GB | 3-5 | 30-60s | 42-83h（不推荐） |
| 服务器 64GB | 15-20 | 20-40s | 5-11h |
| 服务器（直连） | 20-30 | 10-20s | 2-6h |

## 图片处理策略

1. **远程 URL 图片** → 通过代理下载到 `resources/`
2. **下载失败** → 使用 placehold.co 占位图（确认可通过代理访问）
3. **CSS 背景图** → 同上策略
4. **Base64 data: URI** → 保留不动
5. **已本地化的** → 保留不动

## 质量保证

每个输出项目满足：
- [ ] 无远程图片引用（全部本地化或占位）
- [ ] 无远程 CSS 引用（Playwright 自动 inline）
- [ ] 无外部链接（全部 neutralize 为 `#`）
- [ ] 多页项目页面间有导航跳转
- [ ] 文本内容 ≥ 50 字符
- [ ] 语言为中文或英文

## 文件结构

```
preprocess/
  playwright_crawl.py      # 主爬取脚本（crawl/expand/clean 三个子命令）
  extract_webcode2m_urls.py # 从 WebCode2M 提取域名
  expand_multipage.py       # 旧版多页扩展（requests-based，已废弃）
  url2html_snapshot.py      # 单页 snapshot 工具（用于验证）
  PIPELINE.md               # 本文档
```

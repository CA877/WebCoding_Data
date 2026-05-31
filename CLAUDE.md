# CLAUDE.md

## 沟通偏好

- 始终使用中文与用户对话

## 项目目标

构建 WebCode2M 训练集，刷 4 个榜单：WebCompass、Design2Code、Vision2Web、FLAME-VLM-Code。

所有榜单都不要求模型输出远程 URL。训练数据统一用 `assets/` 本地相对路径。

## 项目结构

- `preprocess/` — 数据清洗（下载、去噪、图片本地化）
- `construct/` — 7类任务构造（text-gen, image-gen, video-gen, text-edit, image-edit, text-repair, image-repair）
- `local_trials/` — 本地试验与分析脚本

## 关键技术约束

- WebCode2M 样本的 CSS 已 inline（无远程 CSS 问题）
- 图片处理：远程 URL → 下载到 resources/；失败的 → picsum.photos URL 占位（不下载，保留 URL 让模型学习）
- HuggingFace 使用镜像站 `HF_ENDPOINT=https://hf-mirror.com`
- 运行需要外网的脚本必须设置代理 `socks5h://127.0.0.1:13659`

## 数据流

```
WebRenderBench (31,765 单页 HTML)
  → expand（扩展为多页）→ clean（图片本地化、去噪）

WebCode2M (HuggingFace API)
  → extract_webcode2m_urls.py 提取域名
  → crawl（Playwright 爬取）→ clean

清洗后数据 → construct/ 构造 7 类任务 → 70K 训练集
```

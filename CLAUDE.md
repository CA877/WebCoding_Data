# CLAUDE.md

## 沟通偏好

- 始终使用中文与用户对话

## 项目目标

构建 70K 训练集（7 类任务 × 10K），刷 4 个榜单：WebCompass、Design2Code、Vision2Web、FLAME-VLM-Code。

所有榜单都不要求模型输出远程 URL。训练数据统一用 `assets/` 本地相对路径。

## 项目结构

- `preprocess/` — 数据预处理（两条 Pipeline 并行）
  - Pipeline A: WebRenderBench 31,765 个单页 HTML → expand → clean → add_js（LLM 生成 JS，ratio=0.5）
  - Pipeline B: WebCode2M 28K URL → crawl → postprocess（保留网站原生 JS，无 LLM 调用）
  - 入口脚本: `pipeline_a_sample_level.py` / `pipeline_b_sample_level.py`
  - 服务器运行: `run_server.sh`（并行执行 A+B，A 并发 50，B 并发 100）
- `construct/` — 7 类任务构造（text-gen, image-gen, video-gen, text-edit, image-edit, text-repair, image-repair）
  - `add_js.py` — 43 种 JS 功能目录，确定性分配 4-7 个功能/项目
- `local_trials/` — 本地试验与分析脚本

## 关键技术约束

- Pipeline A 的 CSS 已 inline；Pipeline B 爬取的是真实网站（自带 CSS/JS）
- 图片处理：远程 URL → 下载到 resources/；失败的 → picsum.photos URL 占位
- Pipeline A 调 LLM 生成 JS（50% 项目），Pipeline B 不调 LLM
- HuggingFace 使用镜像站 `HF_ENDPOINT=https://hf-mirror.com`
- 本地开发代理 `socks5h://127.0.0.1:13659`；服务器用 HTTP 代理

## 数据流

```
Phase 1: 预处理（并行，~16h）
├── Pipeline A: WebRenderBench (12K 项目 → ~15K 可用变体)
│   expand → clean → add_js(ratio=0.5)
└── Pipeline B: WebCode2M (28K URL → ~15K 可用项目)
    crawl → postprocess（保留原生 JS）

Phase 1.5: CSS 拆分（TODO）
Phase 2: 任务构造 → 7 × 10K = 70K 训练样本
```

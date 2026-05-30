# CLAUDE.md

## 项目目标

构建 WebCode2M 训练集，刷 4 个榜单：WebCompass、Design2Code、Vision2Web、FLAME-VLM-Code。

所有榜单都不要求模型输出远程 URL。训练数据统一用 `assets/` 本地相对路径。

## 项目结构

- `preprocess/` — 数据清洗（下载、去噪、图片本地化）
- `construct/` — 7类任务构造（text-gen, image-gen, video-gen, text-edit, image-edit, text-repair, image-repair）
- `local_trials/` — 本地试验与分析脚本

## 关键技术约束

- WebCode2M 样本的 CSS 已 inline（无远程 CSS 问题）
- 图片处理：远程 URL → 下载到 assets/；相对路径 → picsum 占位图下载到 assets/
- HuggingFace 使用镜像站 `HF_ENDPOINT=https://hf-mirror.com`
- 运行需要外网的脚本必须设置代理 `socks5h://127.0.0.1:13659`

## 数据流

```
WebCode2M (HuggingFace rows API)
  → 下载原始 HTML
  → preprocess/ 清洗 (CSS inline, 图片本地化, 去噪)
  → construct/ 构造 7 类任务
  → 训练集
```

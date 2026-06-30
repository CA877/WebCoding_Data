# WebCompass 数据构造方案（@qianqian 部分）

## 一、基于 Image 生成

### 1.1 逆向构造（有标准答案）
- 输入：已有网页的源码 + 截图
- 流程：
  1. 用 Playwright 对网页截多张图（不同视口、不同页面）
  2. 将截图 + 源码送入多模态 LLM，生成详细的 description（即 query）
  3. 源码作为 ground truth
  4. 按 WebCompass 格式输出 JSON（含 problem_statement/checklist）
- 数据来源：
  - webrenderbench 已有数据（需要用 agent 重新完整抓取源码）
  - 自己爬取高质量网页

### 1.2 正向构造（无标准答案）
- 流程：
  1. 给定目标 URL 列表
  2. 用 Playwright 访问并截图
  3. 用多模态 LLM 根据截图写 caption（即 query）
  4. 不提供 ground truth，只提供 query + 截图
- 输出格式：与 `webcompass_samples/image-generation/` 一致

## 二、基于 Video 生成

- 参考 image 方案
- 流程：
  1. 录制/获取网页交互视频（或用 Playwright 自动录屏）
  2. 用 ffmpeg 提取关键帧
  3. 将帧序列送入多模态 LLM 生成 description
  4. 按 WebCompass video-generation 格式输出
- 与 image 的区别：video 强调交互和动画的时序描述

## 三、Edit 任务构造

### 3.1 从 Generate 中间状态构造
- 在 agent 生成网页过程中，每个可运行的中间版本作为 edit 的起点
- 下一个版本的变更作为 edit 的 description
- 需要 agent 在生成过程中用 git commit 记录中间状态

### 3.2 从 GitHub Commit Diff 构造
- 流程：
  1. 在 GitHub 上搜索前端项目（HTML/CSS/JS）
  2. 遍历 commit history，筛选有意义的 diff（非 merge、非大规模重构）
  3. checkout 到 parent commit 作为 src_code
  4. 用 LLM 根据 diff 内容生成自然语言 edit description
  5. 按 `webcompass_samples/editing/` 格式输出

## 四、输出格式

所有 pipeline 输出 JSONL，每行一条数据，字段与 `webcompass_samples/` 中对应任务格式一致。

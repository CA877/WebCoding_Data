# 四个 Benchmark 调研

> 2026-05-30 调研

## 一句话总结

| Benchmark | 模型输出 | CSS | JS | 评估 |
|-----------|---------|-----|-----|------|
| **WebCompass** | 多文件 `index.html` + `styles.css` + `script.js` | **单独文件** | **单独文件** | Agent + LLM-as-Judge |
| **Design2Code** | 单个 HTML | **inline `<style>`** | inline / 无 | 视觉相似度 (Block/Text/Position/Color/CLIP) |
| **Vision2Web** | 完整项目目录 (不限技术栈) | 不限 | 不限 | GUI Agent 功能验证 + VLM 视觉评分 |
| **FLAME-VLM-Code** | React 组件 `component.js` + `style.css` | **单独文件** | **React JSX** | 截图相似度 + 代码结构相似度 |

---

## WebCompass

**来源**: NJU-LINK / Kwaipilot, arXiv:2604.18224

**规模**: 933 题 = Generation(333) + Editing(300) + Repair(300), 单页/多页各半

### 输入

| 任务类型 | 输入 |
|----------|------|
| Text Generation (123) | 设计文档 (PRD) |
| Image Generation (116) | 参考截图 |
| Video Generation (94) | 操作视频 (自动提取关键帧) |
| Editing (300) | 已有代码 + 修改指令 |
| Repair (300) | 有 bug 代码 + 目标描述 |

### 输出格式

模型用 Markdown 输出多文件，每个文件用 `# path/to/file.ext` + 代码块：

```
index.html      ← <link href="styles.css"> + <script src="script.js">
styles.css       ← 单独 CSS 文件
script.js        ← 单独 JS 文件
```

**Prompt 明确要求**: "Use HTML, CSS, and JavaScript only. No frameworks or build tools required."

### 评估

- **Runnability (~10%)**: 页面能否加载，Console 有无报错
- **Spec Implementation (~60-70%)**: Claude Code agent 在 Docker 中按 checklist 验证功能
- **Design Quality (~20-25%)**: VLM 对比截图评分

### 对训练数据的要求

1. **必须分文件**：HTML/CSS/JS 三个独立文件，不能 inline
2. **JS 必须有**：agent 会检查交互功能
3. **单页+多页**：约各占 50%
4. Console 零错误

---

## Design2Code

**来源**: Stanford SALT Lab, arXiv:2403.03163

**规模**: 484 + 80 (Hard) = 564 测试用例

### 输入

单张网页截图 (PNG)

### 输出格式

**单个 HTML 文件**，CSS 全部 inline 在 `<style>` 标签中。图片用 `rick.jpg` 占位。

```html
<!DOCTYPE html>
<html>
<head><style>/* all CSS here */</style></head>
<body><!-- content --></body>
</html>
```

### 评估

5 个自动指标，按元素粒度分解：
- Block-Match: HTML 块匹配
- Text: 文本内容
- Position: 布局位置
- Color: 颜色准确度
- CLIP: 整体视觉相似度

### 对训练数据的要求

1. 单文件 HTML，CSS inline — **和我们当前的数据格式一致**
2. 不需要 JS
3. 图片用占位符

---

## Vision2Web

**来源**: Tsinghua / zai-org, arXiv:2603.26648 (ICML 2026 Spotlight)

**规模**: 193 任务, 918 原型图, 1255 测试用例

### 三个层级

| Level | 任务 | 输入 | 输出 | 评估 |
|-------|------|------|------|------|
| L1: Static (100) | 静态响应式页面 | 三种视口原型图 | 可运行网站 | 仅视觉 |
| L2: Interactive (66) | 多页交互前端 | 原型图 + 文本需求 | 多页交互项目 | 视觉 + 功能 |
| L3: Full-Stack (27) | 全栈系统 | 原型图 + PRD 文档 | 全栈项目 | 视觉 + 功能 |

### 输出格式

面向 coding agent（OpenHands / Claude Code），提交完整项目目录 + `start.sh` 部署脚本。**不限技术栈**，可用 React/Vue/原生 HTML。

### 评估

- **Visual Score**: VLM 对比原型图与实际截图
- **Functional Score**: GUI Agent 按 `workflow.json` 执行操作验证功能

### 对训练数据的要求

1. 多文件项目格式
2. L2/L3 需要 JS 交互
3. 响应式布局（desktop/tablet/mobile 三种视口）
4. 更依赖 agent 能力，对单次输出格式要求宽松

---

## FLAME-VLM-Code

**来源**: arXiv:2503.01619

### 输入

组件截图（单图或多图迭代）

### 输出格式

**React 组件**，分两部分输出：

```
// CSS
.container { ... }

// JavaScript (JS)
import React from 'react';
import './style.css';
function Component() { return <div>...</div>; }
export default Component;
```

放入 create-react-app 模板的 `src/components/component.js` + `src/components/style.css`。

### 评估

- `npm start` 渲染 → 截图
- **img_similarity**: 图像编码器 (SigLIP) cosine similarity
- **code_similarity**: 代码结构对比
- 空白/报错截图视为失败

### 对训练数据的要求

1. **React 组件格式**，不是原生 HTML — 需要额外构造
2. CSS 单独文件
3. 需要 useState / useEffect 等 React hooks 的使用

---

## 关键结论：当前数据缺什么

| 需求 | 当前状态 | 差距 |
|------|---------|------|
| WebCompass 要求 CSS 单独文件 | CSS inline 在 HTML 中 | **需要拆分 CSS 到 styles.css** |
| WebCompass 要求 JS 单独文件 | main.js 已分离 | 已满足 |
| Design2Code 要求单文件+CSS inline | 当前就是这样 | 已满足 |
| Vision2Web 不限格式 | 当前多文件项目 | 基本满足 |
| FLAME 要求 React 组件 | 只有原生 HTML | **需要额外构造 React 格式** |

**最紧迫的工作**：
1. **CSS 拆分**：把 inline CSS 从 HTML 的 `<style>` 标签中提取到 `styles.css`，HTML 改为 `<link href="styles.css">`。WebCompass 和 Vision2Web 都受益。
2. **React 转换**（如果要刷 FLAME）：把原生 HTML+CSS 转换为 React 组件格式，但这是独立工作流，复杂度较高。

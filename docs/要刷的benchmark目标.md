# Benchmark 目标与数据规划

## 当前范围

本轮只规划和优化 **Text Generate 12,500 条**。以下为最终 Text 配额，不套用 Image Generate 的 screenshot-to-code 分布。Image Generate、Edit、Repair 的数据处理不在本轮范围内。

主要服务 ArtifactsBench、WebCompass、WebGen-Bench、MiniAppBench、Cookie-Bench、FrontendBench，并补充 DesignBench / Vision2Web 的工程能力。完整目标 benchmark 另含 Interaction2Code、Flame-VLM-Code，共 10 个。

## 总量规划

| 一级任务 | 目标数量 |
| --- | ---: |
| Text Generate | 12,500 |

## Text Generate 技术栈配额

| 类型 | 数量 | 比例 |
| --- | ---: | ---: |
| Vanilla HTML/CSS/JS | 6,000 | 48.0% |
| React + Vite | 5,000 | 40.0% |
| Vue 3 + Vite | 700 | 5.6% |
| React Full-stack | 500 | 4.0% |
| Angular | 300 | 2.4% |
| **总计** | **12,500** | **100%** |

## Text Generate 产品类型配额

| 类型 | 数量 | 比例 |
| --- | ---: | ---: |
| Dashboard / Management System | 1,100 | 8.8% |
| Tool / Productivity App | 1,300 | 10.4% |
| Editor / Creator | 900 | 7.2% |
| Form / Workflow App | 800 | 6.4% |
| E-commerce / Business App | 600 | 4.8% |
| Game | 1,500 | 12.0% |
| Simulation | 1,200 | 9.6% |
| SVG / Diagram Artifact | 800 | 6.4% |
| Canvas / Generative Art | 600 | 4.8% |
| Data Visualization | 900 | 7.2% |
| Multimedia App | 300 | 2.4% |
| Social / Communication App | 200 | 1.6% |
| Content / Landing / Portfolio | 500 | 4.0% |
| Multi-page Product Website | 1,100 | 8.8% |
| React Full-stack Application | 700 | 5.6% |
| **总计** | **12,500** | **100%** |

Game + Simulation + SVG + Canvas + Data Visualization 共 **5,000 条（40%）**。

## 技术栈与产品类型搭配

- Game / Simulation / SVG / Canvas：70–80% Vanilla。
- Dashboard / Tool / Editor：React 为主。
- Multi-page Website：React 为主，少量 Vanilla / Vue。
- Full-stack：全部 React。
- Form / Business App：Vanilla 与 React 均覆盖。
- Vue / Angular：主要覆盖 Dashboard、Tool、Business、Form。

**待统一的配额**：React Full-stack 技术栈 500 条，React Full-stack Application 产品类型 700 条；在“全栈全部 React”的约束下存在 200 条差额。保留两项原数，分类统计不自动调整配额。

## 细粒度任务

细粒度任务沿用下列分类；本轮未指定子类数量，不从此前 Text/Image 合计配额直接推导缺口。

| 大类 | 子类 |
| --- | --- |
| Game | Puzzle/Logic；Board/Card；Arcade/Reflex；Physics Game；Strategy/Management；Educational/Science；Drawing/Creative；Other |
| Simulation | Physics；Mathematics；Biology/Ecology；Chemistry/Science；Astronomy/Geography；Economics/Finance；Network/System；Social/Population；Other |
| SVG / Diagram | Flowchart/Process；Network/Graph；Timeline；Map-like；Infographic；Technical Diagram；Icon/Vector；Interactive SVG；Animated SVG |
| Canvas / Generative Art | Drawing/Paint；Particle System；Generative Art；Animation；Physics Visualization；Pixel/Sprite Editor；Interactive Geometry；Other |
| Data Visualization | Bar/Line/Area；Pie/Donut；Scatter/Bubble；Heatmap；Network Graph；Timeline；Spatial；Multi-chart Dashboard；Interactive Explorer |

## 标注与过量处理

每条 Text Generate 记录统一技术栈、任务大类、细粒度任务三个属性。纯规则分类，有歧义保留未确定；不能把页面中的图标、装饰 Canvas 或次要组件直接当作主任务。

过量样本先标注“待移除”，不删除。选择只依据配额，不等于质量判定；保留未知类别及已不足配额的已知类别。技术栈与类型目标分别统计，缺口不可相加；联合分布用于后续定向补充。

## 能力优先级

| 优先级 | 能力 | 主要覆盖 |
| --- | --- | --- |
| P0 | HTML5、CSS3、JavaScript、DOM、Browser API | 全部 benchmark |
| P0 | 前端交互：form、modal、tab、dropdown、drag/drop、状态切换 | ArtifactsBench、WebCompass、MiniAppBench、Cookie-Bench、FrontendBench、Interaction2Code |
| P0 | 视觉 artifact：SVG、Canvas、动画、Chart、Game、Simulation | ArtifactsBench、MiniAppBench、Cookie-Bench、WebCompass |
| P0 | React、TypeScript、Vite、React Router | WebCompass、Vision2Web、WebGen-Bench、Flame-VLM-Code、MiniAppBench、Cookie-Bench、DesignBench |
| P0 | Responsive / Screenshot-to-Code：Flex/Grid、breakpoint、多 viewport | Vision2Web、Flame-VLM-Code、DesignBench、WebCompass |
| P0 | 多文件前端工程：package、assets、routing、组件拆分 | WebGen-Bench、Vision2Web、Cookie-Bench、MiniAppBench、WebCompass |
| P0 | Edit / Repair：局部修改、错误定位、验证修复 | WebCompass、DesignBench |
| P1 | Vue 3 + Vite | WebCompass、DesignBench |
| P1 | Full-stack：React + Express + SQLite + REST | WebGen-Bench、Vision2Web L3 |
| P2 | Angular 基础组件和模板能力 | DesignBench |

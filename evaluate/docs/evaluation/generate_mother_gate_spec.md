
## 3. 母本准入目标

### 3.1 来源与许可可追踪

- 保存 `source_type`、原始 URL/仓库、最终跳转 URL、commit/snapshot、采集时间和许可证；
- 来源或许可证不明确的样本进入 `review/quarantine`，不能直接训练；
- 不包含 API key、cookie、token、密码、内部地址和私人敏感信息；
- 排除成人、赌博、诈骗、恶意下载等不允许训练的内容；
- 原始候选、清洗记录和最终项目分别保存，不能只留下不可追溯的处理结果。

### 3.2 完整项目与 40K

- 样本单位是完整项目，不是某个入口文件或代码片段；
- 枚举全部保留的 HTML/HTM/CSS/JS/JSX/TS/TSX 文件，按项目相对路径稳定序列化；
- 使用实际训练所用 Qwen tokenizer 精确计数；
- 完整代码必须 `<= 40,000` token；
- 超限整条拒绝，不截断、不只选主文件、不静默省略长文件或 bundle；
- 项目必须有明确入口，代码引用图、页面和路由可审计；
- 不接收只能依赖 node_modules、构建产物或不可读第三方 bundle 才能运行的项目。

40K 在这里是母本准入条件。虽然 text-generate 的输入不是原始代码，但母本后续需要作为完整代码上下文复用，因此不能在 generate 池中保留一个无法完整输入的项目。

### 3.3 资源与外链策略

最稳健的验证目标是 hermetic rendering：禁止外网后仍能得到同样页面。

正式批量接入新来源前，必须在 gate 配置中冻结三个会改变数据分布的选择：URL 新鲜度窗口、单页/多页目标配比，以及外链图片策略（任意经验证 HTTPS 图片或受限 host 白名单）。在它们明确前，只能做小规模探索或统计，不能启动大规模正式获取。

必须拒绝：

- 外部脚本、CSS、字体、iframe、音视频和远程 HTML；
- `fetch`、XHR、WebSocket、EventSource、动态模块 CDN 和远程 API；
- 分析、广告、支付、登录和埋点 SDK；
- 指向站外页面的功能性导航；
- `javascript:`、`vbscript:`、`data:text/html` 等危险协议。

对于图片有两种可版本化策略：

- `strict_offline`：所有图片本地化或使用可审计的内联 SVG，不允许任何外部图片请求。这是更 solid、可复现的推荐策略。
- `https_image_exception`：只允许经过验证、无需鉴权、稳定返回图片内容的 HTTPS 图片，除此之外零外部请求。

无论选择哪种，浏览器都必须记录全部 request/response；不能只用正则扫描源码来宣称“没有外链”。当前正式采用哪种图片策略，应写入 gate 配置和 release manifest，不能在同一版本中混用。

### 3.4 能够正常、稳定渲染

每个用户可达页面必须在统一 Playwright Chromium 环境通过：

- 本地 HTTP 返回 2xx/3xx；
- 触发懒加载后页面高度稳定；
- 无资源 404、坏图、CSS background/font/media 失败；
- 无 page crash、未捕获异常、unhandled rejection 或持续高严重度 console error；
- 不是空白背景、骨架屏、无限 loading、登录阻断、验证码或 JS 空壳；
- 全页面截图成功，不发生无限滚动或无限高度增长；
- 多页项目逐页验证，SPA 项目按 route manifest 逐路由验证；
- 同一配置至少重复渲染两次，主要 DOM、页面高度和截图保持稳定。

规范主视口为 1920×1080，使用 `full_page=True`。建议额外用 1366×768 和 390×844 检查脆弱响应式布局。动态时间、随机数和动画应固定种子或在截图时暂停。

### 3.5 不包含无意义网页

以下页面即使能打开也拒绝：

- 404/403/500、默认服务器页、维护页、停放域名和反爬页；
- coming soon、未定制默认模板、lorem ipsum、单个 hero 占位；
- 只有标题和少量链接/按钮的空页面；
- SEO/link farm、广告聚合、下载诱导和无内容目录；
- 只有原始长文本、缺少网页设计和信息组织的文档转储；
- 关键图片或组件缺失，大面积异常空白、遮挡、重叠、裁切、溢出或不可读；
- 多个区域机械重复，内容与图片无关，或主要功能需要登录/外部服务才能出现。

“是否有意义”是语义判断。规则可以发现错误页标记、空白度和元素数量，但最终必须由真实 VLM/LLM 查看截图、DOM/运行摘要和必要代码后，分别判断：

1. 内容是否有明确主题；
2. 是否具有真实用户价值；
3. 页面是否完整；
4. 布局和视觉是否达到训练质量；
5. 是否存在明显垃圾、占位或安全问题。

不得用关键词规则直接代替最终语义判断。


## 4. 相关工作中的 Verify 机制

### 4.1 WebCode2M

[WebCode2M: A Real-World Dataset for Code Generation from Webpage Designs](https://webcode2m.github.io/) 采用与本项目相近的反向路线：清洗真实网页代码、浏览器渲染截图、用人工标注训练质量 scorer，再按视觉质量过滤并抽取 layout 信息。

值得借鉴：代码清洗、真实渲染、人工校准的视觉质量模型，以及代码/截图/layout 联合保存。其不足是视觉质量分不能单独证明资源自包含和 query–功能一致。

### 4.2 Design2Code

[Design2Code: Benchmarking Multimodal Code Generation for Automated Front-End Engineering](https://aclanthology.org/2025.naacl-long.199.pdf) 先过滤过长、过简单和重复网页，再移除外部依赖，人工检查独立渲染、敏感内容和排版。评估同时使用整体 CLIP 和 block match、文本、位置、颜色等细粒度指标。

值得借鉴：stand-alone rendering 是准入条件；整体视觉 embedding 需要元素级指标补充；自动指标必须与人工判断校准。

### 4.3 WebGen-Bench

[WebGen-Bench: Evaluating LLMs on Generating Interactive and Functional Websites from Scratch](https://proceedings.neurips.cc/paper_files/paper/2025/hash/6841eed8bb6a2ec49e49235c8115efee-Abstract-Datasets_and_Benchmarks_Track.html) 将每个功能写成“操作 + 期望结果”，让浏览器导航 agent 执行后判断结果，并独立评价渲染和外观质量。

值得借鉴：页面出现某个按钮不代表功能成立，必须观察真实状态变化；功能证据和外观质量应分别记录。

### 4.4 ArtifactsBench

[ArtifactsBench: Bridging the Visual-Interactive Gap in LLM Code Generation Evaluation](https://arxiv.org/abs/2507.04952) 使用标准化执行环境，保存交互前/中/后的时序截图，并将代码与视觉证据交给 checklist 引导的 MLLM judge。它还结合代码/DOM/文本 MinHash、语义相似度和截图感知哈希去重，并用人工种子集校准 judge。

值得借鉴：动态页面不能只看一张截图；judge 必须回答具体 checklist；多模态去重和人工一致性是自动 judge 可信度的重要证据。

### 4.5 WebCoderBench 与 WebGrader

[WebCoderBench: Benchmarking Web Application Generation with Comprehensive and Interpretable Evaluation Metrics](https://arxiv.org/abs/2601.02430) 将客观规则与 LLM-as-a-judge 结合，并保留细粒度质量维度。[WebGrader: Training LLMs for Web Development with Self-Evolving Programmatic Grader](https://arxiv.org/abs/2608.06474) 将测试规划、动作定位、证据收集和语义判断分离，只有观察到目标状态转换才通过。

值得借鉴：程序负责客观事实，LLM/VLM 负责开放语义；不同证据不能压成一个相互抵消的总分；新 verifier 必须在独立验证集上验证并冻结版本。

## 5. 统一母本门控

```text
raw candidate
  -> G0 provenance / license / benchmark isolation
  -> G1 complete project / exact Qwen <= 40K
  -> G2 code graph / resource policy / no forbidden URL
  -> G3 sandbox serve / runtime network audit
  -> G4 all-route render / console / stability
  -> G5 visual and semantic value judge
  -> G6 query-code-render-behavior consistency
  -> G7 multimodal deduplication / distribution control
  -> accepted generate mother
```

每层状态只能是：

- `pass`：证据完整且通过；
- `reject`：确定性质量失败；
- `retryable`：浏览器、网络或模型服务偶发异常；
- `review`：证据不足或 judge 分歧，需要人工判断；
- `not_run`：上游失败导致未执行，不能视为通过。

最终 `mother_eligible=true` 只在 G0–G7 的必需项均为 `pass` 时产生。外链、泄漏、超长、不能渲染等致命问题不能被高视觉分抵消。

## 6. 每条样本的审计证据

每个候选 append 一条 JSONL，至少包含：

```json
{
  "sample_id": "...",
  "source": {"type": "repo|crawl|dataset|generated", "uri": "...", "revision": "...", "license": "..."},
  "gate_version": "generate-mother-v1",
  "resource_policy": "strict_offline|https_image_exception",
  "status": "pass|reject|retryable|review",
  "mother_eligible": true,
  "code": {"qwen_tokens": 12345, "file_count": 8, "sha256": "..."},
  "render": {"routes": [], "outbound_requests": [], "console_errors": [], "screenshots": []},
  "semantic_review": {"model": "...", "prompt_version": "...", "verdict": "pass"},
  "requirement_evidence": [],
  "dedup": {"group": "...", "matches": []},
  "reject_reasons": []
}
```

密钥、cookie 和代理不得写入 manifest。保留模型名、prompt 版本、浏览器版本、tokenizer hash、重试次数和状态。

## 7. 如何落实到现有代码

当前可复用：

- `preprocess/pipeline_c/qwen_token_gate.py`：完整代码序列化与 Qwen token；
- `preprocess/pipeline_c/final_gate.py`：外部引用、bundle、source map、orphan/duplicate code；
- `preprocess/final_screenshot.py`：本地 HTTP、懒加载、全页截图、坏图和空壳检查；
- `preprocess/pipeline_c/visual_review.py`：VLM 视觉语义判断；
- `validation/content_qc.py`：静态问题候选；
- `validation/release_pipeline.py`：release 结构和去重审计。

建议新增一个唯一 orchestrator，例如 `preprocess/mother_gate.py`，严格按 G0–G7 调用上述组件，并配套：

- `configs/mother_gate_v1.yaml`：视口、token、资源策略、timeout、judge、denylist；
- `schemas/mother_gate_v1.json`：manifest schema；
- `tests/fixtures/mother_gate/`：正例、真实失败例和单变量损坏例；
- `logs/mother_gate/<run_id>/`：命令、环境、append-only JSONL、完整日志；
- `reports/mother_gate/<run_id>.md`：逐层通过率、失败原因和来源分布。

批处理必须逐条 append/flush、支持断点续跑，并为下载、浏览器和模型步骤分别设置 timeout。新 gate 版本写新结果，不能覆盖既有产出。

### 7.1 当前实现差距

- `final_screenshot.py` 默认 1280×800，尚未与规范 1920×1080 统一；
- 当前坏图默认可容忍 5%，正式母本的关键资源应零失败；
- 浏览器运行期“禁止请求”尚未成为统一硬断言；
- console、pageerror、unhandled rejection、requestfailed 尚未统一记录；
- 多页检查主要枚举 HTML，SPA route manifest 仍需补齐；
- 当前 VLM judge 尚未用独立人工金标集校准；
- query requirement evidence map 尚未实现；
- 测试集污染和去重尚未统一到代码、DOM、query、截图四路指纹。

因此，这份文件是 generate 母本的目标规范，不代表现有历史数据已经全部按此验收。

## 8. 如何调试门控是否符合预期

### 8.1 最小真实样本

新来源先选 1 个真实项目跑完 G0–G7，不使用 mock LLM。确认每层有状态、理由和证据，偶发基础设施错误标为 `retryable`，重跑不覆盖原结果。

### 8.2 Gate Challenge Set

建立独立校准集，包括人工确认的优质正例，以及：外链/CDN、坏图、CSS 资源失败、JS crash、空壳、无限 loading、error/parked/captcha、低价值模板、link farm、布局破损、query 幻觉、代码/截图不一致、测试集污染和近重复。

一部分使用真实失败样本；一部分从合格母本做单变量损坏，每次只改变一个因素，用来验证对应 gate 是否真的能捕获该问题。

### 8.3 人工金标与指标

建议先建立约 200 条分层样本，由两名标注者独立判定 `accept/reject/review` 并标失败原因，分歧交给第三人裁决。报告：

- mother precision 和 recall；
- fatal-error false accept；
- 每类失败的召回率；
- `review` 比例；
- judge–judge 和 judge–human 一致性。

质量优先的初始目标可以是 fatal-error false accept = 0、mother precision >= 98%，但必须经过金标测量后才能声称达到。

### 8.4 阈值校准与 Shadow Run

- 40K、测试泄漏和禁止外部依赖属于政策门槛，不因留存率降低而放宽；
- 空白度、元素量、截图稳定差异和近重复相似度属于经验阈值，必须在 challenge set 上校准；
- 校准集和最终抽查集分开；
- 新版本先 shadow run，与旧门控比较新增拒绝/接受，并人工检查全部 disagreement；
- prompt、模型、浏览器、阈值或资源策略改变即升级 `gate_version`；
- 正式 run 内冻结 gate，不能边生产边改变标准。

## 9. 可以形成的创新点

### 9.1 Query–Code–Render–Behavior 四证据闭环

现有工作常重点检查代码、截图或交互中的一部分。本项目可以要求四类证据同时一致，任何一类不支持 query 都不能通过。

### 9.2 Requirement Evidence Map

把反向 query 拆成原子要求，并绑定 screenshot region、DOM element、browser flow 或 code location。它比单一相似度更可解释，也能直接分析 query 幻觉和遗漏。

### 9.3 Hermetic Render Reproducibility

把运行期网络日志和重复渲染稳定性纳入母本定义，而不只是清洗源码中的 URL。这样能够区分“当前偶然加载成功”和“未来仍可复现”的页面。

### 9.4 可演进但冻结的 Verifier

从漏放/误杀残差中提出新 verifier，在独立 challenge set 上验证后才晋级；正式生产版本内冻结。每个 gate 通过单变量损坏集做 ablation，报告其独有捕获能力和误杀成本。

## 10. 完成标准

只有满足以下条件，才能声称一个新来源被可靠接入 generate 母本池：

1. G0–G7 的统一入口、配置、schema 和 reason code 已实现；
2. 客观 gate 具有单元测试和定向损坏测试；
3. 真实项目、真实浏览器、真实 LLM/VLM 的最小端到端流程通过；
4. challenge set 上已报告 precision、recall、致命错误漏放率和 judge 一致性；
5. shadow run 的分歧样本已经人工复核；
6. 正式运行 append-only、可断点续跑，日志和证据完整；
7. release 中每条 generate 样本都可追溯到 `mother_eligible=true` 的 manifest；
8. 每条母本具有完整代码、clean 全页面截图、反向 query 和逐项 requirement evidence；
9. 测试集隔离、去重和来源分布报告随 release 一并交付。

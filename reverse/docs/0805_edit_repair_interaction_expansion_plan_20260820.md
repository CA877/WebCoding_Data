# 0805 Edit / Repair 交互与多页扩展实施方案

## 1. 结论

本轮不应只扩充 `construct_common.py` 中的 task type 名称。现有构造链路的核心数据单元仍是“代码 + 指令 → patch”，而交互任务真正需要的是可执行的状态转换：

```text
源项目状态 + 编辑指令 + 可选视觉参考
  -> patch
  -> 目标项目状态
  -> 浏览器动作复现
  -> 状态断言、截图差异和非目标区域保护
```

因此，保留 `construct/` 作为主体构造目录，同时在现有 v2 训练记录之外增加隐藏的 `TaskSpec v3`。v3 负责构造、执行和验收；通过后再投影为 text/image edit/repair 的训练输入，不能把 evaluator 答案或 repair 诊断泄漏给模型。

第一版 schema 和校验器已经落在 `construct/task_specs.py`，对应单元测试为 `tests/test_construct_task_specs.py`。它不修改或覆盖已有 v2 JSONL。

## 2. 当前实现缺口

| 需求 | 当前 `construct/` 状态 | 必须补充 |
| --- | --- | --- |
| interaction-rich Edit | 已增加 22 类标签、四套 profile、每类一个隐藏 action/assertion | 继续扩展 DOM/ARIA 与非目标区域保护 |
| image edit 的交互截图 | 已应用 patch 后真实渲染 source/default target/action target | 后续补充 selector ROI 差异与 transient/settled 双状态 |
| 理想编辑后图片 | 已支持 source、target、source+target 三种图片输入 | 后续显式区分外部 ideal reference 与构造器渲染 target |
| 四类 Repair | 已有四类 `controlled_repair` 与 leaf taxonomy；输出仍为 patch | 本轮暂不构造 Natural Repair；每类必须通过对应独立证据门 |
| 多页 Edit/Repair | 已有 `--page-scope mp` 和跨页 patch scope 门 | 后续补齐同一 browser context 的 route 级状态保持断言 |
| 截图“明确差异” | 已有动作后全页差异硬门；Hover 实测差异可检出 | 继续加入 ROI + DOM/ARIA 状态门，小 tooltip 不使用统一全图 1% 门 |

## 3. 数据分类

### 3.1 Edit interaction taxonomy

统一使用 22 个可组合标签：

```text
click, hover, focus, input, select, toggle, tab_switch, accordion,
dropdown, modal, tooltip, carousel, drag_drop, sort, filter,
pagination, navigation, form_validation, conditional_rendering,
loading_state, toast, animation
```

这些标签是可观测状态变化，不是单纯组件名。一个样本可以组合多个标签，例如：

- `input + filter + conditional_rendering`
- `click + modal + form_validation + toast`
- `drag_drop + sort + animation`
- `navigation + loading_state + pagination`

构造 prompt 要求每个标签都绑定至少一个 action、一个 target assertion；不能只让 LLM 在 description 中提到标签。

### 3.2 Benchmark 能力映射

| 来源 | 对 Edit/Repair 的用途 | 不应照搬的部分 |
| --- | --- | --- |
| Interaction2Code | before/action/after；reveal、selection、motion、media、navigation | 不把官方 test case 直接变成训练样本；只抽能力和状态表达 |
| ArtifactsBench | 游戏、工具、可视化、管理系统中的复杂本地交互和 checklist | checklist 只能作为构造参考；正式样本必须生成自己的独立 verifier |
| FrontendBench | dynamic effect、basic interaction、complex interaction、complex page + complex interaction 的难度分层 | 当前仓库将其视为 capability reference；没有公开 seed 时不得标记为 FrontendBench 来源样本 |
| WebCompass | 现有 edit/repair task 分布、单页/多页形态、输出兼容性 | 旧 task type 仅作语义先验，不能替代浏览器验收 |

### 3.3 Repair taxonomy

```text
Repair
├── runtime_repair：build_compile / boot_render / event_runtime / route_resource / async_lifecycle / state_persistence
├── visual_repair：layout_geometry / appearance_style / responsive / dynamic_state / overlay / animation / cross_page
├── interaction_repair：trigger_execution / state_transition / feedback / overlay / forms / navigation / direct_manipulation / keyboard_focus
└── quality_refinement：semantic_accessibility / reuse_consistency / regression_control / maintainability / requirement_alignment
```

Repair 的 family 必须在失败复现后确定：

| family | 最低证据 | 典型来源 |
| --- | --- | --- |
| runtime_repair | defective 相对 clean 新增的 build/page/console/request error | DesignBench、ArtifactsBench、WebGen-Bench 型受控故障 |
| visual_repair | screenshot diff 或布局断言失败 | after 图、响应式或局部视觉门失败 |
| interaction_repair | clean action contract 通过且 defective 对同一 contract 失败 | Interaction2Code、FullFront、WebCompass 型状态转换 |
| quality_refinement | accessibility/performance/responsive/quality audit 失败 | 可复现、可度量的质量门，不是主观“再美化” |

本轮只生成 `controlled_mutation`，JSONL 明确写入 `bug_injection_method=llm|rule`。Natural Repair 暂不进入本轮 schema、配额和批量统计。

## 4. TaskSpec v3

关键字段：

```json
{
  "schema_version": "webcoding-task-spec-v3",
  "task_family": "edit",
  "instruction": "...",
  "page_scope": "mp",
  "project_pages": ["index.html", "detail.html"],
  "affected_pages": ["index.html", "detail.html"],
  "interaction_types": ["filter", "sort", "navigation"],
  "visual_references": {
    "source_images": ["screens/source.png"],
    "target_images": ["references/ideal-after.png"]
  },
  "browser_contract": {
    "checkpoints": [
      {
        "id": "before",
        "state_role": "source",
        "route": "index.html",
        "actions": [],
        "assertions": [{"type": "visible", "selector": "#results"}],
        "capture": true
      },
      {
        "id": "after-filter",
        "state_role": "target",
        "route": "index.html",
        "actions": [{"action": "fill", "selector": "#filter", "value": "open"}],
        "assertions": [{"type": "text", "selector": "#results", "expected": "Open"}],
        "capture": true
      }
    ]
  },
  "difference_contracts": [
    {
      "before_checkpoint": "before",
      "after_checkpoint": "after-filter",
      "region_selector": "#results",
      "minimum_changed_pixels": 100,
      "minimum_region_changed_ratio": 0.01,
      "expected_difference": "visible rows and order change"
    }
  ],
  "construction_route": "forward_edit",
  "training_view": {
    "output": "patch",
    "hidden_fields": ["browser_contract", "difference_contracts", "failure_evidence"]
  }
}
```

支持四种 Edit 输入组合：

1. `code_instruction`
2. `code_instruction_source_image`
3. `code_instruction_target_image`
4. `code_instruction_source_target_images`

最终 output 都仍是精确 patch。`target_images` 是可选的理想编辑结果输入；应用 patch 后真实渲染得到的 `dst_screenshot` 是验收证据，两者不能混为一个字段。

## 5. 截图与状态采集

### 5.1 每类交互怎么截

| interaction | source checkpoint | target/transient checkpoint |
| --- | --- | --- |
| click/toggle/tab/accordion/dropdown/modal | 点击前 | 点击后的展开、选中或覆盖层状态 |
| hover/focus/tooltip | 默认态 | hover/focus 保持时立即截图 |
| input/select/filter/sort/pagination | 原数据状态 | 输入或选择后，等待 DOM 稳定再截图 |
| form validation | 未提交或有效态 | 无效提交后的字段错误、summary、disabled/enabled 状态 |
| loading state/toast | 动作前 | transient checkpoint；必要时再加 settled checkpoint |
| carousel/animation | 初始关键帧 | 人工触发后的确定性关键帧；自动播放需冻结时间或记录短视频 |
| drag/drop | 拖动前 | drop 后排序/容器归属变化 |
| navigation | 原 route | 新 route；多页还要验证 back/return 和共享状态 |

### 5.2 “明确差异”的门禁

不能统一使用全页 `changed_ratio >= 1%`。tooltip、focus ring、toast 可能语义明确但占页面很小。建议三层门禁：

1. action 全部执行成功，且 target assertion 通过；
2. `region_selector` 的 DOM/ARIA/value/URL 状态发生预期变化；
3. 在该区域的截图 ROI 内达到 `minimum_changed_pixels` 和 `minimum_region_changed_ratio`。

全页 diff 只作为辅助统计和“页面是否被意外大改”的上界。应额外对未授权 roots 使用现有 semantic DOM/ARIA guard，保证非目标区域不变。

## 6. 多页样本

多页不是“目录里 HTML 数量大于一”就完成。每条 mp Edit/Repair 至少保存：

- `project_pages`：项目完整页面集合；
- `affected_pages`：patch 允许影响的页面；
- route 级 checkpoints；
- shared shell/components 的 preservation roots；
- 跨页状态规则，如筛选条件、购物车、草稿、当前账号、返回位置；
- 导航的目标页、回退路径和 deep-link 行为；
- 每个受影响 route 的 patch、截图和断言证据。

第一批多页组合优先选择可独立验证的路径：

- 列表过滤/排序 → 详情 → 返回后状态保留；
- 表单 → review → confirmation → 返回修正；
- catalog → detail → cart → 本地 confirmation；
- overview → record detail → edit → list 状态更新。

## 7. 代码改造顺序

### Phase A：统一 contract（本轮已开始）

- 新增 `construct/task_specs.py`；
- 覆盖 22 类 interaction、4 类 repair、4 种 edit input variant、mp 页面集合；
- repair 必须携带同 family 匹配且 `status=reproduced` 的证据；
- browser/evaluator/failure evidence 默认隐藏于训练输入。

### Phase B：Edit 生成器

- 将 `build_forward_edit_synthesizer()` 的 XML 输出升级为 JSON TaskSpec + patch，或保留 XML patch、另生成 TaskSpec；
- task selection 从粗粒度组件名扩展为 `benchmark_profile + interaction_types + page_scope`；
- 先生成 instruction/contract，再生成 patch；两步可使用同一真实 LLM，但 verifier 不能由同一次回答自证；
- 应用 patch 到临时完整项目，禁止只检查字符串 round-trip。

### Phase C：状态执行与 image-edit

- 新增 `construct/execute_task_spec.py`，复用 typed Playwright action contract；
- 同一 browser context 顺序执行 checkpoint，按 checkpoint ID 保存截图、DOM/ARIA snapshot、console/network；
- image-edit exporter 加入 `target_reference_images` 和真实 `dst_screenshot`；
- transient state 单独保存，不覆盖 settled target。

### Phase D：Controlled Repair taxonomy（本轮）

- 从 clean 0805 项目注入受控 leaf defect；
- `repair_family`、`repair_subfamily`、`defect_type`、`benchmark_alignment` 写入同一 JSONL，不按 family 拆目录；
- 排除代理、模型 API、截图服务、invalid test contract 等基础设施失败；
- 独立证据门通过后才允许 `status=ok`；
- 输入为 broken code，并按 modality 可附 broken screenshot；输出仍为 patch；诊断和 evidence 只进 metadata。

### Phase E：多页与导出

- executor 按 route 执行并保留同一 browser context；
- patch scope 同时限制文件路径和 semantic roots；
- `v2_records.py` 先兼容读取 v3 hidden contract，再由 release packer 决定是否发布 v3 字段；
- v2 旧记录保持只读，不覆盖已有 JSONL。

## 8. 小规模验证顺序

不直接批量。按以下真实样本矩阵推进：

1. 1 个真实单页：`click + modal`，source/target 图和 ROI diff；
2. 4 个真实单页：hover tooltip、input validation、drag/drop sort、loading + toast；
3. 2 个真实多页：filter → detail → back，form → review → confirmation；
4. 四个 controlled Repair family 各构造 1 条；Runtime/Visual/Interaction/Quality 分别使用差分 runtime error、截图差异、clean-pass/defect-fail action contract、DOM/accessibility regression；
5. 相关单元测试、完整 patch round-trip、本地 HTTP Playwright、无外网请求、截图/DOM/action evidence 全部通过后，再做 20–50 条真实 LLM pilot。

该 pilot 只用于估计：TaskSpec 合法率、patch 可应用率、浏览器行为通过率、截图差异通过率、controlled repair 证据通过率和多页通过率。它不是正式 benchmark 提升结论。

## 9. 批量前需要用户确认的决策

达到 300 条前需要确认：

1. Edit 中四种 input variant 的配比；
2. 22 类 interaction 的目标分布，是均衡还是按四个 benchmark 加权；
3. 四个 controlled Repair family 与各 leaf defect 的比例；
4. 多页样本比例、最多页面数和最大 action steps；
5. ideal target image 的来源：人工设计、已有 benchmark prototype、还是独立 VLM/设计模型生成；
6. ROI diff 的分类型阈值，以及 animation 是否必须同时保留视频。

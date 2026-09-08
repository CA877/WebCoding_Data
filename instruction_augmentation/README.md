# 灵感库生成与连续 Edit 链生成

本模块包含两条相接的流程：从网页积累可迁移的功能灵感，再针对一个目标网页生成连续的完整 Edit 任务。

## 1. 灵感库生成

```text
公开 URL / 本地网页项目
→ 桌面与移动端浏览器观察
→ 自动操作 + LLM 多步探索
→ LLM 抽取功能灵感
→ 定位局部参考代码
→ capability_pool.jsonl
```

统一入口：[mine_live_url_capability_pool.py](../scripts/mine_live_url_capability_pool.py)，单来源监管入口：[run_live_url_audit_case.py](../scripts/run_live_url_audit_case.py)。

输入使用 sources JSONL，每行一个来源：

```json
{"seed_id":"demo_url","entry_url":"https://example.com/demo"}
```

或在 `--mode local_project` 下：

```json
{"seed_id":"demo_project","project_path":"/absolute/path/to/project"}
```

本地项目当前要求可通过 index.html 直接运行。两种来源共用探索和抽卡方法；本地从项目文件定位源码，在线从页面获取局部 DOM/CSS/JS 和公开示例。实际挖掘在项目运行服务器执行，开发机用于编辑、单元测试和查看结果。

- `scan`：只采集浏览器事实，无 LLM 调用。
- `full`：自带基线采集、探索、抽卡和参考代码获取。
- 在线 `--source-mode reference/examples/none` 分别获取局部参考、仅公开示例、仅灵感。
- 保持输入输出接口不变，内部探索与抽取策略可以改进。

卡片主要保存 `capability_id/change_type/summary/requires/user_actions/produces/visible_result/future_uses/source_slices`，并附现有来源和观察关联。原始观察、截图及参考文件单独保存。卡片数量由实际观察决定。

## 2. 连续 Edit 链生成

```text
目标网页项目 + 原需求 + 浏览器事实 + 灵感库
→ 确定链长度 N
→ LLM 编写检索 query
→ embedding Top-K 召回
→ LLM 制定 N 项功能计划及依赖
→ LLM 生成英文 Q1–QN
→ 既有结构检查
→ sequences/ + edit_queries.jsonl
```

主入口：[run_linear_edit_query_augmentation.py](../scripts/run_linear_edit_query_augmentation.py)，单样本监管入口：[run_edit_instruction_case.py](../scripts/run_edit_instruction_case.py)。

默认 N 在 4–12 中等概率抽取，支持指定长度和随机种子，续跑保持原长度。默认 Top-K 为 8，同类上限为 2。常规流程每个目标网页包含三次聊天调用（query、plan、generate）及一次 query embedding；首次为卡池建立向量和额外浏览器探索另计。已有向量通过 embedding-dir 或 embedded-capability-pool 复用，池内容、模型及维度必须匹配。

每条 Edit 是达到 WebCompass 对应类型粒度的完整任务。多张局部灵感可以共同支撑一条任务。例如筛选、排序、分页、行选择和空结果提示，可以共同组成“为课程列表增加完整数据表”的一条 Edit。

Q2 只有实际消费 Q1 预计新增的状态时才依赖 Q1；共享页面或要求保留旧功能本身不构成依赖。输出是指令和预计状态，真实后续网页、patch 与训练样本由下游 Harness 负责。

生成后执行既有结构检查并导出。新运行不调用独立审核模型。英文原文用于落盘，向用户展示时可逐条提供完整中文译文。

## 3. 代码阅读顺序

| 文件 | 职责 |
|---|---|
| [production_browser.py](production_browser.py) | 启动页面、执行动作、采集页面事实 |
| [deep_browser_exploration.py](deep_browser_exploration.py) | 自动与 LLM 路径探索、状态合并和压缩 |
| [dynamic_capability_retrieval.py](dynamic_capability_retrieval.py) | 抽卡、卡池合并及共用工具；也保留部分旧逐轮检索逻辑 |
| [live_component_sources.py](live_component_sources.py) | 在线局部参考代码获取 |
| [one_shot_capability_retrieval.py](one_shot_capability_retrieval.py) | 本地代码片段、检索 query、Top-K 和功能计划 |
| [linear_edit_queries.py](linear_edit_queries.py) | 指令生成、结构约束与数据格式 |
| [doc_api.py](doc_api.py) | 模型接口与请求/用量记录 |

先看两个主入口，再沿调用关系阅读上述模块即可。

## 4. 配置与运行

项目聊天默认使用 TokenWave gpt-5.5；各入口的历史客户端默认值可能不同，运行前显式配置供应商与模型。Edit 监管入口使用 TOKENWAVE_API_KEY / TOKENWAVE_OPENAI_API_KEY 等受保护凭据。embedding 服务独立配置，复用向量时使用原模型和维度。密钥通过环境或监管器 stdin 注入。

先从仓库根目录查看单样本入口参数：

```bash
uv run python scripts/run_live_url_audit_case.py --help
uv run python scripts/run_edit_instruction_case.py --help
```

使用实际来源清单、项目路径、卡池路径和新运行目录；避免直接沿用代码中的机器专用默认路径。单样本监管器提供尝试量限制、心跳、进程超时与子进程清理；批次参数按实际计算资源配置。

## 5. 相关测试

从仓库根目录运行：

```bash
uv run pytest -q \
  tests/test_inspiration_modes_and_library.py \
  tests/test_live_mining_evidence_fixes.py \
  tests/test_live_component_sources.py \
  tests/test_edit_chain_integration.py \
  tests/test_one_shot_capability_retrieval.py \
  tests/test_linear_edit_query_augmentation.py
```

测试覆盖输入输出、代码引用、检索及生成接线与结构约束。模型生成效果使用真实小样本另行调试。

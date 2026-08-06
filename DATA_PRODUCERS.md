# WebCoding Data Producers

本仓库使用两条互补的数据生产路线。二者服务于同一训练集，但不能混淆来源、
评测证据或任务标签。

## 1. Reverse / controlled producer

位置：`construct/`

- 从清洁网页项目出发，受控地构造 generation、editing 与 repair 数据。
- 强调覆盖率、配额、可回放 search/replace、截图稳定性和发布格式一致性。
- 人工或规则 mutation 必须标为 controlled，不得声称是 agent 自然产生的缺陷。

## 2. Forward / agentic producer

位置：`web-coding-agent/`

- 通过 planner → generator → evaluator 的长程 harness 产生真实实现轨迹。
- edit 从 accepted baseline 出发；repair 必须对应 evaluator 实际复现的缺陷。
- DOM/ARIA contract、独立功能验收和视觉复核共同决定轨迹能否导出。
- 正式运行数据写入 `runs/agentic/`，日志写入 `logs/agentic/`。

## 3. Shared consumers

- `web_evograph/`：读取真实 harness 轨迹，进行演化、筛选和 SFT 导出实验。
- `scripts/`：跨 producer 的审计、转换、打包和发布工具。
- `tests/`：仓库级数据合同与发布布局回归；harness 自身测试位于
  `web-coding-agent/tests/`。

## Provenance boundary

统一 schema 不等于统一来源。正式记录至少应保留 producer、construction mode、
source/final commit、evaluator mode、guard status 和可回放验证结果。预检查、基础设施
失败、controlled mutation 与 natural trajectory 必须分开统计。

## Local artifact layout

```text
runs/
├── agentic/              # forward harness workdirs and exports
└── <reverse run id>/     # controlled/reverse construction outputs

logs/
├── agentic/              # forward harness and API logs
└── <pipeline run id>/    # reverse/crawl/packaging logs
```

`runs/`、`logs/`、凭据、虚拟环境和临时 worktree 均不进入 Git。

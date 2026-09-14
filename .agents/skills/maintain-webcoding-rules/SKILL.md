---
name: maintain-webcoding-rules
description: 当用户要求 WebCoding 规则、任务路由或知识 owner 跨会话长期适用时，维护唯一的指导文件与对应 skill。
---

# Maintain WebCoding Rules

先读取根 `AGENTS.md`、最匹配的 skill 和对应 canonical doc。将信息放入唯一 owner：全项目不变量在 `AGENTS.md`；任务工作流在 skill；项目事实/设计在 `docs/`；运行细节在 `docs/operations/`；状态在 `PROJECT_STATUS.md` 或 `current_state.md`；历史结论在报告或 archive。

迁移或修改规则时，保留原信息、更新引用并删除完整重复副本；不要把临时参数、进度或单次例外升级为长期规则。规则改变数据语义、运行行为或接口时，同步更新实现和权威文档；用户仅要求文档时不扩大为实现任务。

完成后运行 `skill-creator/scripts/quick_validate.py` 验证受影响 skill，并检查引用路径。将重要文档登记到 `docs/README.md`。

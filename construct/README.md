# edit / repair 构造交付说明

## 构造规则

- 每个项目随机生成 2–10 个不同 task type；2–5 合计约 80%，6–10 合计约 20%。
- 每个 task type 至少一个 patch，可有多个 patch；每个 patch 必须带自己的 `task_type`。
- **旧交付包的构造器**仍使用 HTML（移除脚本）+ 作者 CSS、60K 的历史口径，不能作为最终 WebCompass 对齐版本。
- 已确认的新最终口径是：完整 HTML、内联 CSS/JS、作者外部 CSS/JS、以及保留在最终项目内的本地第三方 bundle 全部进入模型上下文；使用精确 Qwen tokenizer，最大 **40K**。超过上限直接淘汰，不能截断或隐藏 bundle。
- 在新 40K 全代码 serializer 与重新筛选完成前，不要用当前构造器直接批量生产最终训练数据；可仅用于验证既有 JSONL/截图流程。
- 输出为可恢复追加的 `records.jsonl`。只使用 `status=ok` 行构造训练集。
- image-editing 不重新截图，只验证并引用项目根目录的已审核 PNG；repair 在缺陷注入后只截一张 desktop 视口图（`<项目名>/index__desktop.jpg`），不再做 clean/defective 多视口对比与视觉变化量门禁（patch 应用已保证代码级改动，视觉 delta 对 text-repair 训练无增益）。

## 一条命令批量运行

```bash
cd /data1/xieqianqian/webcoding/WebCoding_Data
cp construct/.env.example .env
# 编辑 .env，填写对方自己的 KIMI_API_KEY（或 OPENAI_API_KEY）
bash construct/run_edit_repair_batch.sh
```

脚本会默认读取仓库根目录的 `.env`；若对方的凭据文件在别处，可用 `API_ENV_FILE=/path/to/secret.env` 覆盖。key 不写入 Bash、README、JSONL 或 ModelScope 交付包。

默认输出到 `runs/construct_edit_repair_0721/`：

```text
text_edit/records.jsonl
image_edit_records.jsonl
text_repair/records.jsonl
image_repair/repair_defect_screenshots/<项目名>/
```

可按环境变量调整：

```bash
TASKS=edit EDIT_WORKERS=1 OUTPUT_ROOT=runs/construct_edit_trial \
  bash construct/run_edit_repair_batch.sh

# 不调用 API，只检查参数、项目清单和最终命令
DRY_RUN=1 bash construct/run_edit_repair_batch.sh
```

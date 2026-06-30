# WebCompass 本地跑通记录

## 概述

在 macOS (Apple Silicon) + Docker Desktop 环境下，成功跑通 WebCompass 项目的完整流水线（推理 + 评测），只跑了 1 个 case（实例 694）。

使用的 API：阿里云 idealab 代理的 `claude_sonnet4_5` 模型。

---

## 修改的代码文件

### 1. `generation/evaluation/agents/claude_code_web_coding/create_traj.sh`

**修改 1：修复双重认证头冲突（第 87-95 行）**

- **问题**：脚本同时导出 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN`，导致 Anthropic SDK 同时发送 `X-Api-Key` 和 `Authorization: Bearer` 两个认证头。阿里云 idealab API 代理会拒绝这种请求，报错："x-api-key和Authorization不可以同时存在"。
- **修改**：当 `ANTHROPIC_AUTH_TOKEN` 已设置时，跳过导出 `ANTHROPIC_API_KEY`，只保留一个认证头。

```diff
+# NOTE: Do NOT export ANTHROPIC_API_KEY when ANTHROPIC_AUTH_TOKEN is also set,
+# because the Anthropic SDK will send both x-api-key and Authorization headers,
+# which some API proxies reject.
 if [ -n "$TASK_ANTHROPIC_API_KEY" ] && [ "$TASK_ANTHROPIC_API_KEY" != "null" ]; then
-    export ANTHROPIC_API_KEY="$TASK_ANTHROPIC_API_KEY"
+    if [ -z "$ANTHROPIC_AUTH_TOKEN" ] || [ "$ANTHROPIC_AUTH_TOKEN" = "null" ]; then
+        export ANTHROPIC_API_KEY="$TASK_ANTHROPIC_API_KEY"
+    else
+        echo "[create_traj] Skipping ANTHROPIC_API_KEY ..."
+    fi
 fi
```

**修改 2：修复模型名称硬编码（第 237、256 行）**

- **问题**：Step 1 和 Step 2 的 claude 命令中 `--model` 参数硬编码为 `opus`，但变量 `$MODEL_ARG` 已经从 task.json 正确读取了模型名称，只是没有使用。
- **修改**：将 `--model opus` 改为 `--model "$MODEL_ARG"`。

```diff
-        --model opus
+        --model "$MODEL_ARG"
```

### 2. `generation/evaluation/src/utils/docker.py`

**修改 1：降低 Docker 资源限制（第 25-26 行）**

- **问题**：默认 `cpus="16"`, `memory="64g"`，超出 macOS Docker Desktop 限制（最大 10 CPU）。
- **修改**：改为 `cpus="10"`, `memory="16g"`。

```diff
-    cpus: str = "16",
-    memory: str = "64g",
+    cpus: str = "10",
+    memory: str = "16g",
```

**修改 2：将 `--mount` 改为 `-v` 语法（第 63-67 行）**

- **问题**：`--mount type=bind,source=X,target=Y` 在 macOS Docker Desktop (VirtioFS) 上要求目标路径预先存在，否则报 "path does not exist"。
- **修改**：改为 `-v X:Y` 语法，Docker 会自动创建目标目录。

```diff
-        "--mount", f"type=bind,source={agent_workspace},target=/agent_workspace",
+        "-v", f"{agent_workspace}:/agent_workspace",
```

**修改 3：添加 macOS 文件同步等待（第 95 行）**

- **问题**：macOS VirtioFS 文件系统同步有延迟，Docker 容器启动时可能读不到刚创建的文件。
- **修改**：在执行 Docker 命令前 `time.sleep(2)`。

---

## 新增的文件（不修改原仓库代码）

| 文件 | 说明 |
|------|------|
| `generation/evaluation/agents/claude_code_web_coding/Dockerfile.build` | 自定义 Dockerfile，使用阿里云 apt 镜像源和 npmmirror npm 镜像，替换原项目中依赖内部镜像源的 Dockerfile |
| `generation/evaluation/configs/my_config.json` | 单 case 评测配置文件 |
| `data_text_1.jsonl` | 从 HuggingFace 下载的 1 条测试数据（实例 694） |

---

## 配置注意事项

### `anthropic_base_url` 不要包含 `/v1`

Claude Code SDK 会自动在 base URL 后拼接 `/v1/messages`。如果配置中写 `https://xxx/api/anthropic/v1`，实际请求会变成 `https://xxx/api/anthropic/v1/v1/messages`，触发 WAF 拦截。

正确配置：
```json
"anthropic_base_url": "https://idealab.alibaba-inc.com/api/anthropic"
```

### `evaluate.py` 的 checklist.json 路径

`evaluate.py` 期望 `checklist.json` 在 `<output_dir>/<instance_id>/checklist.json`，但 Docker 容器实际生成在 `<output_dir>/<instance_id>/output_*/generated_web_pages/testbed/checklist.json`。需要手动复制或调整路径。

---

## Token 消耗估算

### 推理阶段（网页生成）

通过 OpenAI 兼容 API 调用，流式输出，无精确 token 记录。

| 项目 | 估算 |
|------|------|
| 输入 tokens（prompt 模板 + instruction） | ~2,200 tokens |
| 输出 tokens（生成的 index.html） | ~3,000 tokens |
| **单 case 推理总计** | **~5,200 tokens** |

### 评测阶段（Docker 内 Claude Code 验证）

通过 Anthropic Messages API，有精确记录：

| 项目 | 数值 |
|------|------|
| 输入 tokens | 110 |
| 输出 tokens | 12,483 |
| 缓存创建 input tokens | 77,488 |
| 缓存读取 input tokens | 2,598,487 |
| **总轮次** | 64 |
| **耗时** | 372 秒 |
| **费用（按官方定价估算）** | $1.26 |

> 评测阶段 token 消耗远大于推理阶段（约 500:1），因为 Claude Code 需要多轮交互：读取代码、启动浏览器、截图、逐项检查 checklist、填写分数和理由。

### 单 case 总消耗

| 阶段 | Token 消耗 | 费用估算 |
|------|-----------|---------|
| 推理（生成网页） | ~5,200 tokens | ~$0.02 |
| 评测（Docker 验证） | ~2,688,568 tokens | ~$1.26 |
| **合计** | **~2.69M tokens** | **~$1.28** |

> **注意**：评测阶段使用了 prompt caching，2.6M 的缓存读取 tokens 费用远低于非缓存 tokens。实际费用取决于 API 代理的定价策略。

---

## 评测结果（实例 694）

| 维度 | 得分 |
|------|------|
| 可运行性 (Runnability) | 40.00% (4/10) |
| 需求实现 (Spec Implementation) | 15.38% (8/52) |
| 设计质量 (Design Quality) | 0.00% (0/38) |
| **平均准确率** | **14.00%** |
| 调和平均 | 1.48% |

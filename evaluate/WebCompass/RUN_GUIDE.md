# WebCompass 单 Case 跑通指南

本文档指导你在一台新电脑上从零跑通 WebCompass 项目的完整流水线（推理 + 评测），只跑 1 个 case。

## 前置要求

- macOS 或 Linux
- Docker Desktop 已安装并启动（macOS 建议分配 ≥10 CPU、≥16GB 内存）
- Python 3.9+
- Git

## 第一步：克隆项目 & 安装依赖

```bash
git clone https://github.com/NJU-LINK/WebCompass.git web-coding
cd web-coding

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
pip install datasets   # 用于下载 HuggingFace 数据集
```

## 第二步：下载 1 条测试数据

```bash
# 如果在国内，先设置 HuggingFace 镜像
export HF_ENDPOINT=https://hf-mirror.com

python3 -c "
from datasets import load_dataset
import json

ds = load_dataset('NJU-LINK/WebCompass', 'text-generation', split='train')
# 取第一条数据
item = ds[0]
with open('data_text_1.jsonl', 'w') as f:
    f.write(json.dumps(item, ensure_ascii=False) + '\n')
print(f'已保存 1 条数据，instance_id: {item[\"instance_id\"]}')
"
```

## 第三步：构建 Docker 镜像

项目自带的 Dockerfile 依赖内部镜像源，需要用修改后的 `Dockerfile.build`：

```bash
cd generation/evaluation/agents/claude_code_web_coding

# 构建镜像（约 5-10 分钟）
docker build -f Dockerfile.build -t web_bench/base:latest .

cd ../../../..  # 回到项目根目录
```

> **注意**：`Dockerfile.build` 使用阿里云 apt 镜像和 npmmirror npm 镜像。如果在海外，可以将镜像源替换回官方源。

## 第四步：推理（生成网页代码）

你需要一个支持 OpenAI 兼容 API 的模型。以下以阿里云 idealab 的 `claude_sonnet4_5` 为例：

```bash
source .venv/bin/activate

python3 -m generation.scripts.run_text_inference \
    --data data_text_1.jsonl \
    --output output_text \
    --model claude_sonnet4_5 \
    --base-url "https://idealab.alibaba-inc.com/api/openai/v1" \
    --api-key "你的API_KEY" \
    --model-id claude_sonnet4_5 \
    --workers 1
```

运行成功后，会在 `output_text/<instance_id>/index.html` 生成网页文件。

> **替换模型**：可以用任何 OpenAI 兼容 API，比如 `--base-url "https://api.openai.com/v1" --model gpt-4o --model-id gpt-4o`。

## 第五步：准备评测配置

### 5.1 复制推理结果到评测路径

`test.py` 会用 `model` 字段拼接路径，所以需要按模型名建子目录：

```bash
INSTANCE_ID=$(python3 -c "import json; print(json.loads(open('data_text_1.jsonl').readline())['instance_id'])")
MODEL_NAME="claude_sonnet4_5"  # 和配置文件中的 model 字段保持一致

mkdir -p "output_text/${MODEL_NAME}/${INSTANCE_ID}"
cp "output_text/${INSTANCE_ID}/index.html" "output_text/${MODEL_NAME}/${INSTANCE_ID}/"
```

### 5.2 创建评测配置文件

```bash
PROJECT_ROOT=$(pwd)

cat > generation/evaluation/configs/my_config.json << EOF
{
    "tasks_file": "${PROJECT_ROOT}/data_text_1.jsonl",
    "agent_dir": "${PROJECT_ROOT}/generation/evaluation/agents/claude_code_web_coding",
    "output_dir": "${PROJECT_ROOT}/eval_output/${MODEL_NAME}/",
    "existing_site_root": "${PROJECT_ROOT}/output_text/${MODEL_NAME}/",
    "start_index": 0,
    "end_index": 1,
    "num_tasks": 1,
    "num_processes": 1,
    "retry_count": 1,
    "anthropic_base_url": "https://idealab.alibaba-inc.com/api/anthropic",
    "anthropic_auth_token": "你的API_KEY",
    "network_mode": "bridge",
    "model": "claude_sonnet4_5"
}
EOF
```

> **关键**：`anthropic_base_url` 不要包含 `/v1`！Claude Code SDK 会自动拼接 `/v1/messages`，写成 `.../anthropic/v1` 会变成 `.../anthropic/v1/v1/messages` 导致请求失败。

## 第六步：运行评测

```bash
source .venv/bin/activate

# 清除可能干扰的环境变量
unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN

python3 -m generation.evaluation.test --config generation/evaluation/configs/my_config.json
```

评测过程：
1. 启动 Docker 容器（Ubuntu 22.04 + Chrome + Claude Code）
2. 将推理生成的网页复制到容器内
3. Claude Code 在容器内启动 Chrome，逐项验证 checklist（截图 + 交互测试）
4. 生成 `checklist.json` 评分文件

**耗时约 5-10 分钟**，取决于网络和 API 响应速度。

## 第七步：计算最终分数

评测完成后，需要将 checklist.json 复制到 `evaluate.py` 期望的位置：

```bash
INSTANCE_ID=$(python3 -c "import json; print(json.loads(open('data_text_1.jsonl').readline())['instance_id'])")

# 找到最新的 output 目录中的 checklist.json 并复制
LATEST_OUTPUT=$(ls -td eval_output/${MODEL_NAME}/${INSTANCE_ID}/output_* | head -1)
cp "${LATEST_OUTPUT}/generated_web_pages/testbed/checklist.json" \
   "eval_output/${MODEL_NAME}/${INSTANCE_ID}/checklist.json"

# 运行评分
python3 -m generation.evaluation.evaluate \
    --text_dir "eval_output/${MODEL_NAME}" \
    --score_mode checklist
```

输出示例：
```
Modality: TEXT
Tasks evaluated: 1
Average accuracy: 0.1400 (14.00%)

By Category:
  Runnability: 0.4000 (40.00%)
  Spec Implementation: 0.1538 (15.38%)
  Design Quality: 0.0000 (0.00%)
```

## 常见问题

### Docker CPU/内存限制报错
macOS Docker Desktop 默认 CPU 上限可能低于代码中的设置。如果报错，修改 `generation/evaluation/src/utils/docker.py` 中的默认值：
```python
cpus: str = "10",    # 不要超过你 Docker Desktop 设置的 CPU 数
memory: str = "16g", # 不要超过你 Docker Desktop 设置的内存
```

### API 认证报错 "Invalid API key"
检查是否同时设置了 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN` 环境变量。某些 API 代理不允许同时存在 `x-api-key` 和 `Authorization` 两个认证头。`create_traj.sh` 中已有处理逻辑，如果仍有问题，在运行前 `unset ANTHROPIC_API_KEY`。

### WAF 拦截 / 请求被阻断
大概率是 `anthropic_base_url` 多了 `/v1`，导致实际请求 URL 变成 `.../v1/v1/messages`。去掉末尾的 `/v1`。

### `evaluate.py` 显示 "Tasks evaluated: 0"
`evaluate.py` 期望 `checklist.json` 直接在 `<output_dir>/<instance_id>/` 下，但 Docker 容器生成在更深的子目录里。按第七步手动复制即可。

### Docker 容器内网络不通
如果使用 `"network_mode": "bridge"`，确保容器可以访问外网（调用 API）。如果不行，尝试改为 `"network_mode": "host"`（Linux 上有效，macOS 上 host 模式行为不同）。

## Token 消耗参考（单 case）

| 阶段 | Token 消耗 | 费用估算 |
|------|-----------|---------|
| 推理（生成网页） | ~5,000 tokens | ~$0.02 |
| 评测（Docker 内验证） | ~2.7M tokens（含缓存） | ~$1.26 |
| **合计** | **~2.7M tokens** | **~$1.28** |

评测阶段消耗远大于推理，因为 Claude Code 需要 60+ 轮交互完成验证。

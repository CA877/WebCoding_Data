# WebCompass Generation & Evaluation

本模块提供网页生成（Inference）和评测（Evaluation）的完整流程。

## 目录结构

```
generation/
├── inference/                 # 网页生成模块
│   ├── text_to_web.py        # 文本 → 网页
│   ├── image_to_web.py       # 图片 → 网页
│   └── video_to_web.py       # 视频 → 网页
├── evaluation/                # 评测模块
│   ├── agents/               # Docker Agent 配置
│   │   └── claude_code_web_coding/
│   ├── configs/              # 评测配置文件
│   ├── test.py               # Text/Video 评测入口
│   ├── test_image.py         # Image 评测入口
│   ├── judge_image.py        # Image LLM 评判（复刻质量）
│   └── evaluate.py           # 统一算分脚本
├── scripts/                   # 运行脚本
│   ├── run_text_inference.py
│   ├── run_image_inference.py
│   └── run_video_inference.py
├── call_model.py             # 模型调用封装
├── model_client.py           # 模型客户端
├── prompts.py                # Prompt 模板
└── utils.py                  # 工具函数
```

---

## 一、网页生成（Inference）

### 1.1 环境变量配置

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选，默认 OpenAI
```

### 1.2 Text-to-Web（文本生成网页）

从文本设计文档生成网页。

```bash
python -m generation.scripts.run_text_inference \
    --data /path/to/tasks.jsonl \
    --output /path/to/output \
    --model gpt-4o \
    --workers 4
```

**参数说明：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--data` | 输入 JSONL 文件路径 | 必填 |
| `--output` | 输出目录 | 必填 |
| `--model` | 模型名称 | 必填 |
| `--base-url` | API Base URL | 环境变量 |
| `--api-key` | API Key | 环境变量 |
| `--workers` | 并行数 | 4 |
| `--max-retries` | 最大重试次数 | 3 |

### 1.3 Image-to-Web（图片生成网页）

从参考截图生成网页。

```bash
python -m generation.scripts.run_image_inference \
    --data /path/to/tasks.jsonl \
    --output /path/to/output \
    --model gpt-4o \
    --workers 4
```

### 1.4 Video-to-Web（视频生成网页）

从视频演示生成网页（自动提取关键帧）。

```bash
python -m generation.scripts.run_video_inference \
    --data /path/to/tasks.jsonl \
    --output /path/to/output \
    --model gpt-4o \
    --workers 4 \
    --fps 3.0 \
    --max-frames 30
```

**额外参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--fps` | 提取帧率 | 3.0 |
| `--max-frames` | 最大帧数 | 30 |

---

## 二、网页评测（Evaluation）

评测分为三步：**构建镜像 → 运行评测 → 算分**

### 2.1 环境变量

网页生成（inference）：
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选
```

图像评测（judge_image.py）：
```bash
export OPENAI_API_KEY="your-gemini-api-key"
export OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
```

### 2.2 构建 Docker 镜像

首次使用或更新 Agent 后需要重新构建：

```bash
cd /share/leixinping/WebCompass/generation/evaluation/agents/claude_code_web_coding
bash build_image.sh
```

### 2.3 配置文件

创建评测配置文件（JSON 格式）：

```json
{
    "tasks_file": "/path/to/tasks.jsonl",
    "agent_dir": "/path/to/WebCompass/generation/evaluation/agents/claude_code_web_coding",
    "output_dir": "/path/to/output/model_name",
    "existing_site_root": "/path/to/generated_sites/model_name",
    "start_index": 0,
    "end_index": 100,
    "num_tasks": -1,
    "num_processes": 4,
    "retry_count": 3,
    "anthropic_base_url": "https://api.anthropic.com/v1",
    "anthropic_auth_token": "YOUR_ANTHROPIC_API_KEY",
    "model": "claude-sonnet-4-6"
}
```

**字段说明：**
| 字段 | 说明 |
|------|------|
| `tasks_file` | 任务文件路径（JSONL 格式） |
| `agent_dir` | Agent 目录路径 |
| `output_dir` | 评测输出目录 |
| `existing_site_root` | 已生成网页的根目录（用于续跑） |
| `start_index` / `end_index` | 评测范围 |
| `num_tasks` | 评测任务数（-1 表示全部） |
| `num_processes` | 并行进程数 |
| `retry_count` | 失败重试次数 |
| `anthropic_auth_token` | Anthropic API Key |
| `model` | 使用的模型 |

### 2.4 Text/Video 评测流程

Text 和 Video 任务使用相同的评测脚本：

```bash
# 运行评测（Claude Code 会自动验证 checklist 并打分）
python -m generation.evaluation.test \
    --config /path/to/config.json \
    --models "model1,model2"

# 统一算分
python -m generation.evaluation.evaluate \
    --text_dir /path/to/text/results \
    --video_dir /path/to/video/results \
    --output_dir ./eval_output
```

### 2.5 Image 评测流程

Image 任务需要额外的 LLM 评判步骤：

```bash
# Step 1: 运行评测（生成网页截图）
python -m generation.evaluation.test_image \
    --config /path/to/config.json \
    --models "model1,model2"

# Step 2: LLM 评判（对比原图与生成图）
# 注意：需要配置 OPENAI_API_KEY 和 OPENAI_BASE_URL 用于 Gemini API
python -m generation.evaluation.judge_image \
    --root /path/to/image/results \
    --model Gemini-3-Pro \
    --workers 4

# Step 3: 统一算分
python -m generation.evaluation.evaluate \
    --image_dir /path/to/image/results \
    --score_mode llm_judge \
    --output_dir ./eval_output
```

### 2.6 evaluate.py 参数说明

```bash
python -m generation.evaluation.evaluate [OPTIONS]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--text_dir` | Text 结果目录 | - |
| `--image_dir` | Image 结果目录 | - |
| `--video_dir` | Video 结果目录 | - |
| `--root` | 单一根目录（自动检测模态） | - |
| `--score_mode` | 评分模式：`checklist` / `llm_judge` | `checklist` |
| `--model` | LLM Judge 使用的模型 | `Gemini-3-Pro` |
| `--output_dir` | 输出目录 | `./eval_output` |
| `--workers` | 并行数 | 4 |

---

## 三、完整评测流程示例

### 3.1 Text 任务

```bash
# 1. 生成网页
python -m generation.scripts.run_text_inference \
    --data /path/to/text_tasks.jsonl \
    --output /path/to/output/text/ModelName \
    --model ModelName

# 2. 构建 Docker 镜像（首次）
bash generation/evaluation/agents/claude_code_web_coding/build_image.sh

# 3. 运行评测
python -m generation.evaluation.test \
    --config /path/to/text_config.json \
    --models "ModelName"

# 4. 算分
python -m generation.evaluation.evaluate \
    --text_dir /path/to/output/text/ModelName
```

### 3.2 Image 任务

```bash
# 1. 生成网页
python -m generation.scripts.run_image_inference \
    --data /path/to/image_tasks.jsonl \
    --output /path/to/output/image/ModelName \
    --model ModelName

# 2. 运行评测
python -m generation.evaluation.test_image \
    --config /path/to/image_config.json \
    --models "ModelName"

# 3. LLM 评判（必须步骤）
python -m generation.evaluation.judge_image \
    --root /path/to/output/image/ModelName \
    --model Gemini-3-Pro

# 4. 算分
python -m generation.evaluation.evaluate \
    --image_dir /path/to/output/image/ModelName \
    --score_mode llm_judge
```

### 3.3 Video 任务

```bash
# 1. 生成网页
python -m generation.scripts.run_video_inference \
    --data /path/to/video_tasks.jsonl \
    --output /path/to/output/video/ModelName \
    --model ModelName

# 2. 运行评测
python -m generation.evaluation.test \
    --config /path/to/video_config.json \
    --models "ModelName"

# 3. 算分
python -m generation.evaluation.evaluate \
    --video_dir /path/to/output/video/ModelName
```

---

## 四、输出文件说明

### 4.1 生成阶段输出

```
output/
└── ModelName/
    └── {instance_id}/
        ├── index.html
        ├── styles.css
        ├── script.js
        ├── screenshots/      # 原始参考图（Image 任务）
        ├── frames/           # 视频帧（Video 任务）
        └── .done             # 完成标记
```

### 4.2 评测阶段输出

```
output/
└── ModelName/
    └── {instance_id}/
        ├── task.json         # 任务配置
        ├── checklist.json    # 评分结果
        ├── image/            # 评测截图
        └── output_*/         # 每次运行的日志
```

### 4.3 算分输出

```
eval_output/
├── eval_results_{timestamp}.json   # 详细结果
└── eval_summary_{timestamp}.csv    # 汇总表格
```

---

## 五、评分指标

| 指标 | 说明 |
|------|------|
| **Runnability** | 网页能否正常运行、加载 |
| **Spec Implementation** | 功能是否符合需求规格 |
| **Design Quality** | 视觉设计是否与原图一致 |
| **Accuracy** | 总分 / 满分 |
| **Harmonic Mean** | 各项准确率的调和平均数 |

---

## 六、常见问题

### Q1: Docker 镜像构建失败？
确保已安装 Docker 并有足够权限：
```bash
docker info
```

### Q2: 评测卡住或超时？
- 检查 `num_processes` 是否过大
- 检查网络连接
- 查看 `output_*/` 下的日志

### Q3: checklist.json 中 score 为 null？
表示该条目未完成验证。增加 `retry_count` 或手动检查原因。

### Q4: LLM Judge 报错？
- 检查 API Key 是否有效
- 检查 `screenshots/` 和 `image/` 目录是否有图片

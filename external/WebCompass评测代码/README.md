<p align="center">
<pre align="center">
<b>
  ██╗    ██╗███████╗██████╗  ██████╗ ██████╗ ███╗   ███╗██████╗  █████╗ ███████╗███████╗
  ██║    ██║██╔════╝██╔══██╗██╔════╝██╔═══██╗████╗ ████║██╔══██╗██╔══██╗██╔════╝██╔════╝
  ██║ █╗ ██║█████╗  ██████╔╝██║     ██║   ██║██╔████╔██║██████╔╝███████║███████╗███████╗
  ██║███╗██║██╔══╝  ██╔══██╗██║     ██║   ██║██║╚██╔╝██║██╔═══╝ ██╔══██║╚════██║╚════██║
  ╚███╔███╔╝███████╗██████╔╝╚██████╗╚██████╔╝██║ ╚═╝ ██║██║     ██║  ██║███████║███████║
   ╚══╝╚══╝ ╚══════╝╚═════╝  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝
</b>
</pre>
</p>

<p align="center">
  <a href="https://www.nju.edu.cn"><img src="site/public/figures/nju_logo.png" height="72" alt="Nanjing University"></a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://huggingface.co/Kwaipilot"><img src="site/public/figures/kwaipilot_logo.png" height="72" alt="Kwaipilot"></a>
</p>
<p align="center">
  <b>NJU-LINK</b>&nbsp;&nbsp;×&nbsp;&nbsp;<b>Kwaipilot</b>
</p>

<h3 align="center">A Unified Multimodal Benchmark for Web Generation</h3>

<p align="center">
  <a href="https://arxiv.org/abs/xxxx.xxxxx"><img src="https://img.shields.io/badge/arXiv-xxxx.xxxxx-b31b1b.svg?style=for-the-badge" alt="arXiv"></a>
  <a href="https://nju-link.github.io/WebCompass/"><img src="https://img.shields.io/badge/docs-Project%20Page-blue.svg?style=for-the-badge&logo=readthedocs&logoColor=white" alt="Docs"></a>
  <a href="https://huggingface.co/datasets/NJU-LINK/WebCompass"><img src="https://img.shields.io/badge/🤗-WebCompass-yellow.svg?style=for-the-badge" alt="Dataset"></a>
</p>
<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green.svg?style=flat-square" alt="License"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#dataset">Dataset</a> &bull;
  <a href="#evaluation">Evaluation</a> &bull;
  <a href="#citation">Citation</a>
</p>

---

**WebCompass** is a unified multimodal benchmark and evaluation framework for assessing LLMs' ability to generate functional web pages from three types of inputs: text design documents, reference screenshots, and video demonstrations.

## Highlights

- **Multimodal Input Support**: Evaluate web generation from text, images, or videos
- **Three-Dimension Evaluation**: Runnability, Spec Implementation, and Design Quality
- **LLM-as-Judge**: Visual comparison using multimodal LLMs
- **Extensible Framework**: Easy integration of new models and agents

---

## Dataset

The dataset is hosted on HuggingFace: **[NJU-LINK/WebCompass](https://huggingface.co/datasets/NJU-LINK/WebCompass)**

### Download

```python
from datasets import load_dataset

# Generation tasks
ds_text  = load_dataset("NJU-LINK/WebCompass", "text-generation",  split="train")  # 123
ds_image = load_dataset("NJU-LINK/WebCompass", "image-generation", split="train")  # 116
ds_video = load_dataset("NJU-LINK/WebCompass", "video-generation", split="train")  # 94

# Editing tasks (single-page / multi-page splits, 150 each)
ds_edit_sp = load_dataset("NJU-LINK/WebCompass", "editing", split="sp")
ds_edit_mp = load_dataset("NJU-LINK/WebCompass", "editing", split="mp")

# Repair tasks (single-page / multi-page splits, 150 each)
ds_repair_sp = load_dataset("NJU-LINK/WebCompass", "repair", split="sp")
ds_repair_mp = load_dataset("NJU-LINK/WebCompass", "repair", split="mp")
```

For editing/repair, the JSONL records carry the source code as text but reference screenshots and binary assets that ship as parallel files. Use `editing_repair/scripts/download_from_hf.py` to fetch and reconstruct the local layout the evaluator expects.

### Dataset Structure

| Config             | Split   | Samples | Description |
|--------------------|---------|---------|-------------|
| `text-generation`  | train   | 123 | Generate from text design documents |
| `image-generation` | train   | 116 | Generate from reference screenshots |
| `video-generation` | train   | 94  | Generate from video demonstrations |
| `editing`          | sp / mp | 150 / 150 | Add features to a single- / multi-page site |
| `repair`           | sp / mp | 150 / 150 | Fix a broken single- / multi-page site to match a target |

Additional files on HuggingFace:
- `image/{id}/screenshots/` — reference screenshots for image generation
- `video/videos/{id}.mp4` — video demonstrations for video generation
- `editing/{sp,mp}/{instance_id}/src/...` — assets for editing tasks
- `repair/{sp,mp}/{instance_id}/{src,dst}/...` — broken assets and target screenshots for repair tasks
- `packages/anthropic-ai-claude-code-2.0.67.tgz` — Claude Code package for evaluation

---

## Quick Start

### Installation

```bash
git clone https://github.com/NJU-LINK/WebCompass.git
cd WebCompass
pip install -e .
```

### Configure LLM

Set environment variables for API access:

```bash
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_API_KEY="your-api-key"
```

```python
from generation.call_model import call_api

response = call_api("Hello, what model are you?", model="gpt-4o")
```

---

## Evaluation

### Running Agent Evaluation

The evaluation uses Docker containers with Claude Code. Follow these steps:

#### 1. Download Required Package

Download the Claude Code package from HuggingFace and place it in the packages directory:

```bash
# Download from HuggingFace
wget https://huggingface.co/datasets/NJU-LINK/WebCompass/resolve/main/packages/anthropic-ai-claude-code-2.0.67.tgz \
  -O generation/evaluation/agents/claude_code_web_coding/packages/anthropic-ai-claude-code-2.0.67.tgz
```

#### 2. Build Docker Image

```bash
cd generation/evaluation/agents/claude_code_web_coding
bash build_image.sh
```

#### 3. Configure API Keys

Edit `generation/evaluation/configs/lab_api.json`:

```json
{
    "tasks_file": "path/to/your/tasks.jsonl",
    "agent_dir": "generation/evaluation/agents/claude_code_web_coding",
    "anthropic_base_url": "https://api.anthropic.com/v1",
    "anthropic_auth_token": "YOUR_ANTHROPIC_API_KEY",
    "output_dir": "./output",
    "model": "claude-sonnet-4-6",
    "num_processes": 4,
    "retry_count": 3
}
```

The evaluation runner (`test.py`) reads this config and generates `task.json` for each task, which is then passed to the Docker container.

#### 4. Run Evaluation

```bash
# Run agent inference (generates web pages in Docker containers)
python -m generation.evaluation.test

# Score the results
python -m generation.evaluation.evaluate \
  --root /path/to/results \
  --output_dir ./eval_output
```

### Evaluation Dimensions

| Dimension | Description | Weight |
|-----------|-------------|--------|
| **Runnability** | Page loads without errors | ~10% |
| **Spec Implementation** | Interactions match specification | ~60-70% |
| **Design Quality** | Visual fidelity and layout accuracy | ~20-25% |

---

## Project Structure

```
WebCompass/
├── site/                           # Project website (Next.js)
├── generation/                     # Evaluation framework
│   ├── call_model.py               # Unified model client
│   ├── evaluation/                 # Evaluation tools
│   │   ├── agents/                 # Agent implementations
│   │   │   └── claude_code_web_coding/
│   │   │       ├── build_image.sh  # Docker build script
│   │   │       ├── create_traj.sh  # Evaluation runner
│   │   │       └── packages/       # Required packages (download from HF)
│   │   ├── configs/                # Configuration files
│   │   ├── evaluate.py             # Main evaluation script
│   │   └── judge_image.py          # LLM visual judge
│   └── scripts/                    # CLI scripts
├── requirements.txt
├── setup.py
└── README.md
```

---

## Citation

If you use WebCompass in your research, please cite:

```bibtex
@misc{webcompass2024,
  title={WebCompass: A Unified Multimodal Benchmark for Web Generation},
  author={WebCompass Team},
  year={2024},
}
```

## License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built at <a href="https://www.nju.edu.cn">Nanjing University</a> &amp; <a href="https://huggingface.co/Kwaipilot">Kwaipilot</a></sub>
</p>

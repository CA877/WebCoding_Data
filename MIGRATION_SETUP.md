# 迁移到新电脑操作手册（2026-08-04）

> 本文档供新电脑上的 Codex/开发者照做。所有命令假设你在新电脑的 `WebCoding_Data` 项目根目录执行。
> 迁移方式：旧 Mac → 物理机中转（`migration_from_mac_20260804/`）→ 新电脑拉取。

---

## 0. 背景与现状

- 项目目标：构建 70K 训练集（7 类任务 × 10K），对齐 WebCompass / Design2Code / Vision2Web / FLAME-VLM-Code 四榜单。
- 代码仓库：`CA877/WebCoding_Data`（GitHub，**旧电脑无法 push，本次不走 GitHub**，全部经物理机中转）。
- 物理机：`adminweihunj@36.213.175.38:65022`，项目目录 `/data1/xieqianqian/webcoding/WebCoding_Data`（最终数据落点，51G）。
- 本次迁移内容（在物理机 `migration_from_mac_20260804/` 下，2.3G）：
  - 完整代码 + `.git` 历史、`construct/`、`scripts/`、`preprocess/`、`tests/`
  - `runs/`：`artifactsbench_3k_qwen3.7max_20260804`（3k 生成快照，约 1300 个项目）、`complex_query_qwen37_full_20260801`（1k 样本）、`construct_edit_repair_precheck_20260804`（edit/repair 预检查）、`artifactsbench_queries_3k_qwen3.7max_20260731`（queries 源）
  - `docs/`（含 `项目用api.pdf` 之外的文档）、`audits/`、`logs/`、`.cache/qwen3-tokenizer.json`、`review_output_full_samples/`
  - `third_party/`（ArtifactsBenchmark / WebGen-Agent / WebCompass）、`web-coding-agent/`（**不含 .venv**）
- 已删除：本地 `datasets/` 11.5G（旧口径构造产物，删除清单在旧电脑 `logs/migration_20260804/datasets_deleted_manifest.json`）。
- 未搬/需单独传：所有 `.env` 敏感文件、`docs/项目用api.pdf`（在 `secrets_20260804.tar.gz` 里，**不经过物理机**）。

---

## 1. 从物理机拉取项目

```bash
mkdir -p ~/Documents/code && cd ~/Documents/code
rsync -av -e 'ssh -p 65022' \
  adminweihunj@36.213.175.38:/data1/xieqianqian/webcoding/WebCoding_Data/migration_from_mac_20260804/ \
  ~/Documents/code/WebCoding_Data/
cd ~/Documents/code/WebCoding_Data
```

验证：
```bash
git log --oneline -3            # 应看到历史提交
ls construct scripts runs .cache/qwen3-tokenizer.json
```

> 注意：SSH 偶发 `Bad file descriptor` 瞬断，重试即可；`rsync` 命令必须带 `-e 'ssh -p 65022'`，否则走默认 22 端口失败。

---

## 2. 恢复敏感文件（用户单独传输）

用户会提供 `secrets_20260804.tar.gz`（含 3 个 env 文件 + `docs/项目用api.pdf`）。解压后放回：

| 包内文件名 | 恢复位置 |
|---|---|
| `env_root.env` | `WebCoding_Data/.env` |
| `env_abq3k.env` | `WebCoding_Data/.env.abq3k`（3k 生成用 Dashscope key） |
| `env_web_coding_agent.env` | `WebCoding_Data/web-coding-agent/.env` |
| `项目用api.pdf` | `WebCoding_Data/docs/项目用api.pdf` |

```bash
# 示例（tar 解压到临时目录后逐个放回）
chmod 600 .env .env.abq3k web-coding-agent/.env
```

这些文件已被 `.gitignore` 忽略（`.env.*`），不会污染 git。

---

## 3. 环境搭建

### 3.1 Python 3.12 + 依赖

```bash
# 确认 Python 版本（旧电脑用的是系统 Python 3.12）
python3 --version   # 需要 3.12.x
python3 -m pip install --upgrade pip
python3 -m pip install openai httpx playwright Pillow python-dotenv pytest requests
```

### 3.2 Playwright Chromium

构造/渲染脚本通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指定浏览器（旧电脑是 macOS arm64 `chromium-1200`）：

```bash
python3 -m playwright install chromium
# 找到实际路径后导出，例如：
export PLAYWRIGHT_CHROMIUM_EXECUTABLE="$HOME/Library/Caches/ms-playwright/chromium-1200/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
```

### 3.3 Node.js（`node --check` 校验用）

```bash
node --version   # 任意现代版本（旧电脑 v20.19.6）
```

### 3.4 web-coding-agent 虚拟环境（可选，若要用该子项目）

```bash
cd web-coding-agent && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt 2>/dev/null || true
```

---

## 4. 项目自检

```bash
cd ~/Documents/code/WebCoding_Data
python3 -m pytest tests/ -q
ls -la .cache/qwen3-tokenizer.json          # 构造脚本依赖，必须有
ls runs/artifactsbench_3k_qwen3.7max_20260804/projects | wc -l   # 应 ~1300+
```

---

## 5. 3k 生成：续跑或补齐

物理机副本是「进行中快照」：每个项目原子写入（`tmp` + `os.replace`，无半成品），但可能缺最后几个未完成项目。

### 5.1 若旧电脑已跑完 → 直接增量同步最新版

```bash
# 在旧电脑上执行一次，或在新电脑上从物理机拿最新：
rsync -av -e 'ssh -p 65022' \
  adminweihunj@36.213.175.38:/data1/xieqianqian/webcoding/WebCoding_Data/migration_from_mac_20260804/runs/artifactsbench_3k_qwen3.7max_20260804/ \
  runs/artifactsbench_3k_qwen3.7max_20260804/
```

### 5.2 若未跑完 → 断点续跑（自动跳过已有 `metadata.json` 的项目）

```bash
cd ~/Documents/code/WebCoding_Data
export OPENAI_API_KEY="$(grep -o '^OPENAI_API_KEY=.*' .env.abq3k | cut -d= -f2)"
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL=qwen3.7-max
python3 -u scripts/solve_artifactsbench_cases.py \
  --input runs/artifactsbench_queries_3k_qwen3.7max_20260731/queries.jsonl \
  --output-dir runs/artifactsbench_3k_qwen3.7max_20260804 \
  --env-file .env.abq3k --all --workers 8 --model qwen3.7-max \
  --max-tokens 20000 --max-retries 2 --request-timeout 900 \
  2>&1 | tee -a logs/solve_abq_3k_qwen37_20260804/run.log
```

> 注意：`results.jsonl` 落盘可能被一批里卡在 API 超时重试的 job 阻塞（主线程等待），**项目以 `metadata.json` 为准**，不影响数据。批量运行请用前台会话/`nohup` + 持久日志（见 AGENTS.md）。

---

## 6. 后续主要任务（edit/repair 构造）

预检查已跑通：edit(forward) 3/3、repair 简化版（单 desktop 缺陷截图、无视觉 delta 门禁）6/6。全量构造命令：

```bash
cd ~/Documents/code/WebCoding_Data
export OPENAI_API_KEY="$(grep -o '^OPENAI_API_KEY=.*' .env.abq3k | cut -d= -f2)"
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export OPENAI_MODEL=qwen3.7-max
export QWEN_TOKENIZER_JSON="$PWD/.cache/qwen3-tokenizer.json"
export CONSTRUCT_API_TIMEOUT=600 SSL_NO_VERIFY=1
export PLAYWRIGHT_CHROMIUM_EXECUTABLE="<上一步查到的 chromium 路径>"

# 先生成各项目的 clean 截图（edit/repair 记录引用 <项目名>_clean.png）
python3 scripts/prepare_clean_screenshots.py \
  --projects runs/artifactsbench_3k_qwen3.7max_20260804/projects/abq-* \
  2>&1 | tee -a logs/construct_edit_repair_20260804/prepare_screens.log

# edit（forward）
python3 -u construct/construct_text_editing.py \
  --project-list <项目清单> --output-dir runs/construct_edit_repair_20260804/text_edit \
  --workers 8 --min-tasks 2 --max-tasks 10 --max-output-tokens 8192 \
  2>&1 | tee -a logs/construct_edit_repair_20260804/edit.log

# repair（本地无代理，--browser-proxy 传空）
python3 -u construct/construct_text_repair.py \
  --project-list <项目清单> --output-dir runs/construct_edit_repair_20260804/text_repair \
  --workers 8 --min-tasks 2 --max-tasks 10 --max-output-tokens 8192 --browser-proxy "" \
  2>&1 | tee -a logs/construct_edit_repair_20260804/repair.log
```

项目清单示例：每行一个项目绝对路径（`find runs/artifactsbench_3k_qwen3.7max_20260804/projects -maxdepth 1 -type d | sort > edit_projects.txt`）。
构造器按口径要求：完整 HTML/CSS/JS 进上下文、40K Qwen token 上限，超限项目自动淘汰（`construct/README.md`）。

---

## 7. 物理机数据访问（最终数据落点，无需搬）

```bash
ssh -p 65022 adminweihunj@36.213.175.38
# 物理机 Python（lora 环境）：
#   /data1/xieqianqian/webcoding/WebCoding_Data/web-coding-agent/.conda/lora/bin/python
# 关键数据：
#   /data1/xieqianqian/webcoding/WebCoding_Data/data/20260804/all_merged_instructions/sft_train/train_sharegpt.jsonl   (7,503 条)
#   /data1/xieqianqian/webcoding/WebCoding_Data/datasets/pipeline_a/useful                                   (WebRenderBench 31,765 项目)
```

同步本地修改到物理机的常规方式：
```bash
rsync -e 'ssh -p 65022' -av <本地文件> adminweihunj@36.213.175.38:/data1/xieqianqian/webcoding/WebCoding_Data/<目标路径>
```

---

## 8. 关键环境约定（来自 AGENTS.md，务必遵守）

- **外网访问必须代理**（本机脚本；当前 Clash Verge `mixed-port` 为 `7897`）：
  ```bash
  export ALL_PROXY=http://127.0.0.1:7897
  export HTTPS_PROXY=http://127.0.0.1:7897
  export HTTP_PROXY=http://127.0.0.1:7897
  export NO_PROXY="idealab.alibaba-inc.com,alibaba-inc.com,localhost,127.0.0.1"
  ```
- **物理机代理用 HTTP**：`http://127.0.0.1:7890`（不要用 7891）。
- **HuggingFace 用镜像**：`export HF_ENDPOINT=https://hf-mirror.com`；下载用 `httpx`（requests 走 SOCKS 会 SSL 报错）。
- 调外部 API 设 `export SSL_NO_VERIFY=1`。
- 物理机相关写入只能在 `/data1/xieqianqian/webcoding/WebCoding_Data/` 下；脚本先本地改好再 rsync，不远程手写。
- 长任务必须持久化日志到项目 `logs/<task>/<run_id>/`，禁止只写 `/tmp`。
- 禁用 `rm -f`（Codex 安全策略会拦截），用临时文件 + `os.replace`。
- 命名禁止 `smoke`；小规模验证称「预检查运行」。

---

## 9. 常见坑

1. **rsync 走错端口**：必须 `-e 'ssh -p 65022'`，否则连 22 端口失败。
2. **SSH 瞬断 `Bad file descriptor`**：重试（一般 2-3 次内成功）。
3. **macOS 自带老 rsync**：不支持 `--info=stats2` 等 GNU 参数，用 `-a --stats` 即可。
4. **Playwright 找不到浏览器**：设 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指向实际安装路径。
5. **3k `results.jsonl` 不更新**：缓冲/主线程阻塞，以 `projects/<id>/metadata.json` 为准。
6. **构造器要求项目根有 `<项目名>*.png`**：先跑 `prepare_clean_screenshots.py`。

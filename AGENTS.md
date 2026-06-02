# AGENTS.md

## 终极目标

构建 **70K 训练集**（7 类任务 × 10K），使模型在以下 4 个榜单上取得高分：

| 榜单 | 输出格式 | 评测要点 |
|------|----------|----------|
| **WebCompass** | 多文件项目（index.html + styles.css + script.js） | Docker 内 http.server 渲染 |
| **Design2Code** | 单 HTML，CSS inline | 视觉相似度 |
| **Vision2Web** | 多文件项目 | Visual Score + Functional Score |
| **FLAME-VLM-Code** | React 组件 | 渲染截图 cosine similarity |

所有榜单都不要求模型输出远程 URL。训练数据统一用 `assets/` 本地相对路径。

## 数据来源与处理

- **Pipeline A** — WebRenderBench 31,765 个单页 HTML，expand → clean → add_js（LLM 生成 43 种 JS 功能之一，ratio=0.5）
- **Pipeline B** — WebCode2M 28K URL，Playwright 爬取 → postprocess（保留网站原生 JS，无 LLM 调用）
- 两条 Pipeline 并行执行，入口: `preprocess/run_server.sh`
- 预计产出 ~30K 可用项目 → 构造 70K 训练样本

---

## 运行实验原则：决策价值导向

1. 实验应以假设和决策价值为导向，而不是为了补齐路径、填满表格，或让 ablation 看起来完整。每组实验都应回答一个明确假设，或支持一个后续决策。

2. 不在低边际信息增益的方向上穷举。如果可以预见某组实验对性能提升、方向判断或后续改进没有明显贡献，尤其只是重复确认"不可行 / 无效果"，应停止该方向，不做穷举式验证。

3. 当某个方向已经表现很差时，不要把它在所有条件下跑满后才给出相同结论。应尽早记录已有证据、停止追加实验，并把资源转向更可能改变决策的方向。

4. 设计数据构造或模型评测任务时，优先说明该实验会改变什么判断：例如是否继续扩量、是否修改 schema、是否切换构造方法、是否保留某类任务。

5. 例如 huggingface 等请使用中国镜像网站。

## 远程脚本工作流

1. 涉及远程服务器 / H 集群的脚本修改，必须先在本地仓库里编辑和检查脚本，再通过 `rsync` 同步到 SSH 服务器上执行。

2. 不直接在远程服务器上临时手写或改脚本；除非只是查看状态、启动已有脚本、杀进程、检查日志等操作。

3. 连接 H 集群使用：

```bash
ssh -CAXY main.liujiaheng.ailab-colab.ws@h.pjlab.org.cn
```

对应的 `rsync`：

```bash
rsync -e 'ssh -CAXY' ...
```

4. H 集群项目目录：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

5. H 集群上所有 WebCoding_Data 相关写入都必须放在 `xieqianqian` 项目目录下，即：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

不要写入 `/mnt/shared-storage-user/colab-share/liujiaheng/workspace/webcoding_smoke_code_*` 或其他非 `xieqianqian` 工作目录。历史 smoke 目录只允许只读排查，不作为新实验输出位置。

6. 在 H 集群运行 WebCoding_Data 相关脚本时，使用 `lora` 环境，不使用系统 Python 或其他临时环境。

7. Pipeline A 使用 H 集群上的 WebRenderBench useful 数据构造，不使用 `webrenderbench_raw` 原始数据目录。useful 数据目录为：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/h_rebuild/webrenderbench_clean_split/useful
```

该目录已确认包含 31,765 个项目目录，且 31,765 个项目目录均包含 `index.html`。

8. Pipeline A 的样本级预处理必须设置硬超时保护，避免单个 expand/clean worker 卡死导致整批任务挂住。运行 `preprocess/pipeline_a_sample_level.py` 时传 `--site-timeout`，100 条 smoke run 建议先用 `--site-timeout 900`。

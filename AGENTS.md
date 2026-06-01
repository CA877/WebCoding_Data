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

3. 从 GitHub 同步别人的代码更新后，应立即将本地仓库同步到 H 集群的项目目录，保证本地与 `h-liu` 上的代码一致。

4. 如果在 H 集群上跑小规模测试，应将测试结果打包并同步回本地，方便用户在本地检查结果。

5. 连接 H 集群使用：

```bash
ssh -CAXY main.liujiaheng.ailab-colab.ws@h.pjlab.org.cn
```

本机 SSH 配置中可使用别名：

```bash
ssh -CAXY h-liu
```

对应的 `rsync`：

```bash
rsync -e 'ssh -CAXY' ...
```

6. H 集群项目目录：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

7. H 集群上所有 WebCoding_Data 相关写入都必须放在 `xieqianqian` 项目目录下，即：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

不要写入历史临时测试目录或其他非 `xieqianqian` 工作目录。历史临时测试目录只允许只读排查，不作为新实验输出位置。除非用户明确指定其他项目，否则新脚本、日志、数据、临时文件都只能写入上述 `webcoding_data` 目录及其子目录。

8. 在 H 集群运行 WebCoding_Data 相关脚本时，使用 `lora` 环境，不使用系统 Python 或其他临时环境。

9. 新实验、脚本、日志、目录和结果包命名禁止使用 `smoke`；小规模验证统一称为“小规模测试”或“预检查运行”。

10. Pipeline A 使用 H 集群上的 WebRenderBench useful 数据构造，不使用 `webrenderbench_raw` 原始数据目录。useful 数据目录为：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/datasets/pipeline_a/useful
```

该目录已确认包含 31,765 个项目目录，且 31,765 个项目目录均包含 `index.html`。旧路径
`/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/h_rebuild/webrenderbench_clean_split/useful`
保留为指向该目录的 symlink，仅用于兼容历史脚本。

11. Pipeline A / Pipeline B 的样本级预处理与爬取必须设置硬超时保护，避免单个 worker 卡死导致整批任务挂住。100 条小规模预检查运行建议先用 `--site-timeout 600`。

# AGENTS.md

## 运行实验原则：决策价值导向

1. 实验应以假设和决策价值为导向，而不是为了补齐路径、填满表格，或让 ablation 看起来完整。每组实验都应回答一个明确假设，或支持一个后续决策。

2. 不在低边际信息增益的方向上穷举。如果可以预见某组实验对性能提升、方向判断或后续改进没有明显贡献，尤其只是重复确认“不可行 / 无效果”，应停止该方向，不做穷举式验证。

3. 当某个方向已经表现很差时，不要把它在所有条件下跑满后才给出相同结论。应尽早记录已有证据、停止追加实验，并把资源转向更可能改变决策的方向。

4. 设计数据构造或模型评测任务时，优先说明该实验会改变什么判断：例如是否继续扩量、是否修改 schema、是否切换构造方法、是否保留某类任务。

5. 例如huggingface等请使用中国镜像网站。
   
6. 本项目的数据存储在：
ssh -p 47795 root@connect.westd.seetacloud.com
密码：SnDXpsEmpF0t

## 远程脚本工作流

1. 之后涉及远程服务器 / H 集群的脚本修改，必须先在本地仓库里编辑和检查脚本，再通过 `rsync` 同步到 SSH 服务器上执行。

2. 不直接在远程服务器上临时手写或改脚本；除非只是查看状态、启动已有脚本、杀进程、检查日志等操作。

3. 连接 H 集群必须使用下面这个 SSH 命令形式：

```bash
ssh -CAXY main.liujiaheng.ailab-colab.ws@h.pjlab.org.cn
```

对应的 `rsync` 也必须显式使用：

```bash
rsync -e 'ssh -CAXY' ...
```

4. H 集群当前项目目录默认使用：

```text
/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data
```

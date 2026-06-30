# 实验室 H 集群使用文档

## 实验室 H 集群管理新规

为应对实验室集群管理相关新出台制度，同时提高资源的利用率。请各位研究员严格遵守以下规章：

1. **杜绝任务碎片化**

    1. 起任务之前，通过管理界面（顶部导航栏“**管理**”\-\>左侧栏“**智能私有机器管理**”）查看显卡空余情况，保证不出现**A节点\+B节点的已占有卡数\<=8**的情况出现

    2. Rjob name 后缀带人名。例如：train\_qwen3\_shihao。便于管理员联系任务负责人。

    3. 杜绝碎片化首选使用占卡控制台，其次通过参数指定节点id：[实验室 H 集群使用文档](https://my.feishu.cn/wiki/Ul2XwWujTiULpFkx92LcVLBMnD7#share-JLztdyJD3ocWImxDDn7cgsZcnXg)

2. **保证任务利用率**

    占卡平台规则：

    1. 对于空闲卡，发现后倒计时 30 min，过时仍空闲就占用

    2. 对于任务，监控利用率，浪费卡数\>1开始倒计时，30min警告一次，60min关闭任务，对应显卡自动进入规则 1

    1. 有同学因为是跑推理任务，可能跑不满卡的利用率，我这有个程序，会自动和主程序一起拉满利用率，有可能影响主程序的速度（未验证），但是能保证卡是满的。建议大家起任务时都把它挂在后台运行。对于高利用率（例如训练），这个占卡程序会退化为利用率监控程序，理论上完全不会影响高利用率任务。同时本程序只监控利用率，不监控显存，本身只占用几G显存，基本不影响

    2. /mnt/shared\-storage\-user/colab\-share/liujiaheng/workspace/smart\_gpu\_keeper\.py

3. **杜绝显卡闲置**

    1. 开发机 **monitor** 禁止非管理员使用，只用于运行占卡控制台

    2. 占卡程序由管理员和各位使用者共同使用，对

    3. 空闲卡进行常驻占用。

    4. **要跑任务前去控制台关闭所需数量的卡**（用多少关多少，这样也能同时避免出现碎片化的情况）

    5. **跑完任务后去控制台重新占据空闲的卡**

    6. 占卡控制台地址：

        1. colabnew：https://h\.pjlab\.org\.cn/kapi/workspace\.kubebrain\.io/ailab\-colabnew/ws\-568f94f0d49f7f77/vscode/proxy/8001/

        2. colab：https://h\.pjlab\.org\.cn/kapi/workspace\.kubebrain\.io/ailab\-colab/ws\-c36b9bbd96bf3cda/vscode/proxy/8001/

1. 程序界面。任何使用或维护问题联系管理员@李世昊

![Image](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTE5OTQyYjNhOTg1NWNmNGNmZjI4NTRjMDJkNDdjOWNfMjI4ZGEwYzRkN2JjYzUxZTliYzQyYTY0MWRmMTZmMGJfSUQ6NzYzNDkzMjY5NTU5NTk3NzkzN18xNzgwNDUxNjYxOjE3ODA1MzgwNjFfVjM)



## VPN 账号

首选线路：

|lishihao|z38Jh6R\_:UAzF9h|
|---|---|

备选线路：

|liujiaheng|9Y9v8HV3txkwAL\.|
|---|---|

## 最新镜像地址

registry\.h\.pjlab\.org\.cn/ailab\-colab\-colab\_gpu/liujiaheng:main\-20260309202300



`source /mnt/shared-storage-user/colab-share/liujiaheng/anaconda3/etc/profile.d/conda.sh`

## VPN当日使用预约

VPN每次只能同时登陆2人

|lishihao||liujiaheng|||lishihao||liujiaheng|||
|---|---|---|---|---|---|---|---|---|---|
|使用人A|使用人B|使用人C|使用人D|时间段|使用人A|使用人B|使用人C|使用人D|时间段|
|||||8:30\-9:00|lwl|wzh|||16:00\-16:30|
|||||9:00\-9:30|lwl|wzh|||16:30\-17:00|
|zjx||||9:30\-10:00|lwl|wzh|||17:00\-17:30|
|zjx|xqq|||10:00\-10:30||sicheng|||17:30\-18:00|
|zjx|xqq|||10:30\-11:00||sicheng|||18:00\-18:30|
|zlt|xqq|||11:00\-11:30||sicheng|||18:30\-19:00|
|zlt|xqq|||11:30\-12:00|zlt|sicheng|||19:00\-19:30|
|||||12:00\-12:30|zlt|sicheng|||19:30\-20:00|
|||||12:30\-13:00|||||20:00\-20:30|
|||||13:00\-13:30|wjt||lwl||20:30\-21:00|
|lwl||||13:30\-14:00|||lwl||21:00\-21:30|
|lwl||||14:00\-14:30|wzh|xqq|lwl||21:30\-22:00|
|lwl||||14:30\-15:00|wzh|xqq|lwl||22:00\-22:30|
|lwl||||15:00\-15:30|wzh|xqq|lwl||22:30\-23:00|
|lwl||||15:30\-16:00|wzh|xqq|||23:00\-24:00|
||||||wzh|xqq|||24:00\-次日|

## 前置

### 使用文档知识库

[   H集群使用指引](https://aicarrier.feishu.cn/mindnotes/ECWzbrfiSmioKIncgJ1clP9gnhe#mindmap)

### 登录管理界面

需要使用 AI Lab VPN 登录内部账号使用

https://vpn\.pjlab\.org\.cn:1443/portal/\#/login

#### 集群地址

https://h\.pjlab\.org\.cn/control\-center/index?lang=zh\_CN

**注**：登录集群使用

liujiaheng

9Y9v8HV3txkwAL\.

### 工作目录

`/mnt/shared-storage-user/colab-share/liujiaheng/workspace/`

#### 共享资源目录

**模型目录**

`/mnt/shared-storage-user/colab-share/liujiaheng/pjlab-oss/models`

**数据集目录**

`/mnt/shared-storage-user/colab-share/liujiaheng/pjlab-oss/datasets/`

### Rlauch 和 Rjob 机制

H 集群的开发机本身只有少量的 cpu 和内存资源以供文本编辑、安装软件等。所有的高性能计算资源不属于开发机，由 Rlauch 和 Rjob 机制进行启用。

其中 Rlauch 近似普通集群上的 debug，相当于召唤一个有 gpu 的开发机，默认使用开发机的本地环境进行克隆；Rjob 类似任务，需要额外指定镜像

### SSH

`ssh -CAXY ``main.liujiaheng.ailab-colab.ws@h.pjlab.org.cn`

如果需要添加SSH公钥，请登录集群管理界面\-密钥管理\-添加（阿里云上的ssh公钥已经全部迁移过了）

## Rlaunch单机流程

关于使用 oss 的问题：[实验室 H 集群使用文档](https://tcn8xrfzxv1n.feishu.cn/wiki/Ul2XwWujTiULpFkx92LcVLBMnD7#share-IclTdxC1iozInbxjS9XcO5ehnbb)

### 基于 Rlaunch 进行调试

```Bash
rlaunch \
  --gpu=1 \
  --memory=96000 \
  --cpu=64 \
  --charged-group=colabnew_gpu \
  --private-machine=group \
  --mount=gpfs://gpfs1/colab-share:/mnt/shared-storage-user/colab-share \
  -- bash
```

可以直接在开发机的终端自动连接到rlaunch的终端进行自由调试，crtl\+D 就可以退出了

注意，及时检查这种进程是否被退出/回收了，否则会变成僵尸进程占用资源（尤其是在占用GPU的情况下）

**如果调试涉及oss：**

```Bash
rlaunch \
  --gpu=1 \
  --memory=32000 \
  --cpu=32 \
  --charged-group=colabnew_gpu \
  --private-machine=group \
  --mount=gpfs://gpfs1/colab-share:/mnt/shared-storage-user/colab-share \
  --custom-resources brainpp.cn/fuse=1 \
  -- bash
```



### 参数详解

#### 常用参数

|参数格式|功能|示例|
|---|---|---|
|\-\-charged\-group=xxx|任务运行的资源组|\-\-charged\-group=colab\_gpu|
|\-private\-machine=group|（加上即可）|\-private\-machine=group|
|\-\-mount=\<存储路径\>:\<容器内挂载路径\><br>|文件挂载<br>|\-\-mount=gpfs://gpfs1/colab\-share:/mnt/shared\-storage\-user/colab\-share|
|\-\-cpu n|cpu数目|\-\-cpu=100|
|\-\-memory|内存\(MB\)|\-\-memory=800000|
|\-\-gpu n|gpu数目|\-\-gpu=8|

#### 不常用参数

|参数格式|功能|示例|
|---|---|---|
|\-\-image=xxx|指定镜像|\-\-image=registry\.h\.pjlab\.org\.cn/x/x|
|\-\-max\-wait\-duration=3m0s|最长等待时间|\-\-max\-wait\-duration=3m0s|

### 通用设置

```Bash
source /mnt/shared-storage-user/colab-share/liujiaheng/anaconda3/etc/profile.d/conda.sh
export HF_DATASETS_CACHE="/mnt/shared-storage-user/colab-share/hf_cache"
export TRANSFORMERS_CACHE="/mnt/shared-storage-user/colab-share/hf_cache"
export TMPDIR="/mnt/shared-storage-user/colab-share/tmp"
conda activate <your_conda_env>
cd /path/to/your/file

# your command here
```

### 注意事项

#### **关于 worker 被清理的问题**

- **原因**：

    - 如果 worker 执行的任务本身已经结束，进程就会自然退出。

    - 如果 worker 是通过 `bash` 命令启动的，那么当终端断开连接时，worker 也会被清理掉。

- **解决方法**：

    1. 建议通过 **网页端开发机终端** 打开并执行 `rlaunch` 命令。

    2. 在 `rlaunch` 启动时，不要直接用 `bash`，而是执行一个 **不会结束的命令**，例如：

    `python test.py; sleep inf`

    3. 启动完成后，可以关闭网页端，不会导致终端断开，worker 也能持续保持运行。

这样即使运行失败也会被挂起，不会被清理。但请注意及时手动释放资源。

### 参考资料

如果遇到难以解决的问题，可以查看参考资料：

[012\-\-rlaunch](https://aicarrier.feishu.cn/docx/AAaMdkGhUo3f2OxkiBNcQwiunHb)

## Rjob 单机流程

关于使用 oss 的问题：[实验室 H 集群使用文档](https://tcn8xrfzxv1n.feishu.cn/wiki/Ul2XwWujTiULpFkx92LcVLBMnD7#share-IclTdxC1iozInbxjS9XcO5ehnbb)

### 简单示例rjob\.sh 创建 rjob 任务：

```Bash
rjob delete rjob-test     #防止同名任务
rjob submit \
--name=rjob-test  \     #任务名
--gpu=8 \     #gpu数量
-P 1 \     #节点数量
-e DISTRIBUTED_JOB=true \
--memory=64000 \     #内存单位是MB
--cpu=32 \     #CPU数量
--charged-group=colab_gpu \    #GPU任务选择GPU组，cpu任务可以改为colab_cpu
--private-machine=group \
--mount=gpfs://gpfs1/colab-share:/mnt/shared-storage-user/colab-share \ #挂载路径
--image=registry.h.pjlab.org.cn/ailab-colab/liujiaheng-workspace:20250914012534 \ #镜像地址，使用开发机镜像
--host-network=true \
-- bash -exc /mnt/shared-storage-user/colab-share/test.sh #提交的rjob任务中使用的命令脚本
```

test\.sh：

```Bash
set -ex
source /home/liujiaheng/anaconda3/etc/profile.d/conda.sh
conda activate llama_factory
cd /mnt/shared-storage-user/colab-share/workspace_1/xwh_1/LLaMA-Factory
llamafactory-cli train ./examples/train_full/xwh_qwen3_8b__full_sft_lcbv5v6balance_SFT_filtered_2_format32.yaml
```

### 使用技巧

- 配置建议：

- 查看 RJob： `brainctl get rjob `*`rjob_name`*` -n `*`project_name`*

- 删除 RJob： `brainctl delete rjob `*`rjob_name`*` -n `*`project_name`*



## 开发机联网配置

临时配置

```Plain Text
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
source <(curl -sSL http://deploy.i.h.pjlab.org.cn/infra/scripts/setup_proxy.sh)
```

永久配置

`sudo vim ~/.bashrc`

```Plain Text
export http_proxy='http://httpproxy-headless.kubebrain.svc.pjlab.local:3128'
export https_proxy='http://httpproxy-headless.kubebrain.svc.pjlab.local:3128'
export no_proxy='10.0.0.0/8,100.96.0.0/12,.pjlab.org.cn'
```

`sourc``e`` ~/.bashrc`

## 节点选择

### rlaunch \& rjob

```Plain Text
指定某些固定机器
--positive-tags node/gpu-xxxx-xxxx.host.shzhisuan.com,...
--positive-tags node/gpu-xxxx-xxxx.host.shzhisuan.com,...
排除某些嫌疑机器
--negative-tags node/gpu-xxxx-xxxx.host.shzhisuan.com,...
--negative-tags node/gpu-xxxx-xxxx.host.shzhisuan.com,...
```

## OSS 存储

### 基本信息

**Bucket name**：liujiaheng

H 集群使用如下对象存储，可以使用 rclone 进行操作，目前**已挂载**在`/mnt/shared-storage-user/colab-share/liujiaheng/pjlab-oss/`下，可以直接使用

```Bash
[pjlab-oss]
type = s3
provider = Other
access_key_id = wj5aml4l0eqmjxa5ffuv
secret_access_key = 2j7g62hcqdonmpw2t2h9rqeteix1jvtyr0l8bnm4
endpoint = [http://hdd1.h.pjlab.org.cn:8060](http://hdd1.h.pjlab.org.cn:8060) 
```

### 基本配置与使用

#### rclone 配置

查看一下配置文件的位置：

```Plain Text
rclone config file
```

正常情况下应该在：`/home/liujiaheng/.config/rclone/rclone.conf`

`cat {rclone config file}` 查看配置文件内容

`sudo vim {rclone config file}` 修改配置文件内容

#### rclone 使用

rclone 命令行使用方式参考：https://rclone\.cn/commands/

**常用命令：**

文件\&文件夹上传：

```Bash

rclone copy --copy-links --progress --checkers 64 --transfers 64 --ignore-existing $SOURCE_DIR $S3_DIR
示例：路径按实际地址进行替换
rclone copy --copy-links --progress --checkers 64 --transfers 64 --ignore-existing /mnt/shared-storage-user/colab-share/liujiaheng/workspace/models pjlab-oss:liujiaheng/models
# 注意：若上传文件，源路径是文件路径，目标路径是文件夹路径
# 若想转移，可以用 rclone move
```

\-\-ignore\-existing 参数仅同步目标目录中完全不存在的新文件，若需完整增量同步，需移除该参数

文件夹删除

```Plain Text
rclone purge pjlab-oss:liujiaheng/models
```

### Worker 挂载

Rjob \& Rlaunch 使用 oss 中的文件请按如下挂载：

```Bash
# rlaunch或rjob启动脚本添加以下行，
--custom-resources brainpp.cn/fuse=1 \

# Worker启动后，~/.bashrc添加AK/SK环境变量，
source ~/.bashrc
# 关闭代理
unset https_proxy
unset http_proxy
cd /mnt/shared-storage-user/colab-share/liujiaheng
./s3mount liujiaheng pjlab-oss --endpoint-url http://hdd1.h.pjlab.org.cn:8060 --force-path-style --allow-delete --allow-overwrite
# 在Worker里面执行，只读mount，则去掉--allow-delete ，--allow-overwrite这两个选项
# 后面再跟原本的source和cd等命令进行任务执行
```

如果 rjob 挂载不上，且使用的最新镜像，可以：

```Bash
# 把 source ~/.bashrc 替换为：
export AWS_ACCESS_KEY_ID=wj5aml4l0eqmjxa5ffuv
export AWS_SECRET_ACCESS_KEY=2j7g62hcqdonmpw2t2h9rqeteix1jvtyr0l8bnm4
```

### 卸载挂载

```Bash
fusermount -u pjlab-oss
# 或者
sudo umount -f pjlab-oss
```





## 常见问题 QA

- **挂载不见了：**

    - 正常情况下可以直接执行第 1 步，遇到错误再试试第 0 步：

```Bash
# 第 0 步，安装挂载工具
sudo apt update
sudo apt install fuse3
# 第 0.1 步：卸载挂载
sudo chown liujiaheng:liujiaheng /mnt/shared-storage-user/colab-share/liujiaheng/pjlab-oss
chmod 755 /mnt/shared-storage-user/colab-share/liujiaheng/pjlab-oss
sudo umount -l pjlab-oss
# 第 1 步，进入挂载目录，关闭代理并挂载
cd /mnt/shared-storage-user/colab-share/liujiaheng
unset https_proxy
unset http_proxy
./s3mount liujiaheng pjlab-oss --endpoint-url http://hdd1.h.pjlab.org.cn:8060 --force-path-style --allow-delete --allow-overwrite
```

- **如何查看oss容量：**

```Bash
curl http://xsky-query.sre.svc.h.pjlab.org.cn/hdd_user/liujiaheng
```

- **Conda虚拟环境的包下载/链接到local环境去了：**

```Plain Text
export PYTHONNOUSERSITE=1
```




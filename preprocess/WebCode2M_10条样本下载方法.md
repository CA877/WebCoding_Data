# WebCode2M 10 条样本下载方法

## 下载方式

不要下载全量 parquet。使用 Hugging Face datasets-server 的 rows API 只取小批量样本。

```text
https://datasets-server.huggingface.co/rows?dataset=xcodemind%2Fwebcode2m&config=default&split=train&offset=0&length=10
```

参数：

- `dataset=xcodemind%2Fwebcode2m`
- `config=default`
- `split=train`
- `offset=0`：起始行号
- `length=10`：取 10 条

换一批样本时只改 `offset`，例如：

```text
https://datasets-server.huggingface.co/rows?dataset=xcodemind%2Fwebcode2m&config=default&split=train&offset=1100000&length=10
```

## 输出结构

当前本地 10 条样本保存在：

```text
paper/research_samples/webcode2m_10_samples/
```

目录含义：

- `samples.jsonl`：10 条 raw row，每行一个 JSON。
- `images/sample_00.png` 到 `images/sample_09.png`：每条 row 对应的截图。
- `summary.json`：记录 source URL、总行数、字段信息、保存数量。
- `README.md`：样本索引表，包含语言、score、scale、文本长度和 preview。

## 字段

API 返回的每条 `row` 主要字段：

- `image`：截图 URL、宽、高。
- `bbox`：页面元素布局树。
- `text`：WebCode2M 清洗后的 HTML/CSS 文本，CSS 通常在内联 `<style>` 中。
- `score`：质量评分。
- `scale`：截图尺寸。
- `lang`：语言。
- `tokens`：大致对应 CSS/HTML token 数。
- `hash`：图像 hash。

注意：row 里没有单独的 `css` 字段，也没有原网页 `url` 字段。

## 可复跑脚本

```python
import json
from pathlib import Path
from urllib.request import urlretrieve

import requests

offset = 0
length = 10
out_dir = Path("paper/research_samples/webcode2m_10_samples")
image_dir = out_dir / "images"
out_dir.mkdir(parents=True, exist_ok=True)
image_dir.mkdir(parents=True, exist_ok=True)

url = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=xcodemind%2Fwebcode2m"
    "&config=default"
    "&split=train"
    f"&offset={offset}"
    f"&length={length}"
)

data = requests.get(url, timeout=60).json()

with (out_dir / "samples.jsonl").open("w", encoding="utf-8") as f:
    for i, item in enumerate(data["rows"]):
        row = item["row"]
        row["row_idx"] = item["row_idx"]
        image_src = row.get("image", {}).get("src")
        if image_src:
            image_path = image_dir / f"sample_{i:02d}.png"
            urlretrieve(image_src, image_path)
            row["image"]["local_path"] = str(image_path)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

summary = {
    "dataset": "xcodemind/webcode2m",
    "config": "default",
    "split": "train",
    "source": url,
    "num_rows_total": data.get("num_rows_total"),
    "num_samples_saved": len(data["rows"]),
    "features": data.get("features", []),
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
```

## 已用结果

之前的 10 条样本就是用：

```text
offset=0&length=10
```

生成的。对应 source 记录在：

```text
paper/research_samples/webcode2m_10_samples/summary.json
```

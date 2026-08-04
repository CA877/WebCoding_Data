#!/usr/bin/env python3
"""清理 HTML/CSS 中的所有远程资源依赖，使页面完全离线可渲染。

这是向后兼容的 CLI 入口，实际逻辑已迁移到 preprocess/clean_resources.py。
使用 BeautifulSoup 解析 + 4 层图片尺寸提取，比旧版正则方案更准确。

用法:
    python3 scripts/clean_remote_deps.py --input-dir /path/to/sp --dry-run
    python3 scripts/clean_remote_deps.py --input-dir /path/to/sp
"""
import sys
from pathlib import Path

# Add preprocess/ to sys.path
_PREPROCESS_DIR = str(Path(__file__).resolve().parent.parent / "preprocess")
if _PREPROCESS_DIR not in sys.path:
    sys.path.insert(0, _PREPROCESS_DIR)

from clean_resources import main  # noqa: E402

if __name__ == "__main__":
    main()

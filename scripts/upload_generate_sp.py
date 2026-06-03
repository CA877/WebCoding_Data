"""
Upload project folders to HuggingFace Hub.

Usage:
    # 最简用法（需要先设置下面的配置区）
    python3 scripts/upload_to_hf.py

    # 覆盖默认参数
    python3 scripts/upload_to_hf.py --data-dir /other/path --repo other/repo

    # 预览不上传
    python3 scripts/upload_to_hf.py --dry-run

    # 传所有文件（含图片字体）
    python3 scripts/upload_to_hf.py --all-files

    # 指定文件类型
    python3 scripts/upload_to_hf.py --patterns "*.html" "*.json"
"""

import argparse
import functools
import logging
import os
import sys
import time
from pathlib import Path

# 强制 print 实时刷新
print = functools.partial(print, flush=True)

# 确保 huggingface_hub 日志和进度条输出到终端
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

# ============ 配置区（改这里就够了）============
DEFAULT_DATA_DIR = "/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/generate/sp"
DEFAULT_REPO = "mistletoe111/webcoding2"
DEFAULT_REPO_PREFIX = "generate/sp"
DEFAULT_HF_ENDPOINT = "https://huggingface.co"
DEFAULT_HF_TOKEN = "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"
# K8s 集群内部 HTTP 代理（参照 xuqiankai/upload_env_proxy.sh）
HTTP_PROXY = "http://httpproxy-headless.kubebrain.svc.pjlab.local:3128"
# ================================================

# 走代理访问 huggingface.co（参照 xuqiankai/upload_env_proxy.sh）
# 强制覆盖，清除可能存在的 SOCKS 代理
os.environ.pop("all_proxy", None)
os.environ.pop("ALL_PROXY", None)
os.environ["http_proxy"] = HTTP_PROXY
os.environ["https_proxy"] = HTTP_PROXY

CODE_PATTERNS = ["*.html", "*.js", "*.css"]


def main():
    parser = argparse.ArgumentParser(
        description="Upload files from subfolders to HuggingFace Hub"
    )
    parser.add_argument("--data-dir", type=str, default=DEFAULT_DATA_DIR,
                        help=f"Local directory (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--repo", type=str, default=DEFAULT_REPO,
                        help=f"HuggingFace repo ID (default: {DEFAULT_REPO})")
    parser.add_argument("--repo-type", type=str, default="dataset",
                        choices=["dataset", "model", "space"])
    parser.add_argument("--repo-prefix", type=str, default=DEFAULT_REPO_PREFIX,
                        help="Path prefix in HF repo (e.g. 'data/')")
    parser.add_argument("--token", type=str, default=None,
                        help="HF token (default: HF_TOKEN env var)")
    parser.add_argument("--endpoint", type=str, default=None,
                        help="HF endpoint override")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--patterns", type=str, nargs="+", default=None,
                        help="File patterns to upload (e.g. '*.html' '*.json'). Overrides default.")
    parser.add_argument("--all-files", action="store_true",
                        help="Upload all files, not just html/js/css")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only, don't upload")
    args = parser.parse_args()

    # Endpoint: CLI > env > default mirror
    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint
    elif "HF_ENDPOINT" not in os.environ:
        os.environ["HF_ENDPOINT"] = DEFAULT_HF_ENDPOINT
    hf_endpoint = os.environ["HF_ENDPOINT"]

    # Token: CLI > env > hardcoded
    token = args.token or os.environ.get("HF_TOKEN") or globals().get("DEFAULT_HF_TOKEN")

    # Validate
    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}")
        sys.exit(1)

    # Pattern priority: --all-files > --patterns > CODE_PATTERNS default
    if args.all_files:
        allow_patterns = None
    elif args.patterns:
        allow_patterns = args.patterns
    else:
        allow_patterns = CODE_PATTERNS

    print(f"Endpoint:  {hf_endpoint}")
    print(f"Data dir:  {data_dir}")
    print(f"Repo:      {args.repo}")
    print(f"Filter:    {'all files' if not allow_patterns else ', '.join(allow_patterns)}")
    if args.repo_prefix:
        print(f"Prefix:    {args.repo_prefix}")

    if args.dry_run:
        # 快速统计目录数（避免网络文件系统递归扫描卡顿）
        subdirs = [d for d in data_dir.iterdir() if d.is_dir()]
        print(f"\n  {len(subdirs)} project folders")
        print("Dry run — nothing uploaded.")
        return

    # Auth check
    if not token:
        print("Error: HF token required. Set HF_TOKEN env var or DEFAULT_HF_TOKEN in script.")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Error: pip install huggingface_hub")
        sys.exit(1)

    api = HfApi(token=token)
    path_in_repo = args.repo_prefix.rstrip("/") if args.repo_prefix else ""

    print(f"\nUploading to {args.repo} ...")

    last_error = None
    for attempt in range(1, args.max_retries + 1):
        try:
            api.upload_folder(
                folder_path=str(data_dir),
                path_in_repo=path_in_repo or None,
                repo_id=args.repo,
                repo_type=args.repo_type,
                allow_patterns=allow_patterns,
                commit_message=f"Upload from {data_dir.name}",
            )
            print("Done!")
            print(f"View: {hf_endpoint}/datasets/{args.repo}")
            return
        except Exception as e:
            last_error = e
            if attempt < args.max_retries:
                wait = 30 * attempt
                print(f"  Attempt {attempt} failed: {e}")
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)

    print(f"FAILED after {args.max_retries} attempts: {last_error}")
    sys.exit(1)


if __name__ == "__main__":
    main()

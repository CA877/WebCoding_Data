"""
Upload compressed tarball to HuggingFace Hub.

Usage:
    # 最简用法（需要先设置下面的配置区）
    python3 scripts/upload_webcoding_hf.py

    # 覆盖默认参数
    python3 scripts/upload_webcoding_hf.py --file /path/to/file.tar.gz --repo other/repo
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
DEFAULT_FILE = "/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/repair_sp.tar.gz"
DEFAULT_REPO = "mistletoe111/webcoding1"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"
# HF_TOKEN 从环境变量读，或者取消下面的注释直接写
# DEFAULT_HF_TOKEN = "hf_xxx"
# ================================================


def main():
    parser = argparse.ArgumentParser(
        description="Upload a tarball file to HuggingFace Hub"
    )
    parser.add_argument("--file", type=str, default=DEFAULT_FILE,
                        help=f"Tarball file path (default: {DEFAULT_FILE})")
    parser.add_argument("--repo", type=str, default=DEFAULT_REPO,
                        help=f"HuggingFace repo ID (default: {DEFAULT_REPO})")
    parser.add_argument("--repo-type", type=str, default="dataset",
                        choices=["dataset", "model", "space"])
    parser.add_argument("--repo-prefix", type=str, default="",
                        help="Path in HF repo (e.g. 'data/file.tar.gz')")
    parser.add_argument("--token", type=str, default=None,
                        help="HF token (default: HF_TOKEN env var)")
    parser.add_argument("--endpoint", type=str, default=None,
                        help="HF endpoint override")
    parser.add_argument("--max-retries", type=int, default=3)
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
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(f"Error: file not found: {file_path}")
        sys.exit(1)
    if not file_path.is_file():
        print(f"Error: not a file: {file_path}")
        sys.exit(1)

    file_size_mb = file_path.stat().st_size / 1024 / 1024

    # Auth check
    if not token:
        print("Error: HF token required. Set HF_TOKEN env var or DEFAULT_HF_TOKEN in script.")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Error: pip install huggingface_hub")
        sys.exit(1)

    # 确定 repo 中的文件路径
    repo_path = args.repo_prefix.rstrip("/") if args.repo_prefix else file_path.name
    if repo_path.endswith("/"):
        repo_path += file_path.name

    print(f"Endpoint:  {hf_endpoint}")
    print(f"File:      {file_path}")
    print(f"Size:      {file_size_mb:.1f} MB")
    print(f"Repo:      {args.repo}")
    print(f"Path:      {repo_path}")

    api = HfApi(token=token)

    print(f"\nUploading to {args.repo} ...")

    last_error = None
    for attempt in range(1, args.max_retries + 1):
        try:
            api.upload_file(
                path_or_fileobj=str(file_path),
                path_in_repo=repo_path,
                repo_id=args.repo,
                repo_type=args.repo_type,
                commit_message=f"Upload {file_path.name}",
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

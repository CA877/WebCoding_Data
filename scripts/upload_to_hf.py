"""
Upload project folders to HuggingFace Hub (only .html/.js/.css files).

Usage:
    # 最简用法（需要先设置下面的配置区）
    python3 scripts/upload_to_hf.py

    # 覆盖默认参数
    python3 scripts/upload_to_hf.py --data-dir /other/path --repo other/repo

    # 预览不上传
    python3 scripts/upload_to_hf.py --dry-run

    # 传所有文件（含图片字体）
    python3 scripts/upload_to_hf.py --all-files
"""

import argparse
import os
import sys
import tempfile
import shutil
import time
from pathlib import Path

# ============ 配置区（改这里就够了）============
DEFAULT_DATA_DIR = "/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/datasets/pipeline_a/runs/run_a_fast/output"
DEFAULT_REPO = "mistletoe111/webcoding"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"
# HF_TOKEN 从环境变量读，或者取消下面的注释直接写
# DEFAULT_HF_TOKEN = "hf_xxx"
# ================================================

ALLOWED_EXTENSIONS = {".html", ".js", ".css"}


def main():
    parser = argparse.ArgumentParser(
        description="Upload html/js/css files from subfolders to HuggingFace Hub"
    )
    parser.add_argument("--data-dir", type=str, default=DEFAULT_DATA_DIR,
                        help=f"Local directory (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--repo", type=str, default=DEFAULT_REPO,
                        help=f"HuggingFace repo ID (default: {DEFAULT_REPO})")
    parser.add_argument("--repo-type", type=str, default="dataset",
                        choices=["dataset", "model", "space"])
    parser.add_argument("--repo-prefix", type=str, default="",
                        help="Path prefix in HF repo (e.g. 'data/')")
    parser.add_argument("--token", type=str, default=None,
                        help="HF token (default: HF_TOKEN env var)")
    parser.add_argument("--endpoint", type=str, default=None,
                        help="HF endpoint override")
    parser.add_argument("--max-retries", type=int, default=3)
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

    subdirs = sorted([d for d in data_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    if not subdirs:
        print(f"Error: no subfolders found in {data_dir}")
        sys.exit(1)

    print(f"Endpoint:  {hf_endpoint}")
    print(f"Data dir:  {data_dir}")
    print(f"Repo:      {args.repo}")
    print(f"Filter:    {'all files' if args.all_files else 'html/js/css only'}")
    print(f"Folders:   {len(subdirs)}")
    if args.repo_prefix:
        print(f"Prefix:    {args.repo_prefix}")

    def should_include(f: Path) -> bool:
        return args.all_files or f.suffix.lower() in ALLOWED_EXTENSIONS

    # Stage all files into temp dir
    print("\nStaging files...")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        total_files = 0
        total_size = 0
        skipped_dirs = 0

        for subdir in subdirs:
            files = [f for f in subdir.rglob("*") if f.is_file() and should_include(f)]
            if not files:
                skipped_dirs += 1
                continue
            for f in files:
                rel = f.relative_to(data_dir)
                dest = tmp_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                total_files += 1
                total_size += f.stat().st_size

        print(f"  {total_files} files, {total_size / 1024 / 1024:.1f} MB "
              f"({len(subdirs) - skipped_dirs} folders, {skipped_dirs} skipped)")

        if args.dry_run:
            print("\nDry run — nothing uploaded.")
            return

        if total_files == 0:
            print("No files to upload.")
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

        # Single upload
        path_in_repo = args.repo_prefix.rstrip("/") if args.repo_prefix else ""
        print(f"\nUploading {total_files} files to {args.repo} ...")

        last_error = None
        for attempt in range(1, args.max_retries + 1):
            try:
                api.upload_folder(
                    folder_path=str(tmp_path),
                    path_in_repo=path_in_repo or None,
                    repo_id=args.repo,
                    repo_type=args.repo_type,
                    commit_message=f"Upload {len(subdirs) - skipped_dirs} projects ({total_files} files)",
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

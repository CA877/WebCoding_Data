"""
Upload project folders to HuggingFace Hub (only .html/.js/.css files).

Usage:
    # Basic usage (uses hf-mirror.com by default)
    HF_TOKEN=hf_xxx python scripts/upload_to_hf.py --repo CA877/WebCoding_Data --data-dir /path/to/data

    # With proxy
    HTTPS_PROXY=socks5://127.0.0.1:13659 HF_TOKEN=hf_xxx python scripts/upload_to_hf.py \
        --repo CA877/WebCoding_Data --data-dir /path/to/data

    # Dry run to preview
    python scripts/upload_to_hf.py --repo CA877/WebCoding_Data --data-dir /path/to/data --dry-run

    # Upload to a subdirectory in the repo
    HF_TOKEN=hf_xxx python scripts/upload_to_hf.py --repo CA877/WebCoding_Data \
        --data-dir /path/to/data --repo-prefix data/

    # Include all files (images, fonts, etc.)
    HF_TOKEN=hf_xxx python scripts/upload_to_hf.py --repo CA877/WebCoding_Data \
        --data-dir /path/to/data --all-files
"""

import argparse
import os
import sys
import tempfile
import shutil
from pathlib import Path

ALLOWED_EXTENSIONS = {".html", ".js", ".css"}


def main():
    parser = argparse.ArgumentParser(
        description="Upload html/js/css files from subfolders to HuggingFace Hub"
    )
    parser.add_argument("--data-dir", type=str, required=True,
                        help="Local directory containing subfolders to upload")
    parser.add_argument("--repo", type=str, required=True,
                        help="HuggingFace repo ID (e.g. CA877/WebCoding_Data)")
    parser.add_argument("--repo-type", type=str, default="dataset",
                        choices=["dataset", "model", "space"],
                        help="HuggingFace repo type (default: dataset)")
    parser.add_argument("--repo-prefix", type=str, default="",
                        help="Path prefix in the HF repo (e.g. 'data/')")
    parser.add_argument("--token", type=str, default=None,
                        help="HF token (or set HF_TOKEN env var)")
    parser.add_argument("--endpoint", type=str, default=None,
                        help="HF endpoint override")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Max retries for upload (default: 3)")
    parser.add_argument("--all-files", action="store_true",
                        help="Upload all files, not just html/js/css")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be uploaded without uploading")
    args = parser.parse_args()

    # Setup endpoint: CLI > env > default mirror
    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint
    elif "HF_ENDPOINT" not in os.environ:
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    hf_endpoint = os.environ["HF_ENDPOINT"]
    print(f"HF endpoint: {hf_endpoint}")

    # Validate data dir
    data_dir = Path(args.data_dir).resolve()
    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}")
        sys.exit(1)

    # Collect subfolders
    subdirs = sorted([d for d in data_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    if not subdirs:
        print(f"Error: no subfolders found in {data_dir}")
        sys.exit(1)

    print(f"Data dir: {data_dir}")
    print(f"Found {len(subdirs)} subfolders")
    print(f"Repo: {args.repo} (type: {args.repo_type})")
    print(f"Filter: {'all files' if args.all_files else 'html/js/css only'}")
    if args.repo_prefix:
        print(f"Repo prefix: {args.repo_prefix}")

    def should_include(f: Path) -> bool:
        if args.all_files:
            return True
        return f.suffix.lower() in ALLOWED_EXTENSIONS

    # Build staging directory with all subfolders at once
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

        # Auth
        token = args.token or os.environ.get("HF_TOKEN")
        if not token:
            print("Error: HF token required. Set --token or HF_TOKEN env var.")
            sys.exit(1)

        try:
            from huggingface_hub import HfApi
        except ImportError:
            print("Error: huggingface_hub not installed. Run: pip install huggingface_hub")
            sys.exit(1)

        api = HfApi(token=token)

        # Single upload for the entire directory
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
                print(f"View at: {hf_endpoint}/datasets/{args.repo}")
                return
            except Exception as e:
                last_error = e
                if attempt < args.max_retries:
                    wait = 30 * attempt
                    print(f"  Attempt {attempt} failed: {e}")
                    print(f"  Retrying in {wait}s...")
                    import time
                    time.sleep(wait)

        print(f"FAILED after {args.max_retries} attempts: {last_error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

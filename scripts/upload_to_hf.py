"""
Upload subfolders to HuggingFace Hub, only including .html, .js, .css files.

Usage:
    # Basic usage
    HF_TOKEN=hf_xxx python scripts/upload_to_hf.py --repo CA877/WebCoding_Data --data-dir /path/to/data

    # With HF mirror (China)
    HF_ENDPOINT=https://hf-mirror.com HF_TOKEN=hf_xxx python scripts/upload_to_hf.py \
        --repo CA877/WebCoding_Data --data-dir /path/to/data

    # With proxy
    HTTPS_PROXY=socks5://127.0.0.1:13659 HF_TOKEN=hf_xxx python scripts/upload_to_hf.py \
        --repo CA877/WebCoding_Data --data-dir /path/to/data

    # Dry run to preview
    python scripts/upload_to_hf.py --repo CA877/WebCoding_Data --data-dir /path/to/data --dry-run

    # Upload to a subdirectory in the repo
    HF_TOKEN=hf_xxx python scripts/upload_to_hf.py --repo CA877/WebCoding_Data \
        --data-dir /path/to/data --repo-prefix data/
"""

import argparse
import os
import sys
import tempfile
import shutil
import time
from pathlib import Path

ALLOWED_EXTENSIONS = {".html", ".js", ".css"}


def collect_files(folder: Path) -> list[Path]:
    """Collect all .html/.js/.css files in a folder (recursively)."""
    files = []
    for f in folder.rglob("*"):
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append(f)
    return sorted(files)


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
                        help="HF endpoint (e.g. https://hf-mirror.com)")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Max retries per upload (default: 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be uploaded without uploading")
    args = parser.parse_args()

    # Setup endpoint
    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint
    hf_endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
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
    if args.repo_prefix:
        print(f"Repo prefix: {args.repo_prefix}")

    # Dry run: show stats
    if args.dry_run:
        total_files = 0
        total_size = 0
        print(f"\n{'Subfolder':<30} {'Files':>6} {'Size':>10}")
        print("-" * 50)
        for subdir in subdirs:
            files = collect_files(subdir)
            size = sum(f.stat().st_size for f in files)
            total_files += len(files)
            total_size += size
            if files:
                print(f"{subdir.name:<30} {len(files):>6} {size / 1024:.1f} KB")
        print("-" * 50)
        print(f"{'TOTAL':<30} {total_files:>6} {total_size / 1024 / 1024:.1f} MB")
        return

    # Auth
    token = args.token or os.environ.get("HF_TOKEN")
    if not token:
        print("Error: HF token required. Set --token or HF_TOKEN env var.")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi, login
    except ImportError:
        print("Error: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    login(token=token)
    api = HfApi()
    print(f"\nLogged in. Uploading to: {args.repo}")
    print("=" * 60)

    success_count = 0
    fail_count = 0

    for idx, subdir in enumerate(subdirs, 1):
        files = collect_files(subdir)
        if not files:
            print(f"  [{idx}/{len(subdirs)}] {subdir.name} - no html/js/css files, skipping")
            continue

        hf_prefix = f"{args.repo_prefix}{subdir.name}" if args.repo_prefix else subdir.name
        print(f"  [{idx}/{len(subdirs)}] {hf_prefix} ({len(files)} files) ...", end=" ", flush=True)

        # Create a temp directory with only the allowed files, preserving structure
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for f in files:
                rel = f.relative_to(subdir)
                dest = tmp_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

            # Upload the filtered folder
            for attempt in range(1, args.max_retries + 1):
                try:
                    api.upload_folder(
                        folder_path=str(tmp_path),
                        path_in_repo=hf_prefix,
                        repo_id=args.repo,
                        repo_type=args.repo_type,
                        token=token,
                        commit_message=f"Upload {hf_prefix}",
                    )
                    print("OK")
                    success_count += 1
                    break
                except Exception as e:
                    if attempt < args.max_retries:
                        wait = 10 * attempt
                        print(f"\n    Retry {attempt}/{args.max_retries}: {e}")
                        print(f"    Waiting {wait}s...", end=" ", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"\n    FAILED after {args.max_retries} attempts: {e}")
                        fail_count += 1

    print("\n" + "=" * 60)
    print(f"Done! Success: {success_count}, Failed: {fail_count}")
    print(f"View at: {hf_endpoint}/datasets/{args.repo}")


if __name__ == "__main__":
    main()

"""
Upload run_a_fast/output subfolders to HuggingFace (only .html/.js/.css files).

Usage:
    HF_TOKEN=hf_xxx python upload_run_a_fast.py
    HF_ENDPOINT=https://hf-mirror.com HF_TOKEN=hf_xxx python upload_run_a_fast.py
"""

import os
import sys
import shutil
import tempfile
import time
from pathlib import Path

DATA_DIR = "/mnt/shared-storage-user/colab-share/liujiaheng/workspace/xieqianqian/webcoding_data/datasets/pipeline_a/runs/run_a_fast/output"
REPO_ID = "mistletoe111/webcoding"
REPO_TYPE = "dataset"
ALLOWED_EXTENSIONS = {".html", ".js", ".css"}
MAX_RETRIES = 3


def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("Error: set HF_TOKEN env var")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi, login
    except ImportError:
        print("pip install huggingface_hub")
        sys.exit(1)

    data_dir = Path(DATA_DIR)
    if not data_dir.exists():
        print(f"Error: {data_dir} not found")
        sys.exit(1)

    login(token=token)
    api = HfApi()

    hf_endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    print(f"Endpoint: {hf_endpoint}")
    print(f"Data dir: {data_dir}")
    print(f"Repo: {REPO_ID}")

    subdirs = sorted([d for d in data_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
    print(f"Found {len(subdirs)} subfolders\n")

    success, failed = 0, 0

    for idx, subdir in enumerate(subdirs, 1):
        files = [f for f in subdir.rglob("*") if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS]
        if not files:
            print(f"[{idx}/{len(subdirs)}] {subdir.name} - skip (no html/js/css)")
            continue

        print(f"[{idx}/{len(subdirs)}] {subdir.name} ({len(files)} files) ...", end=" ", flush=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for f in files:
                rel = f.relative_to(subdir)
                dest = tmp_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    api.upload_folder(
                        folder_path=str(tmp_path),
                        path_in_repo=subdir.name,
                        repo_id=REPO_ID,
                        repo_type=REPO_TYPE,
                        token=token,
                        commit_message=f"Upload {subdir.name}",
                    )
                    print("OK")
                    success += 1
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        wait = 10 * attempt
                        print(f"\n  retry {attempt}: {e}, wait {wait}s...", end=" ", flush=True)
                        time.sleep(wait)
                    else:
                        print(f"\n  FAILED: {e}")
                        failed += 1

    print(f"\nDone! success={success}, failed={failed}")
    print(f"View: {hf_endpoint}/datasets/{REPO_ID}")


if __name__ == "__main__":
    main()

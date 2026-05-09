"""
Edit task construction pipeline:
Extract edit tasks from GitHub commit diffs of frontend projects.

Flow:
1. Clone a GitHub repo (or use local)
2. Walk commit history, find diffs that modify HTML/CSS/JS
3. For each meaningful diff:
   - Parent commit = src_code
   - Use LLM to describe the change as an edit instruction
   - Output in WebCompass editing format

Usage:
    python -m data_pipeline.edit_construct \
        --repo https://github.com/user/repo.git \
        --output data_pipeline/output/edit_construct.jsonl \
        [--max_commits 50] [--max_items 10]

    # Or from local repo:
    python -m data_pipeline.edit_construct \
        --local_repo /path/to/repo \
        --output data_pipeline/output/edit_construct.jsonl
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import git

from .common import get_client, call_llm_text, append_jsonl, TEXT_MODEL


EDIT_DESCRIPTION_PROMPT = """You are a web development project manager.
Below is a git diff from a frontend web project. Your task is to write a natural language
edit instruction that describes what changes need to be made.

Rules:
1. Write as if you're giving instructions to a developer who has the current (before) code
2. Be specific about what to add, modify, or remove
3. Reference existing elements/styles in the code that should be preserved or extended
4. Do NOT include actual code in your instruction — describe the desired outcome
5. Group related changes into a coherent feature description

Git diff:
---
{diff}
---

Files involved: {files}

Write a clear, detailed edit instruction. Output ONLY the instruction text."""


FRONTEND_EXTENSIONS = {".html", ".css", ".js", ".jsx", ".tsx", ".ts", ".vue", ".svelte", ".scss", ".less"}


def is_frontend_file(path: str) -> bool:
    """Check if a file is a frontend source file."""
    return Path(path).suffix.lower() in FRONTEND_EXTENSIONS


def clone_repo(repo_url: str, target_dir: str) -> git.Repo:
    """Clone a git repository."""
    print(f"Cloning {repo_url}...")
    return git.Repo.clone_from(repo_url, target_dir, depth=200)


def get_file_content_at_commit(repo: git.Repo, commit: git.Commit, file_path: str) -> str:
    """Get file content at a specific commit."""
    try:
        blob = commit.tree / file_path
        return blob.data_stream.read().decode("utf-8", errors="replace")
    except (KeyError, ValueError):
        return ""


def collect_src_code(repo: git.Repo, commit: git.Commit) -> list[dict]:
    """Collect all frontend source files at a given commit.

    Returns list of {"path": path, "code": content}.
    """
    src_files = []
    try:
        for blob in commit.tree.traverse():
            if hasattr(blob, 'path') and is_frontend_file(blob.path):
                try:
                    content = blob.data_stream.read().decode("utf-8", errors="replace")
                    # Skip very large files
                    if len(content) > 200_000:
                        continue
                    src_files.append({"path": blob.path, "code": content})
                except Exception:
                    continue
    except Exception:
        pass
    return src_files


def find_edit_commits(repo: git.Repo, max_commits: int = 50) -> list[tuple[git.Commit, git.Commit, str]]:
    """Find commits that modify frontend files.

    Returns list of (parent_commit, child_commit, diff_text) tuples.
    """
    results = []
    commits = list(repo.iter_commits(max_count=max_commits))

    for commit in commits:
        # Skip merge commits
        if len(commit.parents) != 1:
            continue

        parent = commit.parents[0]

        # Get diff
        diffs = parent.diff(commit, create_patch=True)
        frontend_diffs = []
        changed_files = []

        for diff in diffs:
            path = diff.b_path or diff.a_path
            if not is_frontend_file(path):
                continue

            # Skip very large diffs
            try:
                diff_text = diff.diff.decode("utf-8", errors="replace")
            except Exception:
                continue

            if len(diff_text) > 50_000:
                continue

            frontend_diffs.append(diff_text)
            changed_files.append(path)

        if not frontend_diffs:
            continue

        # Skip if too many files changed (likely a big refactor)
        if len(changed_files) > 10:
            continue

        combined_diff = "\n".join(frontend_diffs)
        # Skip trivially small diffs
        if len(combined_diff) < 50:
            continue

        results.append((parent, commit, combined_diff, changed_files))

    return results


def build_edit_item(
    instance_id: str,
    edit_descriptions: list[dict],
    src_code: list[dict],
    changed_files: list[str] = None,
    resources: list[dict] = None,
) -> dict:
    """Build an edit task item in WebCompass format."""
    task_types = [d["task_type"] for d in edit_descriptions]

    return {
        "instance_id": instance_id,
        "task": "edit",
        "task_type": task_types,
        "description": edit_descriptions,
        "src_code": src_code,
        "dst_code": [],
        "src_screenshot": [],
        "dst_screenshot": [],
        "label_modified_files": changed_files or [],
        "resources": resources or [],
    }


def process_commit(
    repo: git.Repo,
    parent: git.Commit,
    child: git.Commit,
    diff_text: str,
    changed_files: list[str],
    instance_id: str,
    client,
) -> dict:
    """Process a single commit diff into an edit task item."""
    print(f"  Generating edit description for {instance_id}...")

    description = call_llm_text(
        client, TEXT_MODEL,
        EDIT_DESCRIPTION_PROMPT.format(
            diff=diff_text[:10000],
            files=", ".join(changed_files),
        ),
    )

    task_type_prompt = f"""Given this edit instruction, generate a short (2-5 word) label for the type of edit.
Examples: "Add Dark Mode", "Fix Navigation Layout", "Update Form Validation", "Add Search Feature".

Instruction: {description[:500]}

Output ONLY the label, nothing else."""

    task_type = call_llm_text(client, TEXT_MODEL, task_type_prompt).strip().strip('"')

    src_code = collect_src_code(repo, parent)

    edit_descriptions = [{
        "task_type": task_type,
        "description": description,
    }]

    return build_edit_item(
        instance_id=instance_id,
        edit_descriptions=edit_descriptions,
        src_code=src_code,
        changed_files=changed_files,
    )


def main():
    parser = argparse.ArgumentParser(description="Edit task construction from GitHub diffs")
    parser.add_argument("--repo", default=None, help="GitHub repo URL to clone")
    parser.add_argument("--local_repo", default=None, help="Path to local git repo")
    parser.add_argument("--output", default="data_pipeline/output/edit_construct.jsonl")
    parser.add_argument("--max_commits", type=int, default=50, help="Max commits to scan")
    parser.add_argument("--max_items", type=int, default=10, help="Max edit items to generate")
    args = parser.parse_args()

    if not args.repo and not args.local_repo:
        print("Error: Must provide either --repo or --local_repo")
        sys.exit(1)

    client = get_client()

    if args.local_repo:
        repo = git.Repo(args.local_repo)
        repo_name = Path(args.local_repo).name
    else:
        tmp_dir = tempfile.mkdtemp(prefix="webcompass_edit_")
        repo = clone_repo(args.repo, tmp_dir)
        repo_name = args.repo.rstrip("/").split("/")[-1].replace(".git", "")

    print(f"Scanning commits in {repo_name}...")
    edit_commits = find_edit_commits(repo, max_commits=args.max_commits)
    print(f"Found {len(edit_commits)} commits with frontend changes")

    if not edit_commits:
        print("No suitable commits found.")
        sys.exit(0)

    # Limit items
    edit_commits = edit_commits[:args.max_items]

    success = 0
    for i, (parent, child, diff_text, changed_files) in enumerate(edit_commits):
        instance_id = f"{repo_name}_{child.hexsha[:8]}_{i}"
        try:
            item = process_commit(
                repo=repo,
                parent=parent,
                child=child,
                diff_text=diff_text,
                changed_files=changed_files,
                instance_id=instance_id,
                client=client,
            )
            append_jsonl(args.output, item)
            print(f"  -> Saved {instance_id}")
            success += 1
        except Exception as e:
            print(f"  [ERROR] {instance_id}: {e}")

    print(f"\nDone! {success}/{len(edit_commits)} edit items generated.")


if __name__ == "__main__":
    main()

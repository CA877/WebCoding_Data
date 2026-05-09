"""
Extract edit/repair data from git commit history of an agent-generated website.

This is the "unified pipeline" approach: when an agent generates a website inside Docker,
it is instructed (via CLAUDE.md) to git commit at intermediate checkpoints:
  - "CHECKPOINT: ..." commits = working versions -> edit data (adjacent pairs)
  - "BUGFIX: ..." commits = bug fixes -> repair data

This script parses the git log and extracts structured edit/repair data items.

Usage:
    # From a repo where agent has committed intermediate states:
    python -m data_pipeline.edit_from_git \
        --repo_dir /path/to/agent/output/repo \
        --output_edit data_pipeline/output/edit_from_git.jsonl \
        --output_repair data_pipeline/output/repair_from_git.jsonl

    # From eval_output (where Docker agent results are stored):
    python -m data_pipeline.edit_from_git \
        --repo_dir eval_output/claude_sonnet4_5/694/output_0/generated_web_pages \
        --output_edit data_pipeline/output/edit_from_git.jsonl
"""

import argparse
import json
import os
import sys
from pathlib import Path

import git

from .common import get_client, call_llm_text, append_jsonl, TEXT_MODEL


EDIT_DESCRIPTION_PROMPT = """You are a web development project manager.
Below is a git diff showing changes made to a website between two working versions.
Write a natural language edit instruction describing what changes need to be made.

Rules:
1. Write as instructions to a developer who has the "before" code
2. Be specific about what to add, modify, or remove
3. Reference existing elements/styles that should be preserved or extended
4. Do NOT include actual code — describe the desired outcome
5. Be detailed enough that the developer can implement without seeing the diff

Git diff:
---
{diff}
---

Changed files: {files}

Write ONLY the edit instruction."""


REPAIR_DESCRIPTION_PROMPT = """You are a QA engineer reporting a bug.
Below is a git diff showing a bug fix applied to a website.
Write a bug report describing the problem (NOT the fix).

The bug report should:
1. Describe what is broken or not working correctly
2. Describe expected behavior vs actual behavior
3. Be specific about which component/feature is affected
4. Do NOT reveal the fix — only describe the problem

Git diff (this is the FIX, so invert it to understand the BUG):
---
{diff}
---

Write ONLY the bug report."""


TASK_TYPE_PROMPT = """Given this instruction, generate a short (2-5 word) label.
Examples: "Add Dark Mode", "Fix Navigation Layout", "Update Form Validation".

Instruction: {description}

Output ONLY the label."""


FRONTEND_EXTENSIONS = {".html", ".css", ".js", ".jsx", ".tsx", ".ts", ".vue", ".svelte", ".scss", ".less"}


def is_frontend_file(path: str) -> bool:
    return Path(path).suffix.lower() in FRONTEND_EXTENSIONS


def collect_files_at_commit(repo: git.Repo, commit: git.Commit) -> list[dict]:
    """Collect all frontend source files at a commit."""
    src_files = []
    try:
        for blob in commit.tree.traverse():
            if not hasattr(blob, 'path') or not is_frontend_file(blob.path):
                continue
            try:
                content = blob.data_stream.read().decode("utf-8", errors="replace")
                if len(content) > 200_000:
                    continue
                src_files.append({"path": blob.path, "code": content})
            except Exception:
                continue
    except Exception:
        pass
    return src_files


def get_diff_between(repo: git.Repo, parent: git.Commit, child: git.Commit) -> tuple[str, list[str]]:
    """Get diff text and list of changed files between two commits."""
    diffs = parent.diff(child, create_patch=True)
    diff_parts = []
    changed_files = []

    for d in diffs:
        path = d.b_path or d.a_path
        if not is_frontend_file(path):
            continue
        try:
            diff_text = d.diff.decode("utf-8", errors="replace")
        except Exception:
            continue
        if len(diff_text) > 50_000:
            continue
        diff_parts.append(diff_text)
        changed_files.append(path)

    return "\n".join(diff_parts), changed_files


def classify_commit(message: str) -> str:
    """Classify a commit by its message prefix.

    Returns: 'checkpoint', 'bugfix', or 'other'
    """
    msg = message.strip().upper()
    if msg.startswith("CHECKPOINT"):
        return "checkpoint"
    if msg.startswith("BUGFIX") or msg.startswith("BUG FIX") or msg.startswith("FIX:"):
        return "bugfix"
    return "other"


def extract_edit_pairs(repo: git.Repo) -> list[dict]:
    """Extract all pairs of adjacent commits suitable for edit data.

    Returns list of {parent, child, diff, files, type} dicts.
    """
    commits = list(repo.iter_commits())
    commits.reverse()  # Oldest first

    pairs = []
    for i in range(len(commits) - 1):
        parent = commits[i]
        child = commits[i + 1]

        # Skip merge commits
        if len(child.parents) != 1:
            continue

        commit_type = classify_commit(child.message)
        diff_text, changed_files = get_diff_between(repo, parent, child)

        if not diff_text or not changed_files:
            continue

        # Skip trivially small diffs
        if len(diff_text) < 30:
            continue

        pairs.append({
            "parent": parent,
            "child": child,
            "diff": diff_text,
            "files": changed_files,
            "type": commit_type,
            "message": child.message.strip(),
        })

    return pairs


def process_pair_as_edit(
    pair: dict,
    repo: git.Repo,
    instance_id: str,
    client,
) -> dict:
    """Convert a commit pair into an edit data item."""
    diff_text = pair["diff"][:10000]
    files_str = ", ".join(pair["files"])

    # Generate description
    description = call_llm_text(
        client, TEXT_MODEL,
        EDIT_DESCRIPTION_PROMPT.format(diff=diff_text, files=files_str),
    )

    # Generate task type
    task_type = call_llm_text(
        client, TEXT_MODEL,
        TASK_TYPE_PROMPT.format(description=description[:500]),
    ).strip().strip('"').strip("'")

    # Get source code at parent commit
    src_code = collect_files_at_commit(repo, pair["parent"])

    return {
        "instance_id": instance_id,
        "task": "edit",
        "task_type": [task_type],
        "description": [{"task_type": task_type, "description": description}],
        "src_code": src_code,
        "dst_code": [],
        "src_screenshot": [],
        "dst_screenshot": [],
        "label_modified_files": pair["files"],
        "resources": [],
        "meta": {
            "source": "git_trajectory",
            "commit_message": pair["message"],
            "commit_sha": pair["child"].hexsha,
        },
    }


def process_pair_as_repair(
    pair: dict,
    repo: git.Repo,
    instance_id: str,
    client,
) -> dict:
    """Convert a bugfix commit pair into a repair data item."""
    diff_text = pair["diff"][:10000]

    # Generate bug report (describe the problem, not the fix)
    bug_report = call_llm_text(
        client, TEXT_MODEL,
        REPAIR_DESCRIPTION_PROMPT.format(diff=diff_text),
    )

    # Get source code at parent commit (the broken version)
    src_code = collect_files_at_commit(repo, pair["parent"])

    return {
        "instance_id": instance_id,
        "task": "repair",
        "bug_description": bug_report,
        "src_code": src_code,
        "dst_code": [],
        "label_modified_files": pair["files"],
        "meta": {
            "source": "git_trajectory",
            "commit_message": pair["message"],
            "commit_sha": pair["child"].hexsha,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Extract edit/repair data from git history")
    parser.add_argument("--repo_dir", required=True, help="Path to git repo with agent commits")
    parser.add_argument("--output_edit", default="data_pipeline/output/edit_from_git.jsonl")
    parser.add_argument("--output_repair", default="data_pipeline/output/repair_from_git.jsonl")
    parser.add_argument("--base_id", default=None, help="Base instance ID prefix")
    args = parser.parse_args()

    if not os.path.isdir(os.path.join(args.repo_dir, ".git")):
        print(f"Error: {args.repo_dir} is not a git repository")
        sys.exit(1)

    repo = git.Repo(args.repo_dir)
    base_id = args.base_id or Path(args.repo_dir).name

    print(f"Scanning git history in {args.repo_dir}...")
    pairs = extract_edit_pairs(repo)
    print(f"Found {len(pairs)} commit pairs")

    checkpoints = [p for p in pairs if p["type"] in ("checkpoint", "other")]
    bugfixes = [p for p in pairs if p["type"] == "bugfix"]
    print(f"  Checkpoints/other: {len(checkpoints)}")
    print(f"  Bugfixes: {len(bugfixes)}")

    client = get_client()

    # Process edit pairs
    edit_count = 0
    for i, pair in enumerate(checkpoints):
        instance_id = f"{base_id}_edit_{i}"
        print(f"\n  Processing edit {instance_id}...")
        try:
            item = process_pair_as_edit(pair, repo, instance_id, client)
            append_jsonl(args.output_edit, item)
            edit_count += 1
            print(f"    -> Saved ({len(item['src_code'])} src files, {len(item['label_modified_files'])} changed)")
        except Exception as e:
            print(f"    [ERROR] {e}")

    # Process repair pairs
    repair_count = 0
    for i, pair in enumerate(bugfixes):
        instance_id = f"{base_id}_repair_{i}"
        print(f"\n  Processing repair {instance_id}...")
        try:
            item = process_pair_as_repair(pair, repo, instance_id, client)
            append_jsonl(args.output_repair, item)
            repair_count += 1
            print(f"    -> Saved ({len(item['src_code'])} src files)")
        except Exception as e:
            print(f"    [ERROR] {e}")

    print(f"\nDone! Edit items: {edit_count}, Repair items: {repair_count}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Convert the complex_query_qwen37_full_20260801 run into ShareGPT jsonl.

Each project directory becomes one ShareGPT sample:
  {"conversations": [{"from": "human", "value": <generation prompt + query>},
                     {"from": "gpt", "value": <all project files serialized>}],
   "id": <job_id>, "source": <run name>}
The human turn reuses the exact generation prompt (prompt_for + STACK_RULES)
from solve_complex_stack_cases.py so prompt and answer stay consistent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.solve_complex_stack_cases import prompt_for

FENCE_LANGS = {
    ".html": "html", ".htm": "html", ".css": "css", ".js": "js", ".mjs": "js",
    ".ts": "ts", ".tsx": "tsx", ".jsx": "jsx", ".vue": "vue", ".json": "json",
    ".md": "markdown", ".py": "python", ".java": "java", ".xml": "xml",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".sh": "bash",
    ".sql": "sql", ".go": "go", ".rs": "rust", ".cpp": "cpp", ".c": "c",
    ".h": "c", ".svg": "svg", ".txt": "text", ".env": "text", ".ini": "ini",
    ".lock": "text", ".gitignore": "text", ".dockerignore": "text",
    ".editorconfig": "ini", ".prettierrc": "json", ".eslintrc": "json",
    ".babelrc": "json", ".npmrc": "ini", ".nvmrc": "text", ".gitattributes": "text",
}


def serialize_files(project_dir: Path) -> str:
    blocks = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or path.name == ".generation.json":
            continue
        rel = path.relative_to(project_dir).as_posix()
        lang = FENCE_LANGS.get(path.suffix.lower(), path.suffix.lstrip(".") or "text")
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks.append(f"#{rel}\n```{lang}\n{content}\n```")
    return "\n".join(blocks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--projects", type=Path, required=True,
                    help="run projects dir, e.g. runs/complex_query_qwen37_full_20260801/projects")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source", default="complex_query_qwen37_full_20260801")
    args = ap.parse_args()

    projects = sorted(args.projects.glob("complex-*"))
    if not projects:
        print("no project dirs found", file=sys.stderr)
        return 2
    seen = 0
    with args.output.open("w", encoding="utf-8") as out:
        for project in projects:
            meta_path = project / ".generation.json"
            if not meta_path.is_file():
                print(f"skip {project.name}: missing .generation.json", file=sys.stderr)
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            row = {"job_id": meta["job_id"], "technology_track": meta["technology_track"],
                   "query": meta["query"]}
            human = prompt_for(row)
            gpt = serialize_files(project)
            record = {
                "conversations": [
                    {"from": "human", "value": human},
                    {"from": "gpt", "value": gpt},
                ],
                "id": meta["job_id"],
                "source": args.source,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            seen += 1
    print(f"converted {seen} samples -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

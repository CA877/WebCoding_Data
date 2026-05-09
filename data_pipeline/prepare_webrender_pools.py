from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


TASKS = ("text", "image", "video")


def safe_instance_id(split: str, name: str) -> str:
    return f"{split}__{name}"


def has_html(project_dir: Path) -> bool:
    return any(project_dir.rglob("*.html"))


def discover_projects(split: str, root: Path, require_html: bool = True) -> List[Tuple[str, Path]]:
    projects: List[Tuple[str, Path]] = []
    for project in sorted(root.iterdir()):
        if not project.is_dir() or project.name.startswith("."):
            continue
        if require_html and not has_html(project):
            continue
        projects.append((safe_instance_id(split, project.name), project.resolve()))
    return projects


def load_ok_ids(paths: Iterable[Path]) -> set[str]:
    ok: set[str] = set()
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                instance_id = infer_instance_id(obj)
                if not instance_id:
                    continue
                if obj.get("status") == "ok" or obj.get("passed") is True:
                    ok.add(instance_id)
    return ok


def infer_instance_id(obj: Dict[str, Any]) -> str | None:
    for key in ("instance_id", "id"):
        if obj.get(key):
            return str(obj[key])

    for key in ("html_dir", "project_dir", "path"):
        value = obj.get(key)
        if not value:
            continue
        path = Path(str(value))
        name = path.name
        parent = path.parent.name.lower()
        if name.startswith(("train__", "test__")):
            return name
        if "train" in parent:
            return safe_instance_id("train", name)
        if "test" in parent:
            return safe_instance_id("test", name)
    return None


def allocate(
    candidates: List[Tuple[str, Path]],
    target_per_task: int,
    seed: int,
) -> Dict[str, List[Tuple[str, Path]]]:
    needed = target_per_task * len(TASKS)
    if len(candidates) < needed:
        raise ValueError(f"Need {needed} candidates, found {len(candidates)}")

    shuffled = list(candidates)
    random.Random(seed).shuffle(shuffled)
    pools: Dict[str, List[Tuple[str, Path]]] = {}
    offset = 0
    for task in TASKS:
        pools[task] = shuffled[offset : offset + target_per_task]
        offset += target_per_task
    return pools


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def create_symlink_pools(link_root: Path, pools: Dict[str, List[Tuple[str, Path]]]) -> None:
    if link_root.exists():
        shutil.rmtree(link_root)
    link_root.mkdir(parents=True, exist_ok=True)

    for task, items in pools.items():
        task_dir = link_root / task
        task_dir.mkdir(parents=True, exist_ok=True)
        for instance_id, source in items:
            target = task_dir / instance_id
            os.symlink(source, target, target_is_directory=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare non-overlapping WebRenderBench pools")
    parser.add_argument("--train-dir", type=Path, required=True)
    parser.add_argument("--test-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Path to selected_pools.json")
    parser.add_argument("--link-root", type=Path, default=None,
                        help="Optional directory where per-task symlink pools are created")
    parser.add_argument("--target-per-task", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=506)
    parser.add_argument("--validation-jsonl", type=Path, action="append", default=[],
                        help="Optional validation JSONL files. Keeps records with status=ok or passed=true.")
    parser.add_argument("--allow-no-html", action="store_true",
                        help="Do not require at least one HTML file during discovery.")
    args = parser.parse_args()

    candidates = (
        discover_projects("train", args.train_dir, require_html=not args.allow_no_html)
        + discover_projects("test", args.test_dir, require_html=not args.allow_no_html)
    )

    if args.validation_jsonl:
        ok_ids = load_ok_ids(args.validation_jsonl)
        candidates = [(instance_id, path) for instance_id, path in candidates if instance_id in ok_ids]

    pools = allocate(candidates, args.target_per_task, args.seed)
    selected_ids = {task: [instance_id for instance_id, _ in items] for task, items in pools.items()}
    selected_paths = {
        task: {instance_id: str(path) for instance_id, path in items}
        for task, items in pools.items()
    }

    all_ids = [instance_id for items in selected_ids.values() for instance_id in items]
    if len(all_ids) != len(set(all_ids)):
        raise RuntimeError("Selected pools overlap")

    write_json(
        args.output,
        {
            "seed": args.seed,
            "target_per_task": args.target_per_task,
            "candidate_count": len(candidates),
            "pools": selected_ids,
            "paths": selected_paths,
        },
    )

    if args.link_root:
        create_symlink_pools(args.link_root, pools)

    print(f"candidates={len(candidates)}")
    for task in TASKS:
        print(f"{task}={len(selected_ids[task])}")
    print(f"overlap=0")
    print(f"output={args.output}")
    if args.link_root:
        print(f"link_root={args.link_root}")


if __name__ == "__main__":
    main()

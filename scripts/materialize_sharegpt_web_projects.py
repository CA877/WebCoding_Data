#!/usr/bin/env python3
"""Materialize WebCompass ShareGPT answers as safe local web projects.

The 6,503-source dataset stores each generated project in the final GPT turn
using Markdown headings followed by fenced HTML/CSS/JavaScript files.  This
script restores those files without changing their contents and writes an
audit manifest plus an optional absolute project list for downstream gates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


FILE_BLOCK_RE = re.compile(
    r"(?ms)^#{1,6}[ \t]+`?([^\n`]+?)`?[ \t]*\n"
    r"```(html|css|javascript|js)[ \t]*\n(.*?)^```[ \t]*$"
)
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_SUFFIXES = {".html", ".css", ".js"}


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """Read physical JSONL lines without treating Unicode separators as rows."""
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            yield line_number, json.loads(line)


def safe_instance_id(source_id: str) -> str:
    value = SAFE_ID_RE.sub("_", source_id.strip()).strip("._")
    if not value:
        raise ValueError("sample id becomes empty after sanitization")
    return value


def safe_relative_file(value: str) -> PurePosixPath:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe project file path: {value!r}")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported project file type: {value!r}")
    return path


def parse_project_files(answer: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in FILE_BLOCK_RE.finditer(answer):
        relative = safe_relative_file(match.group(1))
        name = relative.as_posix()
        if name in seen:
            raise ValueError(f"duplicate project file: {name}")
        seen.add(name)
        files.append({"path": name, "code": match.group(3)})
    if not files:
        raise ValueError("no headed HTML/CSS/JavaScript fences found")
    if "index.html" not in seen:
        raise ValueError("project does not contain index.html")
    return files


def assistant_answer(row: dict[str, Any]) -> str:
    conversations = row.get("conversations")
    if not isinstance(conversations, list):
        raise ValueError("conversations must be a list")
    for message in reversed(conversations):
        if not isinstance(message, dict):
            continue
        if message.get("from") in {"gpt", "assistant"} and isinstance(message.get("value"), str):
            return message["value"]
    raise ValueError("no GPT answer found")


def write_project(output_root: Path, instance_id: str, files: list[dict[str, str]], overwrite: bool) -> Path:
    target = output_root / instance_id
    if target.exists() and not overwrite:
        raise FileExistsError(f"project already exists: {target}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{instance_id}.", dir=output_root))
    try:
        for item in files:
            destination = temporary / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(item["code"], encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target.resolve()


def temporary_file(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
    )
    handle.close()
    return Path(handle.name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--audit-jsonl", type=Path, required=True)
    parser.add_argument("--project-list", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.offset < 0 or args.limit < 0:
        parser.error("--offset and --limit must be non-negative")
    if not args.input_jsonl.is_file():
        parser.error(f"input does not exist: {args.input_jsonl}")

    audit_tmp = temporary_file(args.audit_jsonl)
    list_tmp = temporary_file(args.project_list) if args.project_list else None
    selected = written = errors = 0
    seen_ids: set[str] = set()
    try:
        with audit_tmp.open("w", encoding="utf-8") as audit:
            project_list = list_tmp.open("w", encoding="utf-8") if list_tmp else None
            try:
                for ordinal, (line_number, row) in enumerate(iter_jsonl(args.input_jsonl)):
                    if ordinal < args.offset:
                        continue
                    if args.limit and selected >= args.limit:
                        break
                    selected += 1
                    source_id = row.get("id")
                    record: dict[str, Any] = {"line": line_number, "source_id": source_id}
                    try:
                        if not isinstance(source_id, str):
                            raise ValueError("sample id must be a string")
                        instance_id = safe_instance_id(source_id)
                        if instance_id in seen_ids:
                            raise ValueError(f"duplicate materialized id: {instance_id}")
                        seen_ids.add(instance_id)
                        files = parse_project_files(assistant_answer(row))
                        project = write_project(args.output_dir, instance_id, files, args.overwrite)
                        record.update(
                            status="ok",
                            instance_id=instance_id,
                            project=str(project),
                            file_count=len(files),
                            code_bytes=sum(len(item["code"].encode("utf-8")) for item in files),
                            files=[item["path"] for item in files],
                        )
                        if project_list:
                            project_list.write(str(project) + "\n")
                        written += 1
                    except Exception as exc:  # noqa: BLE001
                        record.update(status="error", error=f"{type(exc).__name__}: {exc}")
                        errors += 1
                    audit.write(json.dumps(record, ensure_ascii=False) + "\n")
            finally:
                if project_list:
                    project_list.close()
        os.replace(audit_tmp, args.audit_jsonl)
        if list_tmp and args.project_list:
            os.replace(list_tmp, args.project_list)
    finally:
        for temporary in (audit_tmp, list_tmp):
            if temporary and temporary.exists():
                temporary.unlink()
    print(json.dumps({"selected": selected, "written": written, "errors": errors}, ensure_ascii=False))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

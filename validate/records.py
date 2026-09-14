from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXPECTED_TASK_BY_RELEASE_FILE = {
    "text-generate.jsonl": "text-generation",
    "image-generate.jsonl": "image-generation",
    "text-edit.jsonl": "text-editing",
    "image-edit.jsonl": "image-editing",
    "text-repair.jsonl": "text-repair",
    "image-repair.jsonl": "image-repair",
}

IMAGE_ROOT_BY_RELEASE_FILE = {
    "image-generate.jsonl": Path("images/image-generate"),
    "image-edit.jsonl": Path("images/image-edit"),
    "image-repair.jsonl": Path("images/image-repair"),
}

WHITESPACE_RE = re.compile(r"\s+")


def sample_id(record: dict[str, Any], file_name: str, line_no: int) -> str:
    value = record.get("instance_id")
    return value if isinstance(value, str) and value else f"{file_name}:{line_no}"


def file_array(record: dict[str, Any], key: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in record.get(key) or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
            out.append({"path": item["path"], "code": item["code"]})
    return out


def instruction_code_files(record: dict[str, Any]) -> list[dict[str, str]]:
    instruction = record.get("instruction")
    if isinstance(instruction, dict):
        for key in ("src_code", "input_files", "files"):
            files = instruction.get(key)
            if isinstance(files, list):
                out = [
                    {"path": x["path"], "code": x["code"]}
                    for x in files
                    if isinstance(x, dict) and isinstance(x.get("path"), str) and isinstance(x.get("code"), str)
                ]
                if out:
                    return out
    if isinstance(instruction, list):
        out = [
            {"path": x["path"], "code": x["code"]}
            for x in instruction
            if isinstance(x, dict) and isinstance(x.get("path"), str) and isinstance(x.get("code"), str)
        ]
        if out:
            return out
    return []


def input_code_files(record: dict[str, Any]) -> list[dict[str, str]]:
    return file_array(record, "input_files") or instruction_code_files(record)


def output_code_files(record: dict[str, Any]) -> list[dict[str, str]]:
    return file_array(record, "output_files")


def response_code_files(record: dict[str, Any]) -> list[dict[str, str]]:
    response = record.get("response")
    if not isinstance(response, list) or not all(isinstance(x, dict) for x in response):
        return []
    if not any("code" in x for x in response):
        return []
    return [
        {"path": str(x.get("path", "index.html")), "code": x.get("code", "")}
        for x in response
        if isinstance(x.get("code"), str)
    ]


def patch_array(record: dict[str, Any]) -> list[dict[str, Any]]:
    patches = record.get("patches")
    if patches is None:
        patches = record.get("response")
    return patches if isinstance(patches, list) else []


def all_code(record: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in input_code_files(record):
        chunks.append(item["code"])
    for item in output_code_files(record):
        chunks.append(item["code"])
    for item in response_code_files(record):
        chunks.append(item["code"])
    return "\n".join(chunks)


def target_code_for_hash(record: dict[str, Any], task_name: str) -> str:
    if "generation" in task_name or "generate" in task_name:
        files = output_code_files(record) or response_code_files(record)
    else:
        files = input_code_files(record)
    return "\n".join(f"{item['path']}\n{item['code']}" for item in files)


def normalized_hash(text: str) -> str:
    normalized = WHITESPACE_RE.sub(" ", text).strip()
    return hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()


def image_refs(record: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for key in ("input_images", "src_screenshot", "dst_screenshot"):
        for value in record.get(key) or []:
            if isinstance(value, str):
                refs.append((key, value))
    return refs


def normalized_domain(record: dict[str, Any]) -> str:
    for key in ("source_url", "url"):
        value = record.get(key)
        if isinstance(value, str) and value:
            host = urlparse(value if "://" in value else f"https://{value}").netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            if host:
                return host
    value = record.get("instance_id")
    if isinstance(value, str) and "__" in value:
        return value.split("__", 1)[0].lower().removeprefix("www.")
    return ""

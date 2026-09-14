"""Exact Qwen accounting for the WebCompass-aligned full-code context."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re

from tokenizers import Tokenizer


TRAIN_CODE_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".jsx", ".ts", ".tsx"}
BUNDLE_NAME_RE = re.compile(
    r"(?:^|[._-])(?:vendor|vendors|common-vendors?|runtime|webpack|chunk|bundle|polyfills?|"
    r"jquery|react(?:-dom)?|vue|angular|bootstrap|swiper|tinymce|stripe|recaptcha|scripts\.min)"
    r"(?:[._-]|$)|\.min\.(?:css|js)$",
    re.I,
)
BUNDLE_SOURCE_RE = re.compile(
    r"webpackBootstrap|__webpack_require__|webpackJsonp|jQuery JavaScript Library|"
    r"ReactDOM|common[-_ ]vendors?|sourceMappingURL=.*(?:chunk|bundle)",
    re.I,
)
MINIFIED_BUNDLE_BYTES = 100_000


@lru_cache(maxsize=4)
def _load(path: str) -> Tokenizer:
    tokenizer_path = Path(path)
    if not tokenizer_path.is_file():
        raise FileNotFoundError(f"Qwen tokenizer.json not found: {tokenizer_path}")
    return Tokenizer.from_file(str(tokenizer_path))


def read_render_dependencies(project: Path, *, verify_hashes: bool = False) -> list[dict]:
    """Explicit image-task resources, never inferred exclusions in legacy projects."""
    manifest = project / 'render_dependencies.json'
    if not manifest.exists():
        return []
    policy = json.loads(manifest.read_text(encoding='utf-8'))
    if (policy.get('schema') != 'webcoding_render_dependencies_v1'
            or policy.get('usage') != 'image_based_edit_repair_only'):
        raise ValueError('invalid_render_dependency_policy')
    rows = policy.get('files')
    if not isinstance(rows, list):
        raise ValueError('invalid_render_dependency_files')
    seen = set()
    for row in rows:
        relative = row.get('file','')
        path = project / relative
        if (not relative or Path(relative).is_absolute() or '..' in Path(relative).parts
                or path.suffix.lower() not in TRAIN_CODE_SUFFIXES - {'.html','.htm'}
                or not path.is_file() or not path.resolve().is_relative_to(project.resolve())
                or relative in seen or row.get('model_input') is not False
                or row.get('editable') is not False or not row.get('exclusion_reason')):
            raise ValueError('invalid_render_dependency:' + str(relative))
        seen.add(relative)
        if verify_hashes and hashlib.sha256(path.read_bytes()).hexdigest() != row.get('saved_sha256'):
            raise ValueError('render_dependency_modified:' + relative)
    return rows


def iter_training_code_files(project: Path, *, include_render_only: bool = False) -> list[Path]:
    """Model-visible files; explicitly marked image render dependencies stay hidden."""
    excluded = set() if include_render_only else {x['file'] for x in read_render_dependencies(project)}
    return sorted(
        (path for path in project.rglob("*")
         if path.is_file() and path.suffix.lower() in TRAIN_CODE_SUFFIXES
         and path.relative_to(project).as_posix() not in excluded),
        key=lambda path: path.relative_to(project).as_posix(),
    )


def is_render_bundle(project: Path, path: Path, text: str) -> bool:
    """Classify auditable render/build dependencies omitted by the optional policy."""
    relative = path.relative_to(project)
    if "author_styles" in relative.parts:
        return False
    if path.suffix.lower() not in {".css", ".js", ".jsx", ".ts", ".tsx"}:
        return False
    evidence = relative.as_posix()
    if BUNDLE_NAME_RE.search(evidence) or BUNDLE_SOURCE_RE.search(text[:16_384]):
        return True
    size = len(text.encode("utf-8", errors="replace"))
    if size < MINIFIED_BUNDLE_BYTES or "resources" not in relative.parts:
        return False
    nonempty = [line for line in text.splitlines() if line.strip()]
    longest = max((len(line) for line in nonempty), default=0)
    return longest / max(len(text), 1) >= 0.50


def serialize_training_project(project: Path, *, exclude_render_bundles: bool = False,
                               externalize_resource_dependencies: bool = False,
                               externalize_all_code_dependencies: bool = False,
                               include_render_only: bool = False) -> str:
    """Serialize the complete retained code context without rewriting it.

    HTML is read verbatim, including inline code. Explicit render-only manifests
    are respected by default; legacy projects retain their all-file behavior.
    """
    chunks: list[str] = []
    for path in iter_training_code_files(project, include_render_only=include_render_only):
        relative = path.relative_to(project).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        code_dependency = path.suffix.lower() in {".css", ".js", ".mjs", ".jsx", ".ts", ".tsx"}
        externalized = (externalize_all_code_dependencies and code_dependency) or (
            externalize_resource_dependencies and "resources" in path.relative_to(project).parts and code_dependency)
        if exclude_render_bundles and (externalized or is_render_bundle(project, path, text)):
            label = "externalized render dependency" if externalized else "render bundle"
            chunks.append(f"<file path={relative!r}>\n/* omitted {label} */\n</file>")
            continue
        chunks.append(f"<file path={relative!r}>\n{text}\n</file>")
    return "\n\n".join(chunks)


def count_project_tokens(project: Path, tokenizer_json: Path, *, exclude_render_bundles: bool = False,
                         externalize_resource_dependencies: bool = False,
                         externalize_all_code_dependencies: bool = False,
                         include_render_only: bool = False) -> int:
    serialized = serialize_training_project(
        project, exclude_render_bundles=exclude_render_bundles,
        externalize_resource_dependencies=externalize_resource_dependencies,
        externalize_all_code_dependencies=externalize_all_code_dependencies,
        include_render_only=include_render_only)
    return len(_load(str(tokenizer_json.resolve())).encode(serialized).ids)


def count_serialized_tokens(serialized: str, tokenizer_json: Path) -> int:
    """Count an already-serialized training context with the exact Qwen tokenizer."""
    return len(_load(str(tokenizer_json.resolve())).encode(serialized).ids)


def project_context_stats(project: Path, tokenizer_json: Path, *, exclude_render_bundles: bool = False,
                          externalize_resource_dependencies: bool = False,
                          externalize_all_code_dependencies: bool = False) -> dict[str, int]:
    files = iter_training_code_files(project,include_render_only=True)
    render_only = read_render_dependencies(project)
    tokens = count_project_tokens(
        project, tokenizer_json, exclude_render_bundles=exclude_render_bundles,
        externalize_resource_dependencies=externalize_resource_dependencies,
        externalize_all_code_dependencies=externalize_all_code_dependencies)
    bundles = []
    if exclude_render_bundles:
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            code_dependency = path.suffix.lower() in {".css", ".js", ".mjs", ".jsx", ".ts", ".tsx"}
            externalized = (externalize_all_code_dependencies and code_dependency) or (
                externalize_resource_dependencies and "resources" in path.relative_to(project).parts and code_dependency)
            if externalized or is_render_bundle(project, path, text):
                bundles.append(path)
    by_suffix = {suffix: [p for p in files if p.suffix.lower() == suffix]
                 for suffix in TRAIN_CODE_SUFFIXES}
    return {
        "code_tokens": tokens,
        # Compatibility alias for older manifests/readers.
        "prompt_tokens": tokens,
        "code_files": len(files),
        "code_bytes": sum(p.stat().st_size for p in files),
        "html_files": len(by_suffix[".html"]) + len(by_suffix[".htm"]),
        "css_files": len(by_suffix[".css"]),
        "js_files": sum(len(by_suffix[s]) for s in {".js", ".mjs", ".jsx", ".ts", ".tsx"}),
        "bundle_files_omitted": len(bundles),
        "bundle_bytes_omitted": sum(path.stat().st_size for path in bundles),
        "render_only_files_omitted": len(render_only),
        "render_only_bytes_omitted": sum((project/row['file']).stat().st_size for row in render_only),
    }

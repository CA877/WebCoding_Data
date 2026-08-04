"""Exact Qwen accounting for the WebCompass-aligned full-code context."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from tokenizers import Tokenizer


TRAIN_CODE_SUFFIXES = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx"}
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


def iter_training_code_files(project: Path) -> list[Path]:
    """Return every retained code file in stable project-relative order."""
    return sorted(
        (path for path in project.rglob("*")
         if path.is_file() and path.suffix.lower() in TRAIN_CODE_SUFFIXES),
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
                               externalize_all_code_dependencies: bool = False) -> str:
    """Serialize the complete retained code context without rewriting it.

    HTML is read verbatim, so inline style/script bodies remain included. Local
    vendor and minified CSS/JS are ordinary code files and are included too.
    """
    chunks: list[str] = []
    for path in iter_training_code_files(project):
        relative = path.relative_to(project).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        code_dependency = path.suffix.lower() in {".css", ".js", ".jsx", ".ts", ".tsx"}
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
                         externalize_all_code_dependencies: bool = False) -> int:
    serialized = serialize_training_project(
        project, exclude_render_bundles=exclude_render_bundles,
        externalize_resource_dependencies=externalize_resource_dependencies,
        externalize_all_code_dependencies=externalize_all_code_dependencies)
    return len(_load(str(tokenizer_json.resolve())).encode(serialized).ids)


def count_serialized_tokens(serialized: str, tokenizer_json: Path) -> int:
    """Count an already-serialized training context with the exact Qwen tokenizer."""
    return len(_load(str(tokenizer_json.resolve())).encode(serialized).ids)


def project_context_stats(project: Path, tokenizer_json: Path, *, exclude_render_bundles: bool = False,
                          externalize_resource_dependencies: bool = False,
                          externalize_all_code_dependencies: bool = False) -> dict[str, int]:
    files = iter_training_code_files(project)
    tokens = count_project_tokens(
        project, tokenizer_json, exclude_render_bundles=exclude_render_bundles,
        externalize_resource_dependencies=externalize_resource_dependencies,
        externalize_all_code_dependencies=externalize_all_code_dependencies)
    bundles = []
    if exclude_render_bundles:
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            code_dependency = path.suffix.lower() in {".css", ".js", ".jsx", ".ts", ".tsx"}
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
        "js_files": sum(len(by_suffix[s]) for s in {".js", ".jsx", ".ts", ".tsx"}),
        "bundle_files_omitted": len(bundles),
        "bundle_bytes_omitted": sum(path.stat().st_size for path in bundles),
    }

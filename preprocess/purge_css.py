#!/usr/bin/env python3
"""CSS 瘦身：移除 HTML 中未使用的 CSS 规则。

用 tinycss2 解析 <style> 块和 resources/*.css，
只保留 DOM 中实际引用的选择器对应的规则。

用法:
    python3 preprocess/purge_css.py --input-dir datasets/edit_sp --dry-run
    python3 preprocess/purge_css.py --input-dir datasets/edit_sp --threshold 50000
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import tinycss2
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 从 DOM 提取被引用的原子
# ---------------------------------------------------------------------------

def extract_used_atoms(soup: BeautifulSoup) -> set[str]:
    """收集 DOM 中所有 tag name、class name、id。"""
    atoms: set[str] = set()
    for el in soup.find_all(True):
        atoms.add(el.name)
        for cls in el.get("class") or []:
            atoms.add(cls)
        eid = el.get("id")
        if eid:
            atoms.add(eid)
    return atoms


def extract_script_atoms(project_dir: Path) -> set[str]:
    """Collect class/id names that JavaScript demonstrably applies or queries."""
    atoms: set[str] = set()
    patterns = (
        re.compile(r"classList\.(?:add|remove|toggle|contains)\(\s*['\"]([\w-]+)['\"]"),
        re.compile(r"getElementById\(\s*['\"]([\w-]+)['\"]"),
        re.compile(r"(?:querySelector|querySelectorAll)\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"setAttribute\(\s*['\"](?:class|id)['\"]\s*,\s*['\"]([^'\"]+)['\"]"),
    )
    for path in project_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            for value in pattern.findall(text):
                atoms.update(re.findall(r"[A-Za-z_][\w-]*", value))
    return atoms


# ---------------------------------------------------------------------------
# 选择器匹配判定
# ---------------------------------------------------------------------------

# 永远保留的选择器 pattern
_ALWAYS_KEEP_RE = re.compile(
    r"(?:^|\s|,)"              # 选择器开头/分隔符
    r"(?:"
    r":root|html|body|\*"      # 全局选择器
    r"|::?(?:before|after|placeholder|selection|backdrop|marker|first-line|first-letter)"  # 伪元素
    r")",
    re.IGNORECASE,
)

# 从选择器文本中提取 class/id/tag 的 token
_SELECTOR_TOKEN_RE = re.compile(
    r"(?:\.)([a-zA-Z_][\w-]*)"    # .class-name
    r"|(?:#)([a-zA-Z_][\w-]*)"    # #id
    r"|(?:^|[\s>+~,])([a-zA-Z][\w-]*)" # tag name
)


def selector_matches(selector_text: str, atoms: set[str]) -> bool:
    """判断选择器是否引用了 DOM 中存在的原子。

    保守策略：只要选择器中任一 token 出现在 atoms 中就保留。
    """
    # 永远保留的选择器
    if _ALWAYS_KEEP_RE.search(selector_text):
        return True

    # 提取 tokens
    tokens: set[str] = set()
    for m in _SELECTOR_TOKEN_RE.finditer(selector_text):
        token = m.group(1) or m.group(2) or m.group(3)
        if token:
            tokens.add(token)

    if not tokens:
        # 无法解析出 token（可能是纯伪类、attr 选择器等）→ 保守保留
        return True

    # Conservative rule-level cleanup: any DOM or explicit JS atom is enough.
    # Exact dead-rule elimination is unsafe for runtime-generated selectors.
    return bool(tokens & atoms)


# ---------------------------------------------------------------------------
# CSS 规则过滤
# ---------------------------------------------------------------------------

def _should_keep_rule(rule, atoms: set[str]) -> bool:
    """判断单条 tinycss2 规则是否应保留。"""
    # AtRule（@规则）
    if rule.type == "at-rule":
        lower_name = rule.at_keyword.lower()

        # 永远保留的 @规则
        if lower_name in ("font-face", "keyframes", "-webkit-keyframes",
                          "-moz-keyframes", "charset", "import", "namespace",
                          "supports", "layer", "property", "counter-style"):
            return True

        # @media — 递归处理内容
        if lower_name == "media" and rule.content is not None:
            inner_rules = tinycss2.parse_rule_list(rule.content)
            kept_any = any(_should_keep_rule(r, atoms) for r in inner_rules
                          if r.type in ("qualified-rule", "at-rule"))
            return kept_any

        # 其他未知 @规则 — 保守保留
        return True

    # QualifiedRule（普通样式规则）
    if rule.type == "qualified-rule":
        selector_text = tinycss2.serialize(rule.prelude).strip()

        # Rules using custom properties are often part of runtime themes.
        # Keep them unless a later render-aware workflow can prove them dead.
        content_text = tinycss2.serialize(rule.content) if rule.content else ""
        if "var(--" in content_text or "--" in selector_text:
            return True

        return selector_matches(selector_text, atoms)

    # 其他类型（注释、空白等）— 保留
    return True


def purge_css_text(css_text: str, atoms: set[str]) -> str:
    """过滤 CSS 文本，移除未使用的规则。"""
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)

    kept_parts: list[str] = []
    for rule in rules:
        if rule.type == "error":
            # 解析错误 — 跳过（无法安全序列化）
            continue

        if rule.type == "at-rule":
            lower_name = rule.at_keyword.lower()

            # @media — 递归过滤子规则
            if lower_name == "media" and rule.content is not None:
                inner_rules = tinycss2.parse_rule_list(rule.content)
                inner_kept = [r for r in inner_rules
                              if r.type != "error"
                              and (r.type not in ("qualified-rule", "at-rule")
                                   or _should_keep_rule(r, atoms))]
                if any(r.type in ("qualified-rule", "at-rule") for r in inner_kept):
                    # 有保留的子规则 — 重建 @media 块
                    prelude = tinycss2.serialize(rule.prelude)
                    inner_css = tinycss2.serialize(inner_kept)
                    kept_parts.append(f"@media {prelude}{{{inner_css}}}")
                continue

            if _should_keep_rule(rule, atoms):
                kept_parts.append(tinycss2.serialize([rule]))
            continue

        if rule.type == "qualified-rule":
            if _should_keep_rule(rule, atoms):
                kept_parts.append(tinycss2.serialize([rule]))
            continue

        # 其他（whitespace, comment 等已被 skip）
        try:
            kept_parts.append(tinycss2.serialize([rule]))
        except TypeError:
            continue

    return "\n".join(kept_parts)


# ---------------------------------------------------------------------------
# 项目级处理
# ---------------------------------------------------------------------------

def purge_project(
    project_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """对一个项目的所有 <style> 块和 resources/*.css 做 CSS 瘦身。"""
    stats = {
        "original_bytes": 0,
        "purged_bytes": 0,
        "style_blocks_processed": 0,
        "css_files_processed": 0,
    }

    # 读取所有 HTML 文件，合并 DOM atoms。Multi-page 项目可能把页面放在子目录。
    html_files = sorted(project_dir.rglob("*.html"))
    if not html_files:
        return {"status": "skipped", "project": project_dir.name, **stats}

    all_atoms: set[str] = set()
    soups: dict[Path, BeautifulSoup] = {}

    for hf in html_files:
        try:
            html = hf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        all_atoms |= extract_used_atoms(soup)
        soups[hf] = soup
    all_atoms |= extract_script_atoms(project_dir)

    if not all_atoms:
        return {"status": "skipped", "project": project_dir.name, **stats}

    # 也从外部 CSS 文件中提取可能被引用的 class/id（CSS 规则可能引用其他 CSS 中的 class）
    # → 不需要，atoms 来自 DOM 即可

    modified = False

    # 处理 <style> 块
    for hf, soup in soups.items():
        style_tags = soup.find_all("style")
        if not style_tags:
            continue

        html_changed = False
        for style_tag in style_tags:
            css_text = style_tag.string
            if not css_text or len(css_text.strip()) < 50:
                continue

            original_len = len(css_text)
            stats["original_bytes"] += original_len

            purged = purge_css_text(css_text, all_atoms)
            purged_len = len(purged)
            stats["purged_bytes"] += purged_len
            stats["style_blocks_processed"] += 1

            if purged_len < original_len * 0.95:
                # 至少减少 5% 才改写（避免无意义的小改动）
                style_tag.string = purged
                html_changed = True

        if html_changed and not dry_run:
            hf.write_text(str(soup), encoding="utf-8")
            modified = True

    # 上游会把 inline CSS 外置到 author_styles/，历史项目也可能使用其他
    # 子目录。孤儿清理已在此步骤前执行，因此剩余 CSS 都是可达资源。
    for css_file in sorted(project_dir.rglob("*.css")):
        try:
            css_text = css_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if len(css_text.strip()) < 50:
            continue

        original_len = len(css_text)
        stats["original_bytes"] += original_len

        purged = purge_css_text(css_text, all_atoms)
        purged_len = len(purged)
        stats["purged_bytes"] += purged_len
        stats["css_files_processed"] += 1

        if purged_len < original_len * 0.95 and not dry_run:
            css_file.write_text(purged, encoding="utf-8")
            modified = True

    reduction = stats["original_bytes"] - stats["purged_bytes"]
    return {
        "status": "purged" if modified else ("would_purge" if reduction > 0 else "no_change"),
        "project": project_dir.name,
        "reduction_bytes": reduction,
        "reduction_pct": f"{reduction / max(stats['original_bytes'], 1) * 100:.1f}%",
        **stats,
    }


def purge_all_projects(
    dataset_dir: Path,
    dry_run: bool = False,
    threshold: int = 50_000,
) -> dict[str, Any]:
    """批量处理数据集中所有项目。

    Args:
        threshold: 只处理 index.html > threshold 字节的项目（默认 50KB）
    """
    projects = sorted(
        d for d in dataset_dir.iterdir()
        if d.is_dir() and d.name != "_rejected" and (d / "index.html").exists()
    )

    total = len(projects)
    processed = 0
    skipped = 0
    total_reduction = 0
    total_original = 0

    for proj in projects:
        index = proj / "index.html"
        if index.stat().st_size < threshold:
            skipped += 1
            continue

        result = purge_project(proj, dry_run=dry_run)
        processed += 1
        total_reduction += result.get("reduction_bytes", 0)
        total_original += result.get("original_bytes", 0)

        if result.get("reduction_bytes", 0) > 10000:
            action = "[DRY] " if dry_run else ""
            print(f"  {action}{result['project']}: "
                  f"{result['original_bytes'] // 1024}KB → "
                  f"{result['purged_bytes'] // 1024}KB "
                  f"(-{result['reduction_pct']})")

    summary = {
        "total_projects": total,
        "processed": processed,
        "skipped_below_threshold": skipped,
        "total_original_css_bytes": total_original,
        "total_reduction_bytes": total_reduction,
        "total_reduction_pct": f"{total_reduction / max(total_original, 1) * 100:.1f}%",
    }

    print(f"\n{'=' * 60}")
    print(f"Dataset: {dataset_dir}")
    print(f"Projects: {total} total, {processed} processed (>{threshold // 1024}KB), {skipped} skipped")
    print(f"CSS: {total_original // 1024}KB original → {(total_original - total_reduction) // 1024}KB purged")
    print(f"Reduction: {total_reduction // 1024}KB ({summary['total_reduction_pct']})")
    if dry_run:
        print("[DRY RUN] No files modified")
    print(f"{'=' * 60}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="CSS 瘦身：移除未使用的 CSS 规则")
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="数据集目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅统计，不修改文件")
    parser.add_argument("--threshold", type=int, default=50_000,
                        help="只处理 index.html 大于此字节数的项目（默认 50000）")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: {args.input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    purge_all_projects(args.input_dir, dry_run=args.dry_run, threshold=args.threshold)


if __name__ == "__main__":
    main()

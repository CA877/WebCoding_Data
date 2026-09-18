#!/usr/bin/env python3
"""Deterministically split the 1k complex-stack queries by agent necessity."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable


ALWAYS_WEBGEN_TRACKS = frozenset({"threejs", "webgl"})
WEBGEN_UNSUPPORTED_TRACKS = frozenset({"python_backend", "java_backend"})
COMPLEX_FAMILY_PATTERNS = {
    "direct_manipulation": re.compile(
        r"drag[- ]and[- ]drop|draggable|resiz|timeline|undo|redo", re.I
    ),
    "graphics_media": re.compile(
        r"canvas|webgl|three\.js|audio|video|waveform|\b3d\b|shader", re.I
    ),
    "live_coordination": re.compile(
        r"real[- ]time|websocket|collaborat|synchroni[sz]|cross-component|cross-view",
        re.I,
    ),
    "resilient_async": re.compile(
        r"offline|retry|concurren|queue|upload|failure|recovery", re.I
    ),
    "simulation": re.compile(
        r"physics|simulation|pathfind|collision|procedural|particle", re.I
    ),
    "device_integration": re.compile(r"camera|geolocation|sensor", re.I),
}


@dataclass(frozen=True)
class RoutingDecision:
    route: str
    complex_families: tuple[str, ...]
    reason: str


def classify_row(row: dict) -> RoutingDecision:
    track = str(row.get("technology_track", "")).strip()
    query = str(row.get("query", ""))
    families = tuple(
        name for name, pattern in COMPLEX_FAMILY_PATTERNS.items() if pattern.search(query)
    )
    if track in WEBGEN_UNSUPPORTED_TRACKS:
        return RoutingDecision("single", families, f"npm-only WebGen does not support: {track}")
    if track in ALWAYS_WEBGEN_TRACKS:
        return RoutingDecision("webgen", families, f"always-agent track: {track}")
    if len(families) >= 4:
        return RoutingDecision(
            "webgen", families, f"{len(families)} distinct complex interaction families"
        )
    return RoutingDecision(
        "single", families, f"{len(families)} complex interaction families"
    )


def route_rows(rows: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    single: list[dict] = []
    webgen: list[dict] = []
    for original in rows:
        row = dict(original)
        decision = classify_row(row)
        routing = asdict(decision)
        routing["complex_families"] = list(decision.complex_families)
        if decision.route == "single":
            row["routing"] = routing
            single.append(row)
        else:
            webgen.append({
                "id": row["job_id"],
                "instruction": row["query"],
                "technology_track": row.get("technology_track"),
                "source": row,
                "routing": routing,
            })
    return single, webgen


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("runs/artifactsbench_complex_stack_1k_qwen3.7max_20260731/queries.jsonl"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    single, webgen = route_rows(rows)
    write_jsonl(args.output_dir / "single.jsonl", single)
    write_jsonl(args.output_dir / "webgen.jsonl", webgen)
    summary = {"total": len(rows), "single": len(single), "webgen": len(webgen)}
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

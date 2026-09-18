#!/usr/bin/env python3
"""Validate a downloaded copy of the ``lxpp/all_merged_instructions`` dataset.

Checks per-file JSONL integrity, required field schemas, ID uniqueness,
instruction/length consistency, cross-file ID consistency, and optionally
compares local file size + sha256 against a Hugging Face manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_LINES: dict[str, int] = {
    "all_merged_instructions.jsonl": 31_900,
    "output/new_instructions.jsonl": 63_203,
    "output/new_instructions_cyber.jsonl": 50,
    "output/sft_messages.jsonl": 6_503,
    "output/step1_inference_log.jsonl": 20_366,
    "output/step1_responses.jsonl": 20_290,
    "output/step2_checklists.jsonl": 13_775,
    "output/step3_code_scores.jsonl": 11_175,
    "output/step3b_interaction_scores.jsonl": 9_441,
    "output/step4_visual_scores.jsonl": 21_050,
    "output/step5_filtered.jsonl": 6_503,
    "sft_train/train_sharegpt.jsonl": 6_503,
    "sft_train/val_sharegpt.jsonl": 65,
}

REQUIRED_FIELDS: dict[str, dict[str, tuple]] = {
    "all_merged_instructions.jsonl": {
        "id": (str,), "instruction": (str,), "length": (int,),
    },
    "output/new_instructions.jsonl": {
        "id": (str,), "instruction": (str,), "original_instruction": (str,), "length": (int,),
    },
    "output/new_instructions_cyber.jsonl": {
        "id": (str,), "instruction": (str,), "original_instruction": (str,), "length": (int,),
    },
    "output/sft_messages.jsonl": {"id": (str,), "messages": (list,)},
    "output/step1_inference_log.jsonl": {
        "id": (str,), "round": (int,), "repo_path": (str,), "status": (str,), "file_count": (int,),
    },
    "output/step1_responses.jsonl": {"id": (str,), "response": (str,)},
    "output/step2_checklists.jsonl": {"id": (str,), "checklist": (list,)},
    "output/step3_code_scores.jsonl": {"id": (str,), "round": (int,), "scores": (list,)},
    "output/step3b_interaction_scores.jsonl": {"id": (str,), "round": (int,), "scores": (list,)},
    "output/step4_visual_scores.jsonl": {"id": (str,), "round": (int,), "scores": (list,)},
    "output/step5_filtered.jsonl": {
        "id": (str,), "instruction": (str,), "checklist": (list,), "best_round": (int,),
        "num_attempts": (int,), "code_total": (int, float), "interaction_total": (int, float),
        "visual_total": (int, float), "combined_score": (int, float),
        "code_scores": (list,), "interaction_scores": (list,), "visual_scores": (list,),
    },
    "sft_train/train_sharegpt.jsonl": {"id": (str,), "conversations": (list,)},
    "sft_train/val_sharegpt.jsonl": {"id": (str,), "conversations": (list,)},
}


def _snippet(obj, limit=160):
    text = json.dumps(obj, ensure_ascii=False)
    return text[:limit] + ("..." if len(text) > limit else "")


def validate_file(path: Path, expected_lines: int | None, max_samples: int) -> dict:
    rel = path.relative_to(path.parents[2]) if False else path.name
    # keep relative name for report
    try:
        rel = str(path.relative_to(_ROOT_ARG))
    except Exception:
        rel = str(path)
    info = {
        "file": rel,
        "lines": 0,
        "parse_errors": 0,
        "parse_error_samples": [],
        "missing_field": Counter(),
        "wrong_type": Counter(),
        "schema_error_samples": [],
        "duplicate_ids": 0,
        "duplicate_id_samples": [],
        "empty_instruction": 0,
        "length_mismatch": 0,
        "length_mismatch_samples": [],
        "key_sets": Counter(),
        "ids": set(),
        "extra": {},
    }
    key = rel
    length_stats = {"min": None, "max": None, "sum": 0, "n": 0}
    id_round_pairs = Counter()
    status_counter = Counter()
    role_counter = Counter()
    from_counter = Counter()
    score_violations = 0
    score_violation_samples = []
    instruction_len = 0

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            info["lines"] += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                info["parse_errors"] += 1
                if len(info["parse_error_samples"]) < max_samples:
                    info["parse_error_samples"].append(
                        {"line": line_no, "error": str(exc), "snippet": line[:160]}
                    )
                continue
            if not isinstance(obj, dict):
                if len(info["schema_error_samples"]) < max_samples:
                    info["schema_error_samples"].append(
                        {"line": line_no, "error": f"top-level type {type(obj).__name__}"}
                    )
                continue

            info["key_sets"][tuple(sorted(obj))] += 1
            fields = REQUIRED_FIELDS.get(key, {})
            for field, types in fields.items():
                if field not in obj:
                    info["missing_field"][field] += 1
                    if len(info["schema_error_samples"]) < max_samples:
                        info["schema_error_samples"].append(
                            {"line": line_no, "error": f"missing field {field!r}", "snippet": _snippet(obj)}
                        )
                elif not isinstance(obj[field], types):
                    info["wrong_type"][field] += 1
                    if len(info["schema_error_samples"]) < max_samples:
                        info["schema_error_samples"].append(
                            {"line": line_no, "error": f"field {field!r} type {type(obj[field]).__name__}",
                             "snippet": _snippet(obj)}
                        )

            row_id = obj.get("id")
            if isinstance(row_id, str):
                if row_id in info["ids"]:
                    info["duplicate_ids"] += 1
                    if len(info["duplicate_id_samples"]) < max_samples:
                        info["duplicate_id_samples"].append(row_id)
                else:
                    info["ids"].add(row_id)
            elif "id" in obj and len(info["schema_error_samples"]) < max_samples:
                info["schema_error_samples"].append({"line": line_no, "error": "id is not a string"})

            # length consistency
            if "instruction" in obj and "length" in obj:
                if isinstance(obj["instruction"], str) and isinstance(obj["length"], int):
                    length_stats["n"] += 1
                    length_stats["sum"] += obj["length"]
                    length_stats["min"] = obj["length"] if length_stats["min"] is None else min(length_stats["min"], obj["length"])
                    length_stats["max"] = obj["length"] if length_stats["max"] is None else max(length_stats["max"], obj["length"])
                    if len(obj["instruction"]) != obj["length"]:
                        info["length_mismatch"] += 1
                        if len(info["length_mismatch_samples"]) < max_samples:
                            info["length_mismatch_samples"].append(
                                {"line": line_no, "id": row_id, "field": obj["length"], "actual": len(obj["instruction"])}
                            )
                    instruction_len += len(obj["instruction"])
                elif isinstance(obj["instruction"], str) and not obj["instruction"]:
                    info["empty_instruction"] += 1

            # per-type extra checks
            if key.startswith("output/step") and "round" in obj and isinstance(obj.get("round"), int):
                id_round_pairs[(row_id, obj["round"])] += 1
            if key == "output/step1_inference_log.jsonl" and isinstance(obj.get("status"), str):
                status_counter[obj["status"]] += 1
            if key == "output/sft_messages.jsonl" and isinstance(obj.get("messages"), list):
                for m in obj["messages"]:
                    if isinstance(m, dict) and isinstance(m.get("role"), str):
                        role_counter[m["role"]] += 1
            if key.startswith("sft_train/") and isinstance(obj.get("conversations"), list):
                for m in obj["conversations"]:
                    if isinstance(m, dict) and isinstance(m.get("from"), str):
                        from_counter[m["from"]] += 1
            if key in ("output/step3_code_scores.jsonl", "output/step3b_interaction_scores.jsonl",
                       "output/step4_visual_scores.jsonl") and isinstance(obj.get("scores"), list):
                for s in obj["scores"]:
                    if isinstance(s, dict) and isinstance(s.get("score"), (int, float)) and isinstance(s.get("max_score"), (int, float)):
                        if not (0 <= s["score"] <= s["max_score"]):
                            score_violations += 1
                            if len(score_violation_samples) < max_samples:
                                score_violation_samples.append({"line": line_no, "id": row_id, "round": obj.get("round"), "score": s})

    if length_stats["n"]:
        length_stats["avg"] = length_stats["sum"] / length_stats["n"]
    else:
        length_stats["avg"] = None
    info["extra"] = {
        "length_stats": length_stats,
        "unique_ids": len(info["ids"]),
        "id_round_unique": sum(1 for v in id_round_pairs.values() if v == 1),
        "id_round_total": sum(id_round_pairs.values()),
        "id_round_duplicate_pairs": sum(1 for v in id_round_pairs.values() if v > 1),
        "status": dict(status_counter),
        "roles": dict(role_counter),
        "froms": dict(from_counter),
        "score_violations": score_violations,
        "score_violation_samples": score_violation_samples[:max_samples],
        "avg_instruction_chars": (instruction_len / info["lines"]) if info["lines"] else None,
    }
    if expected_lines is not None:
        info["expected_lines"] = expected_lines
        info["line_count_ok"] = info["lines"] == expected_lines
    return info


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cross_checks(infos: dict[str, dict]) -> list[str]:
    out = []
    ids = {k: v["ids"] for k, v in infos.items()}
    root = ids.get("all_merged_instructions.jsonl", set())
    step5 = ids.get("output/step5_filtered.jsonl", set())
    msg = ids.get("output/sft_messages.jsonl", set())
    train = ids.get("sft_train/train_sharegpt.jsonl", set())
    val = ids.get("sft_train/val_sharegpt.jsonl", set())
    step1 = ids.get("output/step1_responses.jsonl", set())
    step2 = ids.get("output/step2_checklists.jsonl", set())
    step3 = ids.get("output/step3_code_scores.jsonl", set())
    step3b = ids.get("output/step3b_interaction_scores.jsonl", set())
    step4 = ids.get("output/step4_visual_scores.jsonl", set())
    new_ids = ids.get("output/new_instructions.jsonl", set())
    cyber_ids = ids.get("output/new_instructions_cyber.jsonl", set())

    def rel(name, sub, sup):
        out.append(f"{name}: {len(sub)} ids, subset of {len(sup)} -> {sub <= sup}")

    out.append(f"root unique ids: {len(root)} / {len(infos.get('all_merged_instructions.jsonl', {}).get('ids', set()))} total rows")
    rel("step5 vs sft_messages", step5, msg)
    rel("sft_messages vs step5", msg, step5)
    rel("train vs step5", train, step5)
    rel("train vs sft_messages", train, msg)
    rel("val vs train", val, train)
    rel("val vs step5", val, step5)
    rel("step2 vs step1", step2, step1)
    rel("step3 vs step2", step3, step2)
    rel("step3b vs step3", step3b, step3)
    rel("step4 vs step2", step4, step2)
    rel("new_instructions(unique) vs root", new_ids, root)
    rel("cyber vs root", cyber_ids, root)
    out.append(f"train+val union size: {len(train | val)}")
    out.append(f"train∩val overlap: {len(train & val)}")
    out.append(f"step5∩val overlap: {len(step5 & val)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, type=Path, help="dataset root directory")
    ap.add_argument("--out", required=True, type=Path, help="report output directory")
    ap.add_argument("--manifest", type=Path, help="optional HF manifest JSON {path: {size, sha256}}")
    ap.add_argument("--max-samples", type=int, default=20)
    args = ap.parse_args()

    root: Path = args.root
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    global _ROOT_ARG
    _ROOT_ARG = root

    report = []
    report.append(f"# Download check: {root}")
    report.append(f"checked_at: {__import__('datetime').datetime.now().isoformat()}")
    report.append("")

    infos = {}
    any_fail = False
    for rel, expected in EXPECTED_LINES.items():
        path = root / rel
        if not path.exists():
            report.append(f"[MISSING] {rel}")
            any_fail = True
            continue
        info = validate_file(path, expected, args.max_samples)
        infos[rel] = info
        report.append(f"## {rel}")
        report.append(f"- size_bytes: {path.stat().st_size}")
        report.append(f"- lines: {info['lines']} (expected {expected}, ok={info['line_count_ok']})")
        report.append(f"- parse_errors: {info['parse_errors']}")
        report.append(f"- duplicate_ids: {info['duplicate_ids']} (unique={info['extra']['unique_ids']})")
        report.append(f"- missing_field: {dict(info['missing_field'])}")
        report.append(f"- wrong_type: {dict(info['wrong_type'])}")
        report.append(f"- empty_instruction: {info['empty_instruction']}")
        report.append(f"- length_mismatch: {info['length_mismatch']}")
        ls = info["extra"]["length_stats"]
        if ls["n"]:
            report.append(f"- length: n={ls['n']} min={ls['min']} max={ls['max']} avg={ls['avg']:.1f}")
        if info["extra"]["id_round_total"]:
            report.append(
                f"- (id,round) pairs: {info['extra']['id_round_total']}, unique={info['extra']['id_round_unique']}, "
                f"duplicated={info['extra']['id_round_duplicate_pairs']}"
            )
        if info["extra"]["status"]:
            report.append(f"- status: {info['extra']['status']}")
        if info["extra"]["roles"]:
            report.append(f"- message roles: {info['extra']['roles']}")
        if info["extra"]["froms"]:
            report.append(f"- conversation speakers: {info['extra']['froms']}")
        if info["extra"]["score_violations"]:
            report.append(f"- score>max violations: {info['extra']['score_violations']}")
        for name, samples in (
            ("parse_error_samples", info["parse_error_samples"]),
            ("schema_error_samples", info["schema_error_samples"]),
            ("duplicate_id_samples", info["duplicate_id_samples"]),
            ("length_mismatch_samples", info["length_mismatch_samples"]),
            ("score_violation_samples", info["extra"]["score_violation_samples"]),
        ):
            if samples:
                report.append(f"- {name}:")
                for s in samples:
                    report.append(f"    {s}")
        ok = (info["parse_errors"] == 0 and info["line_count_ok"]
              and not info["missing_field"] and not info["wrong_type"]
              and info["duplicate_ids"] == 0 and info["empty_instruction"] == 0
              and info["length_mismatch"] == 0)
        report.append(f"- RESULT: {'OK' if ok else 'PROBLEMS'}")
        report.append("")
        if not ok:
            any_fail = True

    report.append("## Cross-file checks")
    for line in cross_checks(infos):
        report.append(f"- {line}")
    report.append("")

    # sample values for new_instructions.original_instruction
    new_path = root / "output/new_instructions.jsonl"
    if new_path.exists():
        with new_path.open("r", encoding="utf-8") as fh:
            first = json.loads(fh.readline())
        report.append("## new_instructions sample fields")
        report.append(f"- keys: {sorted(first)}")
        report.append(f"- original_instruction sample: {str(first.get('original_instruction'))[:200]}")
        report.append("")

    if args.manifest:
        report.append("## Checksum vs manifest")
        manifest = json.loads(args.manifest.read_text("utf-8"))
        for rel, meta in sorted(manifest.items()):
            path = root / rel
            if not path.exists():
                report.append(f"- [MISSING] {rel}")
                any_fail = True
                continue
            size_ok = path.stat().st_size == meta.get("size")
            sha = sha256_file(path)
            expected_sha = meta.get("sha256")
            sha_ok = (expected_sha is None) or (sha == expected_sha)
            report.append(
                f"- {rel}: size ok={size_ok} ({path.stat().st_size} vs {meta.get('size')}), "
                f"sha256 ok={'n/a' if expected_sha is None else sha_ok}"
            )
            if not size_ok or (expected_sha is not None and not sha_ok):
                report.append(f"    local  sha256: {sha}")
                report.append(f"    remote sha256: {expected_sha}")
                any_fail = True
        report.append("")

    report_text = "\n".join(report)
    (out_dir / "report.txt").write_text(report_text, "utf-8")
    print(report_text)
    print(f"\nREPORT: {out_dir / 'report.txt'}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())

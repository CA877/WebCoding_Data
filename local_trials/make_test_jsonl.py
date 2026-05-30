#!/usr/bin/env python3
"""Convert raw HTML samples into a JSONL file suitable for the clean pipeline."""
import json
from pathlib import Path

raw_dir = Path(__file__).parent / "webcode2m_raw_10"
output = Path(__file__).parent / "test_samples.jsonl"

with output.open("w", encoding="utf-8") as f:
    for i, html_path in enumerate(sorted(raw_dir.glob("sample_*.html"))):
        html = html_path.read_text(encoding="utf-8")
        row = {
            "row_idx": 500000 + i,
            "text": html,
            "lang": "en",
            "url": "",
            "hash": f"test_{i:03d}",
            "score": 0.5,
            "image": {},
        }
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print(f"Wrote {i+1} rows to {output}")

# WebCoding Pipeline Utils

Reusable implementation of the full WebCoding data gate described in
`docs/planning/从爬取到训练样本的全流程筛选与处理方案.md`.

## Modules

- `records.py`: extracts code files, patches, image references, task ids, domains, and hash keys from mixed legacy/full records.
- `patches.py`: validates search/replace patches, applies them, and records match strategy and location.
- `content_qc.py`: detects risky content, challenge/parked/error pages, language markers, remote dependencies, bad protocols, and low-information code.
- `image_qc.py`: checks image existence/decode/blankness and computes image-repair before/after diffs.
- `resources.py`: audits and optionally removes orphan or duplicate `resources/` files while respecting protected patch paths.
- `release_pipeline.py`: runs the final release gate and writes `accepted.jsonl`, `review.jsonl`, `rejected.jsonl`, `sample_issues.jsonl`, and `quality_pipeline_summary.json`.

## Image URL Policy

New data production must not synthesize replacement image URLs. Do not replace
original links with `picsum.photos`, `loremflickr.com`, or any other placeholder
image service. Real resources can be localized; otherwise keep the original URL
and let QC decide whether the sample is acceptable. Existing placeholder URLs
are treated as hard reject issues by `content_qc.py`.

## CLI

```bash
python3 scripts/run_full_quality_pipeline.py \
  --release-root /path/to/release_sft_6tasks_v1 \
  --out-dir /path/to/qc_out
```

Use `--skip-image-open` for fast static-only checks, and
`--allow-missing-output-files` only when auditing a legacy light release where
edit/repair `output_files` are known to be absent.

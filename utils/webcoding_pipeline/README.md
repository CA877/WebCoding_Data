# WebCoding Pipeline Utils

Reusable implementation of the full WebCoding data gate described in
`docs/planning/从爬取到训练样本的全流程筛选与处理方案.md`.

## Modules

- `records.py`: extracts code files, patches, image references, task ids, domains, and hash keys from mixed legacy/full records.
- `patches.py`: validates search/replace patches, applies them, and records match strategy and location.
- `content_qc.py`: detects risky content, challenge/parked/error pages, language markers, remote dependencies, bad protocols, and low-information code.
- `image_qc.py`: checks image existence/decode/blankness and computes image-repair before/after diffs.
- `resources.py`: audits and optionally removes orphan or duplicate `resources/` files, flags referenced vendor/blob files, and respects protected patch paths.
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

## Resource Slimming

The resource slimming policy separates three cases:

- Orphan or exact duplicate files under `resources/`: safe to delete, because no scanned HTML/CSS/JS file references them or another identical copy already exists.
- Referenced third-party/vendor/blob files, such as reCAPTCHA, analytics, large minified libraries: keep by default. They can be externalized only when CDN use is allowed and an explicit local-path-to-CDN mapping is provided.
- HTML, inline CSS/JS, and author-written scripts: keep as training target code.

Read-only audit:

```bash
python3 scripts/slim_project_resources.py \
  --project-root /path/to/project_or_parent \
  --out-dir /path/to/resource_audit
```

Apply safe orphan/duplicate deletion:

```bash
python3 scripts/slim_project_resources.py \
  --project-root /path/to/project_or_parent \
  --out-dir /path/to/resource_audit \
  --apply
```

Externalize referenced vendor blobs only with an explicit map:

```bash
python3 scripts/slim_project_resources.py \
  --project-root /path/to/project_or_parent \
  --out-dir /path/to/resource_audit \
  --apply \
  --allow-cdn-externalize \
  --externalize-map vendor_cdn_map.json
```

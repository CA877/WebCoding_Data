# Grep-Based Full Release Counts

| file | total | adult/sensitive | challenge | placeholder | remote URL | missing input_files | missing dst_screenshot |
|---|---:|---:|---:|---:|---:|---:|---:|
| `image-edit.jsonl` | 4333 | 3856 (88.99%) | 3053 (70.46%) | 4099 (94.60%) | 4318 (99.65%) | 0 (0.00%) | 0 (0.00%) |
| `image-generate.jsonl` | 9769 | 2422 (24.79%) | 4761 (48.74%) | 7876 (80.62%) | 9671 (99.00%) | 0 (0.00%) | 0 (0.00%) |
| `image-repair.jsonl` | 4845 | 4235 (87.41%) | 3407 (70.32%) | 4447 (91.79%) | 4815 (99.38%) | 0 (0.00%) | 0 (0.00%) |
| `text-edit.jsonl` | 4333 | 3903 (90.08%) | 3053 (70.46%) | 4099 (94.60%) | 4299 (99.22%) | 4333 (100.00%) | 4333 (100.00%) |
| `text-generate.jsonl` | 4959 | 4465 (90.04%) | 3487 (70.32%) | 4644 (93.65%) | 4892 (98.65%) | 4959 (100.00%) | 4959 (100.00%) |
| `text-repair.jsonl` | 4926 | 4369 (88.69%) | 3479 (70.63%) | 4524 (91.84%) | 4879 (99.05%) | 4926 (100.00%) | 4926 (100.00%) |

Notes:
- Counts are line-level full-release scans over JSONL records.
- They are intentionally conservative: a hit anywhere in code, metadata, image path, or instruction marks the sample.
- `missing_input_files` is expected for lightweight text release files, but means patch uniqueness cannot be checked from that release JSONL.

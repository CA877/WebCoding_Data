# Benchmark Sample Notes

This folder contains small local sample files for quick comparison against the
current `case_part*` query pool.

Files:

- `webgen-bench/sample_queries.jsonl`
- `web-bench/sample_tasks.jsonl`

Important note:

- These are not full local mirrors of the Hugging Face datasets.
- Direct command-line downloading from Hugging Face stalled in the current
  environment, so these files are a compact, hand-curated subset assembled from
  publicly visible dataset examples and repository descriptions.
- The goal is fast distribution checking: what the prompts/tasks look like,
  whether they align with your current queries, and what kinds of capability
  they emphasize.

Suggested use:

1. Read a few rows from each sample file.
2. Compare them against `dataset_example/example_data/case_part1.jsonl`.
3. Check whether your current queries are more:
   - landing-page / portfolio / branding heavy
   - or workflow / business-system / repo-edit heavy

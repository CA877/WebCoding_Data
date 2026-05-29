# WebRenderBench useful31765 Filtering Logic

This document records how the WebRenderBench raw webpages were filtered into
the final `31,765` useful samples.

## Source Data

The source data was the raw WebRenderBench `train_webpages` and
`test_webpages` directory layout.

Raw directory counts:

| Split | Count |
|---|---:|
| `train_webpages` | 22,606 |
| `test_webpages` | 22,500 |
| Total | 45,106 |

## Filtering Chain

```text
45,106 raw WebRenderBench projects
-> 38,062 renderable unique projects with split
-> 38,023 after removing WebCompass overlap
-> 23,521 strict clean candidates
+  8,244 rescued inline-asset projects
= 31,765 useful projects
```

The final materialized dataset directory is the rebuilt
`webrenderbench_clean_split/useful` directory.

## Step 1. Keep Renderable Pages

Each project was opened with Playwright Chromium.

Validation rules:

1. Open the page in a browser.
2. Count only `pageerror` as JavaScript execution failure.
3. Do not reject a page only because ordinary third-party resources fail to load.
4. If `body_text_length < 50`, mark the page as `blank`.
5. Otherwise:
   - if there is any `pageerror`, mark it as `js_errors`;
   - if there is no `pageerror`, mark it as `ok`.

Result:

```text
validation_ok_unique_with_split = 38,062
```

## Step 2. Remove WebCompass Overlap

The renderable set was deduplicated against the WebCompass prototype/task
blacklist to avoid leaking benchmark pages into training candidates.

Recorded counts:

```text
webcompass_blacklist_base_count = 50
after_webcompass = 38,023
```

The net reduction is `39` because the blacklist base count and actual
WebRenderBench overlap are not exactly the same unit.

## Step 3. Reject Oversized Code and Long Blobs

Projects were rejected if they had either:

1. any single code file larger than `2,000,000` bytes; or
2. any of these long-token/blob patterns:
   - `data:...;base64,...` where the base64 payload length is at least `1,000`;
   - base64-like long token with length at least `2,000`;
   - hex-like long token with length at least `2,000`.

Result:

```text
rejected_long_gibberish_or_oversized_code = 14,502
clean_candidates = 23,521
```

These `23,521` projects form the strict clean subset.

## Step 4. Rescue Normalizable Inline Assets

Some projects rejected in Step 3 were still useful because their long blobs
were normalizable assets rather than low-quality code. Only projects whose bad
kinds were fully contained in the following set were eligible for rescue:

```text
sourcemap
image_data_uri
font_data_uri
```

Rescue rules:

1. `sourcemap`
   - remove or replace inline `sourceMappingURL=data:application/json;base64,...`.
2. `image_data_uri`
   - decode `data:image/...;base64,...`;
   - write the decoded bytes into the project's local asset directory;
   - replace the original data URI in HTML/CSS with a relative local path.
3. `font_data_uri`
   - decode `data:font/...;base64,...` and compatible `application/font-woff`
     style data URIs;
   - write the decoded bytes into the project's local asset directory;
   - replace the original data URI with a relative local path.

A rescued project was accepted only if both checks passed:

1. the original long-blob match no longer existed;
2. the total code size decreased.

Result:

```text
rescued_inline_assets = 8,244
```

## Final Definition

The final `useful31765` set is:

```text
strict clean candidates + rescued inline-asset projects
= 23,521 + 8,244
= 31,765
```

Downstream data construction does not need to distinguish between the strict
clean subset and the rescued subset. Both are treated as useful WebRenderBench
projects.

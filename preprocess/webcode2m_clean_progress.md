# WebCode2M Clean Prototype Progress

## Benchmark Takeaways

- WebCompass covers seven web-coding tasks across text/image/video generation, text/image editing, and text/image repair. Its evaluation stresses runnability, visual fidelity, interaction, responsiveness, and checklist/agent-based judging.
- Design2Code is mainly screenshot-to-HTML/CSS: good for static visual fidelity, less focused on interaction or multi-page behavior.
- Vision2Web raises the bar toward real websites: static responsive pages, interactive multi-page frontends, and full-stack tasks, judged by GUI workflow verification plus VLM visual scoring.
- Flame-VLM-Code is more a UI-to-code model/data-synthesis line than a benchmark target, but it reinforces the same lesson: visual-to-code training benefits from clean aligned image/code pairs.

## Processing Decision

Use WebCode2M as a source pool, not as final SFT data directly.

For each row:

1. Save `text` as a local `index.html`.
2. Download reachable render resources into `assets/`.
3. Delete tracking/counter/widget noise.
4. Replace missing root-relative/failed images with local deterministic SVG visual assets.
5. Replace missing icons/avatars with local SVG icon/avatar assets.
6. Try multi-page crawling only when crawlable absolute internal links exist.
7. Record all actions in `metadata.json`.

This avoids teaching models to memorize external URLs while preserving page layout and most real assets.

## Current Outputs

- Clean 100 projects: `WebCoding_Data/local_trials/webcode2m_clean_100/projects`
- Seven-task prototype cases: `WebCoding_Data/local_trials/webcode2m_cases_7x10`
- Cleaning script: `WebCoding_Data/preprocess/webcode2m_clean_pipeline.py`
- Case script: `WebCoding_Data/construct/construct_webcode2m_cases.py`

Clean 100 summary:

```json
{
  "ok": 100,
  "downloaded": 213,
  "removed_noise_ref": 26,
  "root_relative_fallback": 113,
  "relative_fallback": 43,
  "fallback_asset": 68
}
```

Case summary:

- `text-generation`: 10
- `image-generation`: 10
- `video-generation`: 10
- `text-editing`: 10
- `image-editing`: 10
- `text-repair`: 10
- `image-repair`: 10

All case HTML pages currently have zero remote render-resource attributes.

## Multi-page Status

The downloaded 100 WebCode2M rows expose no normal `href=` anchors in their purified HTML. Because WebCode2M also does not expose original page URLs/base URLs, these rows cannot be faithfully expanded into original child pages. The cleaner keeps this honest by marking such projects:

```text
multipage_status = "multipage_unavailable"
reason_if_single_page = "no crawlable absolute internal hrefs in WebCode2M text"
```

If a larger WebCode2M slice contains absolute same-domain links, the script will try to crawl up to six child pages.

## Next Best Step

Run human review on the 70 generated cases, then replace the heuristic `text-generation` instructions with VLM-generated PRDs from the cleaned screenshots for higher leaderboard value.

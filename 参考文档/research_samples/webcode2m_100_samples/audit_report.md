# WebCode2M 100-sample audit

## Local files

- `samples.jsonl`: raw 100 dataset rows from datasets-server
- `html/`: one HTML/text file per row, `sample_000.html` ... `sample_099.html`
- `images/`: 100 dataset screenshot PNGs
- `resource_audit/remote_probe_results.json`: remote resource probe results
- `../webcode2m_lang_probe/lang_summary.json`: 1000-row language probe

## Resource dependency

- Unique remote refs in 100 rows: `300`
- Remote refs probed: `80`
- Probe success: `74` / `80` = `92.5%`
- Probe failed: `6`
- Relative/root refs: `224`
- Data URI refs: `15`

Relative/root refs cannot be fetched reliably because WebCode2M rows do not expose the original page base URL.

### Failed remote probes

- row `1` status `404` error `HTTPError: 404`: `http://www.linkwithin.com/pixel.png`
- row `10` status `403` error `HTTPError: 403`: `https://cms.podcastit.me/wp-content/uploads/2019/09/siltala-television-lapset-tunnus-1920x1080.jpg`
- row `15` status `404` error `HTTPError: 404`: `https://heightsbymarstonlakeapts.com/wp-content/uploads/2017/02/swimming-pool-5-300x225.jpg`
- row `20` status `None` error `URLError: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1028)>`: `https://www.syr.se/wp-content/uploads/2016/12/cropped-icon_huvud.jpg`
- row `22` status `404` error `HTTPError: 404`: `https://www.retter-radio.de/images/sponsor/web_logo88a.gif`
- row `27` status `404` error `HTTPError: 404`: `https://www.googletagmanager.com/ns.html?id=GTM-TMS57V`

## Language mix

Downloaded first 100 rows: zh 2%, en 51%, non-zh/en 47%.

Offset-sampled 1000 rows across the dataset:
- zh: `38` / `1000` = `3.8%`
- en: `510` / `1000` = `51.0%`
- non-zh/en: `452` / `1000` = `45.2%`

Top languages in 1000-row probe:
- `en`: `510`
- `ru`: `57`
- `de`: `52`
- `es`: `47`
- `fr`: `45`
- `zh`: `38`
- `ja`: `34`
- `bg`: `34`
- `it`: `29`
- `nl`: `26`
- `pt`: `22`
- `tr`: `20`

## Suitability for seven task construction

WebCode2M is usable as a source pool, but not directly as final seven-task training data for this project.

Main blockers:

- It is mostly single-page static HTML text plus screenshot/layout fields, not a complete clean project directory.
- Many rows contain remote or root-relative image/icon references; some dataset screenshots already show missing resources.
- Original base URL is not exposed, so root-relative assets like `/img/logo.png` cannot be recovered reliably.
- It lacks multi-page structure and local asset folders required by our generation/edit/repair schema.
- Language distribution is broad; Chinese-only or zh/en-focused training needs filtering or stratified sampling.

Recommended use:

- Use `image + text + bbox + score + lang` as candidate source rows.
- Filter by language, score, screenshot quality, text length, and resource dependency severity.
- Convert each accepted row into a local project directory with `index.html` and `assets/`.
- Download accessible important resources; replace failed/tracking/tiny icon resources with deterministic local SVG/icon placeholders.
- Run offline Playwright render verification before admitting rows into training.


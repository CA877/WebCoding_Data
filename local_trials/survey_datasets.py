"""
Survey HuggingFace datasets containing HTML/CSS web page data.
Fetches info and sample rows from each dataset, assesses HTML quality.
"""

import requests
import json
import os
from datetime import datetime

HF_ENDPOINT = "https://hf-mirror.com"
ROWS_API_BASE = HF_ENDPOINT.replace("https://hf-mirror.com", "https://datasets-server.huggingface.co")
# Actually the datasets-server doesn't have a mirror, use direct with proxy
ROWS_API_BASE = "https://datasets-server.huggingface.co"

PROXIES = {
    "http": "socks5h://127.0.0.1:13659",
    "https": "socks5h://127.0.0.1:13659",
}

DATASETS = [
    {
        "name": "HuggingFaceM4/WebSight",
        "description": "Synthetic HTML from LLMs (v0.2)",
        "config_hint": "v0.2",
    },
    {
        "name": "bigcode/the-stack",
        "description": "The Stack - look for HTML subset",
        "config_hint": "html",
    },
    {
        "name": "SALT-NLP/Design2Code",
        "description": "Design2Code benchmark data",
        "config_hint": None,
    },
    {
        "name": "Yuxiang-Luo/WebUIBench",
        "description": "Web UI benchmark",
        "config_hint": None,
    },
]

OUTPUT_PATH = "/Users/apple/Documents/code/WebCoding_Data/local_trials/dataset_survey.md"


def get_dataset_info(dataset_name):
    """Fetch dataset info (configs, splits, sizes)."""
    url = f"{ROWS_API_BASE}/info?dataset={dataset_name}"
    try:
        resp = requests.get(url, proxies=PROXIES, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": f"HTTP {resp.status_code}", "body": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)}


def get_dataset_configs(dataset_name):
    """Try the /splits endpoint to discover configs and splits."""
    url = f"{ROWS_API_BASE}/splits?dataset={dataset_name}"
    try:
        resp = requests.get(url, proxies=PROXIES, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": f"HTTP {resp.status_code}", "body": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)}


def get_rows(dataset_name, config, split, offset=0, length=1):
    """Fetch rows from the dataset."""
    url = f"{ROWS_API_BASE}/rows?dataset={dataset_name}&config={config}&split={split}&offset={offset}&length={length}"
    try:
        resp = requests.get(url, proxies=PROXIES, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        else:
            return {"error": f"HTTP {resp.status_code}", "body": resp.text[:500]}
    except Exception as e:
        return {"error": str(e)}


def find_html_field(row):
    """Find field(s) containing HTML content in a row."""
    html_fields = {}
    for key, value in row.items():
        if isinstance(value, str) and (
            "<html" in value.lower()
            or "<!doctype" in value.lower()
            or "<div" in value.lower()
            or "<style" in value.lower()
        ):
            html_fields[key] = value
    return html_fields


def assess_html(html_content):
    """Assess HTML quality."""
    assessment = {}
    html_lower = html_content.lower()

    assessment["length"] = len(html_content)
    assessment["has_doctype"] = "<!doctype" in html_lower
    assessment["has_html_tag"] = "<html" in html_lower
    assessment["has_head"] = "<head" in html_lower
    assessment["has_body"] = "<body" in html_lower
    assessment["has_style_tag"] = "<style" in html_lower
    assessment["has_inline_style"] = 'style="' in html_lower
    assessment["has_external_css"] = 'rel="stylesheet"' in html_lower or "link rel=" in html_lower
    assessment["has_remote_images"] = "http://" in html_content or "https://" in html_content
    assessment["has_script"] = "<script" in html_lower
    assessment["self_contained"] = (
        not assessment["has_external_css"]
        and (assessment["has_style_tag"] or assessment["has_inline_style"])
    )

    return assessment


def survey_dataset(ds_info):
    """Survey a single dataset."""
    name = ds_info["name"]
    result = {
        "name": name,
        "description": ds_info["description"],
        "info": None,
        "configs": None,
        "sample_row": None,
        "html_assessment": None,
        "errors": [],
    }

    print(f"\n{'='*60}")
    print(f"Surveying: {name}")
    print(f"{'='*60}")

    # Step 1: Get splits/configs
    print(f"  Fetching splits...")
    splits_data = get_dataset_configs(name)
    result["configs"] = splits_data

    if "error" in splits_data:
        print(f"  Error getting splits: {splits_data['error']}")
        result["errors"].append(f"splits: {splits_data['error']}")
    else:
        splits_list = splits_data.get("splits", [])
        print(f"  Found {len(splits_list)} split(s)")
        for s in splits_list[:10]:
            print(f"    - {s.get('dataset')}/{s.get('config')}/{s.get('split')}")

    # Step 2: Get info
    print(f"  Fetching info...")
    info_data = get_dataset_info(name)
    result["info"] = info_data

    if "error" in info_data:
        print(f"  Error getting info: {info_data['error']}")
        result["errors"].append(f"info: {info_data['error']}")
    else:
        # Extract dataset size info
        dataset_info = info_data.get("dataset_info", {})
        for config_name, config_info in dataset_info.items():
            num_rows = config_info.get("splits", {})
            print(f"  Config '{config_name}': splits = {json.dumps({k: v.get('num_examples', v.get('num_rows', '?')) for k, v in num_rows.items()}) if isinstance(num_rows, dict) else num_rows}")

    # Step 3: Fetch a sample row
    # Determine config and split to use
    config = ds_info.get("config_hint") or "default"
    split = "train"

    # Try to use actual config from splits data
    if "error" not in splits_data:
        splits_list = splits_data.get("splits", [])
        if splits_list:
            # Prefer config matching hint
            hint = ds_info.get("config_hint")
            chosen = None
            if hint:
                for s in splits_list:
                    if hint.lower() in s.get("config", "").lower():
                        chosen = s
                        break
            if not chosen:
                chosen = splits_list[0]
            config = chosen.get("config", "default")
            split = chosen.get("split", "train")

    print(f"  Fetching row from config='{config}', split='{split}'...")
    rows_data = get_rows(name, config, split, offset=0, length=2)

    if "error" in rows_data:
        print(f"  Error getting rows: {rows_data['error']}")
        result["errors"].append(f"rows: {rows_data['error']}")
        # Try alternate config
        if config != "default":
            print(f"  Retrying with config='default'...")
            rows_data = get_rows(name, "default", split, offset=0, length=2)
            if "error" in rows_data:
                print(f"  Still failed: {rows_data['error']}")

    if "error" not in rows_data:
        rows = rows_data.get("rows", [])
        if rows:
            row = rows[0].get("row", rows[0])
            result["fields"] = list(row.keys())
            print(f"  Fields: {result['fields']}")

            # Find HTML content
            html_fields = find_html_field(row)
            if html_fields:
                for field_name, html_content in html_fields.items():
                    print(f"  HTML field: '{field_name}' ({len(html_content)} chars)")
                    print(f"  First 300 chars: {html_content[:300]}")
                    assessment = assess_html(html_content)
                    print(f"  Assessment: {json.dumps(assessment, indent=2)}")
                    result["html_assessment"] = {
                        "field": field_name,
                        "assessment": assessment,
                        "preview": html_content[:500],
                    }
            else:
                print(f"  No HTML field found. Field previews:")
                for key, value in row.items():
                    preview = str(value)[:200] if value else "(empty)"
                    print(f"    {key}: {preview}")
                result["sample_preview"] = {k: str(v)[:200] for k, v in row.items()}

            # Check num_rows from response
            num_rows_total = rows_data.get("num_rows_total")
            if num_rows_total:
                result["num_rows_total"] = num_rows_total
                print(f"  Total rows: {num_rows_total}")

    return result


def generate_report(results):
    """Generate markdown report."""
    lines = []
    lines.append("# HuggingFace Dataset Survey for Web Code Generation Training")
    lines.append(f"\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("\n## Summary\n")
    lines.append("| Dataset | Rows | Self-contained HTML | Inline CSS | Quality |")
    lines.append("|---------|------|--------------------:|:----------:|---------|")

    for r in results:
        rows = r.get("num_rows_total", "?")
        if r.get("html_assessment"):
            a = r["html_assessment"]["assessment"]
            self_cont = "Yes" if a.get("self_contained") else "No"
            inline = "Yes" if a.get("has_inline_style") or a.get("has_style_tag") else "No"
            quality = "Good" if a.get("self_contained") and a.get("has_html_tag") else "Partial"
        else:
            self_cont = "N/A"
            inline = "N/A"
            quality = "No HTML found" if not r.get("errors") else "Error"
        lines.append(f"| {r['name']} | {rows} | {self_cont} | {inline} | {quality} |")

    lines.append("\n---\n")

    for r in results:
        lines.append(f"## {r['name']}")
        lines.append(f"\n**Description:** {r['description']}\n")

        if r.get("errors"):
            lines.append(f"**Errors:** {'; '.join(r['errors'])}\n")

        if r.get("num_rows_total"):
            lines.append(f"**Total rows:** {r['num_rows_total']:,}\n")

        # Config/splits info
        if r.get("configs") and "error" not in r["configs"]:
            splits = r["configs"].get("splits", [])
            if splits:
                lines.append("**Available configs/splits:**\n")
                for s in splits[:15]:
                    lines.append(f"- `{s.get('config', '?')}` / `{s.get('split', '?')}`")
                if len(splits) > 15:
                    lines.append(f"- ... and {len(splits) - 15} more")
                lines.append("")

        if r.get("fields"):
            lines.append(f"**Fields:** `{'`, `'.join(r['fields'])}`\n")

        if r.get("html_assessment"):
            ha = r["html_assessment"]
            a = ha["assessment"]
            lines.append("**HTML Assessment:**\n")
            lines.append(f"- Field name: `{ha['field']}`")
            lines.append(f"- Content length: {a['length']:,} chars")
            lines.append(f"- Has DOCTYPE: {a['has_doctype']}")
            lines.append(f"- Has `<html>` tag: {a['has_html_tag']}")
            lines.append(f"- Has `<head>`: {a['has_head']}")
            lines.append(f"- Has `<body>`: {a['has_body']}")
            lines.append(f"- Has `<style>` tag: {a['has_style_tag']}")
            lines.append(f"- Has inline style: {a['has_inline_style']}")
            lines.append(f"- Has external CSS links: {a['has_external_css']}")
            lines.append(f"- Has remote images: {a['has_remote_images']}")
            lines.append(f"- Has `<script>`: {a['has_script']}")
            lines.append(f"- **Self-contained: {a['self_contained']}**")
            lines.append(f"\n**HTML Preview (first 500 chars):**\n")
            lines.append(f"```html\n{ha['preview']}\n```\n")

        elif r.get("sample_preview"):
            lines.append("**Sample row preview (no HTML detected):**\n")
            for k, v in r["sample_preview"].items():
                lines.append(f"- `{k}`: {v[:150]}")
            lines.append("")

        lines.append("\n---\n")

    # Final recommendations
    lines.append("## Recommendations\n")
    lines.append("Based on this survey, datasets suitable for web code generation training should have:")
    lines.append("1. Self-contained HTML (inline or embedded CSS, no external stylesheet links)")
    lines.append("2. Complete HTML structure (doctype, html, head, body)")
    lines.append("3. Large number of diverse samples")
    lines.append("4. Minimal remote resource dependencies (images can be localized)\n")

    return "\n".join(lines)


if __name__ == "__main__":
    results = []
    for ds in DATASETS:
        result = survey_dataset(ds)
        results.append(result)

    report = generate_report(results)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n\nReport saved to: {OUTPUT_PATH}")
    print(f"{'='*60}")
    print("DONE")

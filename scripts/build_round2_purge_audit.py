#!/usr/bin/env python3
"""Build a conservative, full-site purge audit from second-pass signals."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


PARKING = re.compile(
    r"parklogic\.com|sedoparking\.com|domainmarket\.com|buy this domain|domain (?:is )?for sale|related searches",
    re.I,
)
DOORWAY_DOMAIN = re.compile(r"locksmith|garage.?door|acrepair|restorationcompany", re.I)
EXPLICIT_DOMAIN = re.compile(
    r"porn|escort|hookup|casino|poker|betting|sexcam|sexcams|sexy|odd-sex|"
    r"sexacademy|sexfromthecenter|greatsexguidance|cannabis|marijuana|weed4y|"
    r"gunstores|gunrights",
    re.I,
)
LOAN_ALLOWLIST = {"www.consumerfinance.gov", "wallethub.com", "www.savvynewcanadians.com"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--quality-audit", type=Path, required=True)
    parser.add_argument("--template-clusters", type=Path, required=True)
    parser.add_argument("--parking-sites", type=Path,
                        help="Optional newline-delimited site names found by a bulk content search.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    quality = {row["site"]: row for row in map(json.loads, args.quality_audit.open())}
    parking_sites = set(args.parking_sites.read_text().splitlines()) if args.parking_sites else set()
    clusters = json.loads(args.template_clusters.read_text())
    bad_template_sites: set[str] = set()
    for cluster in clusters:
        names = cluster["sites"]
        if (
            all("sitematerials" in name.lower() for name in names)
            or all(re.search(r"cars?.*for.?sale|cars?-forsale|trucks?-forsale|camper-forsale", name, re.I) for name in names)
            or all(re.search(r"date.*singles", name, re.I) for name in names)
        ):
            bad_template_sites.update(names)

    rows = []
    reason_counts: Counter[str] = Counter()
    for site in sorted(path for path in args.root.iterdir() if path.is_dir()):
        item = quality[site.name]
        signals = item.get("signals", {})
        reasons = []
        if site.name in parking_sites:
            reasons.append("parked_or_for_sale_domain")
        if "very_long_mostly_blank_screenshot" in signals:
            reasons.append("broken_long_blank_render")
        if "dominant_gray_placeholder" in signals:
            reasons.append("dominant_gray_placeholder")
        if DOORWAY_DOMAIN.search(site.name) and signals.get("multiple_missing_local_resources"):
            reasons.append("templated_local_service_doorway")
        if site.name in bad_template_sites:
            reasons.append("duplicated_doorway_template_cluster")
        if signals.get("spam_topic_across_pages:gambling"):
            reasons.append("gambling_across_pages")
        if signals.get("repeated_spam_topic:essay") or signals.get("spam_topic_across_pages:essay", 0) >= 3:
            reasons.append("essay_service_spam")
        if signals.get("repeated_spam_topic:pills"):
            reasons.append("pill_sales_spam")
        if signals.get("repeated_spam_topic:loans", 0) >= 3 and site.name not in LOAN_ALLOWLIST:
            reasons.append("payday_loan_spam")
        if EXPLICIT_DOMAIN.search(site.name):
            reasons.append("explicit_unsafe_domain")
        reasons = sorted(set(reasons))
        reason_counts.update(reasons)
        rows.append({
            "site": site.name, "status": "reject" if reasons else "pass",
            "reasons": reasons, "quality_signals": signals,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({
        "sites": len(rows), "reject": sum(row["status"] == "reject" for row in rows),
        "pass": sum(row["status"] == "pass" for row in rows), "reasons": reason_counts,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Analyze raw WebCode2M samples for render issues."""
import re
from pathlib import Path

out_dir = Path(__file__).parent / "webcode2m_raw_10"

remote_url_re = re.compile(r'https?://[^\s"\'<>)]+', re.I)
img_src_re = re.compile(r'<img[^>]*src=["\']([^"\']+)["\']', re.I)
link_css_re = re.compile(r'<link[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\']', re.I)
link_css_re2 = re.compile(r'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']stylesheet["\']', re.I)
script_src_re = re.compile(r'<script[^>]*src=["\']([^"\']+)["\']', re.I)
style_block_re = re.compile(r'<style[^>]*>(.*?)</style>', re.DOTALL | re.I)
css_url_re = re.compile(r'url\(["\']?(https?://[^"\')\\s]+)["\']?\)', re.I)
bg_img_re = re.compile(r'background(?:-image)?\s*:\s*url\(["\']?([^"\')\s]+)["\']?\)', re.I)

print("=" * 80)
print("WebCode2M Raw Sample Render Analysis")
print("=" * 80)

total_issues = {"remote_css": 0, "remote_img": 0, "broken_relative_img": 0,
                "remote_script": 0, "css_url_remote": 0, "no_css": 0}

for html_path in sorted(out_dir.glob("sample_*.html")):
    content = html_path.read_text(encoding="utf-8")

    all_remote = remote_url_re.findall(content)

    img_srcs = img_src_re.findall(content)
    remote_imgs = [s for s in img_srcs if s.startswith("http")]
    relative_imgs = [s for s in img_srcs if not s.startswith("http") and not s.startswith("data:")]
    data_imgs = [s for s in img_srcs if s.startswith("data:")]

    css_links = link_css_re.findall(content) + link_css_re2.findall(content)
    remote_css = [s for s in css_links if s.startswith("http")]

    script_srcs = script_src_re.findall(content)
    remote_scripts = [s for s in script_srcs if s.startswith("http")]

    style_blocks = style_block_re.findall(content)
    total_css_len = sum(len(s) for s in style_blocks)

    css_remote_urls = css_url_re.findall(content)

    bg_imgs = bg_img_re.findall(content)
    remote_bg = [b for b in bg_imgs if b.startswith("http")]

    print(f"\n--- {html_path.name} ({len(content):,} chars) ---")
    print(f"  Inline <style>: {len(style_blocks)} blocks, {total_css_len:,} chars")
    print(f"  Remote <link> CSS: {len(remote_css)}")
    if remote_css:
        for c in remote_css[:2]:
            print(f"    {c[:100]}")
    print(f"  Images: remote={len(remote_imgs)}, relative={len(relative_imgs)}, data-uri={len(data_imgs)}")
    if remote_imgs:
        for im in remote_imgs[:2]:
            print(f"    {im[:100]}")
    if relative_imgs:
        for im in relative_imgs[:3]:
            print(f"    {im}")
    print(f"  Remote <script>: {len(remote_scripts)}")
    print(f"  CSS url(http): {len(css_remote_urls)}")
    if css_remote_urls:
        for u in css_remote_urls[:2]:
            print(f"    {u[:100]}")
    print(f"  Background-image remote: {len(remote_bg)}")
    print(f"  Total remote URLs: {len(all_remote)}")

    issues = []
    if remote_css:
        issues.append(f"{len(remote_css)} remote CSS")
        total_issues["remote_css"] += len(remote_css)
    if remote_imgs:
        issues.append(f"{len(remote_imgs)} remote img")
        total_issues["remote_img"] += len(remote_imgs)
    if relative_imgs:
        issues.append(f"{len(relative_imgs)} broken relative img")
        total_issues["broken_relative_img"] += len(relative_imgs)
    if remote_scripts:
        issues.append(f"{len(remote_scripts)} remote script")
        total_issues["remote_script"] += len(remote_scripts)
    if css_remote_urls:
        issues.append(f"{len(css_remote_urls)} CSS url(http)")
        total_issues["css_url_remote"] += len(css_remote_urls)
    if not style_blocks and not remote_css:
        issues.append("NO CSS")
        total_issues["no_css"] += 1

    if issues:
        print(f"  ** ISSUES: {' | '.join(issues)}")
    else:
        print(f"  OK: self-contained")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
for k, v in total_issues.items():
    print(f"  {k}: {v}")
print("\nVerdict: These raw samples CANNOT render offline without cleaning.")

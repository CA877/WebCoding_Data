#!/usr/bin/env python3
"""Sample-level Pipeline C preprocessing for WebCode2M.

Pipeline C reuses Pipeline B's scheduling, timeout, resume, and postprocess
logic, but changes the crawl policy:

- keep confirmed third-party JS/CSS as external CDN links;
- keep site/authored JS and CSS as captured code;
- preserve Pipeline B behavior everywhere else.
"""

from __future__ import annotations

from pathlib import Path

import pipeline_b_sample_level as pipeline_b
from playwright_crawl import crawl_site as _crawl_site


def crawl_site_pipeline_c(
    url: str,
    output_dir: Path,
    browser,
    session,
    max_pages: int = 4,
    wait_ms: int = 3000,
    subpage_wait_ms: int = 2000,
    timeout_ms: int = 20000,
    code_resources_only: bool = False,
) -> dict:
    return _crawl_site(
        url,
        output_dir,
        browser,
        session,
        max_pages=max_pages,
        wait_ms=wait_ms,
        subpage_wait_ms=subpage_wait_ms,
        timeout_ms=timeout_ms,
        code_resources_only=code_resources_only,
        preserve_third_party_external=True,
        slim_inline_css=True,
    )


def main() -> None:
    pipeline_b.PIPELINE_NAME = "c"
    pipeline_b.crawl_site = crawl_site_pipeline_c
    pipeline_b.main()


if __name__ == "__main__":
    main()

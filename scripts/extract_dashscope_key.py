#!/usr/bin/env python3
"""Extract the DashScope key from the existing API document without persisting it."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> None:
    document = Path(sys.argv[1])
    text = "\n".join(page.extract_text() or "" for page in PdfReader(document).pages)
    match = re.search(r"sk-[A-Za-z0-9_-]{20,}", text)
    if not match:
        raise SystemExit("DashScope key not found in API document")
    print(match.group(0))


if __name__ == "__main__":
    main()

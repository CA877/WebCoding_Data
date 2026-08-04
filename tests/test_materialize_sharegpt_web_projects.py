import json
from pathlib import Path

import pytest

from scripts.materialize_sharegpt_web_projects import (
    assistant_answer,
    parse_project_files,
    safe_instance_id,
    safe_relative_file,
)


def test_parse_multiple_headed_fences_preserves_code() -> None:
    answer = """# index.html
```html
<!doctype html><link rel="stylesheet" href="styles.css">
```

## styles.css
```css
body { color: red; }
```

# app.js
```javascript
console.log("ok");
```
"""
    files = parse_project_files(answer)
    assert [item["path"] for item in files] == ["index.html", "styles.css", "app.js"]
    assert files[1]["code"] == "body { color: red; }\n"


def test_rejects_path_traversal_and_duplicate_files() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        safe_relative_file("../index.html")
    with pytest.raises(ValueError, match="duplicate"):
        parse_project_files(
            "# index.html\n```html\na\n```\n# index.html\n```html\nb\n```\n"
        )


def test_requires_index_and_reads_last_gpt_answer() -> None:
    with pytest.raises(ValueError, match="index.html"):
        parse_project_files("# page.html\n```html\n<p>x</p>\n```\n")
    row = {
        "conversations": [
            {"from": "human", "value": "request"},
            {"from": "gpt", "value": "answer"},
        ]
    }
    assert assistant_answer(row) == "answer"


def test_safe_instance_id() -> None:
    assert safe_instance_id("WebGen-Bench.prompt_4555") == "WebGen-Bench.prompt_4555"
    assert safe_instance_id("a/b c") == "a_b_c"

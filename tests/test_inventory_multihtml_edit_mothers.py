import gzip
import json
import sys

from reverse import inventory_multihtml_edit_mothers as inventory


def write_gzip(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def test_inventory_requires_real_multi_html_and_prefers_four_pages(tmp_path, monkeypatch):
    edit = tmp_path / "edit.jsonl.gz"
    generate = tmp_path / "generate.jsonl.gz"
    current = {
        "instruction": {"src_code": [{"path": "index.html", "code": "existing"}]},
    }
    write_gzip(edit, [current])
    single = [{"path": "index.html", "code": "single"}]
    two = [{"path": "index.html", "code": "two"}, {"path": "about.html", "code": "two"}]
    four = [
        {"path": name, "code": "four"}
        for name in ("index.html", "about.html", "docs.html", "contact.html")
    ]
    write_gzip(
        generate,
        [
            {"instance_id": "single", "response": single},
            {"instance_id": "two", "response": two},
            {"instance_id": "four", "response": four},
        ],
    )
    unpackaged = tmp_path / "unpackaged"
    unpackaged.mkdir()
    (unpackaged / "index.html").write_text("home")
    (unpackaged / "about.html").write_text("about")
    (unpackaged / "App.vue").write_text("<template><main /></template>")
    framework_files = tmp_path / "framework_files.txt"
    framework_files.write_text(str(unpackaged / "App.vue") + "\n")
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inventory",
            "--text-generate-shard", str(generate),
            "--text-edit-shard", str(edit),
            "--framework-file-list", str(framework_files),
            "--output-dir", str(output),
        ],
    )
    inventory.main()
    candidates = [json.loads(line) for line in (output / "candidate_manifest.jsonl").read_text().splitlines()]
    assert {item["html_count"] for item in candidates} == {2, 4}
    assert {item["stack"] for item in candidates} == {"vanilla", "vue"}
    selected = [json.loads(line) for line in (output / "selected_candidates.jsonl").read_text().splitlines()]
    assert selected[0]["html_count"] == 4

import gzip
import json

from reverse import remove_0921_declared_mp_single_html as remover


def write_json(path, value):
    path.write_text(json.dumps(value))


def test_stage_and_apply_remove_only_declared_mp_single_html(tmp_path):
    release = tmp_path / "0921"
    shard = release / remover.SHARD
    shard.parent.mkdir(parents=True)
    rows = [
        {
            "instance_id": "remove",
            "page_type": "mp",
            "metadata": {"instruction_status": "query_ready"},
            "instruction": {"src_code": [{"path": "index.html", "code": "one"}]},
        },
        {
            "instance_id": "keep-mp",
            "page_type": "mp",
            "metadata": {"instruction_status": "query_ready"},
            "instruction": {
                "src_code": [
                    {"path": "index.html", "code": "one"},
                    {"path": "about.html", "code": "two"},
                ]
            },
        },
        {
            "instance_id": "keep-sp",
            "page_type": "sp",
            "metadata": {"instruction_status": "query_failed"},
            "instruction": {"src_code": [{"path": "index.html", "code": "one"}]},
        },
    ]
    with gzip.open(shard, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    digest = remover.sha256(shard)
    index = {
        "tasks": {
            "text-edit": {"num_samples": 3, "sha256": digest},
            "text-generate": {"num_samples": 7},
        },
        "current_optimization": {"text_edit": {}},
    }
    write_json(release / "dataset_index.json", index)
    write_json(release / "manifest.json", {remover.SHARD: {"sha256": digest}})
    (release / "README.md").write_text("old")

    control = tmp_path / "control"
    report = remover.stage(release, control)
    assert report["removed_count"] == 1
    assert [row["instance_id"] for row in remover.read_rows(control / "staged" / remover.SHARD)] == ["keep-mp", "keep-sp"]

    applied = remover.apply(release, control)
    assert applied["status"] == "applied"
    assert [row["instance_id"] for row in remover.read_rows(shard)] == ["keep-mp", "keep-sp"]
    updated = remover.read_json(release / "dataset_index.json")
    assert updated["tasks"]["text-edit"]["num_samples"] == 2
    assert updated["tasks"]["text-edit"]["physical_html_counts"] == {"single_html": 1, "multi_html": 1}
    assert (control / "backup" / remover.SHARD).exists()

import gzip
import json

from reverse.inventory_multihtml_edit_mothers import digest_code
from reverse.materialize_edit_mother_sources import resolve


def source(number):
    return [
        {"path": name, "code": f"<html>{number}-{name}</html>"}
        for name in ("index.html", "about.html", "services.html", "contact.html")
    ]


def manifest(files, *, origins=None, container=None):
    return {
        "candidate_id": digest_code(files),
        "stack": "vanilla",
        "html_count": 4,
        "origins": origins or [],
        "lineages": [{"container": str(container)}] if container else [],
    }


def test_resolves_physical_project_and_dataset_row(tmp_path):
    physical = tmp_path / "physical"
    physical.mkdir()
    first = source(1)
    for item in first:
        (physical / item["path"]).write_text(item["code"])

    second = source(2)
    shard = tmp_path / "data.jsonl.gz"
    with gzip.open(shard, "wt") as stream:
        stream.write(json.dumps({"instruction": "plain text"}) + "\n")
        stream.write(json.dumps({"instance_id": "two", "response": second}) + "\n")

    resolved, counts, missing = resolve(
        [
            manifest(first, origins=[str(physical)]),
            manifest(second, container=shard),
        ]
    )
    assert not missing
    assert set(resolved) == {digest_code(first), digest_code(second)}
    assert counts["physical_project"] == 1
    assert counts[str(shard)] == 1

    dataset_only, dataset_counts, missing = resolve(
        [manifest(second, origins=[str(physical)], container=shard)],
        allow_physical=False,
    )
    assert not missing
    assert set(dataset_only) == {digest_code(second)}
    assert "physical_project" not in dataset_counts


def test_prefers_0921_lineage_over_previous_release(tmp_path):
    files = source(3)
    shards = []
    for release in ("0905", "0921"):
        shard = tmp_path / "releases" / release / "text-generate" / "train.jsonl.gz"
        shard.parent.mkdir(parents=True)
        with gzip.open(shard, "wt") as stream:
            stream.write(json.dumps({"instance_id": release, "response": files}) + "\n")
        shards.append(shard)
    item = manifest(files)
    item["lineages"] = [{"container": str(path)} for path in shards]
    resolved, _, missing = resolve([item], allow_physical=False)
    assert not missing
    assert "/releases/0921/text-generate/" in resolved[digest_code(files)]["container"]

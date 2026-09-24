import json

from reverse.inventory_multihtml_edit_mothers import digest_code
from reverse.plan_0921_edit_mothers import plan_allocation


def code(name="index.html"):
    return [{"path": name, "code": f"<html>{name}</html>"}]


def row(identity, files, stack_name="vanilla"):
    source = list(files)
    if stack_name == "react":
        source.append(
            {
                "path": "package.json",
                "code": json.dumps({"dependencies": {"react": "1"}}),
            }
        )
    return {
        "instance_id": identity,
        "page_type": "sp" if len(files) == 1 else "mp",
        "instruction": {"src_code": source, "description": [{"task_type": "x", "description": "y"}]},
        "metadata": {"instruction_status": "query_ready"},
    }


def candidate(number, html_count=4, container=None, extensions=None):
    names = ("index.html", "about.html", "services.html", "contact.html", "extra.html")[:html_count]
    files = [
        {"path": name, "code": f"<html>{number}-{name}</html>"}
        for name in names
    ]
    return {
        "candidate_id": digest_code(files),
        "stack": "vanilla",
        "html_count": html_count,
        "html_paths": [item["path"] for item in files],
        "code_chars": 100 + number,
        "file_count": 4,
        "origins": [f"project-{number}"],
        "sources": ["0921_text_generate"],
        "lineages": [{"container": container}] if container else [],
        "source_extensions": extensions or [".html", ".css", ".js"],
    }


def test_preserves_existing_queries_and_balances_reuse():
    current = [
        row("sp-react", code(), "react"),
        row("sp-vanilla", code()),
        row("mp", code("index.html") + code("about.html")),
    ]
    preserved, assignments, summary = plan_allocation(
        current,
        [candidate(1), candidate(2)],
        target_total=6,
        target_sp=2,
        target_mp=4,
        preferred_stack="vanilla",
        preferred_html_count=4,
        max_reuse=2,
    )
    assert len(preserved) == 3
    assert len(assignments) == 3
    assert [item["reuse_index"] for item in assignments] == [1, 1, 2]
    assert summary["projected_page_counts"] == {"sp": 2, "mp": 4}
    assert summary["mother_usage_distribution"] == {1: 1, 2: 1}
    assert summary["projected_instruction_status_counts"] == {
        "query_ready": 3,
        "awaiting_query": 3,
    }


def test_formal_text_generate_filter_prefers_four_html_before_fallback():
    current = [
        row("sp", code()),
        row("mp", code("index.html") + code("about.html")),
    ]
    formal = "/data/releases/0921/text-generate/train.jsonl.gz"
    candidates = [
        candidate(1, 4, formal),
        candidate(2, 3, formal),
        candidate(3, 4, "/data/webpages/mothers.jsonl"),
        candidate(4, 4, formal, [".html", ".java"]),
    ]
    _, assignments, summary = plan_allocation(
        current,
        candidates,
        target_total=5,
        target_sp=1,
        target_mp=4,
        preferred_stack="vanilla",
        preferred_html_count=4,
        max_reuse=2,
        formal_text_generate_only=True,
        frontend_only=True,
    )
    assert [item["html_count"] for item in assignments] == [4, 4, 3]
    assert all("/releases/0921/text-generate/" in item["lineages"][0]["container"] for item in assignments)
    assert summary["eligible_unique_mothers"] == 2
    assert summary["assignment_html_count_counts"] == {3: 1, 4: 2}

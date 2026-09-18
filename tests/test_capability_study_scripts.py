"""能力抽取对比研究脚本的单元测试。

这里测的是**聚合算术与数据整形**（纯逻辑，不涉及 LLM 与语义判断），输入是刻意构造的
最小记录，用于锁定口径：状态分类、零卡片与弃权的区别、关联步数反解、Jaccard 重合率。
真实产物上的端到端验证在 pilot 跑完后用真实结果文件执行。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspiration_library.deep_browser_exploration import (
    compact_live_browser_evidence_for_llm,
)
from inspiration_library.utils.classify_capability_cards import card_view, collect_cards
from inspiration_library.utils.inspect_capability_inputs import render_case, resolve_source
from inspiration_library.utils.measure_webchain_interaction_breadth import breadth_stats, interactive_nodes
from inspiration_library.utils.measure_observation_coverage import (
    CAP_CONFIGS,
    adapter_control_keys,
    raw_controls,
)
# summarize_capability_study 也有个 render_report，这里显式改名避免被它盖掉
from inspiration_library.utils.measure_observation_coverage import render_report as render_coverage_report
from inspiration_library.utils.rank_webchain_candidates import candidate_signals, rank_key
from inspiration_library.utils.select_capability_study_pilot import pick_by_host_round_robin
from inspiration_library.utils.select_webchain_interaction_candidates import (
    rank_candidates,
    richness,
    round_robin_by_host,
)
from inspiration_library.utils.summarize_capability_study import (
    kind_stats,
    overlap_stats,
    per_bucket_stats,
    render_report,
    site_of,
    step_count,
)


def _row(bucket: str, seed_id: str, url: str, cards: list[dict], status: str = "ok") -> dict:
    return {"status": status, "bucket": bucket, "seed_id": seed_id, "entry_url": url,
            "extraction": {"capabilities": cards} if status == "ok" else None}


def _card(capability_id: str, family: str = "data_table", steps: list[int] | None = None,
          user_actions: list[str] | None = None) -> dict:
    return {
        "capability_id": capability_id,
        "family": family,
        "user_actions": user_actions if user_actions is not None else ["click"],
        "observation_evidence": [{"state_id": f"traj__step_{i}", "evidence": "e"} for i in (steps or [])],
    }


def test_site_of_handles_missing_url():
    assert site_of("https://www.example.com/a/b") == "www.example.com"
    assert site_of("") == ""
    assert site_of(None) == ""


def test_step_count_counts_distinct_referenced_steps():
    card = _card("c1", steps=[1, 1, 3])
    assert step_count(card) == 2
    assert step_count(_card("c2", steps=[])) == 0


def test_per_bucket_separates_abstention_from_failure():
    rows = [
        _row("b", "s1", "https://a.com/", [_card("c1", steps=[1, 2])]),
        _row("b", "s2", "https://a.com/", []),                      # 弃权：ok 但 0 张卡
        _row("b", "s3", "https://a.com/", [], status="error"),      # 失败：不计入
        _row("b", "s4", "https://a.com/", [], status="no_evidence"),
    ]
    stats = per_bucket_stats(rows)["b"]
    assert stats["n_rows"] == 4
    assert stats["n_ok_trajectories"] == 2
    assert stats["n_cards"] == 1
    assert stats["trajectories_with_zero_cards"] == 1
    assert stats["zero_card_rate"] == 0.5
    assert stats["cards_per_trajectory_mean"] == 0.5
    assert stats["status_counts"] == {"ok": 2, "error": 1, "no_evidence": 1}


def test_overlap_uses_jaccard_within_same_host(tmp_path: Path):
    rows = [
        _row("b", "s1", "https://shop.example.com/a", [_card("c1")]),
        _row("b", "s2", "https://shop.example.com/b", [_card("c2")]),
        _row("b", "s3", "https://other.example.com/", [_card("c3")]),
    ]
    # s1 与 s2 共享 cluster X，各自还有独有 cluster
    (tmp_path / "capability_clusters.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"card_uid": "u1", "cluster_id": "X", "bucket": "b", "seed_id": "s1"},
        {"card_uid": "u1b", "cluster_id": "Y", "bucket": "b", "seed_id": "s1"},
        {"card_uid": "u2", "cluster_id": "X", "bucket": "b", "seed_id": "s2"},
        {"card_uid": "u3", "cluster_id": "Z", "bucket": "b", "seed_id": "s3"},
    ]) + "\n", encoding="utf-8")

    overlap = overlap_stats(tmp_path, rows)
    # 同站只有 s1/s2 一对：{X,Y} vs {X} -> 1/2
    assert overlap["overall"] == {"n_pairs": 1, "mean_jaccard": 0.5,
                                  "median_jaccard": 0.5, "shared_any_rate": 1.0}
    assert overlap["n_sites_with_multiple_trajectories"] == 1


def test_overlap_skips_trajectories_without_cards(tmp_path: Path):
    rows = [
        _row("b", "s1", "https://a.com/1", [_card("c1")]),
        _row("b", "s2", "https://a.com/2", []),
    ]
    (tmp_path / "capability_clusters.jsonl").write_text(json.dumps(
        {"card_uid": "u1", "cluster_id": "X", "bucket": "b", "seed_id": "s1"}) + "\n",
        encoding="utf-8")
    overlap = overlap_stats(tmp_path, rows)
    assert overlap["overall"]["n_pairs"] == 0
    assert overlap["overall"]["mean_jaccard"] is None


def test_overlap_reports_missing_cluster_file(tmp_path: Path):
    assert overlap_stats(tmp_path, [])["available"] is False


def test_kind_stats_computes_shares(tmp_path: Path):
    rows = [{"seed_id": "s1"}]
    (tmp_path / "card_kinds.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"card_uid": "u1", "bucket": "b", "seed_id": "s1", "status": "ok",
         "interaction_kind": "transferable_product_interaction", "family": "data_table"},
        {"card_uid": "u2", "bucket": "b", "seed_id": "s1", "status": "ok",
         "interaction_kind": "navigation_or_information_gathering", "family": "data_table"},
        {"card_uid": "u3", "bucket": "b", "seed_id": "s1", "status": "ok",
         "interaction_kind": "presentation_only", "family": "page_transitions"},
        {"card_uid": "u4", "bucket": "b", "seed_id": "s1", "status": "error"},
    ]) + "\n", encoding="utf-8")
    stats = kind_stats(tmp_path, rows)
    assert stats["n_classified"] == 3
    assert stats["n_unclassified"] == 1
    bucket = stats["per_bucket"]["b"]
    assert bucket["total"] == 3
    assert bucket["product_share"] == 0.333
    assert stats["family_cross_tab"]["data_table"] == {
        "transferable_product_interaction": 1, "navigation_or_information_gathering": 1}


def test_render_report_renders_caveats_and_table():
    rows = [_row("b", "s1", "https://a.com/", [_card("c1")])]
    payload = {
        "per_bucket": per_bucket_stats(rows),
        "kinds": {"available": False, "note": "missing"},
        "overlap": {"available": False, "note": "missing"},
        "unique": {"available": False, "note": "missing"},
        "caveats": ["长度分层是代理指标"],
    }
    report = render_report(payload)
    assert "长度分层是代理指标" in report
    assert "| b | 1 | 1 | 1 |" in report


def test_render_report_states_navigation_residual_bias_when_classified():
    rows = [_row("b", "s1", "https://a.com/", [_card("c1")])]
    payload = {
        "per_bucket": per_bucket_stats(rows),
        "kinds": {"available": True, "n_classified": 1, "n_unclassified": 0, "per_bucket": {
            "b": {"total": 1, "navigation_or_information_gathering": 0,
                  "transferable_product_interaction": 1, "presentation_only": 0,
                  "product_share": 1.0, "navigation_share": 0.0}},
            "family_cross_tab": {}},
        "overlap": {"available": False, "note": "missing"},
        "unique": {"available": False, "note": "missing"},
        "caveats": [],
    }
    report = render_report(payload)
    assert "卡片层的导航占比是残差" in report


def test_collect_cards_skips_failed_rows_and_keeps_provenance(tmp_path: Path):
    (tmp_path / "webchain.jsonl").write_text("\n".join(json.dumps(r) for r in [
        _row("webchain", "s1", "https://a.com/", [_card("cap_1")]),
        _row("webchain", "s2", "https://a.com/", [], status="error"),
    ]) + "\n", encoding="utf-8")
    cards = collect_cards(tmp_path)
    assert len(cards) == 1
    assert cards[0]["card_uid"] == "webchain::s1::cap_1"
    assert cards[0]["bucket"] == "webchain"


def test_card_view_excludes_provenance_fields():
    view = card_view({"name": "x", "summary": "y", "family": "f", "seed_id": "s",
                      "source_url": "https://a.com/", "observation_evidence": [{"state_id": "traj__step_1"}]})
    assert "seed_id" not in view and "source_url" not in view and "observation_evidence" not in view
    assert view["name"] == "x" and view["summary"] == "y"


def test_pilot_selection_spreads_across_hosts():
    hosts = {
        "h1": [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}],
        "h2": [{"id": "b1"}],
        "h3": [{"id": "c1"}, {"id": "c2"}],
    }
    picked = pick_by_host_round_robin([], 4, hosts)
    assert [row["id"] for row in picked] == ["a1", "b1", "c1", "a2"]


def _node(node_id: str, role: str, name: str, tag: str = "") -> dict:
    attrs = {"data-imean-axt-id": node_id}
    if tag:
        attrs["html_tag"] = tag
    return {"role": role, "name": name, "attributes": attrs, "children": []}


def _tree() -> dict:
    return {"role": "generic", "name": "", "children": [
        _node("131", "button", "Find a hotel", "button"),
        _node("57", "textbox", "Search destinations", "input"),
        _node("88", "spinbutton", "Adults", "input"),
        _node("9", "heading", "Deals", "h2"),          # 非交互 role，不进 present
    ]}


def _step(action: str, role: str = "", tag: str = "") -> dict:
    data: dict = {}
    if role:
        data["role"] = role
    if tag:
        data["node"] = {"name": tag}
    return {"type": action, "attributes": {"data": data}}


def test_candidate_signals_counts_roles_tags_and_non_click_actions():
    traj = {"steps": [
        _step("launchApp"),
        _step("click", "button", "BUTTON"),
        _step("click", "button", "BUTTON"),
        _step("type", "combobox", "INPUT"),
        _step("select", "option", "SELECT"),
        _step("click", "presentation", "DIV"),        # 非交互 role 不计入
    ]}
    sig = candidate_signals(traj)
    assert sig["roles_touched"] == ["button", "combobox", "option"]
    assert sig["signal_tags_touched"] == ["input", "select"]
    assert sig["n_non_click_actions"] == 2            # type + select（launchApp 不算）
    assert sig["n_interaction_steps"] == 5
    assert sig["stateful_roles_touched"] == ["combobox", "option"]


def test_candidate_signals_skips_steps_without_metadata():
    sig = candidate_signals({"steps": [{"type": "click"}, {"type": "hover"}]})
    assert sig["roles_touched"] == [] and sig["tags_touched"] == []
    assert sig["n_non_click_actions"] == 1            # hover 仍算非点击动作


def test_rank_key_prefers_wider_roles_then_tags():
    wide = {"n_roles_touched": 3, "n_signal_tags_touched": 1,
            "n_non_click_actions": 1, "n_interaction_steps": 5}
    narrow = {"n_roles_touched": 1, "n_signal_tags_touched": 4,
              "n_non_click_actions": 4, "n_interaction_steps": 99}
    assert rank_key(wide) > rank_key(narrow)


def _index_row(traj_id: str, host: str, action_types: dict, steps: int) -> dict:
    return {"traj_id": traj_id, "primary_host": host, "action_types": action_types,
            "n_interaction_steps": steps, "src_file": f"{traj_id}.json"}


def test_richness_counts_only_stateful_action_kinds():
    row = _index_row("t", "h", {"launchApp": 1, "click": 9, "type": 2, "select": 1, "hover": 3}, 12)
    assert richness(row) == (2, 12)          # hover 不算状态化动作


def test_rank_candidates_filters_and_orders_by_richness():
    rows = [
        _index_row("a", "h1", {"click": 9, "type": 1}, 9),                        # 步数不足
        _index_row("b", "h1", {"click": 9, "type": 1}, 20),                       # 只有 1 种状态化
        _index_row("c", "h1", {"click": 9, "type": 1, "select": 1}, 12),
        _index_row("d", "h2", {"click": 9, "type": 1, "select": 1, "drag": 1}, 12),
    ]
    assert [r["traj_id"] for r in rank_candidates(rows)] == ["d", "c"]


def test_round_robin_spreads_across_hosts():
    rows = [_index_row(f"a{i}", "h1", {}, 0) for i in range(3)] + \
           [_index_row(f"b{i}", "h2", {}, 0) for i in range(2)]
    picked = round_robin_by_host(rows, 4)
    assert [r["traj_id"] for r in picked] == ["a0", "b0", "a1", "b1"]


def test_round_robin_stops_when_pool_is_exhausted():
    rows = [_index_row("a0", "h1", {}, 0), _index_row("b0", "h2", {}, 0)]
    assert len(round_robin_by_host(rows, 10)) == 2


def test_interactive_nodes_keeps_roles_and_tags_only_for_interactive():
    nodes = interactive_nodes(_tree())
    assert nodes["131"] == {"role": "button", "tag": "button"}
    assert nodes["57"] == {"role": "textbox", "tag": "input"}
    assert "9" not in nodes          # heading 不是可交互 role
    assert len(nodes) == 3


def test_breadth_stats_separates_touched_from_untouched():
    traj = {"id": "T1", "title": "book a hotel", "steps": [
        {"type": "launchApp", "axtId": None},
        {"type": "click", "axtId": "131", "host": "www.example.com",
         "attributes": {"data": {"node": {"name": "BUTTON"}}}},
        {"type": "click", "axtId": "88"},
    ]}
    stats = breadth_stats(traj, {"1": {"ax_tree": _tree()}, "2": {"ax_tree": _tree()}})
    assert stats["roles_present"] == ["button", "spinbutton", "textbox"]
    assert stats["roles_touched"] == ["button", "spinbutton"]
    assert stats["roles_untouched"] == ["textbox"]      # 页面上有、但没被点
    assert stats["n_states"] == 2
    assert stats["n_matched_by_axtid"] == 2 and stats["n_matched_by_label"] == 0
    assert stats["n_controls_observed"] == 6                   # 3 个控件 × 2 个状态
    assert stats["tags_present"] == ["button", "input"]
    assert stats["tags_touched"] == ["button"]                 # 只有步 1 带了 attributes
    assert stats["primary_host"] == "www.example.com"
    assert stats["action_types"] == {"click": 2, "launchApp": 1}


def test_breadth_stats_falls_back_to_exact_label_match():
    # 7/10 个站点不填 axtId，退回按同状态内标签完全相等对齐
    traj = {"id": "T2", "steps": [{"type": "click", "axtId": None, "value": "Adults"}]}
    stats = breadth_stats(traj, {"0": {"ax_tree": _tree()}})
    assert stats["n_matched_by_label"] == 1 and stats["n_matched_by_axtid"] == 0
    assert stats["roles_touched"] == ["spinbutton"]


def test_breadth_stats_counts_actions_whose_node_is_absent():
    traj = {"id": "T3", "steps": [{"type": "click", "axtId": "999", "value": "nowhere"}]}
    stats = breadth_stats(traj, {"0": {"ax_tree": _tree()}})
    assert stats["n_matched_by_axtid"] == 0 and stats["n_matched_by_label"] == 0
    assert stats["n_actions_unmatched"] == 1
    assert stats["roles_touched"] == []


def test_breadth_stats_flags_ambiguous_label_matches():
    tree = {"role": "generic", "name": "", "children": [
        _node("1", "button", "Done"), _node("2", "button", "Done")]}
    traj = {"id": "T4", "steps": [{"type": "click", "value": "Done"}]}
    stats = breadth_stats(traj, {"0": {"ax_tree": tree}})
    assert stats["n_actions_ambiguous"] == 1 and stats["n_matched_by_label"] == 1


def test_breadth_stats_ignores_steps_without_tree():
    traj = {"id": "T5", "steps": [{"type": "click", "axtId": "131"}, {"type": "click", "axtId": "57"}]}
    stats = breadth_stats(traj, {"1": {"ax_tree": _tree()}})   # 只有 index 1 有树
    assert stats["n_states"] == 1 and stats["n_matched_by_axtid"] == 1
    # trees[i] 配 steps[i]，所以配上的只有步 1 的 axtId="57"
    assert stats["roles_touched"] == ["textbox"]
    assert stats["roles_untouched"] == ["button", "spinbutton"]


def _observation() -> dict:
    state = {"title": "t", "visible_text": "v", "aria_snapshot": "a", "interactive": [1, 2]}
    return {
        "entry_url": "https://a.com/",
        "baseline": dict(state),
        "exploration_paths": [{
            "id": "traj",
            "before": dict(state),
            "steps": [
                {"index": 1, "status": "ok", "state_id": "traj__step_1", "state": dict(state),
                 "action": {"action": "click", "target": "9", "target_description": "[9] button 'Go'"}},
                {"index": 2, "status": "ok", "state_id": "traj__step_2", "state": dict(state),
                 "action": {"action": "fill", "target": ""}},
            ],
            "after": dict(state),
        }],
    }


def _evidence(payload: dict | None = None) -> dict:
    return {"status": "ok", "evidence_state_ids": ["traj__step_1"], "action_steps": [{"a": 1}]} \
        if payload is None else payload


def test_resolve_source_prefers_explicit_subset(tmp_path: Path):
    subset = tmp_path / "cand_48.jsonl"
    dataset, path, axtrees, label = resolve_source(
        bucket=None, subset=subset, axtrees_dir=tmp_path / "ax")
    assert (dataset, path, label) == ("webchain", subset, "cand_48")
    assert axtrees == tmp_path / "ax"


def test_resolve_source_requires_axtrees_for_explicit_subset(tmp_path: Path):
    with pytest.raises(SystemExit):
        resolve_source(bucket=None, subset=tmp_path / "x.jsonl", axtrees_dir=None)


def test_resolve_source_rejects_both_and_neither(tmp_path: Path):
    with pytest.raises(SystemExit):
        resolve_source(bucket="webchain", subset=tmp_path / "x.jsonl", axtrees_dir=tmp_path)
    with pytest.raises(SystemExit):
        resolve_source(bucket=None, subset=None, axtrees_dir=None)


def test_resolve_source_falls_back_to_preset_bucket():
    dataset, path, axtrees, label = resolve_source(
        bucket="autonomous", subset=None, axtrees_dir=None)
    assert dataset == "webworld" and label == "autonomous"
    assert path.name == "autonomous_100.jsonl" and axtrees is None


def test_render_case_shows_actions_and_locates_state_ids():
    text = render_case({"seed_id": "s1", "entry_url": "https://a.com/"},
                       _observation(),
                       {"n_steps": 2, "action_types": {"click": 1, "fill": 1}},
                       _evidence(),
                       max_evidence_chars=None)
    assert "[ 1] traj__step_1" in text
    assert "[9] button 'Go'" in text
    assert "我的 state_id 出现在证据里: 1/2" in text
    assert "action_steps 条数: 1" in text


def test_render_case_truncates_evidence_when_capped():
    text = render_case({"seed_id": "s1"}, _observation(),
                       {"n_steps": 2, "action_types": {}},
                       _evidence({"status": "ok", "blob": "x" * 500}),
                       max_evidence_chars=200)
    assert "共 " in text and "字符，加 --full 看全部" in text


# ------------------------------------------------------------------ 容量上限漏斗

def test_cap_configs_start_from_the_shipped_defaults():
    """第一档必须是现状，否则漏斗的基准线就不是当前行为。"""
    current = CAP_CONFIGS[0]
    assert current.name == "current"
    assert (current.limits.max_controls, current.limits.max_visible_chars,
            current.limits.max_aria_chars, current.control_limit) == (150, 4000, 12000, 64)
    names = [config.name for config in CAP_CONFIGS]
    assert names == ["current", "x2", "x4", "unlimited"]
    assert CAP_CONFIGS[-1].control_limit is None


def test_raw_controls_dedupes_by_node_id_and_keeps_roles():
    """按 node id 去重才是「页面上有多少个控件」；没有 id 的用 role+标签兜底。"""
    tree = {"role": "generic", "name": "", "children": [
        _node("1", "button", "Book"),
        _node("1", "button", "Book"),             # 同一 node id 重复出现
        _node("3", "textbox", "Book"),            # 同名不同 id，分开算
        _node("4", "heading", "Book"),            # 非交互 role，不计
        {"role": "link", "name": "Help", "attributes": {"html_tag": "a"}},   # 无 id
    ]}
    assert raw_controls(tree) == {
        "1": "button", "3": "textbox", "link:help": "link"}


def test_adapter_control_keys_dedupes_across_states():
    observation = {
        "baseline": {"interactive": [{"role": "button", "aria_label": "Book"}]},
        "exploration_paths": [{"steps": [
            {"state": {"interactive": [{"role": "button", "aria_label": "Book"},
                                       {"role": "link", "text": "Help"}]}},
        ]}],
    }
    assert adapter_control_keys(observation) == {("button", "book"), ("link", "help")}


_DISTINCT_LABELS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
                    "golf", "hotel", "india", "juliet")


def _observation_with_controls(count: int, *, labels: tuple[str, ...] | None = None) -> dict:
    names = labels or _DISTINCT_LABELS
    controls = [{"role": "button", "aria_label": names[index], "tag": "button"}
                for index in range(count)]
    state = {"title": "t", "visible_text": "v", "aria_snapshot": "a",
             "interactive": [dict(row) for row in controls]}
    return {
        "entry_url": "https://a.com/",
        "baseline": state,
        "exploration_paths": [{"id": "traj", "before": state, "steps": [], "after": state}],
    }


def test_evidence_keeps_every_control_when_limit_is_none():
    """`control_limit=None` 必须真的不抽样，否则量不出上限损失。"""
    observation = _observation_with_controls(10)
    capped = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, control_limit=2)
    full = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, control_limit=None)

    assert len(capped["observed_controls"]) == 2
    assert capped["observed_control_total"] == 10
    assert len(full["observed_controls"]) == 10


def test_evidence_keeps_all_controls_when_limit_exceeds_pool():
    observation = _observation_with_controls(3)
    full = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, control_limit=None)
    assert len(full["observed_controls"]) == 3


def test_controls_differing_only_in_digits_collapse_to_two():
    """`_online_control_rows` 把标签里的数字抹成 `#` 再分组，每组最多留 2 行。

    这是**独立于 `control_limit` 的另一道上限**：分页按钮「1 2 3 …」只会留下
    两个代表，所以哪怕 `control_limit=None` 也数不全。这条行为必须显式记住，
    否则会把「上限调高就好了」当成结论。
    """
    observation = _observation_with_controls(
        6, labels=("Page 1", "Page 2", "Page 3", "Page 4", "Page 5", "Page 6"))
    full = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, control_limit=None)

    assert full["observed_control_total"] == 6
    assert len(full["observed_controls"]) == 2      # 同 pattern 只留 2 个代表


def _coverage_record(name: str, *, raw: int, adapter: int, ceiling: int, delivered: int,
                     host: str = "a.com", traj_id: str = "T1", chars: int = 1000) -> dict:
    return {"config": {"name": name}, "raw_controls": raw, "adapter_controls": adapter,
            "ceiling_controls": ceiling, "delivered_controls": delivered,
            "raw_roles": 8, "delivered_roles": 3, "evidence_chars": chars,
            "visible_text_lines": 40, "primary_host": host, "traj_id": traj_id}


def test_render_report_turns_counts_into_funnel_ratios():
    records = [
        _coverage_record("current", raw=100, adapter=80, ceiling=30, delivered=20, chars=1000),
        _coverage_record("current", raw=100, adapter=80, ceiling=70, delivered=60,
                         host="b.com", traj_id="T2", chars=3000),
        _coverage_record("unlimited", raw=100, adapter=100, ceiling=100, delivered=100),
    ]
    text = render_coverage_report(records, top=1)
    lines = text.splitlines()
    current_line = next(line for line in lines if line.startswith("current"))
    unlimited_line = next(line for line in lines if line.startswith("unlimited"))
    assert "40.0%" in current_line          # (20+60)/200
    assert "100.0%" in unlimited_line
    assert "2000" in current_line            # 证据字符取平均 (1000+3000)/2
    assert "① 原始控件" in text and "③ 折叠上限" in text   # 漏斗各段有表头
    assert "T1" in text.split("前 1")[1]     # --top 只列送达率最低的那条
    assert "x" * 300 not in text

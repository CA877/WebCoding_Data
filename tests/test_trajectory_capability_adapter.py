"""轨迹 adapter 的单元测试。

测试数据全部取自**真实**数据集产物（WebChain 子集与远端抓取的 AX 树、WebWorldData
world-model 记录），不使用构造样例；校验器契约部分直接调用纯函数，不涉及 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspiration_library.deep_browser_exploration import compact_live_browser_evidence_for_llm
from inspiration_library.dynamic_capability_retrieval import validate_live_card_evidence
from inspiration_library.trajectory_capability_adapter import (
    NoTrajectoryEvidence,
    ObservationLimits,
    UNLIMITED_LIMITS,
    a11y_text_to_state,
    load_axtrees,
    parse_a11y_text,
    webchain_to_observation,
    webchain_tree_to_text,
    webworld_record_to_observation,
)

ROOT = Path(__file__).resolve().parents[1]
WEBCHAIN_SUBSET = ROOT / "datasets/webchain_explore/subset_100.jsonl"
WEBCHAIN_AXTREES = ROOT / "datasets/webchain_explore/axtrees_sample"
WEBWORLD = ROOT / "datasets/webworld_explore/autonomous_100.jsonl"
WEBCHAIN_SAMPLE_ID = "4jLN3tPKXzTU-R7WEtqtw"


def _first_jsonl(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.loads(fh.readline())


@pytest.fixture(scope="module")
def webworld_row() -> dict:
    return _first_jsonl(WEBWORLD)


@pytest.fixture(scope="module")
def webchain_row() -> dict:
    with WEBCHAIN_SUBSET.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row["trajectory"]["id"] == WEBCHAIN_SAMPLE_ID:
                return row
    raise AssertionError(f"{WEBCHAIN_SAMPLE_ID} missing from the subset")


@pytest.fixture(scope="module")
def webchain_axtrees() -> dict:
    return load_axtrees(WEBCHAIN_AXTREES / f"{WEBCHAIN_SAMPLE_ID}.json.gz")


# ------------------------------------------------------------------ A11y 文本解析

def test_parses_node_lines_and_strips_trailing_attributes():
    text = "RootWebArea '财经科学杂志', focused=True\n\t[16] link '首页 >', focusable=True\n\t\tStaticText '>'\n"
    rows = parse_a11y_text(text)
    assert [row["id"] for row in rows] == ["16"]
    assert rows[0]["role"] == "link"
    assert rows[0]["name"] == "首页 >"
    assert rows[0]["static_text"] == ">"
    assert rows[0]["depth"] == 1


def test_in_main_flag_excludes_sibling_nodes():
    text = (
        "RootWebArea 'x'\n"
        "[1] main ''\n"
        "\t[2] button 'Go'\n"
        "[3] contentinfo ''\n"
        "\t[4] link 'Privacy'\n"
    )
    rows = {row["id"]: row for row in parse_a11y_text(text)}
    assert rows["2"]["in_main"] is True
    assert rows["4"]["in_main"] is False


def test_state_reads_url_attribute_but_ignores_about_blank():
    text = "RootWebArea 'Page', focused=True, url='https://example.org/a'\n[1] link 'x'\n"
    assert a11y_text_to_state(text, url="https://fallback/")["url"] == "https://example.org/a"
    blank = "RootWebArea '', focused=True, url='about:blank'\n"
    assert a11y_text_to_state(blank, url="https://fallback/")["url"] == "https://fallback/"


def test_controls_collect_label_when_node_name_is_empty():
    text = "RootWebArea 'x'\n[7] textbox ''\n"
    state = a11y_text_to_state(text, label_by_node_id={"7": "search"})
    assert state["interactive"] == [
        {"role": "textbox", "text": "search", "aria_label": "search", "in_main": False,
         "visible": True, "tag": "input"}
    ]


# ---------------------------------------------------------------------- WebWorld

def test_webworld_record_becomes_observation(webworld_row):
    seed, observation = webworld_record_to_observation(
        webworld_row, seed_id="ww_auto_000", host="cjkx.fabiao.com.cn")

    assert seed["entry_url"] == observation["entry_url"]
    # entry_url 取自记录内的 goto 动作原文，不额外规范化
    assert observation["entry_url"] == "https://cjkx.fabiao.com.cn"
    # turn0 的 about:blank 占位页不能当 baseline
    assert observation["baseline"]["title"] == "财经科学杂志-财经科学出版社"
    path = observation["exploration_paths"][0]
    assert path["id"] == "traj"
    assert len(path["steps"]) >= 1
    assert [step["state_id"] for step in path["steps"]] == [
        f"traj__step_{i}" for i in range(1, len(path["steps"]) + 1)
    ]
    first = path["steps"][0]
    assert first["status"] == "ok"
    assert first["action"]["action"] == "goto"
    assert first["state"]["url"] == observation["entry_url"]


def test_webworld_action_resolves_clicked_node_label(webworld_row):
    _, observation = webworld_record_to_observation(webworld_row, seed_id="ww_auto_000",
                                                    host="cjkx.fabiao.com.cn")
    described = [step["action"].get("target_description")
                 for step in observation["exploration_paths"][0]["steps"]]
    assert any(desc and desc.startswith("[") for desc in described), described


def test_webworld_rejects_non_world_model_record():
    with pytest.raises(ValueError, match="world-model"):
        webworld_record_to_observation({"conversations": [{"from": "human", "value": "hello"}]},
                                       seed_id="bad")


def test_observation_passes_extractor_evidence_gate(webworld_row):
    _, observation = webworld_record_to_observation(webworld_row, seed_id="ww_auto_000",
                                                    host="cjkx.fabiao.com.cn")
    evidence = compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, include_action_steps=True)
    ids = set(evidence["evidence_state_ids"])
    path = observation["exploration_paths"][0]
    assert "baseline" in ids
    assert {step["state_id"] for step in path["steps"]} <= ids

    # 交互类卡片引用成功动作状态 -> 通过；引用不存在的 id -> 拒绝
    extraction = {
        "source_url": observation["entry_url"],
        "capabilities": [{
            "capability_id": "traj_click",
            "user_actions": ["click"],
            "observation_evidence": [{"state_id": "traj__step_1", "evidence": "clicked"}],
        }],
    }
    assert validate_live_card_evidence(extraction, observation)["admission_status"] == "available"

    bad = {"source_url": observation["entry_url"], "capabilities": [{
        "capability_id": "traj_bad", "user_actions": [],
        "observation_evidence": [{"state_id": "traj__step_999", "evidence": "x"}]}]}
    with pytest.raises(ValueError, match="unknown or missing"):
        validate_live_card_evidence(bad, observation)


# ---------------------------------------------------------------------- WebChain

def test_renders_real_ax_tree_into_a11y_text(webchain_axtrees):
    tree = webchain_axtrees["1"]["ax_tree"]
    text, labels = webchain_tree_to_text(tree, title="Cheap Hotels, Cars, & Flights | Hotwire")
    assert text.startswith("RootWebArea 'Cheap Hotels, Cars, & Flights | Hotwire'")
    # 根 document 节点的 name 是整页文本，不能渲染成节点行
    assert "[0] document" not in text
    assert all("\n" not in line for line in text.splitlines())
    assert labels["24"] == "Sign in"
    assert "[24] button 'Sign in'" in text
    # 输入框没有可访问名，用属性兜底
    assert labels["60"] == "Message us"


def test_webchain_trajectory_becomes_observation(webchain_row, webchain_axtrees):
    seed, observation = webchain_to_observation(
        webchain_row["trajectory"], webchain_axtrees, seed_id="wc_000")

    assert seed["task_instruction"].startswith("- Find a luxurious hotel in Toronto")
    assert seed["entry_url"] == observation["entry_url"] == "https://www.hotwire.com/"
    path = observation["exploration_paths"][0]
    # 首步 launchApp 没有 AX 树，baseline 从第一个有树的状态起
    assert len(path["steps"]) == len(webchain_axtrees) - 1
    assert {step["action"]["action"] for step in path["steps"]} == {"click"}
    assert observation["baseline"]["title"].startswith("Cheap Hotels, Cars, & Flights")
    ids = set(compact_live_browser_evidence_for_llm(
        observation, include_selectors=False, include_action_steps=True)["evidence_state_ids"])
    assert {step["state_id"] for step in path["steps"]} <= ids


def test_default_limits_match_the_shipped_constants():
    """默认值必须等于仓库沿用至今的取值，否则改上限会静默改变既有结果。"""
    assert ObservationLimits() == ObservationLimits(
        max_controls=150, max_visible_chars=4000, max_aria_chars=12000)
    assert UNLIMITED_LIMITS.as_dict() == {
        "max_controls": None, "max_visible_chars": None, "max_aria_chars": None}


def test_control_cap_is_honoured_and_none_means_unbounded(webchain_axtrees):
    tree = next(payload["ax_tree"] for payload in webchain_axtrees.values()
                if isinstance(payload, dict) and payload.get("ax_tree") is not None)
    text, _ = webchain_tree_to_text(tree, title="")

    capped = a11y_text_to_state(text, limits=ObservationLimits(max_controls=5))
    unbounded = a11y_text_to_state(text, limits=UNLIMITED_LIMITS)

    assert len(capped["interactive"]) == 5
    assert len(unbounded["interactive"]) > 5
    # 截断只影响控件列表，不该动到其它字段
    assert capped["state_sha256"] == unbounded["state_sha256"]


def test_text_caps_are_honoured_and_none_means_unbounded(webchain_axtrees):
    tree = next(payload["ax_tree"] for payload in webchain_axtrees.values()
                if isinstance(payload, dict) and payload.get("ax_tree") is not None)
    text, _ = webchain_tree_to_text(tree, title="")

    tight = a11y_text_to_state(text, limits=ObservationLimits(
        max_visible_chars=100, max_aria_chars=200))
    loose = a11y_text_to_state(text, limits=UNLIMITED_LIMITS)

    assert tight["visible_text"].endswith("...[truncated]")
    assert tight["aria_snapshot"].endswith("...[truncated]")
    assert len(loose["visible_text"]) > len(tight["visible_text"])
    assert len(loose["aria_snapshot"]) > len(tight["aria_snapshot"])


def test_webchain_observation_threads_limits_into_every_state(webchain_row, webchain_axtrees):
    capped = webchain_to_observation(webchain_row["trajectory"], webchain_axtrees,
                                     seed_id="wc_cap",
                                     limits=ObservationLimits(max_controls=1))
    loose = webchain_to_observation(webchain_row["trajectory"], webchain_axtrees,
                                    seed_id="wc_loose", limits=UNLIMITED_LIMITS)

    capped_sizes = [len(state["interactive"]) for state in _states(capped[1])]
    loose_sizes = [len(state["interactive"]) for state in _states(loose[1])]
    assert capped_sizes and all(size <= 1 for size in capped_sizes)
    # baseline 与每个 step 状态都要走到上限，不能只有 baseline 生效
    assert any(loose_size > cap for loose_size, cap in zip(loose_sizes, capped_sizes))


def test_webworld_observation_threads_limits(webworld_row):
    capped = webworld_record_to_observation(webworld_row, seed_id="ww_cap",
                                            limits=ObservationLimits(max_visible_chars=10))
    loose = webworld_record_to_observation(webworld_row, seed_id="ww_loose",
                                           limits=UNLIMITED_LIMITS)
    capped_states = _states(capped[1])
    loose_states = _states(loose[1])
    assert capped_states and len(capped_states) == len(loose_states)
    truncated = [(loose_state, capped_state)
                 for loose_state, capped_state in zip(loose_states, capped_states)
                 if capped_state["visible_text"].endswith("...[truncated]")]
    assert truncated, "限制没生效：没有任何状态被截断"
    for loose_state, capped_state in truncated:
        assert len(loose_state["visible_text"]) > len(capped_state["visible_text"])
        assert loose_state["visible_text"].startswith(capped_state["visible_text"][:10])


def _states(observation: dict) -> list[dict]:
    """observation 里所有状态快照（baseline + 每步结果状态）。"""
    states = [observation["baseline"]]
    for path in observation["exploration_paths"]:
        states.extend(step["state"] for step in path["steps"])
    return states


def test_webchain_rejects_trajectory_without_trees():
    with pytest.raises(NoTrajectoryEvidence, match="accessibility trees"):
        webchain_to_observation({"steps": [{"type": "click"}]}, {}, seed_id="wc_empty")


def test_webchain_pairs_actions_across_tree_index_gaps(webchain_row, webchain_axtrees):
    """实测 38/100 条轨迹的 axTree 下标有缺口，配对不能假设连续。"""
    gapped = {key: value for key, value in webchain_axtrees.items() if key != "2"}
    assert "2" not in gapped
    _, observation = webchain_to_observation(
        webchain_row["trajectory"], gapped, seed_id="wc_gap")

    path = observation["exploration_paths"][0]
    assert len(path["steps"]) == len(gapped) - 1
    # 缺下标 2 时，产生下标 3 状态的动作是第 2 步 click，仍能配对
    actions = [step["action"]["action"] for step in path["steps"]]
    assert actions == ["click"] * (len(gapped) - 1)

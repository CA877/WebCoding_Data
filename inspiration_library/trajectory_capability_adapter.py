"""把外部轨迹数据集转成 `extract_seed_capabilities` 接受的 observation 形状。

`extract_seed_capabilities` 原本只吃本仓库浏览器探索产出的 observation：它要求
`baseline` 是起始状态、`exploration_paths[*].steps[*].state` 是每次成功动作后的状态，
卡片校验会按 `<path_id>__step_<i>` 派生 state_id，并要求交互类卡片至少引用一个
**成功动作** 对应的 step。本模块把两条外部数据源映射到同一形状，使两边共用同一个
抽取器、同一套卡片 schema，从而让卡片的数量与构成可比。

支持两类输入：

1. `webworld_record_to_observation` —— WebWorldData 的单条 world-model 记录
   `{conversations: [...]}`。回合序列为 `human0, gpt1, human2, gpt3, ...`：
   human0 给出初始状态（实测为 `about:blank` 占位）与首个动作，gpt2i+1 给出第 i 个
   真实页面状态，human2i+2 给出第 i+1 个动作。状态是 A11y 文本，动作引用状态里的
   节点 id（`click('114')`）。**记录里没有任务目标**。
2. `webchain_to_observation` —— WebChain 原始轨迹 `{id, title, steps[]}`，每题带
   自然语言任务标题；每一步的 `axTree` 是远端 URL，需先用 `fetch_webchain_axtrees.py`
   下载。AX 树是嵌套 JSON，本模块把它渲染成**与 WebWorld 相同的 A11y 文本格式**，
   使模型看到的证据形态对称。

两边产出的 `(seed, observation)` 中，`seed["entry_url"]` 与 `observation["entry_url"]`
始终一致（校验器要求二者相等）。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# 与 linear_edit_queries 的交互控件筛选保持一致的可交互角色
INTERACTIVE_ROLES = {
    "link", "button", "textbox", "searchbox", "combobox", "listbox", "checkbox",
    "radio", "switch", "slider", "spinbutton", "menuitem", "menuitemcheckbox",
    "menuitemradio", "tab", "option", "treeitem", "gridcell", "cell",
}

# 节点名缺失时依次尝试的属性，用于给出可读控件标签
_LABEL_ATTRS = ("placeholder", "aria-label", "aria_label", "title", "alt", "value", "id", "name", "href")

# A11y 行尾的属性列表，如 `, focusable=True, url='about:blank'`
_ATTR_SUFFIX_RE = re.compile(
    r"(?:,\s*[A-Za-z_][\w-]*=(?:True|False|-?\d+(?:\.\d+)?|'[^']*'))+\s*$"
)
_NODE_LINE_RE = re.compile(r"^(\t*)\[(\d+)\]\s+(\S+)\s*(?:'(.*)')?\s*$")
_STATICTEXT_RE = re.compile(r"^\t*StaticText '(.*)'\s*$")
_ROOT_RE = re.compile(r"RootWebArea '([^']*)'")
_URL_ATTR_RE = re.compile(r"\burl='([^']*)'")
_ACTION_FN_RE = re.compile(r"^\s*([A-Za-z_][\w]*)\s*\(")
_ACTION_ARG_RE = re.compile(r"^\s*[A-Za-z_][\w]*\s*\((.*)\)\s*$", re.S)
_NODE_ID_ARG_RE = re.compile(r"^'?(\d+)'?$")

# WebWorld 回合里的分隔标记
_TURN0_RE = re.compile(r"Initial Page State:\s*\n(.*?)\n\s*First Action:\s*'(.+?)'\s*\n", re.S)
_CONTINUE_RE = re.compile(r"Action:\s*'(.*?)'\s*\n\s*Next Page State:", re.S)

class NoTrajectoryEvidence(ValueError):
    """轨迹本身没有任何可用的结构证据（例如全部 axTree 缺失）。

    与转换错误区分开：这不是代码问题，而是该条数据无法参与抽取，应在报告里单列。
    """


_BOUND_ARIA_CHARS = 12000
_BOUND_VISIBLE_CHARS = 4000
_MAX_CONTROLS = 150
_MAX_LABEL_CHARS = 200
# 这两个角色的 `name` 是整页文本或元信息，不渲染成节点行（子树仍然遍历）
_SKIPPED_ROLES = {"document", "meta"}


@dataclass(frozen=True)
class ObservationLimits:
    """转换阶段的三道容量上限，决定 LLM 到底能看到多少页面结构。

    它们和轨迹本身的上限是两件事：轨迹记录了整页，这里是**渲染成 observation 时**
    主动砍掉的量。默认值即仓库沿用至今的取值；任何一项给 `None` 表示不截断。
    """

    max_controls: int | None = _MAX_CONTROLS
    max_visible_chars: int | None = _BOUND_VISIBLE_CHARS
    max_aria_chars: int | None = _BOUND_ARIA_CHARS

    def as_dict(self) -> dict[str, int | None]:
        return {
            "max_controls": self.max_controls,
            "max_visible_chars": self.max_visible_chars,
            "max_aria_chars": self.max_aria_chars,
        }


# 完全不截断：用于量化「上限到底损失了多少」
UNLIMITED_LIMITS = ObservationLimits(
    max_controls=None, max_visible_chars=None, max_aria_chars=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bounded(value: str, limit: int | None) -> str:
    """按字符数截断；`limit=None` 表示不截断。"""
    value = value or ""
    if limit is None or len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _clean_name(raw: str) -> str:
    """把 A11y 名字里的转义与空白规范化，去掉行尾属性残留。"""
    name = _ATTR_SUFFIX_RE.sub("", raw or "")
    name = name.replace("\\'", "'").replace('\\"', '"')
    return " ".join(name.split())[:200]


def parse_a11y_text(text: str) -> list[dict[str, Any]]:
    """把 `[id] role 'name'` 缩进树解析成节点行，深度用前导 tab 数表示。

    `StaticText '...'` 没有 id，挂到上一条有 id 的节点上作为其可见文本。
    """
    rows: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        stripped = _ATTR_SUFFIX_RE.sub("", line)
        match = _NODE_LINE_RE.match(stripped)
        if match:
            tabs, node_id, role, name = match.groups()
            rows.append({
                "depth": len(tabs),
                "id": node_id,
                "role": role,
                "name": _clean_name(name or ""),
                "static_text": "",
                "in_main": False,
            })
            continue
        text_match = _STATICTEXT_RE.match(stripped)
        if text_match and rows:
            rows[-1]["static_text"] = _clean_name(text_match.group(1))
    # 标记位于 main 内的节点（main 的兄弟节点不属于 main）
    main_depths: list[int] = []
    for row in rows:
        while main_depths and row["depth"] <= main_depths[-1]:
            main_depths.pop()
        if row["role"] == "main":
            main_depths.append(row["depth"])
            row["in_main"] = True
            continue
        row["in_main"] = bool(main_depths)
    return rows


def a11y_text_to_state(
    text: str,
    *,
    url: str = "",
    fallback_title: str = "",
    label_by_node_id: dict[str, str] | None = None,
    selector_by_node_id: dict[str, str] | None = None,
    limits: ObservationLimits | None = None,
) -> dict[str, Any]:
    """把 A11y 文本渲染成一个 observation 状态快照。"""
    limits = limits or ObservationLimits()
    rows = parse_a11y_text(text)
    title_match = _ROOT_RE.search(_ATTR_SUFFIX_RE.sub("", text or "").split("\n", 1)[0])
    title = title_match.group(1) if title_match else fallback_title
    url_match = _URL_ATTR_RE.search(text or "")
    if url_match and url_match.group(1) not in {"about:blank", ""}:
        url = url_match.group(1)

    label_by_node_id = label_by_node_id or {}
    controls: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for row in rows:
        if row["role"] not in INTERACTIVE_ROLES:
            continue
        name = row["name"] or row["static_text"] or label_by_node_id.get(row["id"], "")
        key = (row["role"], name, row["id"])
        if key in seen:
            continue
        seen.add(key)
        control: dict[str, Any] = {
            "role": row["role"],
            "text": name,
            "aria_label": name,
            "in_main": row["in_main"],
            "visible": True,
            "tag": {"link": "a", "button": "button", "textbox": "input",
                    "searchbox": "input", "combobox": "select"}.get(row["role"], ""),
        }
        selector = (selector_by_node_id or {}).get(row["id"])
        if selector:
            control["selector"] = selector
        controls.append(control)
        if limits.max_controls is not None and len(controls) >= limits.max_controls:
            break

    visible_text = "\n".join(
        row["static_text"] or row["name"] for row in rows
        if (row["static_text"] or row["name"]).strip()
    )
    return {
        "state_sha256": _sha(text or ""),
        "url": url,
        "title": title,
        "visible_text": _bounded(visible_text, limits.max_visible_chars),
        "aria_snapshot": _bounded(text or "", limits.max_aria_chars),
        "interactive": controls,
        "viewport": None,
        "horizontal_overflow": None,
    }


class _PathBuilder:
    """累积一条轨迹，产出 observation。

    约定（与校验器一致）：`baseline` 是起始状态；第 i 个成功动作的结果状态命名为
    `<path_id>__step_<i>`（i 从 1 起），因此卡片可引用它，交互类卡片也因此满足
    「至少引用一个成功动作状态」的要求。
    """

    def __init__(self, path_id: str, entry_url: str, *,
                 limits: ObservationLimits | None = None) -> None:
        self.path_id = path_id
        self.entry_url = entry_url
        self.limits = limits or ObservationLimits()
        self.baseline: dict[str, Any] | None = None
        self.rows: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def set_baseline(self, state: dict[str, Any]) -> None:
        self.baseline = state

    def add_step(self, action: dict[str, Any], state: dict[str, Any]) -> None:
        self.rows.append((action, state))

    def observation(self) -> dict[str, Any]:
        if self.baseline is None:
            raise ValueError("trajectory produced no baseline state")
        steps = [
            {
                "index": index,
                "status": "ok",
                "action": action,
                "state": state,
                "state_id": f"{self.path_id}__step_{index}",
            }
            for index, (action, state) in enumerate(self.rows, 1)
        ]
        path = {
            "id": self.path_id,
            "purpose": "imported_trajectory",
            "status": "ok",
            "before": self.baseline,
            "steps": steps,
            "after": steps[-1]["state"] if steps else self.baseline,
        }
        return {
            "status": "ok",
            "source_kind": "live_url",
            "entry_url": self.entry_url,
            "baseline": self.baseline,
            "exploration_paths": [path],
            "remote_requests": [],
            "console_errors": [],
            "page_errors": [],
            "dialog_events": [],
            "visual_routing": {},
            "observation_limits": ["imported_trajectory", "no_live_browser"],
        }


def _action_row(raw: str, *, label_by_node_id: dict[str, str] | None = None,
                role_by_node_id: dict[str, str] | None = None) -> dict[str, Any]:
    """把 `click('114')` 这类动作串拆成 action/target，并在可解析时带上目标标签。"""
    name_match = _ACTION_FN_RE.match(raw or "")
    action = name_match.group(1) if name_match else "unknown"
    arg_match = _ACTION_ARG_RE.match(raw or "")
    target = arg_match.group(1).strip().strip("'") if arg_match else ""
    row: dict[str, Any] = {"action": action, "target": target, "source": "trajectory"}
    id_match = _NODE_ID_ARG_RE.match(target)
    if id_match and label_by_node_id:
        label = label_by_node_id.get(id_match.group(1), "")
        role = (role_by_node_id or {}).get(id_match.group(1), "")
        if label or role:
            row["target_description"] = f"[{id_match.group(1)}] {role} '{label}'".strip()
    return row


def _maps_from_text(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """从状态文本里取出 node_id -> 标签 与 node_id -> role 两张映射。"""
    labels: dict[str, str] = {}
    roles: dict[str, str] = {}
    for row in parse_a11y_text(text):
        roles[row["id"]] = row["role"]
        label = row["name"] or row["static_text"]
        if label:
            labels[row["id"]] = label
    return labels, roles


# --------------------------------------------------------------------------- WebWorld

def webworld_record_to_observation(
    record: dict,
    *,
    seed_id: str,
    host: str = "",
    entry_url: str | None = None,
    limits: ObservationLimits | None = None,
) -> tuple[dict, dict]:
    """把一条 WebWorldData world-model 记录转成 (seed, observation)。

    `host` 取自记录自带的 `features.primary_host`（记录内动作 URL 的主机），用于在
    没有 `goto(...)` 动作时给出一条真实的入口 URL。
    """
    convs = record.get("conversations") or []
    if not convs:
        raise ValueError("record has no conversations")
    if convs[0].get("from") != "human":
        raise ValueError("record does not start with a human turn")

    turn0 = _TURN0_RE.search(str(convs[0].get("value", "")))
    if not turn0:
        raise ValueError("record is not a world-model trajectory")
    initial_text, first_action = turn0.groups()

    state_texts: list[str] = [initial_text]
    raw_actions: list[str] = [first_action]
    for conv in convs[1:]:
        value = str(conv.get("value", ""))
        if conv.get("from") == "gpt":
            state_texts.append(value)
        elif conv.get("from") == "human":
            match = _CONTINUE_RE.search(value)
            if match:
                raw_actions.append(match.group(1))

    entry_url = entry_url or _entry_url_from_actions(raw_actions) or (
        f"https://{host}/" if host else f"https://webworld.invalid/{seed_id}"
    )

    # turn0 的初始状态实测是 about:blank 占位页，不能当 baseline；用第一个真实页面状态。
    builder = _PathBuilder("traj", entry_url, limits=limits)
    builder.set_baseline(a11y_text_to_state(state_texts[1] if len(state_texts) > 1 else state_texts[0],
                                            url=entry_url, limits=limits))
    for index, raw in enumerate(raw_actions):
        next_index = index + 2
        if next_index >= len(state_texts):
            break
        labels, roles = _maps_from_text(state_texts[index + 1])
        builder.add_step(
            _action_row(raw, label_by_node_id=labels, role_by_node_id=roles),
            a11y_text_to_state(state_texts[next_index], url=entry_url, limits=limits),
        )

    observation = builder.observation()
    observation["baseline"]["url"] = entry_url
    seed = {
        "seed_id": seed_id,
        "entry_url": entry_url,
        "dataset": "webworld_data",
        "mining_focus": "imported world-model trajectory; the record carries no task instruction",
    }
    return seed, observation


def _entry_url_from_actions(actions: Iterable[str]) -> str:
    """从 goto 动作里取首个站点作为 entry_url。"""
    for raw in actions:
        match = re.search(r"goto\(\s*'?\"?(https?://[^\s'\")]+)", raw or "")
        if match:
            return match.group(1)
    return ""


# ---------------------------------------------------------------------------- WebChain

def webchain_tree_to_text(tree: Any, *, title: str = "") -> tuple[str, dict[str, str]]:
    """把 WebChain 嵌套 AX 树渲染成 A11y 文本，返回 (文本, node_id -> 标签)。

    角色词汇与 WebWorld 一致（`link` / `button` / `textbox` / `main` …），因此产出
    的文本可以直接喂给 `a11y_text_to_state`，两边证据形态对称。

    两个实测得到的渲染约定：
    - 根 `document` 节点的 `name` 是**整页文本**（含换行），不是标题；标题用调用方
      传入的 `title`（WebChain 每步自带 `hostTitle`）。`document` / `meta` 节点本身
      不渲染成行，但其子树继续遍历，正文因此保留在各级节点上。
    - 所有名字折叠空白并截断，保证一行一节点，使文本可被稳定解析。
    """
    lines: list[str] = []
    labels: dict[str, str] = {}
    if not isinstance(tree, dict):
        return "", labels

    def node_label(node: dict) -> str:
        name = " ".join(str(node.get("name") or "").split())
        if name:
            return name[:_MAX_LABEL_CHARS]
        attrs = node.get("attributes") or {}
        for key in _LABEL_ATTRS:
            value = " ".join(str(attrs.get(key) or "").split())
            if value:
                return value[:_MAX_LABEL_CHARS]
        return ""

    def walk(node: Any, depth: int) -> None:
        if not isinstance(node, dict):
            return
        role = str(node.get("role") or "").strip()
        attrs = node.get("attributes") or {}
        node_id = str(attrs.get("data-imean-axt-id") or "").strip()
        indent = "\t" * depth
        if role and role not in _SKIPPED_ROLES and node_id:
            label = node_label(node)
            labels[node_id] = label
            lines.append(f"{indent}[{node_id}] {role} '{label}'")
            html_tag = str(attrs.get("html_tag") or "").lower()
            if label and role not in INTERACTIVE_ROLES and html_tag not in {"input", "select", "textarea", "img"}:
                lines.append(f"{indent}\tStaticText '{label}'")
        for child in node.get("children") or []:
            walk(child, depth + 1)

    lines.append(f"RootWebArea '{' '.join((title or '').split())[:200]}'")
    for child in tree.get("children") or []:
        walk(child, 1)
    return "\n".join(lines), labels


def webchain_to_observation(
    traj: dict,
    axtrees: dict[str, dict],
    *,
    seed_id: str,
    limits: ObservationLimits | None = None,
) -> tuple[dict, dict]:
    """把一条 WebChain 轨迹转成 (seed, observation)。

    `axtrees` 是 `fetch_webchain_axtrees.py` 产出的 `steps` 映射（字符串下标 → 该步的
    `ax_tree` 等）。第 i 步的树是**执行第 i 步动作时**的页面状态，因此产生下标 j 状态的
    动作是第 `j-1` 步。

    实测 100 条子集中有 38 条的树在部分下标缺失（该步 axTree 下载失败或本就无 URL），
    所以这里按「下标 j 的状态 ← 第 j-1 步的动作」逐树配对，不假设下标连续；动作目标的
    标签优先从下标 j-1 的树解析，缺失时退回第一条可用树。完全没有树的轨迹抛
    `NoTrajectoryEvidence`，与其它失败区分开。
    """
    steps = traj.get("steps") or []
    if not steps:
        raise ValueError("trajectory has no steps")

    entry_url = ""
    for step in steps:
        if step.get("href"):
            entry_url = str(step["href"])
            break
    if not entry_url:
        host = next((str(s["host"]) for s in steps if s.get("host")), "")
        entry_url = f"https://{host}/" if host else f"https://webchain.invalid/{seed_id}"

    trees_by_index: dict[int, dict] = {}
    for index in range(len(steps)):
        payload = axtrees.get(str(index))
        tree = payload.get("ax_tree") if isinstance(payload, dict) else None
        if tree is not None:
            trees_by_index[index] = tree
    if not trees_by_index:
        raise NoTrajectoryEvidence("trajectory has no accessibility trees")

    def page_title(step: dict) -> str:
        return str(step.get("hostTitle") or "")

    def render(index: int) -> str:
        return webchain_tree_to_text(trees_by_index[index], title=page_title(steps[index]))[0]

    first_index = min(trees_by_index)
    builder = _PathBuilder("traj", entry_url, limits=limits)
    builder.set_baseline(a11y_text_to_state(render(first_index), url=entry_url, limits=limits))

    for index in sorted(trees_by_index):
        if index <= first_index:
            continue
        action_step = steps[index - 1]
        label_source = trees_by_index.get(index - 1, trees_by_index[first_index])
        _, labels = webchain_tree_to_text(label_source, title=page_title(action_step))
        builder.add_step(
            _action_row(_webchain_action(action_step), label_by_node_id=labels),
            a11y_text_to_state(render(index),
                               url=str(steps[index].get("href") or entry_url),
                               limits=limits),
        )

    observation = builder.observation()
    observation["baseline"]["url"] = entry_url
    seed = {
        "seed_id": seed_id,
        "entry_url": entry_url,
        "dataset": "webchain",
        "task_instruction": str(traj.get("title") or "").strip(),
        "mining_focus": "human-annotated task trajectory on a real website",
    }
    return seed, observation


def _webchain_action(step: dict | None) -> str:
    if not step:
        return "unknown()"
    action_type = str(step.get("type") or "unknown")
    render = {
        "click": "click", "type": "fill", "select": "select_option",
        "hover": "hover", "drag": "drag_and_drop", "back": "go_back",
        "press_enter": "press", "double_click": "double_click", "paste": "fill",
    }.get(action_type, action_type)
    value = str(step.get("value") or "").replace("'", "").strip()[:120]
    return f"{render}('{value}')" if value else f"{render}()"


def load_axtrees(path: str | Path) -> dict[str, dict]:
    """读取 `fetch_webchain_axtrees.py` 产出的单轨迹 gzip 文件。"""
    with gzip.open(Path(path), "rt", encoding="utf-8") as fh:
        return json.load(fh).get("steps", {})

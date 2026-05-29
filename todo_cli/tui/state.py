from __future__ import annotations

import json
import os

from textual.widgets.tree import TreeNode


_UI_STATE_PATH = os.path.expanduser("~/.todo_ui_state.json")

_THEMES = [
    "gruvbox",
    "dracula",
    "textual-dark",
    "nord",
    "catppuccin-latte",
    "solarized-light",
]


def load_ui_state() -> dict:
    try:
        with open(_UI_STATE_PATH, "r") as f:
            data = json.load(f)
        return {
            "expanded": set(data.get("expanded", [])),
            "theme": data.get("theme", _THEMES[0]),
            "filter_mode": data.get("filter_mode", 0),
        }
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return _migrate_pickle_state()


def _migrate_pickle_state() -> dict:
    pickle_path = os.path.expanduser("~/.todo_ui_state.pkl")
    try:
        import pickle
        with open(pickle_path, "rb") as f:
            data = pickle.load(f)
        result: dict = {"expanded": set(), "theme": _THEMES[0]}
        if isinstance(data, set):
            result["expanded"] = data
        elif isinstance(data, dict):
            result["expanded"] = data.get("expanded", set())
            result["theme"] = data.get("theme", _THEMES[0])
        os.remove(pickle_path)
        return result
    except (FileNotFoundError, Exception):
        return {"expanded": set(), "theme": _THEMES[0]}


def collect_expanded(node: TreeNode[int], expanded_ids: set[int]) -> None:
    if node.data is not None and node.is_expanded:
        expanded_ids.add(node.data)
    for child in node.children:
        collect_expanded(child, expanded_ids)


def save_ui_state(tree, theme: str, filter_mode: int) -> None:
    expanded_ids: set[int] = set()
    for node in tree.root.children:
        collect_expanded(node, expanded_ids)
    state = {"expanded": sorted(expanded_ids), "theme": theme, "filter_mode": filter_mode}
    with open(_UI_STATE_PATH, "w") as f:
        json.dump(state, f)

"""The page tree: nodes as the descendants list returns them, put in reading order."""
from __future__ import annotations

from typing import Sequence

from .model import TreeNode

_LAST = 1 << 30


def arrange(nodes: Sequence[TreeNode], root_id: str) -> list[TreeNode]:
    """Depth first, children in their position under the parent (then by title). A node whose parent is not in the
    list, which happens when the list was cut short, comes last, ordered by depth."""
    children: dict[str, list[TreeNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.position if node.position is not None else _LAST, node.title.casefold(), node.id))
    ordered: list[TreeNode] = []
    seen: set[str] = set()
    stack = list(reversed(children.get(root_id, [])))
    while stack:
        node = stack.pop()
        if node.id in seen:
            continue
        seen.add(node.id)
        ordered.append(node)
        stack.extend(reversed(children.get(node.id, [])))
    rest = [node for node in nodes if node.id not in seen]
    ordered.extend(sorted(rest, key=lambda node: (node.depth, node.title.casefold(), node.id)))
    return ordered

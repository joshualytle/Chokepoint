"""Maps — the processing topology packets flow through.

This is the graph model of the pipeline. A map is a directed graph of **nodes**
(junctions where packets queue) joined by **edges** (the routes between them).
Packets enter at the ``source`` and head for the ``sink`` (the protected exit);
a turret attaches to a node and drains that node's queue.

Phase 1 is a single trunk: a linear chain source -> ... -> sink, one outgoing
edge per node. The adjacency structure (``adj``) is already a graph, so later
phases add branches and gates without another rewrite — routing just chooses
among several outgoing edges instead of the one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# game-area width; the info panel sits to the right of this
GW = 720


@dataclass(frozen=True)
class Node:
    """A junction in the pipeline. Packets queue here; turrets serve the queue."""

    id: str
    x: float
    y: float


@dataclass
class Graph:
    """A processing topology: nodes joined by directed edges, with one entry
    (``source``) and one protected exit (``sink``)."""

    name: str
    nodes: dict[str, Node]
    adj: dict[str, list[str]]              # node id -> downstream node ids
    source: str
    sink: str
    slots: list[tuple[float, float]]       # suggested turret positions (loadout hints)

    def pos(self, node_id: str) -> tuple[float, float]:
        n = self.nodes[node_id]
        return (n.x, n.y)

    def next_of(self, node_id: str) -> str | None:
        """The downstream node along the (single, in phase 1) outgoing edge."""
        outs = self.adj.get(node_id, [])
        return outs[0] if outs else None

    def edge_len(self, a: str, b: str) -> float:
        ax, ay = self.pos(a)
        bx, by = self.pos(b)
        return math.hypot(bx - ax, by - ay)

    def edges(self) -> list[tuple[str, str]]:
        """All directed (src, dst) pairs — for drawing and traversal."""
        return [(src, dst) for src, dsts in self.adj.items() for dst in dsts]

    def nearest_node(self, x: float, y: float) -> str:
        """The node id closest to (x, y) — maps a click to a service point."""
        return min(self.nodes, key=lambda nid: (self.nodes[nid].x - x) ** 2
                   + (self.nodes[nid].y - y) ** 2)


def _linear(name: str, pts: list[tuple[float, float]],
            slots: list[tuple[float, float]]) -> Graph:
    """Build a single-trunk graph: one node per point, edge to the next."""
    nodes = {f"n{i}": Node(f"n{i}", x, y) for i, (x, y) in enumerate(pts)}
    adj = {f"n{i}": ([f"n{i + 1}"] if i + 1 < len(pts) else []) for i in range(len(pts))}
    return Graph(name, nodes, adj, source="n0", sink=f"n{len(pts) - 1}", slots=slots)


MAPS: dict[str, Graph] = {
    "switchback": _linear(
        "switchback",
        [(-30, 140), (200, 140), (200, 420), (440, 420),
         (440, 160), (620, 160), (620, 470), (760, 470)],
        slots=[(290, 270), (500, 290), (660, 330)],
    ),
    "spiral": _linear(
        "spiral",
        [(-30, 320), (560, 320), (560, 120), (160, 120),
         (160, 470), (660, 470), (660, 250), (760, 250)],
        slots=[(330, 320), (360, 200), (520, 470)],
    ),
    "fork": _linear(
        "fork",
        [(-30, 90), (360, 90), (360, 300), (120, 300),
         (120, 520), (560, 520), (560, 260), (760, 260)],
        slots=[(250, 90), (240, 300), (430, 520)],
    ),
}
MAP_LIST: list[str] = list(MAPS)

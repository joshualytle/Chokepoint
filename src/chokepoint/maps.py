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
        """The first downstream node (a linear node has exactly one)."""
        outs = self.adj.get(node_id, [])
        return outs[0] if outs else None

    def branches(self, node_id: str) -> list[str]:
        """All downstream nodes from here (>1 means it's a branching node)."""
        return self.adj.get(node_id, [])

    def branching_nodes(self) -> list[str]:
        """Nodes with more than one outgoing edge — where a gate matters."""
        return [nid for nid in self.nodes if len(self.adj.get(nid, [])) > 1]

    def nearest_branch_node(self, x: float, y: float) -> str | None:
        """Nearest branching node to (x, y), or None if the map has no forks."""
        forks = self.branching_nodes()
        if not forks:
            return None
        return min(forks, key=lambda nid: (self.nodes[nid].x - x) ** 2
                   + (self.nodes[nid].y - y) ** 2)

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


def build_graph(name: str, coords: dict[str, tuple[float, float]],
                edges: list[tuple[str, str]], source: str, sink: str,
                slots: list[tuple[float, float]]) -> Graph:
    """Generic graph builder from node coords + directed edges. Supports forks."""
    nodes = {nid: Node(nid, x, y) for nid, (x, y) in coords.items()}
    adj: dict[str, list[str]] = {nid: [] for nid in coords}
    for a, b in edges:
        adj[a].append(b)
    return Graph(name, nodes, adj, source=source, sink=sink, slots=slots)


def _linear(name: str, pts: list[tuple[float, float]],
            slots: list[tuple[float, float]]) -> Graph:
    """Build a single-trunk graph: one node per point, edge to the next."""
    coords = {f"n{i}": p for i, p in enumerate(pts)}
    edges = [(f"n{i}", f"n{i + 1}") for i in range(len(pts) - 1)]
    return build_graph(name, coords, edges, "n0", f"n{len(pts) - 1}", slots)


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
    # A real branch: traffic splits at n1 into a top and bottom lane, then
    # rejoins at n6. Place a gate at n1 to route each kind down the lane whose
    # consumers can handle it.
    "delta": build_graph(
        "delta",
        {"n0": (-30, 340), "n1": (180, 340),
         "n2": (340, 180), "n3": (520, 180),       # top lane
         "n4": (340, 500), "n5": (520, 500),       # bottom lane
         "n6": (620, 340), "n7": (760, 340)},
        edges=[("n0", "n1"), ("n1", "n2"), ("n1", "n4"),
               ("n2", "n3"), ("n3", "n6"), ("n4", "n5"), ("n5", "n6"), ("n6", "n7")],
        source="n0", sink="n7",
        slots=[(340, 180), (340, 500), (520, 180)],
    ),
    # Three lanes off one fork — a gate here can split traffic three ways.
    "trident": build_graph(
        "trident",
        {"n0": (-30, 340), "n1": (170, 340),
         "n2": (340, 120), "n3": (560, 120),       # top lane
         "n4": (340, 340), "n5": (560, 340),       # middle lane
         "n6": (340, 560), "n7": (560, 560),       # bottom lane
         "n8": (650, 340), "n9": (760, 340)},
        edges=[("n0", "n1"), ("n1", "n2"), ("n1", "n4"), ("n1", "n6"),
               ("n2", "n3"), ("n3", "n8"), ("n4", "n5"), ("n5", "n8"),
               ("n6", "n7"), ("n7", "n8"), ("n8", "n9")],
        source="n0", sink="n9",
        slots=[(340, 120), (340, 340), (340, 560)],
    ),
}
MAP_LIST: list[str] = list(MAPS)

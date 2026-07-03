"""Tests for player-editable topology: grow the graph, kept acyclic."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.maps import build_graph
from chokepoint.simulation import World


def trunk():
    # n0(source) -> n1 -> n2(sink)
    return build_graph(
        "edit-test",
        {"n0": (0, 0), "n1": (100, 0), "n2": (200, 0)},
        edges=[("n0", "n1"), ("n1", "n2")],
        source="n0", sink="n2", slots=[(100, 0)],
    )


# ---- reachability ---- #
def test_reachable_follows_edges():
    g = trunk()
    assert g.reachable("n0", "n2")
    assert g.reachable("n1", "n1")     # trivially reaches itself
    assert not g.reachable("n2", "n0")  # edges are directed


# ---- adding ---- #
def test_add_node_gets_a_fresh_id():
    g = trunk()
    nid = g.add_node(50, 80)
    assert nid not in ("n0", "n1", "n2")
    assert nid in g.nodes and g.adj[nid] == []


def test_add_edge_creates_a_branch():
    g = trunk()
    b = g.add_node(120, 90)
    assert g.add_edge("n1", b) is True       # fork off n1
    assert g.add_edge(b, "n2") is True        # rejoin the sink
    assert g.branches("n1") == ["n2", b]
    assert g.reachable("n0", b)


# ---- guards ---- #
def test_add_edge_rejects_self_loop_and_duplicate():
    g = trunk()
    assert g.add_edge("n1", "n1") is False
    assert g.add_edge("n0", "n1") is False    # already exists


def test_add_edge_rejects_cycles():
    g = trunk()
    # n0->n1->n2 exists; adding n2->n0 (or n1->n0) would loop packets forever
    assert g.add_edge("n2", "n0") is False
    assert g.add_edge("n1", "n0") is False
    assert g.reachable("n2", "n0") is False   # still acyclic


# ---- removing ---- #
def test_remove_edge_and_node():
    g = trunk()
    extra = g.add_node(120, 90)
    g.add_edge("n1", extra)
    assert g.remove_edge("n1", extra) is True
    assert extra not in g.branches("n1")
    assert g.remove_node(extra) is True
    assert extra not in g.nodes


def test_cannot_remove_source_or_sink():
    g = trunk()
    assert g.remove_node("n0") is False
    assert g.remove_node("n2") is False


def test_remove_node_allowed_when_a_parallel_path_remains():
    # diamond: n0 -> {a, b} -> n3(sink). Removing 'a' leaves n0->b->n3, so it's
    # allowed, and a's incoming edge (n0->a) is dropped with it.
    g = build_graph("diamond",
                    {"n0": (0, 0), "a": (100, -50), "b": (100, 50), "n3": (200, 0)},
                    edges=[("n0", "a"), ("n0", "b"), ("a", "n3"), ("b", "n3")],
                    source="n0", sink="n3", slots=[(100, 0)])
    assert g.remove_node("a") is True
    assert "a" not in g.nodes
    assert g.branches("n0") == ["b"]        # the n0->a edge went with it
    assert g.reachable("n0", "n3")


def test_remove_edge_allowed_when_a_parallel_path_remains():
    g = build_graph("diamond",
                    {"n0": (0, 0), "a": (100, -50), "b": (100, 50), "n3": (200, 0)},
                    edges=[("n0", "a"), ("n0", "b"), ("a", "n3"), ("b", "n3")],
                    source="n0", sink="n3", slots=[(100, 0)])
    assert g.remove_edge("a", "n3") is True   # a branch edge; n0->b->n3 still connects
    assert ("a", "n3") not in g.edges()
    assert g.reachable("n0", "n3")


def test_cannot_strand_the_pipeline():
    # a bare trunk has a single path; removing the middle node or the only edge
    # would leave incoming alerts nowhere to go, so both are rejected (no change).
    g = trunk()
    assert g.remove_node("n1") is False
    assert "n1" in g.nodes and g.reachable("n0", "n2")
    assert g.remove_edge("n0", "n1") is False
    assert g.branches("n0") == ["n1"]


# ---- copy isolation ---- #
def test_copy_is_independent_of_the_base():
    g = trunk()
    c = g.copy()
    c.add_node(10, 10)
    c.add_edge("n0", "n2")
    assert len(c.nodes) == len(g.nodes) + 1      # base node count unchanged
    assert "n2" not in g.branches("n0")          # base edges unchanged


# ---- world rebind after an edit ---- #
def test_to_python_round_trips_a_custom_topology():
    from chokepoint.editor import ArsenalEditor
    g = trunk()
    extra = g.add_node(120, 90)   # fork off n1 and rejoin the sink
    g.add_edge("n1", extra)
    g.add_edge(extra, "n2")

    src = ArsenalEditor().to_python(g)
    ns: dict = {}
    exec(src, ns)  # noqa: S102 - exercising the generated loadout source
    rebuilt = ns["build_topology"]()

    assert set(rebuilt.nodes) == set(g.nodes)
    assert sorted(rebuilt.edges()) == sorted(g.edges())
    assert (rebuilt.source, rebuilt.sink) == (g.source, g.sink)
    assert rebuilt.branches("n1") == g.branches("n1")  # the fork survived


def test_rebind_snaps_turret_to_a_new_node():
    g = trunk()
    w = World(g)
    w.set_turrets([Turret(140, 0, make_gun("sieve"))])  # nearest existing node is n1
    assert w.turrets[0].node == "n1"
    near = g.add_node(140, 0)   # a new node right at the turret
    w.rebind()
    assert w.turrets[0].node == near

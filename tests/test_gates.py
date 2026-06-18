"""Tests for branching topology and gate routing (pure core)."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.gates import Gate
from chokepoint.maps import build_graph
from chokepoint.simulation import World


def fork_graph():
    #            n2 (branch A)
    #          /              \
    # n0 -> n1                  n4 (sink)
    #          \              /
    #            n3 (branch B)
    return build_graph(
        "fork-test",
        {"n0": (0, 100), "n1": (100, 100), "n2": (200, 40),
         "n3": (200, 160), "n4": (300, 100)},
        edges=[("n0", "n1"), ("n1", "n2"), ("n1", "n3"), ("n2", "n4"), ("n3", "n4")],
        source="n0", sink="n4", slots=[(200, 40), (200, 160)],
    )


def step_for(world, seconds, dt=1 / 60):
    t = 0.0
    while t < seconds and not world.over:
        world.step(dt)
        t += dt


# ---- graph branching ---- #
def test_graph_reports_its_fork():
    gm = fork_graph()
    assert gm.branches("n1") == ["n2", "n3"]
    assert gm.branching_nodes() == ["n1"]
    assert gm.nearest_branch_node(190, 150) == "n1"  # only fork on the map


def test_linear_graph_has_no_fork():
    from chokepoint.maps import MAPS
    assert MAPS["switchback"].branching_nodes() == []
    assert MAPS["switchback"].nearest_branch_node(100, 100) is None


# ---- gate routing decision ---- #
def test_gate_branch_for_clamps_and_defaults():
    g = Gate(0, 0, routes={"auth": 1}, default_branch=0)
    assert g.branch_for("auth", 2) == 1       # explicit route
    assert g.branch_for("dns", 2) == 0        # falls back to default
    assert g.branch_for("auth", 1) == 0       # out-of-range index clamped to 0


def test_set_gates_binds_to_branch_node():
    w = World(fork_graph())
    w.set_gates([Gate(100, 100, routes={"auth": 1})])
    assert w.gates[0].node == "n1"
    assert w.gate_at("n1") is not None


# ---- routing changes the outcome ---- #
def test_without_gate_traffic_takes_default_branch_and_leaks():
    # turret serves auth only on branch B (n3); default routing sends auth down
    # branch A (n2, index 0) where nothing serves it -> it leaks at the sink.
    w = World(fork_graph())
    w.set_turrets([Turret(200, 160, make_gun("sieve"))])  # -> n3
    step_for(w, 25)
    assert w.stats["auth"].handled == 0
    assert w.stats["auth"].leaked > 0


def test_gate_routes_traffic_to_the_serving_branch():
    # same turret on branch B, but a gate sends auth down branch 1 (n3) -> handled
    w = World(fork_graph())
    w.set_turrets([Turret(200, 160, make_gun("sieve"))])  # -> n3
    w.set_gates([Gate(100, 100, routes={"auth": 1})])     # -> n1, auth to branch B
    step_for(w, 25)
    assert w.stats["auth"].handled > 0

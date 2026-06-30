"""Headless tests for the typed-packet flow simulation (graph + queues)."""

from chokepoint import llm_assist
from chokepoint.arsenal import Turret, make_gun
from chokepoint.loadout import build_loadout
from chokepoint.maps import MAPS, build_graph
from chokepoint.packets import Packet
from chokepoint.simulation import SPILL_AT, START_HEALTH, World


def make_world(turrets=None, map_name="switchback"):
    gm = MAPS[map_name]
    w = World(gm)
    if turrets is None:
        turrets = build_loadout(w.unlocked(), gm.slots)
    w.set_turrets(turrets)
    return w


def step_for(world, seconds, dt=1 / 60):
    t = 0.0
    while t < seconds and not world.over:
        world.step(dt)
        t += dt


# ---- topology geometry ---- #
def test_graph_has_source_sink_and_geometry():
    gm = MAPS["switchback"]
    assert gm.source in gm.nodes and gm.sink in gm.nodes
    assert gm.source != gm.sink
    assert gm.edge_len(gm.source, gm.next_of(gm.source)) > 0
    assert gm.nearest_node(*gm.pos(gm.sink)) == gm.sink


def test_all_maps_have_geometry():
    for gm in MAPS.values():
        assert gm.nodes and gm.slots and gm.edges()
        assert gm.source != gm.sink


# ---- turret binds to a node ---- #
def test_set_turrets_binds_each_to_nearest_node():
    gm = MAPS["switchback"]
    w = World(gm)
    w.set_turrets([Turret(*gm.pos("n1"), make_gun("sieve"))])
    assert w.turrets[0].node == "n1"


# ---- coverage / handling ---- #
def test_covered_kind_gets_handled():
    # a sieve at a node on the route covers auth; auth packets get processed there
    w = make_world([Turret(200, 140, make_gun("sieve"))])  # snaps to n1
    step_for(w, 20)
    auth = w.stats["auth"]
    assert auth.spawned > 0
    assert auth.handled > 0


def test_uncovered_kind_leaks_at_the_sink():
    # only a sieve (auth/dns). Wave 3 of the curriculum is the ids stage; ids is
    # uncovered here, so every ids packet flows untouched to the sink and leaks.
    w = make_world([Turret(200, 140, make_gun("sieve"))])
    w.wave_idx = 3
    w.load_wave(3)
    w.started = True
    step_for(w, 60)
    assert "ids" in w.coverage_gaps()
    ids = w.stats["ids"]
    assert ids.spawned > 0
    assert ids.handled == 0
    assert ids.leaked > 0


def test_default_loadout_covers_early_kinds():
    w = make_world()
    cov = w.coverage()
    assert {"auth", "dns", "ids", "firewall"} <= cov


# ---- the two failure modes ---- #
def test_backpressure_drains_health():
    # one sieve, then dump a big burst of auth on its node faster than it drains.
    # Packets pile up, dwell past the grace period, and bleed the latency budget.
    w = make_world([Turret(200, 140, make_gun("sieve"))])
    w.spawn_q = [(0.0, "auth") for _ in range(16)]
    w.spawn_clock = 0.0
    step_for(w, 12)
    assert w.health < START_HEALTH


def test_queue_overflow_leaks():
    # far more than QUEUE_CAP arrive at one node at once -> the excess is dropped.
    w = make_world([Turret(200, 140, make_gun("sieve"))])
    w.spawn_q = [(0.0, "auth") for _ in range(24)]
    w.spawn_clock = 0.0
    step_for(w, 12)
    assert w.stats["auth"].leaked > 0


# ---- synergy still reaches the turret ---- #
def test_synergy_boost_improves_throughput():
    w = make_world([Turret(200, 140, make_gun("sieve")),
                    Turret(440, 420, make_gun("auditor"))])
    w.step(1 / 60)
    assert any(t.synergy_mult > 1.0 for t in w.turrets)


def test_long_run_stable():
    w = make_world()
    step_for(w, 60)
    assert w.level >= 1


def test_well_covered_loadout_progresses_on_calm():
    # guns covering the early kinds, gentle pace -> the run should advance waves
    gm = MAPS["switchback"]
    w = World(gm, difficulty="calm")
    w.set_turrets([Turret(200, 140, make_gun("sieve")),    # auth/dns
                   Turret(440, 420, make_gun("scatter"))])  # ids/firewall
    step_for(w, 120)
    assert w.wave_idx >= 2  # cleared at least a couple of waves, didn't insta-die


def test_upcoming_kinds_counts_the_queued_wave():
    w = make_world([Turret(200, 140, make_gun("sieve"))])
    w.wave_idx = 3
    w.load_wave(3)  # loads the wave's spawn queue
    upcoming = w.upcoming_kinds()
    assert sum(upcoming.values()) == len(w.spawn_q)
    assert all(v > 0 for v in upcoming.values())


def test_state_summary_includes_health_and_devices():
    w = make_world([Turret(200, 140, make_gun("sieve"))])
    summary = llm_assist.state_summary(w)
    assert "health=" in summary
    assert "node=" in summary  # turret bound to a node, not a spatial range
    assert "coverage_gaps=" in summary


def test_llm_unavailable_is_graceful():
    assert llm_assist.available("http://localhost:9", timeout=0.3) is False
    msg = llm_assist.diagnose("ctx", "why leaks?", url="http://localhost:9", timeout=0.3)
    assert isinstance(msg, str) and "unavailable" in msg.lower()


# ---- spill / overflow routing ("else" to a parallel consumer) ---- #
def _fork_map():
    """source -> n1 (fork) -> {backup, trunk2} -> sink."""
    return build_graph(
        "forktest",
        {"n0": (0, 0), "n1": (100, 0), "backup": (200, -50),
         "trunk2": (200, 50), "sink": (300, 0)},
        [("n0", "n1"), ("n1", "backup"), ("n1", "trunk2"),
         ("backup", "sink"), ("trunk2", "sink")],
        "n0", "sink", [(100, 0), (200, -50)],
    )


def test_spill_routes_excess_to_a_parallel_consumer():
    gm = _fork_map()
    w = World(gm)
    w.spawn_q.clear()
    w.set_turrets([Turret(*gm.pos("n1"), make_gun("sieve")),       # primary on the fork
                   Turret(*gm.pos("backup"), make_gun("sieve"))])  # backup on a branch
    for _ in range(SPILL_AT + 3):
        w.packets.append(Packet("auth", 12, 12, 60, at="n1"))
    w._spill(1 / 60)
    spilled = [p for p in w.packets if p.moving_to == "backup"]
    waiting = [p for p in w.packets if p.moving_to is None and p.at == "n1"]
    assert len(spilled) == 3            # the excess over SPILL_AT
    assert len(waiting) == SPILL_AT     # the primary keeps a working backlog


def test_no_spill_without_a_parallel_consumer():
    gm = build_graph("lin", {"n0": (0, 0), "n1": (100, 0), "sink": (200, 0)},
                     [("n0", "n1"), ("n1", "sink")], "n0", "sink", [(100, 0)])
    w = World(gm)
    w.spawn_q.clear()
    w.set_turrets([Turret(*gm.pos("n1"), make_gun("sieve"))])
    for _ in range(SPILL_AT + 3):
        w.packets.append(Packet("auth", 12, 12, 60, at="n1"))
    w._spill(1 / 60)
    assert all(p.moving_to is None for p in w.packets)  # nowhere to spill -> they stay

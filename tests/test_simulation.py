"""Headless tests for the typed-packet flow simulation (graph + queues)."""

from factory_defense import llm_assist
from factory_defense.arsenal import Turret, make_gun
from factory_defense.loadout import build_loadout
from factory_defense.maps import MAPS
from factory_defense.simulation import START_HEALTH, World


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
    # only a sieve (auth/dns). Force the firewall+ids burst: firewall is uncovered,
    # so every firewall packet flows untouched to the sink and leaks.
    w = make_world([Turret(200, 140, make_gun("sieve"))])
    w.wave_idx = 3
    w.load_wave(3)
    w.started = True
    step_for(w, 40)
    assert "firewall" in w.coverage_gaps()
    fw = w.stats["firewall"]
    assert fw.spawned > 0
    assert fw.handled == 0
    assert fw.leaked > 0


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


def test_llm_unavailable_is_graceful():
    assert llm_assist.available("http://localhost:9", timeout=0.3) is False
    msg = llm_assist.diagnose("ctx", "why leaks?", url="http://localhost:9", timeout=0.3)
    assert isinstance(msg, str) and "unavailable" in msg.lower()

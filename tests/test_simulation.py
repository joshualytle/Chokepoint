"""Headless tests for the typed-packet simulation."""

from factory_defense import llm_assist
from factory_defense.arsenal import Turret, make_gun
from factory_defense.loadout import build_loadout
from factory_defense.maps import MAPS
from factory_defense.simulation import World


def make_world(turrets=None, map_name="switchback"):
    w = World(MAPS[map_name])
    gm = MAPS[map_name]
    if turrets is None:
        turrets = build_loadout(w.unlocked(), gm.slots)
    w.set_turrets(turrets)
    return w


def step_for(world, seconds, dt=1 / 60):
    t = 0.0
    while t < seconds and not world.over:
        world.step(dt)
        t += dt


def test_path_endpoints():
    gm = MAPS["switchback"]
    assert gm.pos_at(0) == gm.path[0]
    assert gm.pos_at(gm.length) == gm.path[-1]
    assert gm.length > 0


def test_all_maps_have_geometry():
    for gm in MAPS.values():
        assert gm.length > 0
        assert gm.slots


def test_covered_kind_gets_handled():
    # a sieve covers auth; auth packets should be handled, not leaked
    w = make_world([Turret(290, 270, make_gun("sieve"))])
    step_for(w, 18)
    auth = w.stats["auth"]
    assert auth.spawned > 0
    assert auth.handled > 0


def test_uncovered_kind_leaks_entirely():
    # only a sieve (auth/dns). Force the firewall+ids burst wave: firewall is
    # uncovered here, so every firewall packet must leak.
    w = make_world([Turret(290, 270, make_gun("sieve"))])
    w.wave_idx = 3
    w.load_wave(3)
    w.started = True
    step_for(w, 30)
    assert "firewall" in w.coverage_gaps()
    fw = w.stats["firewall"]
    assert fw.spawned > 0
    assert fw.handled == 0          # no turret accepts firewall -> never processed
    assert fw.leaked > 0            # so it leaks (the game ends at the leak cap)


def test_default_loadout_covers_early_kinds():
    w = make_world()
    cov = w.coverage()
    assert {"auth", "dns", "ids", "firewall"} <= cov


def test_synergy_boost_improves_throughput():
    # sieve + auditor (Correlation) should out-handle sieve alone on cloudtrail-
    # adjacent load. Here we just assert the multiplier reaches the turret.
    w = make_world([Turret(290, 270, make_gun("sieve")),
                    Turret(500, 290, make_gun("auditor"))])
    w.step(1 / 60)
    assert any(t.synergy_mult > 1.0 for t in w.turrets)


def test_long_run_stable():
    w = make_world()
    step_for(w, 60)
    assert w.level >= 1


def test_llm_unavailable_is_graceful():
    # nothing listening on this port -> fast False, and diagnose returns text
    assert llm_assist.available("http://localhost:9", timeout=0.3) is False
    msg = llm_assist.diagnose("ctx", "why leaks?", url="http://localhost:9", timeout=0.3)
    assert isinstance(msg, str) and "unavailable" in msg.lower()

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


def test_rebinding_turrets_does_not_grant_free_shots():
    # The editor re-syncs (set_turrets) on every click. That must not reset the
    # cooldown, or clicking would push a turret past its static fire_rate.
    gm = MAPS["switchback"]
    w = World(gm)
    w.set_turrets([Turret(*gm.pos("n1"), make_gun("sieve"))])
    w.intermission = 1e9                  # no wave spawns; we feed n1 by hand
    seconds, frames = 5, 60 * 5
    for i in range(frames):
        while len(w.queue_at("n1")) < 3:  # fat packets keep the turret busy
            w.packets.append(Packet("auth", 1e9, 1e9, 60.0, at="n1"))
        if i % 6 == 0:
            w.set_turrets(w.turrets)      # what sync_world() does after a click
        w.health = START_HEALTH           # the fat packets age; keep the run alive
        w.step(1 / 60)
    t = w.turrets[0]
    assert t.fired <= t.gun.fire_rate * seconds + 1


# ---- fire rate: a busy turret shoots at exactly its documented rate ---- #
DT = 1 / 60                               # the game's tick


def shot_times(gun_name, busy_from=0.0, seconds=30.0):
    """Run one turret on n1 and return the time of every shot it fires.

    Before `busy_from` the queue is empty (the turret idles); from then on fat
    packets keep it saturated, so it should fire as fast as its gun allows.
    """
    gm = MAPS["trunk"]
    w = World(gm)
    gun = make_gun(gun_name)
    w.set_turrets([Turret(*gm.pos("n1"), gun)])
    w.intermission = 1e9                  # no wave spawns; we feed n1 by hand
    kind = sorted(gun.accepts)[0]
    times: list[float] = []
    for i in range(round(seconds / DT)):
        now = i * DT
        if now >= busy_from:
            while len(w.queue_at("n1")) < 3:
                w.packets.append(Packet(kind, 1e9, 1e9, 60.0, at="n1"))
        w.health = START_HEALTH           # the fat packets age; keep the run alive
        before = w.turrets[0].fired
        w.step(DT)
        times += [now] * (w.turrets[0].fired - before)
    return times


def test_saturated_turret_fires_at_its_nominal_rate():
    # A cooldown that resets to a full interval throws away the part of a tick
    # it overshot, so at 60 ticks/s guns fired 2-6% slow (sieve 2.87/s, not 3).
    for name in ("sieve", "bastion", "scatter", "auditor"):
        rate = make_gun(name).fire_rate
        seconds = 30.0
        actual = len(shot_times(name, seconds=seconds)) / seconds
        assert abs(actual - rate) / rate < 0.01, (name, actual, rate)


def test_idle_turret_does_not_bank_a_burst():
    # Idle for 5 s, then flooded: the first second of work must not exceed the
    # gun's rate (plus the one shot it was ready to fire), and no two shots may
    # land closer together than one interval minus a single tick.
    for name in ("sieve", "scatter"):
        rate = make_gun(name).fire_rate
        times = shot_times(name, busy_from=5.0, seconds=8.0)
        assert times and times[0] >= 5.0
        first_second = [s for s in times if s < times[0] + 1.0]
        assert len(first_second) <= rate + 1, (name, len(first_second))
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        assert min(gaps) >= 1.0 / rate - DT - 1e-9, (name, min(gaps))


def test_fire_rate_never_exceeded_in_any_one_second_window():
    # Fire rate is static: carrying the overshoot evens out the timing, it must
    # never let a turret out-shoot its gun over any 1 s window.
    for name in ("sieve", "bastion", "scatter"):
        rate = make_gun(name).fire_rate
        times = shot_times(name, seconds=20.0)
        for i, start in enumerate(times):
            in_window = sum(1 for s in times[i:] if s < start + 1.0)
            assert in_window <= rate + 1, (name, start, in_window)


# ---- coverage / handling ---- #
def test_covered_kind_gets_handled():
    # a sieve at a node on the route covers auth; auth packets get processed there
    w = make_world([Turret(200, 140, make_gun("sieve"))])  # snaps to n1
    step_for(w, 20)
    auth = w.stats["auth"]
    assert auth.spawned > 0
    assert auth.handled > 0


def test_turret_activity_counters_track_work():
    # the UI animates flow off these: `fired` per shot, `processed` per packet consumed
    t = Turret(200, 140, make_gun("sieve"))
    w = make_world([t])
    assert t.fired == 0 and t.processed == 0
    step_for(w, 20)
    assert t.fired > 0                       # it shot at the queue
    assert t.processed > 0                   # and fully consumed at least one packet
    assert t.processed <= w.stats["auth"].handled + w.stats["dns"].handled


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

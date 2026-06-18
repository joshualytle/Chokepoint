"""Tests for the telemetry collector, histograms, and the failure debrief."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.maps import MAPS
from chokepoint.metrics import Histogram, Telemetry, summarize_failure
from chokepoint.simulation import World


def step_for(world, seconds, dt=1 / 60):
    t = 0.0
    while t < seconds and not world.over:
        world.step(dt)
        t += dt


# ---- Histogram ---- #
def test_histogram_counts_and_percentiles():
    h = Histogram()
    for v in [0.1, 0.2, 0.3, 0.4, 5.0]:  # four small, one large
        h.add(v)
    assert h.total == 5
    assert h.hi == 5.0
    assert h.percentile(50) <= h.percentile(95)  # monotonic
    assert h.percentile(95) >= 4.0               # the outlier shows up high
    assert abs(h.mean - (6.0 / 5)) < 1e-9


def test_empty_histogram_is_zero():
    h = Histogram()
    assert h.percentile(95) == 0.0
    assert h.mean == 0.0


# ---- event aggregation ---- #
def test_event_aggregation_across_kinds_and_nodes():
    tel = Telemetry()
    for _ in range(3):
        tel.on_spawn("auth", 0)
    tel.on_handle("auth", "n1", 0, 1.5)
    tel.on_leak("auth", "n4", 0, "overflow", 2.0)
    tel.on_leak("auth", "n7", 0, "sink", 0.0)

    ks = tel.kind_summary()["auth"]
    assert (ks.spawned, ks.handled, ks.leaked) == (3, 1, 2)
    assert tel.node_summary()["n4"].overflow_drops == 1
    assert "n7" not in tel.node_summary()  # a sink loss isn't attributed to node load
    # latency gets the handled dwell and the overflow dwell, not the sink one
    assert tel.latency["auth"].total == 2


def test_node_load_fraction():
    nw = Telemetry()._nw("n2", 0)
    nw.total_ticks = 10
    nw.load_ticks = 4
    assert abs(nw.load_fraction - 0.4) < 1e-9


# ---- live sampling against a running world ---- #
def test_observe_records_trend_and_peaks():
    gm = MAPS["switchback"]
    w = World(gm)
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    step_for(w, 4)
    assert w.telemetry.trend                       # at least one ~1s sample
    assert any(kw.peak_inflight > 0 for kw in w.telemetry.kind_wave.values())


def test_efficiency_kpi():
    gm = MAPS["switchback"]
    w = World(gm)
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    step_for(w, 20)
    eff = w.telemetry.efficiency(w)
    assert eff["deployed_cost"] > 0
    if eff["handled"] > 0:
        assert eff["cost_per_handled"] > 0


# ---- failure debrief ---- #
def test_debrief_names_the_coverage_gap_kind_on_a_drop_loss():
    gm = MAPS["switchback"]
    w = World(gm)
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])  # covers auth/dns only
    w.wave_idx = 3
    w.load_wave(3)  # firewall + ids burst, both uncovered here
    w.started = True
    step_for(w, 60)
    assert w.over and not w.won
    deb = summarize_failure(w)
    assert "Dropped" in deb.cause
    assert any("firewall" in ln and "coverage gap" in ln for ln in deb.lines)


def test_debrief_reports_latency_collapse():
    gm = MAPS["switchback"]
    w = World(gm)
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    w.health = 0.0
    w.over, w.won = True, False
    deb = summarize_failure(w)
    assert "Latency" in deb.cause

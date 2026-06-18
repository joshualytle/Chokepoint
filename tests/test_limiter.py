"""Tests for the quelimiter (rate limiter / burst buffer)."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.limiter import LIMITER_RELEASE_RATE, Limiter
from chokepoint.maps import build_graph
from chokepoint.simulation import QUEUE_CAP, World


def line_graph():
    # n0 -> n1 -> n2(sink), short edges so transit doesn't smooth the burst itself
    return build_graph(
        "lim-test",
        {"n0": (0, 0), "n1": (40, 0), "n2": (80, 0)},
        edges=[("n0", "n1"), ("n1", "n2")],
        source="n0", sink="n2", slots=[(40, 0)],
    )


def step_for(world, seconds, dt=1 / 60):
    t = 0.0
    while t < seconds and not world.over:
        world.step(dt)
        t += dt


def burst_world(use_limiter, n=20):
    w = World(line_graph())
    w.set_turrets([Turret(40, 0, make_gun("sieve"))])  # drains auth at n1
    if use_limiter:
        w.set_limiters([Limiter(0, 0, release_rate=1.0)])  # buffers at the source
    w.spawn_q = [(0.0, "auth") for _ in range(n)]
    w.spawn_clock = 0.0
    w.started = True
    return w


# ---- model ---- #
def test_refill_caps_the_token_bucket():
    lim = Limiter(0, 0, release_rate=4.0)
    lim.refill(100.0)  # way more than a second
    assert lim.tokens == 4.0  # capped at ~1s of release, can't hoard a burst


def test_set_limiters_binds_to_nearest_node():
    w = World(line_graph())
    w.set_limiters([Limiter(38, 1)])
    assert w.limiters[0].node == "n1"
    assert w.limiter_at("n1") is not None


def test_default_release_rate_is_positive():
    assert LIMITER_RELEASE_RATE > 0


# ---- behavior ---- #
def test_limiter_buffers_a_burst_beyond_the_normal_cap():
    w = burst_world(use_limiter=True)
    step_for(w, 1.0)
    # most of the 20 are held in the limiter's buffer, well past a bare node's cap
    assert len(w.queue_at("n0")) > QUEUE_CAP


def test_limiter_reduces_drops_from_a_burst():
    # a bare node overflows when the burst lands; the limiter smooths it out
    without = burst_world(use_limiter=False)
    step_for(without, 6.0)
    with_lim = burst_world(use_limiter=True)
    step_for(with_lim, 6.0)
    assert with_lim.stats["auth"].leaked < without.stats["auth"].leaked
    assert without.stats["auth"].leaked > 0  # the burst really did overflow the bare node

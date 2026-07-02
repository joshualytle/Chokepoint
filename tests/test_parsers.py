"""Tests for parsers: raw alerts get decoded to their real kind, then consumed."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.maps import MAPS
from chokepoint.packets import Packet
from chokepoint.parsers import DEFAULT_PARSER_COST, Parser
from chokepoint.simulation import World


def _world_no_spawn(map_name="switchback"):
    """A world with the wave queue cleared, so only injected packets flow."""
    w = World(MAPS[map_name])
    w.spawn_q.clear()
    return w


# ---- the device itself ---- #
def test_can_parse_membership_and_normalizes_handles():
    p = Parser(0, 0, handles=["auth", "dns"])   # a list in author code...
    assert isinstance(p.handles, frozenset)     # ...is normalized to a frozenset
    assert p.can_parse("auth") and not p.can_parse("endpoint")
    assert p.cost == DEFAULT_PARSER_COST


# ---- end-to-end through the simulation ---- #
def test_parser_decodes_raw_then_turret_handles_it():
    w = _world_no_spawn()
    src = w.map.source
    w.set_turrets([Turret(*w.map.pos(src), make_gun("sieve"))])   # sieve accepts auth
    w.set_parsers([Parser(*w.map.pos(src), handles={"auth"})])
    w.packets.append(Packet("raw", 12, 12, 60, at=src, payload="auth"))
    for _ in range(300):
        if w.over:
            break
        w.step(1 / 60)
    assert w.parsed == 1
    assert w.stats["auth"].handled == 1


def test_raw_without_a_parser_flows_through_and_leaks():
    w = _world_no_spawn()
    w.set_turrets([])
    w.set_parsers([])
    w.packets.append(Packet("raw", 12, 12, 60, at=w.map.source, payload="auth"))
    for _ in range(3000):       # travels node->node until it leaks at the sink
        if w.over or w.leaks:
            break
        w.step(1 / 60)
    assert w.parsed == 0
    assert w.leaks >= 1
    assert w.stats["auth"].handled == 0


def test_parser_leaves_payloads_it_cannot_decode_and_flags_a_parse_gap():
    w = _world_no_spawn()
    src = w.map.source
    w.set_parsers([Parser(*w.map.pos(src), handles={"auth"})])
    w.packets.append(Packet("raw", 12, 12, 60, at=src, payload="endpoint"))
    w.step(1 / 60)
    raw = [p for p in w.packets if p.kind == "raw"]
    assert raw and raw[0].payload == "endpoint"   # untouched by an auth-only parser
    assert w.parsed == 0
    assert "endpoint" in w.parse_gaps()


def test_coverage_gaps_excludes_raw():
    w = _world_no_spawn()
    w.stats["raw"].spawned = 5            # raw has shown up...
    assert "raw" not in w.coverage_gaps()  # ...but that's a parser gap, not a turret one


def test_ingest_difficulty_queues_raw_alerts():
    w = World(MAPS["switchback"], difficulty="ingest")
    w.load_wave(2)
    assert any(kind == "raw" for _, kind in w.spawn_q)


def test_spawned_raw_carries_a_consumable_payload():
    w = World(MAPS["switchback"], difficulty="ingest")
    w.load_wave(1)
    w.step(1 / 60)
    while w.spawn_clock < 3 and not w.over:   # let some of the wave spawn
        w.step(1 / 60)
    raw = [p for p in w.packets if p.kind == "raw"]
    assert raw, "ingest wave should have spawned at least one raw alert"
    assert all(p.payload and p.payload != "raw" for p in raw)

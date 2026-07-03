"""Tests for the coaching/hints system."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.hints import coaching
from chokepoint.maps import MAPS
from chokepoint.simulation import World


def test_coverage_gap_names_the_fixing_gun():
    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])  # covers auth/dns, not ids
    w.stats["ids"].spawned = 5                            # ids has appeared, uncovered
    hints = coaching(w)
    # the symptom is in text, the fixing gun in fix, and it teaches the concept
    assert any(h.level == "danger" and "ids" in h.text and "scatter" in h.fix
               and h.concept == "consumer coverage" and h.why for h in hints)


def test_parse_gap_suggests_a_parser():
    from chokepoint.packets import Packet
    w = World(MAPS["switchback"])
    # a raw alert whose payload no parser can decode -> a parse-coverage gap
    w.packets.append(Packet("raw", 12, 12, 60, at="n1", payload="endpoint"))
    hints = coaching(w)
    assert any(h.concept == "parse coverage" and "endpoint" in h.text
               and "parser" in h.fix for h in hints)


def test_solid_coverage_gives_an_all_clear():
    w = World(MAPS["switchback"])
    # sieve + scatter cover the early kinds; nothing has leaked or backed up
    w.set_turrets([Turret(200, 140, make_gun("sieve")),
                   Turret(440, 420, make_gun("scatter"))])
    hints = coaching(w)
    assert hints and hints[0].level == "ok"


def test_fork_without_gate_suggests_a_gate():
    w = World(MAPS["delta"])  # branching map
    w.set_turrets([Turret(340, 180, make_gun("sieve"))])
    assert any("gate" in h.text.lower() and h.level == "tip" for h in coaching(w))


def test_bottleneck_node_is_flagged():
    from chokepoint.packets import Packet
    from chokepoint.simulation import PACKET_SPEED, PACKET_VOLUME
    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    # pile many auth packets onto the sieve's node so it's clearly backed up
    w.packets = [Packet("auth", PACKET_VOLUME, PACKET_VOLUME, PACKET_SPEED, at="n1")
                 for _ in range(12)]
    assert any("backing up" in h.text for h in coaching(w))

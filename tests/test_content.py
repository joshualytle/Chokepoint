"""Tests for the added drop-in content (guns, modules, synergies)."""

from chokepoint.arsenal import (
    GUN_LIBRARY,
    MODULE_LIBRARY,
    Turret,
    active_synergies,
    make_gun,
    unlocked_at,
)


def test_new_guns_registered_with_expected_coverage():
    assert {"warden", "relay", "analyst"} <= set(GUN_LIBRARY)
    assert make_gun("warden").accepts == frozenset({"firewall", "waf"})
    assert make_gun("relay").accepts == frozenset({"dns", "email"})
    assert make_gun("analyst").accepts == frozenset({"ids", "vuln"})


def test_new_modules_registered():
    assert {"cache", "adapter_ids", "adapter_firewall"} <= set(MODULE_LIBRARY)
    assert MODULE_LIBRARY["adapter_ids"].add_accepts == frozenset({"ids"})


def test_new_gun_keeps_static_fire_rate_when_moduled():
    g = make_gun("warden")
    fr = g.fire_rate
    g.attach(MODULE_LIBRARY["cache"])       # a damage module
    assert g.fire_rate == fr                # fire rate is never modified
    assert g.effective_damage() > g.damage  # damage rose


def test_adapter_firewall_adds_firewall_coverage():
    g = make_gun("relay")                   # dns/email only
    assert "firewall" not in g.effective_accepts()
    g.attach(MODULE_LIBRARY["adapter_firewall"])
    assert "firewall" in g.effective_accepts()


def test_new_synergy_activates_with_its_pair():
    ts = [Turret(0, 0, make_gun("warden")), Turret(0, 0, make_gun("scatter"))]
    assert "Perimeter fusion" in {s.name for s in active_synergies(ts)}


def test_content_unlocks_at_its_wave():
    assert "relay" in unlocked_at(3) and "relay" not in unlocked_at(2)
    assert "analyst" in unlocked_at(6) and "analyst" not in unlocked_at(5)
    assert "cache" in unlocked_at(5) and "cache" not in unlocked_at(4)

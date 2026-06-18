"""Tests for the arsenal: gun stats, module attachment, synergies, unlocks."""

from factory_defense.arsenal import (
    GUN_LIBRARY,
    MODULE_LIBRARY,
    Turret,
    compute_synergy_mult,
    make_gun,
    unlocked_at,
)


def test_every_registered_gun_builds():
    for name in GUN_LIBRARY:
        gun = make_gun(name)
        assert gun.fire_rate > 0
        assert gun.accepts


def test_fire_rate_is_static_under_modules():
    gun = make_gun("sieve")
    before = gun.fire_rate
    gun.attach(MODULE_LIBRARY["amp"]).attach(MODULE_LIBRARY["range+"])
    assert gun.fire_rate == before  # modules never touch fire rate


def test_module_raises_damage_range_and_coverage():
    gun = make_gun("sieve")
    base_dmg, base_rng = gun.effective_damage(), gun.effective_range()
    gun.attach(MODULE_LIBRARY["amp"]).attach(MODULE_LIBRARY["range+"])
    gun.attach(MODULE_LIBRARY["adapter_dns"])
    assert gun.effective_damage() > base_dmg
    assert gun.effective_range() > base_rng
    assert "dns" in gun.effective_accepts()


def test_unknown_gun_raises():
    try:
        make_gun("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError for unknown gun")


def test_synergy_applies_when_pair_present():
    a = Turret(0, 0, make_gun("sieve"), id="T1")
    b = Turret(0, 0, make_gun("auditor"), id="T2")
    mult = compute_synergy_mult([a, b])
    assert mult["T1"] > 1.0 and mult["T2"] > 1.0  # Correlation synergy active


def test_synergy_absent_without_pair():
    a = Turret(0, 0, make_gun("sieve"), id="T1")
    mult = compute_synergy_mult([a])
    assert mult["T1"] == 1.0


def test_unlocks_grow_with_waves():
    early = unlocked_at(0)
    late = unlocked_at(5)
    assert early <= late
    assert "lance" not in early and "lance" in late  # endpoint gun unlocks later

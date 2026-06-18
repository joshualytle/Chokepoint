"""Tests for the pure arsenal/placement editor (no pygame needed)."""

from factory_defense.arsenal import Turret, make_gun, unlocked_at
from factory_defense.editor import ArsenalEditor


def full_editor() -> ArsenalEditor:
    """An editor with everything unlocked, for the common case."""
    return ArsenalEditor(unlocked_at(99))


# ---- palette gating ---- #
def test_available_lists_filter_by_unlocked():
    early = ArsenalEditor(unlocked_at(0))
    assert "sieve" in early.available_guns()      # wave-0 gun
    assert "lance" not in early.available_guns()  # endpoint gun unlocks later
    assert "adapter_endpoint" not in early.available_modules()

    late = full_editor()
    assert "lance" in late.available_guns()
    assert "adapter_endpoint" in late.available_modules()


def test_set_unlocked_drops_invalid_selection():
    ed = full_editor()
    ed.select_gun("lance")
    ed.toggle_module("adapter_endpoint")
    ed.set_unlocked(unlocked_at(0))  # lance + adapter_endpoint no longer available
    assert ed.selected_gun is None
    assert ed.pending_modules == []


# ---- placing ---- #
def test_place_adds_turret_with_selected_gun():
    ed = full_editor()
    assert ed.select_gun("sieve")
    t = ed.place(100, 120)
    assert t is not None
    assert t.gun.name == "sieve"
    assert (t.x, t.y) == (100, 120)
    assert ed.to_turrets() == [t]


def test_place_without_selection_returns_none():
    ed = full_editor()
    assert ed.place(50, 50) is None
    assert ed.to_turrets() == []


def test_select_locked_gun_is_rejected():
    ed = ArsenalEditor(unlocked_at(0))
    assert ed.select_gun("lance") is False
    assert ed.selected_gun is None


def test_pending_modules_apply_to_placed_turret():
    ed = full_editor()
    ed.select_gun("sieve")
    assert ed.toggle_module("range+")
    base_range = make_gun("sieve").effective_range()
    t = ed.place(0, 0)
    assert t is not None
    assert t.range() > base_range  # the queued module took effect


def test_selecting_gun_clears_pending_modules():
    ed = full_editor()
    ed.select_gun("sieve")
    ed.toggle_module("range+")
    ed.select_gun("scatter")  # switching guns starts module choices fresh
    assert ed.pending_modules == []


# ---- picking / removing ---- #
def test_turret_at_picks_nearest():
    ed = full_editor()
    ed.select_gun("sieve")
    near = ed.place(100, 100)
    ed.place(300, 300)
    assert ed.turret_at(104, 98) is near  # within radius of the first
    assert ed.turret_at(500, 500) is None  # nothing close


def test_remove_at_removes_nearest():
    ed = full_editor()
    ed.select_gun("sieve")
    ed.place(100, 100)
    assert ed.remove_at(102, 101) is True
    assert ed.to_turrets() == []


def test_remove_at_miss_returns_false():
    ed = full_editor()
    ed.select_gun("sieve")
    ed.place(100, 100)
    assert ed.remove_at(400, 400) is False
    assert len(ed.to_turrets()) == 1


# ---- equipping ---- #
def test_equip_at_attaches_module():
    ed = full_editor()
    ed.select_gun("sieve")
    t = ed.place(100, 100)
    assert t is not None
    before = t.range()
    assert ed.equip_at(100, 100, "range+") is True
    assert t.range() > before


def test_equip_duplicate_rejected():
    ed = full_editor()
    ed.select_gun("sieve")
    ed.place(100, 100)
    assert ed.equip_at(100, 100, "range+") is True
    assert ed.equip_at(100, 100, "range+") is False  # already equipped


def test_equip_keeps_fire_rate_static():
    # Guardrail: modules never change fire rate, even via the editor path.
    ed = full_editor()
    ed.select_gun("sieve")
    t = ed.place(100, 100)
    assert t is not None
    before = t.gun.fire_rate
    ed.equip_at(100, 100, "amp")
    assert t.gun.fire_rate == before


# ---- seeding from / exporting to the loadout ---- #
def test_seed_does_not_alias_caller_list():
    seed = [Turret(0, 0, make_gun("sieve"))]
    ed = full_editor()
    ed.seed(seed)
    ed.select_gun("scatter")
    ed.place(200, 200)
    assert len(seed) == 1            # editing the editor didn't touch the caller's list
    assert len(ed.to_turrets()) == 2


def test_to_turrets_returns_fresh_list():
    ed = full_editor()
    ed.select_gun("sieve")
    ed.place(0, 0)
    exported = ed.to_turrets()
    exported.clear()
    assert len(ed.to_turrets()) == 1  # mutating the export didn't empty the editor

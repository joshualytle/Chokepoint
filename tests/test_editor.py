"""Tests for the pure arsenal/placement editor (no pygame needed)."""

from factory_defense.arsenal import Turret, gun_cost, make_gun, unlocked_at
from factory_defense.economy import Bank
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


# ---- economy: editor spends from a bank when one is attached ---- #
def banked_editor(balance: int) -> tuple[ArsenalEditor, Bank]:
    bank = Bank(balance)
    return ArsenalEditor(unlocked_at(99), bank=bank), bank


def test_place_charges_the_bank():
    ed, bank = banked_editor(1000)
    ed.select_gun("sieve")
    cost = ed.pending_cost()
    assert cost == make_gun("sieve").cost
    t = ed.place(100, 100)
    assert t is not None
    assert bank.balance == 1000 - cost


def test_place_rejected_when_unaffordable_changes_nothing():
    ed, bank = banked_editor(10)  # far less than any gun
    ed.select_gun("sieve")
    assert ed.place(100, 100) is None
    assert bank.balance == 10          # not charged
    assert ed.to_turrets() == []       # not placed


def test_pending_cost_includes_queued_modules():
    ed, _ = banked_editor(1000)
    ed.select_gun("sieve")
    bare = ed.pending_cost()
    ed.toggle_module("range+")
    assert ed.pending_cost() > bare


def test_remove_refunds_the_bank():
    ed, bank = banked_editor(1000)
    ed.select_gun("auditor")
    t = ed.place(100, 100)
    assert t is not None
    spent = 1000 - bank.balance
    assert ed.remove_at(100, 100) is True
    assert bank.balance == 1000        # full refund -> back to start
    assert spent > 0


def test_equip_charges_and_rejects_when_unaffordable():
    ed, bank = banked_editor(100)
    ed.select_gun("sieve")          # costs 90, leaving 10
    ed.place(100, 100)
    assert bank.balance == 10
    # range+ costs 40 -> can't afford; turret keeps its modules unchanged
    assert ed.equip_at(100, 100, "range+") is False
    assert bank.balance == 10


def test_editor_and_world_share_one_bank_by_reference():
    from factory_defense.maps import MAPS
    from factory_defense.simulation import World

    w = World(MAPS["switchback"], starting_credits=500)
    ed = ArsenalEditor(w.unlocked(), bank=w.bank)
    ed.select_gun("sieve")
    ed.place(100, 100)
    # spending through the editor is visible on the world's bank — same object
    assert w.bank.balance == 500 - gun_cost(make_gun("sieve"))

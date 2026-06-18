"""Tests for the credit economy: Bank, gun costs, and wave income."""

from factory_defense.arsenal import gun_cost, make_gun
from factory_defense.economy import Bank
from factory_defense.maps import MAPS
from factory_defense.simulation import (
    WAVE_INCOME_BASE,
    WAVE_INCOME_STEP,
    World,
)


# ---- Bank ---- #
def test_spend_deducts_when_affordable():
    bank = Bank(100)
    assert bank.spend(30) is True
    assert bank.balance == 70


def test_spend_rejected_when_too_expensive_and_leaves_balance():
    bank = Bank(20)
    assert bank.spend(50) is False
    assert bank.balance == 20  # unchanged on failure


def test_can_afford_boundary():
    bank = Bank(50)
    assert bank.can_afford(50) is True
    assert bank.can_afford(51) is False


def test_earn_adds():
    bank = Bank(10)
    bank.earn(15)
    assert bank.balance == 25


# ---- gun cost ---- #
def test_gun_cost_includes_modules():
    from factory_defense.arsenal import MODULE_LIBRARY

    bare = make_gun("sieve")
    base = gun_cost(bare)
    assert base == bare.cost

    upgraded = make_gun("sieve")
    upgraded.attach(MODULE_LIBRARY["range+"])
    assert gun_cost(upgraded) == base + MODULE_LIBRARY["range+"].cost


# ---- wave income on the World ---- #
def test_world_starts_with_starting_credits():
    w = World(MAPS["switchback"], starting_credits=300)
    assert w.bank.balance == 300


def test_wave_income_scales_with_level():
    w = World(MAPS["switchback"])
    assert w.wave_income(2) > w.wave_income(1)
    assert w.wave_income(1) == WAVE_INCOME_BASE + WAVE_INCOME_STEP * 1


def test_clearing_a_wave_grants_income():
    w = World(MAPS["switchback"], starting_credits=200)
    before = w.bank.balance
    # simulate the engine clearing wave 1 -> wave_idx advances in _wave_check
    w.started = True
    w.spawn_q = []
    w.packets = []
    w.intermission = 0.0
    w._wave_check()
    assert w.wave_idx == 1
    assert w.bank.balance == before + w.wave_income(1)


def test_reset_refills_bank_without_replacing_it():
    w = World(MAPS["switchback"], starting_credits=200)
    shared = w.bank          # something else may hold this same reference
    w.bank.spend(150)
    assert w.bank.balance == 50
    w.reset()
    assert w.bank is shared  # same object, not swapped out
    assert w.bank.balance == 200

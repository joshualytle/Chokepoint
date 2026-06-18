"""Tests for difficulty strategies (Easy / Adaptive / Overkill)."""

from chokepoint.maps import MAPS
from chokepoint.packets import (
    DIFFICULTIES,
    WAVES,
    adaptive_wave,
    easy_wave,
    overkill_wave,
)
from chokepoint.simulation import World


def total_count(wave) -> int:
    """Sum of packets across all groups in a wave."""
    return sum(count for _, count, _, _ in wave)


def count_of(wave, kind) -> int:
    return sum(count for k, count, _, _ in wave if k == kind)


# ---- strategy registry ---- #
def test_registry_has_the_three_modes():
    assert set(DIFFICULTIES) >= {"easy", "adaptive", "overkill"}


# ---- easy = today's behavior ---- #
def test_easy_reproduces_curated_waves():
    for i in range(len(WAVES)):
        assert easy_wave(i, {}) == WAVES[i]


def test_easy_falls_back_to_synth_tail():
    tail = easy_wave(len(WAVES), {})
    assert total_count(tail) > 0  # endless generation kicks in


# ---- overkill = more pressure ---- #
def test_overkill_is_heavier_and_tighter_than_easy():
    easy = easy_wave(3, {})
    over = overkill_wave(3, {})
    assert total_count(over) > total_count(easy)
    # gaps tighten (smaller is faster); compare the first group's gap
    assert over[0][2] < easy[0][2]


# ---- adaptive = press the weak spot ---- #
def test_adaptive_without_leaks_matches_easy():
    assert adaptive_wave(2, {}) == easy_wave(2, {})
    assert adaptive_wave(2, {"auth": 0, "ids": 0}) == easy_wave(2, {})


def test_adaptive_amplifies_the_most_leaked_kind():
    # firewall has been leaking the most -> the next wave should pile on firewall
    leaked = {"auth": 1, "firewall": 9, "ids": 2}
    base = easy_wave(2, leaked)
    adapted = adaptive_wave(2, leaked)
    assert count_of(adapted, "firewall") > count_of(base, "firewall")


# ---- World integration ---- #
def test_world_default_difficulty_is_easy_and_matches_curated():
    w = World(MAPS["switchback"])
    assert w.difficulty == "easy"
    # the spawn queue for wave 0 should hold exactly the curated wave-0 count
    assert len(w.spawn_q) == total_count(WAVES[0])


def test_world_overkill_queues_more_than_easy():
    easy = World(MAPS["switchback"], difficulty="easy")
    over = World(MAPS["switchback"], difficulty="overkill")
    assert len(over.spawn_q) > len(easy.spawn_q)


def test_world_adaptive_targets_a_leaked_kind_on_next_wave():
    w = World(MAPS["switchback"], difficulty="adaptive")
    # pretend ids has been leaking, then load the next wave
    w.stats["ids"].leaked = 7
    w.load_wave(2)
    ids_in_queue = sum(1 for _, kind in w.spawn_q if kind == "ids")
    easy_ids = sum(c for k, c, _, _ in easy_wave(2, {}) if k == "ids")
    assert ids_in_queue > easy_ids  # adaptive piled on the leaking kind

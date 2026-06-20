"""Tests for run scoring and high-score persistence."""

from chokepoint.arsenal import Turret, make_gun
from chokepoint.maps import MAPS
from chokepoint.scores import load_highscore, save_highscore
from chokepoint.simulation import World


def test_score_rewards_handled_and_waves():
    w = World(MAPS["switchback"])
    w.set_turrets([Turret(200, 140, make_gun("sieve"))])
    base = w.score()
    w.stats["auth"].handled += 10
    w.wave_idx += 2
    assert w.score() == base + 10 + 100


def test_highscore_missing_file_is_zero(tmp_path):
    assert load_highscore(str(tmp_path / "nope.txt")) == 0


def test_highscore_saves_and_keeps_the_best(tmp_path):
    p = str(tmp_path / "hs.txt")
    assert save_highscore(p, 120) == 120
    assert load_highscore(p) == 120
    assert save_highscore(p, 90) == 120   # lower score doesn't overwrite
    assert save_highscore(p, 200) == 200  # higher does
    assert load_highscore(p) == 200


def test_highscore_handles_garbage_file(tmp_path):
    p = tmp_path / "hs.txt"
    p.write_text("not a number")
    assert load_highscore(str(p)) == 0

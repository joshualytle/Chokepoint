"""Tests for the guided-tutorial cursor and its advancement rules."""

from chokepoint.tutorial import SCRIPT, Step, Tutorial


def test_starts_active_on_the_first_step():
    t = Tutorial()
    assert t.active
    assert t.step is SCRIPT[0]


def test_manual_next_advances_only_manual_steps():
    script = [Step("a", []), Step("b", [], event="edit")]
    t = Tutorial(script)
    t.next()                       # step 0 is manual -> advances
    assert t.step is script[1]
    t.next()                       # step 1 waits for an event -> Next does nothing
    assert t.step is script[1]


def test_signal_advances_matching_event_only():
    script = [Step("a", [], event="edit"), Step("b", [])]
    t = Tutorial(script)
    t.signal("code")               # wrong event -> no move
    assert t.step is script[0]
    t.signal("edit")               # matches -> advance
    assert t.step is script[1]


def test_done_predicate_advances_when_true():
    placed = {"n": 0}
    script = [Step("place", [], done=lambda w, e: placed["n"] >= 1), Step("next", [])]
    t = Tutorial(script)
    t.maybe_advance(None, None)    # predicate false
    assert t.step is script[0]
    placed["n"] = 1
    t.maybe_advance(None, None)    # predicate true
    assert t.step is script[1]


def test_completing_the_last_step_deactivates():
    script = [Step("only", [])]
    t = Tutorial(script)
    t.next()
    assert not t.active
    assert t.step is None


def test_skip_deactivates_immediately():
    t = Tutorial()
    t.skip()
    assert not t.active
    assert t.step is None


def test_default_script_is_walkable_end_to_end():
    t = Tutorial()
    guard = 0
    while t.active and guard < 100:
        step = t.step
        if step.event is not None:
            t.signal(step.event)
        else:
            t.next()               # manual (default script has no done-predicates)
        guard += 1
    assert not t.active            # reached the end without getting stuck

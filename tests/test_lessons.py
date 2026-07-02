"""Tests for the in-editor Python lessons cursor."""

from chokepoint.lessons import LESSONS, Lesson, Lessons


def test_starts_active_on_the_first_lesson():
    le = Lessons()
    assert le.active
    assert le.lesson is LESSONS[0]


def test_checked_lesson_blocks_advance_until_its_check_passes():
    placed = {"n": 0}
    script = [Lesson("do", check=lambda w, e: placed["n"] >= 1), Lesson("next")]
    le = Lessons(script)
    le.check(None, None)          # check false -> not passed, can't advance
    assert not le.can_advance()
    le.next()
    assert le.lesson is script[0]  # stayed put
    placed["n"] = 1
    le.check(None, None)          # now passes
    assert le.can_advance()
    le.next()
    assert le.lesson is script[1]


def test_read_only_lesson_can_advance_immediately():
    script = [Lesson("read"), Lesson("next")]
    le = Lessons(script)
    assert le.can_advance()       # no check -> free to move on
    le.next()
    assert le.lesson is script[1]


def test_skip_hides_and_start_reopens_from_the_top():
    le = Lessons()
    le.i = 2
    le.skip()
    assert not le.active
    le.start()
    assert le.active and le.i == 0 and le.lesson is LESSONS[0]


def test_finishing_the_last_lesson_deactivates():
    script = [Lesson("only")]
    le = Lessons(script)
    le.next()
    assert not le.active


def test_first_default_lesson_checks_a_deployed_turret():
    # lesson 1's check should read the world's turret list
    class _W:
        turrets = [object()]
    le = Lessons()
    le.check(_W(), None)
    assert le.passed  # a turret is deployed -> lesson 1 satisfied

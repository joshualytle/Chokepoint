"""Tests for the in-app code editor's text buffer."""

from chokepoint.codebuffer import TextBuffer


def test_insert_and_text_roundtrip():
    b = TextBuffer("hello")
    b.col = 5
    b.insert(" world")
    assert b.text() == "hello world"
    assert b.col == 11


def test_newline_splits_at_cursor():
    b = TextBuffer("abcd")
    b.col = 2
    b.newline()
    assert b.lines == ["ab", "cd"]
    assert (b.row, b.col) == (1, 0)


def test_backspace_within_and_across_lines():
    b = TextBuffer("ab\ncd")
    b.row, b.col = 1, 1
    b.backspace()                 # delete 'c'
    assert b.lines == ["ab", "d"]
    b.col = 0
    b.backspace()                 # merge line 1 into line 0
    assert b.lines == ["abd"]
    assert (b.row, b.col) == (0, 2)


def test_delete_forward_and_join():
    b = TextBuffer("ab\ncd")
    b.row, b.col = 0, 2           # end of first line
    b.delete()                    # join next line up
    assert b.lines == ["abcd"]


def test_movement_clamps_column():
    b = TextBuffer("longline\nx")
    b.row, b.col = 0, 8
    b.down()                      # next line is shorter -> clamp
    assert (b.row, b.col) == (1, 1)
    b.up()
    assert b.row == 0


def test_left_wraps_to_previous_line_end():
    b = TextBuffer("ab\ncd")
    b.row, b.col = 1, 0
    b.left()
    assert (b.row, b.col) == (0, 2)


def test_home_end():
    b = TextBuffer("hello")
    b.end()
    assert b.col == 5
    b.home()
    assert b.col == 0


def test_edit_sequence_builds_expected_source():
    b = TextBuffer("")
    for ch in "def f():":
        b.insert(ch)
    b.newline()
    b.insert("    return 1")
    assert b.text() == "def f():\n    return 1"

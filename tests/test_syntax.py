"""Tests for the code-editor syntax tokenizer."""

from chokepoint.syntax import spans


def reassemble(line):
    return "".join(t for t, _ in spans(line))


def kinds_of(line, word):
    return [k for t, k in spans(line) if t == word]


def test_spans_reassemble_to_the_original_line():
    for line in ["def build_loadout(unlocked, slots):", "    x = 5  # note", "", "return []"]:
        assert reassemble(line) == line


def test_keywords_numbers_and_comments_classified():
    s = spans("    return 42  # done")
    assert ("return", "kw") in s
    assert ("42", "num") in s
    assert any(t.startswith("#") and k == "comment" for t, k in s)


def test_identifiers_are_plain_text():
    assert kinds_of("make_gun('sieve')", "make_gun") == ["text"]


def test_empty_line_has_no_spans():
    assert spans("") == []

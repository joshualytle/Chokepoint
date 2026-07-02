"""The glossary/HUD-help tables are data the UI depends on — sanity-check them."""

from chokepoint.glossary import GLOSSARY, HUD_HELP


def test_glossary_defines_the_core_concepts():
    terms = {t for t, _ in GLOSSARY}
    assert {"coverage", "leak", "gate", "parser", "spill / overflow"} <= terms
    assert all(defn for _, defn in GLOSSARY)   # every term has a definition


def test_hud_help_covers_the_key_stats_with_titled_tooltips():
    assert {"health", "leaks", "credits", "coverage", "kinds"} <= set(HUD_HELP)
    for lines in HUD_HELP.values():
        assert lines and all(isinstance(ln, str) and ln for ln in lines)

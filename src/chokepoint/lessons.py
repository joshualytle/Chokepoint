"""In-editor Python lessons — teach the language *through* the loadout.

Chokepoint's one file you edit, ``loadout.py``, is real Python. These lessons
sit beside the in-app code editor (press ``C``) and walk a newcomer through the
idioms it uses — functions, calls, lists, sets/membership, comprehensions — with
a short explanation and a task. A lesson either just teaches (advance with Next)
or has a ``check`` predicate over the live (world, editor) that turns ``✓`` once
you've made it true by editing and pressing Ctrl+S.

Pure (no pygame); render draws the panel and reports Ctrl+S applies back here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Lesson:
    title: str
    teach: list[str] = field(default_factory=list)   # explanation paragraphs
    task: str = ""                                    # what to try in the editor
    concept: str = ""                                 # short idiom label
    # None = a read-only lesson (advance with Next); else advance once it's true
    check: Callable[[Any, Any], bool] | None = None
    # a hands-on lesson: load this code into the editor and run it in-memory on
    # Ctrl+S (never writes loadout.py); ``sandbox`` grants free credits to focus
    # on the code, not the budget.
    starter: str | None = None
    sandbox: bool = False


# The track. Keep paragraphs short so they wrap cleanly in the side panel.
LESSONS: list[Lesson] = [
    Lesson(
        "build_loadout is a function",
        ["`build_loadout(unlocked, slots)` is a Python function. The game calls it,"
         " and places whatever list of turrets you `return`.",
         "The board starts empty until you run it."],
        task="Press Ctrl+S to run build_loadout — your turrets appear on the board.",
        concept="functions & return",
        check=lambda w, e: len(w.turrets) >= 1,
    ),
    Lesson(
        "Calls, objects, and *",
        ["`make_gun('sieve')` calls a function that returns a gun object.",
         "`Turret(*slots[0], gun=sieve)` creates a turret; the `*` unpacks the"
         " (x, y) tuple in slots[0] into two arguments."],
        task="Find these calls in the code on the left.",
        concept="function calls & unpacking",
    ),
    Lesson(
        "Lists — cover another type",
        ["Square brackets make a list; more entries mean more turrets.",
         "The starter covers auth/dns with a sieve. `ids` and `firewall` are still"
         " uncovered — a scatter handles those."],
        task="Add  Turret(*slots[1], gun=make_gun('scatter'))  to the list, then Ctrl+S.",
        concept="lists & coverage",
        sandbox=True,
        check=lambda w, e: "ids" in w.coverage(),
        starter=(
            "from chokepoint.arsenal import Turret, make_gun\n\n"
            "def build_loadout(unlocked, slots):\n"
            "    turrets = [Turret(*slots[0], gun=make_gun('sieve'))]  # covers auth, dns\n"
            "    # TODO: add a scatter on slots[1] to also cover ids and firewall\n"
            "    return turrets\n"
        ),
    ),
    Lesson(
        "Sets & membership: if ... in ...",
        ["`unlocked` is a set of names. `if 'range+' in unlocked:` tests membership —"
         " True only once that tool is unlocked.",
         "A gun's `accepts` is also a set of the alert kinds it can handle."],
        task="Spot the `if ... in unlocked:` guard in the example.",
        concept="sets & membership",
    ),
    Lesson(
        "Comprehensions — one per slot",
        ["Build many at once: `[Turret(*s, gun=make_gun('sieve')) for s in slots]`"
         " makes one turret per slot.",
         "That's a list comprehension — Python's compact for-loop-into-a-list."],
        task="Replace the empty list with that comprehension over slots, then Ctrl+S.",
        concept="list comprehensions",
        sandbox=True,
        check=lambda w, e: len(w.turrets) >= len(w.map.slots),
        starter=(
            "from chokepoint.arsenal import Turret, make_gun\n\n"
            "def build_loadout(unlocked, slots):\n"
            "    # TODO: return one sieve per slot, using a list comprehension\n"
            "    return []\n"
        ),
    ),
    Lesson(
        "Parsers in code (ingest)",
        ["On the `ingest` difficulty (press D), raw alerts need decoding first.",
         "Define `build_parsers` to return Parser objects:"
         " `return [Parser(*slots[0], handles={'auth', 'ids'})]`. `{...}` is a set."],
        task="Switch to ingest (D), then add build_parsers to decode raw alerts.",
        concept="sets & drop-in devices",
    ),
]


class Lessons:
    """Cursor over the lesson track, shown in the code editor. Active by default so
    a first-time coder sees it; ``skip`` hides it, ``start`` brings it back."""

    def __init__(self, script: list[Lesson] | None = None) -> None:
        self.script = script if script is not None else LESSONS
        self.i = 0
        self.active = True
        self.passed = False   # current lesson's check satisfied

    @property
    def lesson(self) -> Lesson | None:
        if 0 <= self.i < len(self.script):
            return self.script[self.i]
        return None

    def check(self, world: Any, editor: Any) -> None:
        """Re-evaluate the current lesson's completion (called live by render)."""
        le = self.lesson
        if le is not None and le.check is not None and le.check(world, editor):
            self.passed = True

    def can_advance(self) -> bool:
        """True when the player may move on: read-only lessons always, checked
        lessons once their check has passed."""
        le = self.lesson
        return le is not None and (le.check is None or self.passed)

    def next(self) -> None:
        if not self.can_advance():
            return
        self.i += 1
        self.passed = False
        if self.i >= len(self.script):
            self.active = False   # finished the track

    def skip(self) -> None:
        self.active = False

    def start(self) -> None:
        self.active = True
        self.i = 0
        self.passed = False

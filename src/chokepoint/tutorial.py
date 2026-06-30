"""Guided tutorial — a scripted, stepped onboarding for first-time players.

The game is a teaching tool, so a newcomer should be walked through the core
loop before being left in the sandbox. This module owns the *script* and the
*advancement logic* as pure data so it stays testable headless; ``render.py``
just draws the current step and reports player actions back via ``signal``.

Each step advances one of three ways:
  * **manual**  — the player clicks Next (``event`` and ``done`` both None).
  * **event**   — the player performs an action render reports, e.g. ``"edit"``
    (pressed E) or ``"code"`` (opened the editor).
  * **done**    — a predicate over the live (world, editor) becomes true.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Step:
    title: str
    body: list[str] = field(default_factory=list)
    event: str | None = None                          # advances when render signals this
    done: Callable[[Any, Any], bool] | None = None    # advances when this is true
    button: str = "Next"                              # label for the manual advance button

    @property
    def is_manual(self) -> bool:
        return self.event is None and self.done is None


# The onboarding script. Short lines so it reads cleanly in the on-screen box.
SCRIPT: list[Step] = [
    Step("Welcome to Chokepoint", [
        "Security alerts flood in from the LEFT and flow to the EXIT on the right.",
        "Handle each alert before it reaches the exit — or it LEAKS.",
        "Too many leaks and the run ends.",
    ]),
    Step("Alerts have types", [
        "Every alert has a TYPE, shown by its color.",
        "Your turrets are workers: each turret only handles certain types.",
        "Your job is COVERAGE — a worker for every type that shows up.",
    ]),
    Step("Open Build mode", [
        "Let's add a worker. Press  E  to open Build mode.",
    ], event="edit"),
    Step("Pick a gun, then place it", [
        "On the RIGHT panel, under GUNS, CLICK a gun to select it (it highlights).",
        "A gun's colored squares show the alert types it can handle.",
        "Then CLICK a node on the line to drop the turret there. Right-click removes it.",
        "Place one, then click Next.",
    ]),
    Step("Read the dashboard", [
        "The right panel lists each type:  in / handled / leaked / now.",
        "A  !  marks an UNCOVERED type — no worker handles it, so it will leak.",
    ]),
    Step("Two ways to lose", [
        "1) Uncovered types LEAK at the exit.",
        "2) If a queue backs up too long, the wait bleeds your HEALTH (latency).",
        "Build for both: coverage AND enough speed to keep queues short.",
    ]),
    Step("Build it in Python", [
        "The real power: press  C  to edit your pipeline in code (loadout.py).",
    ], event="code"),
    Step("Your code", [
        "This is Python you control. Ctrl+S applies your changes, Esc closes.",
        "Add or change turrets here, then watch the board react.",
    ]),
    Step("You're ready", [
        "The COACH line (bottom-left) always tells you what to fix next.",
        "Press  H  any time for the full controls and legend.",
        "Click Start — good luck!",
    ], button="Start"),
]


class Tutorial:
    """Cursor over a step script; ``active`` is False once it's done or skipped."""

    def __init__(self, script: list[Step] | None = None) -> None:
        self.script = script if script is not None else SCRIPT
        self.i = 0
        self.active = True

    @property
    def step(self) -> Step | None:
        if self.active and 0 <= self.i < len(self.script):
            return self.script[self.i]
        return None

    def _advance(self) -> None:
        self.i += 1
        if self.i >= len(self.script):
            self.active = False

    def next(self) -> None:
        """Manual advance (the Next/Start button); ignored on non-manual steps."""
        step = self.step
        if step is not None and step.is_manual:
            self._advance()

    def signal(self, event: str) -> None:
        """Report a player action; advances iff the current step waits for it."""
        step = self.step
        if step is not None and step.event == event:
            self._advance()

    def maybe_advance(self, world: Any, editor: Any) -> None:
        """Advance if the current step's state predicate is satisfied."""
        step = self.step
        if step is not None and step.done is not None and step.done(world, editor):
            self._advance()

    def skip(self) -> None:
        self.active = False
